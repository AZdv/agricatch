"""Declarative importer base class.

An importer subclasses :class:`Website` and describes *where* the data is rather
than how to walk it: a URL in ``url_info`` and a set of XPath-addressed fields in
``structure``. Extraction and persistence are kept apart so a subclass can be
exercised against a saved fixture without a database.

Field options
-------------
``type``      ``normal`` (text, the default), ``time`` (parsed to a datetime) or
              ``table`` (a nested record for a related model)
``xpath``     expression evaluated relative to the record node
``required``  skip the whole record when this field is missing (default True)
``format``    ``time`` only; ``%STR%`` is the matched text, ``%TIME%`` the crawl date
``remove``    ``time`` only; substrings stripped before parsing
``function``  name of an ``agricatch.helpers.text`` callable applied to the result
``url``       xpath to a page this one field lives on
"""

from __future__ import annotations

import copy
import datetime
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Protocol

from dateutil.parser import ParserError
from dateutil.parser import parse as parse_date
from django.apps import apps
from django.conf import settings
from django.utils import timezone
from lxml import etree, html

from agricatch import xpath_functions
from agricatch.fetch import CrawlLimitReached, FetchError, FetchSession
from agricatch.helpers import text as text_helpers

logger = logging.getLogger("agricatch.website")

# lxml's default FunctionNamespace is process-wide, so this is done once.
xpath_functions.register()

DATE_PLACEHOLDERS = ("%d", "%m", "%Y")

# lxml elements and xpath results have no public types worth threading through
# here, and the model class is resolved from settings at runtime, so both travel
# as Any rather than being faked into something more specific.
Node = Any
Record = dict[str, Any]


class Fetcher(Protocol):
    """The whole contract :meth:`Website.collect` needs from a session."""

    def get(self, url: str) -> bytes: ...


@dataclass
class RelatedRecord:
    """A nested record destined for a related table.

    Extraction produces these; :meth:`Website.persist` turns them into model
    instances. Keeping them inert until then means an importer can be tested
    against a fixture without a database.
    """

    model: str
    lookup: tuple[str, ...]
    values: dict[str, Any]


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = dataclass_field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated

    def as_dict(self) -> dict[str, Any]:
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

    slug: str | None = None
    model_name: str = "Article"
    parser: str = "xml"
    namespaces: dict[str, str] = {}
    url_info: dict[str, Any] = {}
    structure: dict[str, Any] = {}
    required_by_default: bool = True

    # Following detail pages and pagination multiplies requests, so the pace,
    # the ceiling and how many may overlap are all the importer's to set.
    # Overlapping does not speed up the knocking; see FetchSession.
    crawl_delay: float = 0.5
    max_pages: int | None = 100
    max_concurrency: int = 4

    def __init__(self) -> None:
        cls = type(self)
        self.slug = cls.slug or cls.__name__.lower()
        # Copy the class-level dicts so two instances never share mutable state.
        self.url_info = copy.deepcopy(cls.url_info)
        self.structure = copy.deepcopy(cls.structure)
        self.namespaces = dict(cls.namespaces)
        self.current_url: str | None = None

    # ---- public API ----------------------------------------------------

    def do_import(
        self,
        days: int = 1,
        start_day: datetime.date | None = None,
        url: str | None = None,
    ) -> ImportResult:
        records = self.collect(days=days, start_day=start_day, url=url)
        return self.persist(records)

    def collect(
        self,
        days: int = 1,
        start_day: datetime.date | None = None,
        url: str | None = None,
        session: Fetcher | None = None,
    ) -> list[Record]:
        """Fetch and parse, returning a list of field dicts. Touches no database.

        Pass ``session`` to supply your own fetcher - anything with
        ``get(url) -> bytes`` will do, which is how this gets tested offline.
        """
        start_day = start_day or datetime.date.today()
        session = session or FetchSession(
            delay=self.crawl_delay,
            max_pages=self.max_pages,
            max_concurrency=self.max_concurrency,
        )
        visited: set[str] = set()
        records: list[Record] = []

        try:
            for start_url, crawl_date in self._urls_to_crawl(days, start_day, url):
                pending = [start_url]
                while pending:
                    page_url = pending.pop(0)
                    if page_url in visited:
                        continue
                    visited.add(page_url)

                    page_records, next_pages = self._collect_page(page_url, crawl_date, session)
                    records.extend(page_records)
                    pending.extend(page for page in next_pages if page not in visited)
        except CrawlLimitReached as exc:
            logger.warning("%s: %s", self.slug, exc)

        return records

    def _collect_page(
        self, url: str, crawl_date: datetime.date, session: Fetcher
    ) -> tuple[list[Record], list[str]]:
        """Return ``(records, pagination_urls)`` for one page."""
        self.current_url = url
        try:
            content = session.get(url)
        except FetchError as exc:
            logger.warning("%s: %s", self.slug, exc)
            return [], []

        tree = self.parse(content)
        nodes = self.select_nodes(tree)
        self._prefetch_details(nodes, session, url)

        records: list[Record] = []
        for node in nodes:
            record = self._record_from(node, crawl_date, session, url)
            if record is not None:
                records.append(record)

        logger.info("%s: %d records at %s", self.slug, len(records), url)
        return records, self._pagination_urls(tree, url)

    def _prefetch_details(self, nodes: Sequence[Node], session: Fetcher, base_url: str) -> None:
        """Warm every detail page on this index before extracting any of them.

        Fetching them one at a time means waiting out each response in turn,
        which is the slow part when a site is sluggish rather than when it is
        busy. Skipped when the session has no prefetch, so a plain ``get``-only
        stand-in still works.
        """
        spec = self.structure.get("object_url")
        prefetch = getattr(session, "prefetch", None)
        if not spec or prefetch is None:
            return

        if not isinstance(spec, dict):
            spec = {"xpath": spec}

        targets: list[str] = []
        for node in nodes:
            href = self._extract_field(node, spec, session=session, base_url=base_url)
            if href:
                targets.append(text_helpers.relative_url_to_absolute(href, base_url))
        prefetch(targets)

    def _record_from(
        self, node: Node, crawl_date: datetime.date, session: Fetcher, base_url: str
    ) -> Record | None:
        """Extract one record, following ``object_url`` to a detail page if set."""
        spec = self.structure.get("object_url")
        if not spec:
            return self.extract_record(node, crawl_date, session=session, base_url=base_url)

        if not isinstance(spec, dict):
            spec = {"xpath": spec}
        href = self._extract_field(node, spec, session=session, base_url=base_url)
        if not href:
            logger.debug("%s: no object_url on a record at %s", self.slug, base_url)
            return None

        detail_url = text_helpers.relative_url_to_absolute(href, base_url)
        try:
            content = session.get(detail_url)
        except FetchError as exc:
            logger.warning("%s: %s", self.slug, exc)
            return None

        scope = self.parse(content)
        child_xpath = self.structure.get("object_url_child_xpath")
        if child_xpath:
            found = self.xpath(scope, child_xpath)
            if not found:
                logger.debug("%s: %s has no %s", self.slug, detail_url, child_xpath)
                return None
            scope = found[0]

        return self.extract_record(scope, crawl_date, session=session, base_url=detail_url)

    def _pagination_urls(self, tree: Node, base_url: str) -> list[str]:
        """Absolute URLs of further index pages, from the ``pagination`` xpath."""
        spec = self.structure.get("pagination")
        if not spec:
            return []

        expression = spec["xpath"] if isinstance(spec, dict) else spec
        urls: list[str] = []
        for found in self.xpath(tree, expression):
            href = found if isinstance(found, str) else found.get("href")
            if not href:
                continue
            absolute = text_helpers.relative_url_to_absolute(href, base_url)
            if absolute != base_url and absolute not in urls:
                urls.append(absolute)
        return urls

    def persist(self, records: Sequence[Record]) -> ImportResult:
        """Write records, keyed on the content hash so re-runs update in place."""
        model = self.get_model()
        website_model = apps.get_model(settings.AGRICATCH_APP, "Website")
        website, _ = website_model.objects.get_or_create(
            slug=self.slug,
            defaults={"name": (self.slug or "").title(), "address": self.url_info.get("url", "")},
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
            payload = {k: self.resolve_related(v) for k, v in record.items() if k in writable}
            payload["website"] = website

            _, created = model.objects.update_or_create(
                content_hash=model.build_hash(payload), defaults=payload
            )
            if created:
                result.created += 1
            else:
                result.updated += 1
        return result

    def get_model(self) -> Any:
        """The target model, resolved from settings, so untyped by necessity."""
        return apps.get_model(settings.AGRICATCH_APP, self.model_name)

    def resolve_related(self, value: Any) -> Any:
        """Turn a :class:`RelatedRecord` into a saved instance, nested ones first.

        Matching is get-or-create on the lookup fields, so re-running an import
        reuses the existing row rather than duplicating it, and never overwrites
        a related row that someone has since corrected by hand.
        """
        if not isinstance(value, RelatedRecord):
            return value

        model = apps.get_model(settings.AGRICATCH_APP, value.model)
        resolved = {key: self.resolve_related(item) for key, item in value.values.items()}
        lookup = {key: resolved[key] for key in value.lookup}
        defaults = {key: item for key, item in resolved.items() if key not in lookup}

        instance, _ = model.objects.get_or_create(**lookup, defaults=defaults)
        return instance

    # ---- parsing -------------------------------------------------------

    def parse(self, content: bytes) -> Node:
        if self.parser == "html":
            return html.fromstring(content)
        # Feeds are XML. Parsing them as HTML drops <link> text (a void element
        # in HTML) and flattens namespaces, so it has to be the XML parser here.
        return etree.fromstring(content, parser=etree.XMLParser(recover=True))

    def xpath(self, node: Node, expression: str) -> Any:
        if self.namespaces:
            return node.xpath(expression, namespaces=self.namespaces)
        return node.xpath(expression)

    def select_nodes(self, tree: Node) -> list[Node]:
        child_xpath = self.structure.get("child_xpath")
        if not child_xpath:
            raise ValueError(f"{self.slug}: structure is missing 'child_xpath'")
        found: list[Node] = self.xpath(tree, child_xpath)
        return found

    # ---- extraction ----------------------------------------------------

    def extract_record(
        self,
        node: Node,
        crawl_date: datetime.date | None = None,
        session: Fetcher | None = None,
        base_url: str | None = None,
    ) -> Record | None:
        """Build one record dict, or None when a required field is missing."""
        crawl_date = crawl_date or datetime.date.today()
        fields = self.structure.get("fields", {})
        record = self._extract_fields(node, fields, crawl_date, session, base_url)
        if record is None:
            return None
        return self.hydrate(record, node)

    def _extract_fields(
        self,
        node: Node,
        fields: dict[str, dict[str, Any]],
        crawl_date: datetime.date,
        session: Fetcher | None = None,
        base_url: str | None = None,
    ) -> Record | None:
        """Extract a set of field specs against ``node``.

        Returns None if any required field is missing, which is how a record
        (or a nested related record) gets dropped.
        """
        record: Record = {}
        for name, spec in fields.items():
            required = spec.get("required", self.required_by_default)

            if spec.get("type") == "table":
                related = self._extract_table(node, spec, crawl_date, session, base_url)
                if related is None:
                    if required:
                        logger.debug("%s: dropping record, %r missing", self.slug, name)
                        return None
                    continue
                record[name] = related
                continue

            raw = self._extract_field(node, spec, session=session, base_url=base_url)
            if raw in (None, ""):
                if required:
                    logger.debug("%s: dropping record, %r missing", self.slug, name)
                    return None
                # Leave it out entirely so the model's own default applies.
                continue

            value: Any
            if spec.get("type") == "time":
                value = self._parse_time(str(raw), spec, crawl_date)
                if value is None and required:
                    logger.debug("%s: dropping record, %r unparseable: %r", self.slug, name, raw)
                    return None
            else:
                value = text_helpers.collapse_whitespace(str(raw))

            record[name] = value

        return record

    def _extract_table(
        self,
        node: Node,
        spec: dict[str, Any],
        crawl_date: datetime.date,
        session: Fetcher | None = None,
        base_url: str | None = None,
    ) -> RelatedRecord | None:
        """Extract a nested record for a related model.

        ``child_xpath`` narrows the scope first, for when the related fields sit
        under their own element; without it the nested fields are read straight
        off ``node``.
        """
        try:
            model = spec["model"]
            fields = spec["fields"]
        except KeyError as exc:
            raise ValueError(f"{self.slug}: table field needs 'model' and 'fields'") from exc

        scope = node
        if spec.get("child_xpath"):
            found = self.xpath(node, spec["child_xpath"])
            if not found:
                return None
            scope = found[0]

        values = self._extract_fields(scope, fields, crawl_date, session, base_url)
        if not values:
            return None

        # Without an explicit lookup, every extracted field takes part in the match.
        lookup = tuple(spec.get("lookup") or fields.keys())
        missing = [key for key in lookup if key not in values]
        if missing:
            logger.debug("%s: related %s missing lookup field(s) %s", self.slug, model, missing)
            return None

        return RelatedRecord(model=model, lookup=lookup, values=values)

    def hydrate(self, record: Record, node: Node) -> Record:
        """Hook for subclasses to adjust a record before it is persisted."""
        return record

    def _extract_field(
        self,
        node: Node,
        spec: dict[str, Any] | str,
        session: Fetcher | None = None,
        base_url: str | None = None,
    ) -> str | None:
        if isinstance(spec, dict) and spec.get("url"):
            fetched = self._follow_field_url(node, spec, session, base_url)
            if fetched is None:
                return None
            node = fetched

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

    def _follow_field_url(
        self,
        node: Node,
        spec: dict[str, Any],
        session: Fetcher | None,
        base_url: str | None,
    ) -> Node | None:
        """Fetch the page a field lives on, when it is not the record's own page.

        ``url`` is an xpath to the address; ``xpath`` is then evaluated against
        whatever comes back.
        """
        if session is None:
            logger.warning("%s: field needs a fetch but no session was given", self.slug)
            return None

        href = self._node_to_text(self.xpath(node, spec["url"]))
        if not href:
            return None

        target = text_helpers.relative_url_to_absolute(href, base_url or self.current_url or "")
        try:
            return self.parse(session.get(target))
        except FetchError as exc:
            logger.warning("%s: %s", self.slug, exc)
            return None

    @staticmethod
    def _node_to_text(result: Any) -> str | None:
        if isinstance(result, list):
            if not result:
                return None
            result = result[0]
        if result is None:
            return None
        if hasattr(result, "text_content"):
            return str(result.text_content())
        if hasattr(result, "itertext"):
            return "".join(result.itertext())
        return str(result)

    def _parse_time(
        self, raw: str, spec: dict[str, Any], crawl_date: datetime.date
    ) -> datetime.datetime | None:
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

    def _urls_to_crawl(
        self,
        days: int,
        start_day: datetime.date,
        override: str | None = None,
    ) -> Iterator[tuple[str, datetime.date]]:
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
    def _is_dated(url: str) -> bool:
        return any(token in url for token in DATE_PLACEHOLDERS)
