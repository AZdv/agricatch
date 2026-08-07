"""Crawling beyond a single page: object_url, pagination and per-field url.

The kidsil cases run against real saved pages - a real index, a real post - so
they check the shapes the site actually has. The synthetic ones cover the
mechanics that no source here happens to use.
"""

import pytest

from agricatch.fetch import CrawlLimitReached, FetchError, FetchSession
from agricatch.website import Website
from tech.websites.kidsil import Kidsil

INDEX = "https://www.kidsil.net/"
PAGE_2 = "https://www.kidsil.net/page/2/"
DETAIL = "https://www.kidsil.net/2026/07/singlefile-swallowed-aws-cost-explorer-whole/"


class FakeSession:
    """Serves saved pages and 404s anything else, recording what was asked for."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        if url not in self.pages:
            raise FetchError(f"no such page: {url}")
        return self.pages[url]


@pytest.fixture
def kidsil_pages(fixture_bytes):
    return {
        INDEX: fixture_bytes("kidsil.html"),
        PAGE_2: fixture_bytes("kidsil-page2.html"),
        DETAIL: fixture_bytes("kidsil-detail.html"),
    }


# ---- object_url, against the real site ------------------------------


def test_fields_come_from_the_detail_page(kidsil_pages):
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    records = Kidsil().collect(session=session)

    assert len(records) == 1  # only one detail page was available
    record = records[0]
    assert record["name"] == "SingleFile Swallowed AWS Cost Explorer Whole"
    assert record["link"] == DETAIL
    assert record["time"].year == 2026


def test_the_detail_page_body_is_the_full_post(kidsil_pages):
    """The point of the exercise: the listing only carries an excerpt."""
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    body = Kidsil().collect(session=session)[0]["description"]

    assert len(body) > 1500
    assert "fabricated" in body or "SingleFile" in body


def test_the_index_is_fetched_before_any_detail(kidsil_pages):
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    Kidsil().collect(session=session)
    assert session.requested[0] == INDEX
    assert DETAIL in session.requested


def test_an_unreachable_detail_page_drops_only_that_record(kidsil_pages):
    """Four of the five posts 404 here; the run must still yield the fifth."""
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    assert len(Kidsil().collect(session=session)) == 1


def test_images_are_absolutised_from_the_detail_page(kidsil_pages):
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    image = Kidsil().collect(session=session)[0]["image"]
    assert image.startswith("https://media.kidsil.net/")


def test_the_blog_has_no_byline_and_records_survive_it(kidsil_pages):
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    assert "author" not in Kidsil().collect(session=session)[0]


# ---- pagination ------------------------------------------------------


def test_pagination_follows_the_next_link(kidsil_pages):
    session = FakeSession(kidsil_pages)
    Kidsil().collect(session=session)
    assert PAGE_2 in session.requested


def test_an_endless_chain_stops_at_the_budget_with_records_intact(monkeypatch):
    """A "next page" link that goes on forever must end at max_pages, not raise."""

    def endless(url, timeout=None):
        number = int(url.rsplit("/", 1)[1])
        return (
            f'<html><ul><li>page{number}</li></ul><a href="/{number + 1}">next</a></html>'
        ).encode()

    monkeypatch.setattr("agricatch.fetch.fetch_bytes", endless)

    class Endless(Website):
        parser = "html"
        url_info = {"url": "https://example.com/0"}
        structure = {
            "child_xpath": "//li",
            "pagination": "//a",
            "fields": {"name": {"xpath": "text()"}},
        }

    records = Endless().collect(session=FetchSession(delay=0, max_pages=3))
    assert [r["name"] for r in records] == ["page0", "page1", "page2"]


def test_a_page_is_never_visited_twice():
    class Loop(Website):
        parser = "html"
        url_info = {"url": "https://example.com/a"}
        structure = {
            "child_xpath": "//li",
            "pagination": "//a",
            "fields": {"name": {"xpath": "text()"}},
        }

    pages = {
        "https://example.com/a": b'<html><ul><li>one</li></ul><a href="/b">b</a></html>',
        # b points straight back at a
        "https://example.com/b": b'<html><ul><li>two</li></ul><a href="/a">a</a></html>',
    }
    session = FakeSession(pages)
    records = Loop().collect(session=session)

    assert sorted(r["name"] for r in records) == ["one", "two"]
    assert session.requested.count("https://example.com/a") == 1


# ---- per-field url and nested scoping --------------------------------


def test_a_single_field_can_come_from_another_page():
    class SplitFields(Website):
        parser = "html"
        url_info = {"url": "https://example.com/"}
        structure = {
            "child_xpath": "//li",
            "fields": {
                "name": {"xpath": "h2/text()"},
                # The body lives behind the link, not on the index.
                "description": {"url": "a/@href", "xpath": "//p[@id='body']/text()"},
            },
        }

    pages = {
        "https://example.com/": (
            b'<html><ul><li><h2>Title</h2><a href="/full">go</a></li></ul></html>'
        ),
        "https://example.com/full": b'<html><p id="body">the whole thing</p></html>',
    }
    record = SplitFields().collect(session=FakeSession(pages))[0]

    assert record["name"] == "Title"
    assert record["description"] == "the whole thing"


def test_a_field_needing_a_fetch_without_a_session_is_dropped(fixture_bytes):
    class NeedsFetch(Website):
        parser = "html"
        url_info = {"url": "https://example.com/"}
        structure = {
            "child_xpath": "//li",
            "fields": {"description": {"url": "a/@href", "xpath": "//p/text()"}},
        }

    importer = NeedsFetch()
    tree = importer.parse(b'<html><ul><li><a href="/x">go</a></li></ul></html>')
    node = importer.select_nodes(tree)[0]
    assert importer.extract_record(node) is None


def test_object_url_child_xpath_scopes_into_the_detail_page():
    class Scoped(Website):
        parser = "html"
        url_info = {"url": "https://example.com/"}
        structure = {
            "child_xpath": "//li",
            "object_url": "a/@href",
            "object_url_child_xpath": '//div[@class="main"]',
            "fields": {"name": {"xpath": "h1/text()"}},
        }

    pages = {
        "https://example.com/": b'<html><ul><li><a href="/p">go</a></li></ul></html>',
        # The h1 outside .main must be ignored.
        "https://example.com/p": (
            b'<html><h1>sidebar</h1><div class="main"><h1>real title</h1></div></html>'
        ),
    }
    assert Scoped().collect(session=FakeSession(pages))[0]["name"] == "real title"


def test_a_missing_object_url_skips_the_record():
    class NoLink(Website):
        parser = "html"
        url_info = {"url": "https://example.com/"}
        structure = {
            "child_xpath": "//li",
            "object_url": "a/@href",
            "fields": {"name": {"xpath": "h1/text()"}},
        }

    pages = {"https://example.com/": b"<html><ul><li>no anchor here</li></ul></html>"}
    assert NoLink().collect(session=FakeSession(pages)) == []


# ---- the session itself ----------------------------------------------


def test_session_serves_a_repeated_url_from_memory(monkeypatch):
    calls = []

    def fake_fetch(url, timeout=None):
        calls.append(url)
        return b"<html></html>"

    monkeypatch.setattr("agricatch.fetch.fetch_bytes", fake_fetch)
    session = FetchSession(delay=0)

    session.get("https://example.com/x")
    session.get("https://example.com/x")

    assert calls == ["https://example.com/x"]
    assert session.fetched == 1


def test_session_stops_at_its_page_budget(monkeypatch):
    monkeypatch.setattr("agricatch.fetch.fetch_bytes", lambda url, timeout=None: b"<html></html>")
    session = FetchSession(delay=0, max_pages=2)

    session.get("https://example.com/1")
    session.get("https://example.com/2")
    with pytest.raises(CrawlLimitReached):
        session.get("https://example.com/3")


def test_session_paces_requests(monkeypatch):
    monkeypatch.setattr("agricatch.fetch.fetch_bytes", lambda url, timeout=None: b"<html></html>")
    slept = []
    monkeypatch.setattr("agricatch.fetch.time.sleep", slept.append)

    session = FetchSession(delay=0.5)
    session.get("https://example.com/1")
    session.get("https://example.com/2")

    assert slept and slept[0] > 0
