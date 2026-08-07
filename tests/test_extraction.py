"""Extraction runs against saved captures, so these assert real feed shapes."""

import datetime

import pytest
from lxml import html as lxml_html

from tech.websites.cnet import Cnet
from tech.websites.gizmodo import Gizmodo
from tech.websites.kidsil import Kidsil
from tech.websites.techcrunch import Techcrunch


def records_from(importer, payload):
    tree = importer.parse(payload)
    nodes = importer.select_nodes(tree)
    return nodes, [importer.extract_record(node) for node in nodes]


@pytest.mark.parametrize(
    "importer_class,fixture,expected",
    [
        (Techcrunch, "techcrunch.xml", 20),
        (Gizmodo, "gizmodo.xml", 20),
        (Cnet, "cnet.xml", 25),
        (Kidsil, "kidsil.html", 5),
    ],
)
def test_every_node_yields_a_record(importer_class, fixture, expected, fixture_bytes):
    nodes, records = records_from(importer_class(), fixture_bytes(fixture))
    assert len(nodes) == expected
    assert [r for r in records if r is not None] == records


@pytest.mark.parametrize(
    "importer_class,fixture",
    [
        (Techcrunch, "techcrunch.xml"),
        (Gizmodo, "gizmodo.xml"),
        (Cnet, "cnet.xml"),
        (Kidsil, "kidsil.html"),
    ],
)
def test_core_fields_are_populated(importer_class, fixture, fixture_bytes):
    _, records = records_from(importer_class(), fixture_bytes(fixture))
    for record in records:
        assert record["name"].strip()
        assert record["link"].startswith("http")
        assert isinstance(record["time"], datetime.datetime)
        assert record["time"].tzinfo is not None


def test_rss_author_comes_from_the_dc_namespace(fixture_bytes):
    _, records = records_from(Techcrunch(), fixture_bytes("techcrunch.xml"))
    assert any(r.get("author") for r in records)


def test_kidsil_urls_are_absolute(fixture_bytes):
    _, records = records_from(Kidsil(), fixture_bytes("kidsil.html"))
    for record in records:
        assert record["link"].startswith("https://www.kidsil.net/")
        if record.get("image"):
            assert record["image"].startswith("https://")


def test_kidsil_has_no_author_and_survives_it(fixture_bytes):
    """The blog exposes no byline; an optional field must not drop the record."""
    _, records = records_from(Kidsil(), fixture_bytes("kidsil.html"))
    assert len(records) == 5
    assert all("author" not in r for r in records)


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
