"""Extraction runs against saved captures, so these assert real feed shapes."""

import datetime

import pytest
from lxml import html as lxml_html

from tech.websites.cnet import Cnet
from tech.websites.gizmodo import Gizmodo
from tech.websites.techcrunch import Techcrunch


def records_from(importer, payload):
    tree = importer.parse(payload)
    nodes = importer.select_nodes(tree)
    return nodes, [importer.extract_record(node) for node in nodes]


FEEDS = [
    (Techcrunch, "techcrunch.xml", 20),
    (Gizmodo, "gizmodo.xml", 20),
    (Cnet, "cnet.xml", 25),
]


@pytest.mark.parametrize("importer_class,fixture,expected", FEEDS)
def test_every_node_yields_a_record(importer_class, fixture, expected, fixture_bytes):
    nodes, records = records_from(importer_class(), fixture_bytes(fixture))
    assert len(nodes) == expected
    assert [r for r in records if r is not None] == records


@pytest.mark.parametrize("importer_class,fixture", [(cls, fixture) for cls, fixture, _ in FEEDS])
def test_core_fields_are_populated(importer_class, fixture, fixture_bytes):
    _, records = records_from(importer_class(), fixture_bytes(fixture))
    for record in records:
        assert record["name"].strip()
        assert record["link"].startswith("http")
        assert isinstance(record["time"], datetime.datetime)
        assert record["time"].tzinfo is not None


def test_rss_author_comes_from_the_dc_namespace(fixture_bytes):
    _, records = records_from(Techcrunch(), fixture_bytes("techcrunch.xml"))
    authors = [r["author"] for r in records if r.get("author")]
    assert authors
    assert all(a.model == "Author" for a in authors)
    assert all(a.values["name"].strip() for a in authors)


def test_html_parser_would_lose_the_rss_link(fixture_bytes):
    """Why feeds use the XML parser.

    <link> is a void element in HTML, so an HTML parse drops its text and the
    article URL disappears. This guards against anyone 'simplifying' parse().
    """
    payload = fixture_bytes("techcrunch.xml")
    as_html = lxml_html.fromstring(payload)
    assert as_html.xpath("//item")
    assert not any(node.text_content().strip() for node in as_html.xpath("//item/link"))

    importer = Techcrunch()
    _, records = records_from(importer, payload)
    assert all(r["link"].startswith("http") for r in records)


def test_missing_required_field_drops_the_record(fixture_bytes):
    class Strict(Techcrunch):
        pass

    importer = Strict()
    importer.structure["fields"]["author"] = {"xpath": "nonexistent/text()"}
    _, records = records_from(importer, fixture_bytes("techcrunch.xml"))
    assert records and all(r is None for r in records)
