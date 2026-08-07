"""The ``table`` field type: nested records resolved into related rows."""

import pytest

from agricatch.website import RelatedRecord, Website
from tech.models import Article, Author
from tech.websites.cnet import Cnet
from tech.websites.techcrunch import Techcrunch

ITEMS = b"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
  <item>
    <title>First</title><link>https://example.com/1</link>
    <pubDate>Tue, 06 May 2024 10:00:00 +0000</pubDate>
    <dc:creator>Ada Lovelace</dc:creator>
  </item>
  <item>
    <title>Second</title><link>https://example.com/2</link>
    <pubDate>Tue, 06 May 2024 11:00:00 +0000</pubDate>
    <dc:creator>Ada Lovelace</dc:creator>
  </item>
  <item>
    <title>Third</title><link>https://example.com/3</link>
    <pubDate>Tue, 06 May 2024 12:00:00 +0000</pubDate>
  </item>
</channel></rss>"""


def records_from(importer, payload):
    tree = importer.parse(payload)
    return [importer.extract_record(node) for node in importer.select_nodes(tree)]


# ---- extraction ------------------------------------------------------


def test_table_field_extracts_a_related_record():
    records = records_from(Techcrunch(), ITEMS)
    related = records[0]["author"]
    assert isinstance(related, RelatedRecord)
    assert related.model == "Author"
    assert related.lookup == ("name",)
    assert related.values == {"name": "Ada Lovelace"}


def test_optional_table_field_absent_leaves_the_key_out():
    records = records_from(Techcrunch(), ITEMS)
    assert "author" not in records[2]
    assert records[2]["name"] == "Third"


def test_required_table_field_absent_drops_the_record():
    importer = Techcrunch()
    importer.structure["fields"]["author"]["required"] = True
    records = records_from(importer, ITEMS)
    assert records[2] is None
    assert records[0] is not None


def test_child_xpath_scopes_the_nested_fields(fixture_bytes):
    """CNET nests the byline under <author>, so the spec scopes into it."""
    records = records_from(Cnet(), fixture_bytes("cnet.xml"))
    authors = [r["author"] for r in records if r.get("author")]
    assert authors
    assert all(a.values["name"].strip() for a in authors)


def test_lookup_defaults_to_every_extracted_field():
    class Implicit(Website):
        namespaces = {"dc": "http://purl.org/dc/elements/1.1/"}
        url_info = {"url": "https://example.com/"}
        structure = {
            "child_xpath": "//item",
            "fields": {
                "name": {"xpath": "title/text()"},
                "author": {
                    "type": "table",
                    "model": "Author",
                    "fields": {"name": {"xpath": "dc:creator/text()"}},
                },
            },
        }

    assert records_from(Implicit(), ITEMS)[0]["author"].lookup == ("name",)


def test_tables_nest():
    """A related record may itself contain one."""

    class Nested(Website):
        namespaces = {"dc": "http://purl.org/dc/elements/1.1/"}
        url_info = {"url": "https://example.com/"}
        structure = {
            "child_xpath": "//item",
            "fields": {
                "outer": {
                    "type": "table",
                    "model": "Author",
                    "lookup": ["name"],
                    "fields": {
                        "name": {"xpath": "dc:creator/text()"},
                        "inner": {
                            "type": "table",
                            "model": "Website",
                            "lookup": ["slug"],
                            "fields": {"slug": {"xpath": "title/text()"}},
                        },
                    },
                }
            },
        }

    outer = records_from(Nested(), ITEMS)[0]["outer"]
    assert outer.values["name"] == "Ada Lovelace"
    assert outer.values["inner"].model == "Website"
    assert outer.values["inner"].values == {"slug": "First"}


@pytest.mark.parametrize("missing", ["model", "fields"])
def test_malformed_table_spec_is_reported(missing):
    spec = {"type": "table", "model": "Author", "fields": {"name": {"xpath": "x"}}}
    del spec[missing]

    importer = Techcrunch()
    importer.structure["fields"]["author"] = spec
    with pytest.raises(ValueError, match="table field"):
        records_from(importer, ITEMS)


# ---- persistence -----------------------------------------------------


@pytest.mark.django_db
def test_persist_creates_the_related_row_and_links_it():
    importer = Techcrunch()
    importer.persist([r for r in records_from(importer, ITEMS) if r])

    assert Author.objects.count() == 1
    author = Author.objects.get()
    assert author.name == "Ada Lovelace"
    assert set(author.articles.values_list("name", flat=True)) == {"First", "Second"}


@pytest.mark.django_db
def test_the_same_author_is_reused_not_duplicated():
    importer = Techcrunch()
    records = [r for r in records_from(importer, ITEMS) if r]

    importer.persist(records)
    importer.persist(records)

    assert Author.objects.count() == 1
    assert Article.objects.count() == 3


@pytest.mark.django_db
def test_article_without_an_author_persists_with_a_null_fk():
    importer = Techcrunch()
    importer.persist([r for r in records_from(importer, ITEMS) if r])
    assert Article.objects.get(name="Third").author is None


@pytest.mark.django_db
def test_resolve_related_is_a_no_op_for_plain_values():
    importer = Techcrunch()
    assert importer.resolve_related("plain") == "plain"
    assert importer.resolve_related(None) is None


@pytest.mark.django_db
def test_existing_related_row_is_not_overwritten():
    Author.objects.create(name="Ada Lovelace")
    importer = Techcrunch()
    importer.persist([r for r in records_from(importer, ITEMS) if r])
    assert Author.objects.count() == 1
