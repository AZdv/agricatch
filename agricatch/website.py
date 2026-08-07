"""Declarative importer base class.

An importer subclasses :class:`Website` and describes *where* the data is rather
than how to walk it: a URL in ``url_info`` and a set of XPath-addressed fields in
``structure``. Extraction and persistence are kept apart so a subclass can be
exercised against a saved fixture without a database.

Field options
-------------
``type``      ``normal`` (text, the default) or ``time`` (parsed to a datetime)
``xpath``     expression evaluated relative to the record node
``required``  skip the whole record when this field is missing (default True)
``format``    ``time`` only; ``%STR%`` is the matched text, ``%TIME%`` the crawl date
``remove``    ``time`` only; substrings stripped before parsing
``function``  name of an ``agricatch.helpers.text`` callable applied to the result
"""

import copy
import datetime
import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from dateutil.parser import ParserError
from dateutil.parser import parse as parse_date
from django.apps import apps
from django.conf import settings
from django.utils import timezone
from lxml import etree, html

from agricatch import xpath_functions
from agricatch.fetch import FetchError, fetch_bytes
from agricatch.helpers import text as text_helpers

logger = logging.getLogger("agricatch.website")

# lxml's default FunctionNamespace is process-wide, so this is done once.
xpath_functions.register()

DATE_PLACEHOLDERS = ("%d", "%m", "%Y")


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list = dataclass_field(default_factory=list)

    @property
    def total(self):
        return self.created + self.updated

    def as_dict(self):
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "total": self.total,
            "errors": list(self.errors),
        }


class Website:
    """Base class for every importer.

    Subclasses set :attr:`url_info` and :attr:`structure`; everything else has a
    working default.
    """

    slug = None
    model_name = "Article"
    parser = "xml"
    namespaces = {}
    url_info = {}
    structure = {}
    required_by_default = True

    def __init__(self):
        cls = type(self)
        self.slug = cls.slug or cls.__name__.lower()
        # Copy the class-level dicts so two instances never share mutable state.
        self.url_info = copy.deepcopy(cls.url_info)
        self.structure = copy.deepcopy(cls.structure)
        self.namespaces = dict(cls.namespaces)
        self.current_url = None

    # ---- public API ----------------------------------------------------

    def do_import(self, days=1, start_day=None, url=None):
        records = self.collect(days=days, start_day=start_day, url=url)
        return self.persist(records)

    def collect(self, days=1, start_day=None, url=None):
        """Fetch and parse, returning a list of field dicts. Touches no database."""
        start_day = start_day or datetime.date.today()
        records = []
        for page_url, crawl_date in self._urls_to_crawl(days, start_day, url):
            self.current_url = page_url
            try:
                content = fetch_bytes(page_url)
            except FetchError as exc:
                logger.warning("%s: %s", self.slug, exc)
                continue

            tree = self.parse(content)
            nodes = self.select_nodes(tree)
            logger.info("%s: %d records at %s", self.slug, len(nodes), page_url)
            for node in nodes:
                record = self.extract_record(node, crawl_date=crawl_date)
                if record is not None:
                    records.append(record)
        return records

    def persist(self, records):
        """Write records, keyed on the content hash so re-runs update in place."""
        model = self.get_model()
        website_model = apps.get_model(settings.AGRICATCH_APP, "Website")
        website, _ = website_model.objects.get_or_create(
            slug=self.slug,
            defaults={"name": self.slug.title(), "address": self.url_info.get("url", "")},
        )

        writable = {f.name for f in model._meta.get_fields() if f.concrete}
        result = ImportResult()
        for record in records:
            unknown = set(record) - writable
            if unknown:
                logger.warning(
                    "%s: %s has no field(s) %s, ignoring",
                    self.slug,
                    model.__name__,
                    ", ".join(sorted(unknown)),
                )
            payload = {k: v for k, v in record.items() if k in writable}
            payload["website"] = website

            _, created = model.objects.update_or_create(
                content_hash=model.build_hash(payload), defaults=payload
            )
            if created:
                result.created += 1
            else:
                result.updated += 1
        return result

    def get_model(self):
        return apps.get_model(settings.AGRICATCH_APP, self.model_name)

    # ---- parsing -------------------------------------------------------

    def parse(self, content):
        if self.parser == "html":
            return html.fromstring(content)
        # Feeds are XML. Parsing them as HTML drops <link> text (a void element
        # in HTML) and flattens namespaces, so it has to be the XML parser here.
        return etree.fromstring(content, parser=etree.XMLParser(recover=True))

    def xpath(self, node, expression):
        if self.namespaces:
            return node.xpath(expression, namespaces=self.namespaces)
        return node.xpath(expression)

    def select_nodes(self, tree):
        child_xpath = self.structure.get("child_xpath")
        if not child_xpath:
            raise ValueError(f"{self.slug}: structure is missing 'child_xpath'")
        return self.xpath(tree, child_xpath)

    # ---- extraction ----------------------------------------------------

    def extract_record(self, node, crawl_date=None):
        """Build one record dict, or None when a required field is missing."""
        crawl_date = crawl_date or datetime.date.today()
        record = {}
        for name, spec in self.structure.get("fields", {}).items():
            raw = self._extract_field(node, spec)
            required = spec.get("required", self.required_by_default)

            if raw in (None, ""):
                if required:
                    logger.debug("%s: dropping record, %r missing", self.slug, name)
                    return None
                # Leave it out entirely so the model's own default applies.
                continue

            if spec.get("type") == "time":
                value = self._parse_time(raw, spec, crawl_date)
                if value is None and required:
                    logger.debug("%s: dropping record, %r unparseable: %r", self.slug, name, raw)
                    return None
            else:
                value = text_helpers.collapse_whitespace(raw)

            record[name] = value

        return self.hydrate(record, node)

    def hydrate(self, record, node):
        """Hook for subclasses to adjust a record before it is persisted."""
        return record

    def _extract_field(self, node, spec):
        expression = spec["xpath"] if isinstance(spec, dict) else spec
        try:
            result = self.xpath(node, expression)
        except etree.XPathError:
            logger.warning("%s: bad xpath %r", self.slug, expression)
            return None

        value = self._node_to_text(result)
        if value is None:
            return None

        if isinstance(spec, dict) and spec.get("function"):
            func = getattr(text_helpers, spec["function"], None)
            if func is None:
                logger.warning("%s: no such helper %r", self.slug, spec["function"])
            else:
                value = func(value)
        return value

    @staticmethod
    def _node_to_text(result):
        if isinstance(result, list):
            if not result:
                return None
            result = result[0]
        if result is None:
            return None
        if hasattr(result, "text_content"):
            return result.text_content()
        if hasattr(result, "itertext"):
            return "".join(result.itertext())
        return str(result)

    def _parse_time(self, raw, spec, crawl_date):
        template = spec.get("format", "%STR%")
        value = template.replace("%STR%", raw).replace("%TIME%", crawl_date.strftime("%d-%m-%Y"))
        for removal in spec.get("remove", []):
            value = value.replace(removal, "")

        try:
            parsed = parse_date(value.strip())
        except (ParserError, OverflowError, ValueError):
            return None

        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
        return parsed

    # ---- url planning --------------------------------------------------

    def _urls_to_crawl(self, days, start_day, override=None):
        """Yield ``(url, crawl_date)`` pairs.

        A URL with no date placeholder returns the same bytes whatever the day,
        so it is fetched once no matter how large ``days`` is.
        """
        if override:
            yield override, start_day
            return

        base = self.url_info["url"]
        if self.url_info.get("ignore_time") or not self._is_dated(base):
            yield base, start_day
            return

        step = max(1, int(self.url_info.get("days_on_page", 1)))
        for offset in range(0, max(1, days), step):
            crawl_date = start_day + datetime.timedelta(days=offset)
            yield text_helpers.replace_parameters(base, crawl_date), crawl_date

    @staticmethod
    def _is_dated(url):
        return any(token in url for token in DATE_PLACEHOLDERS)
