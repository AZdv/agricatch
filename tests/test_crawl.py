"""Crawling beyond a single page: object_url, pagination and per-field url.

The kidsil cases run against real saved pages - a real index, a real post - so
they check the shapes the site actually has. The synthetic ones cover the
mechanics that no source here happens to use.
"""

import threading
import time
from collections.abc import Callable, Iterable

import pytest

from agricatch.fetch import CrawlLimitReached, FetchError, FetchSession
from agricatch.website import Website
from tech.websites.kidsil import Kidsil

INDEX = "https://www.kidsil.net/"
PAGE_2 = "https://www.kidsil.net/page/2/"
DETAIL = "https://www.kidsil.net/2026/07/singlefile-swallowed-aws-cost-explorer-whole/"


class FakeSession:
    """Serves saved pages and 404s anything else, recording what was asked for."""

    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.requested: list[str] = []
        self.prefetched: list[list[str]] = []

    def get(self, url: str) -> bytes:
        self.requested.append(url)
        if url not in self.pages:
            raise FetchError(f"no such page: {url}")
        return self.pages[url]

    def prefetch(self, urls: Iterable[str]) -> None:
        self.prefetched.append(list(urls))


class GetOnlySession(FakeSession):
    """A stand-in with no prefetch, to prove the crawl copes without one."""

    prefetch = None  # type: ignore[assignment]


@pytest.fixture
def kidsil_pages(fixture_bytes: Callable[[str], bytes]) -> dict[str, bytes]:
    return {
        INDEX: fixture_bytes("kidsil.html"),
        PAGE_2: fixture_bytes("kidsil-page2.html"),
        DETAIL: fixture_bytes("kidsil-detail.html"),
    }


# ---- object_url, against the real site ------------------------------


def test_fields_come_from_the_detail_page(kidsil_pages: dict[str, bytes]) -> None:
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    records = Kidsil().collect(session=session)

    assert len(records) == 1  # only one detail page was available
    record = records[0]
    assert record["name"] == "SingleFile Swallowed AWS Cost Explorer Whole"
    assert record["link"] == DETAIL
    assert record["time"].year == 2026


def test_the_detail_page_body_is_the_full_post(kidsil_pages: dict[str, bytes]) -> None:
    """The point of the exercise: the listing only carries an excerpt."""
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    body = Kidsil().collect(session=session)[0]["description"]

    assert len(body) > 1500
    assert "fabricated" in body or "SingleFile" in body


def test_the_index_is_fetched_before_any_detail(kidsil_pages: dict[str, bytes]) -> None:
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    Kidsil().collect(session=session)
    assert session.requested[0] == INDEX
    assert DETAIL in session.requested


def test_an_unreachable_detail_page_drops_only_that_record(kidsil_pages: dict[str, bytes]) -> None:
    """Four of the five posts 404 here; the run must still yield the fifth."""
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    assert len(Kidsil().collect(session=session)) == 1


def test_images_are_absolutised_from_the_detail_page(kidsil_pages: dict[str, bytes]) -> None:
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    image = Kidsil().collect(session=session)[0]["image"]
    assert image.startswith("https://media.kidsil.net/")


def test_the_blog_has_no_byline_and_records_survive_it(kidsil_pages: dict[str, bytes]) -> None:
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    assert "author" not in Kidsil().collect(session=session)[0]


# ---- pagination ------------------------------------------------------


def test_pagination_follows_the_next_link(kidsil_pages: dict[str, bytes]) -> None:
    session = FakeSession(kidsil_pages)
    Kidsil().collect(session=session)
    assert PAGE_2 in session.requested


def test_an_endless_chain_stops_at_the_budget_with_records_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A "next page" link that goes on forever must end at max_pages, not raise."""

    def endless(url: str, timeout: float | None = None) -> bytes:
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


def test_a_budget_that_runs_out_mid_page_keeps_what_was_already_extracted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once each record costs its own request, the budget can end partway down a page.

    The earlier test only ever stopped on a page boundary, so it never noticed
    that unwinding out of the page loop threw away everything gathered on it.
    """
    index = b"".join(b'<li><a href="/post-%d">p</a></li>' % n for n in range(5))
    pages = {
        "https://example.com/": b"<html><ul>" + index + b"</ul></html>",
        **{
            f"https://example.com/post-{n}": f"<html><h1>Post {n}</h1></html>".encode()
            for n in range(5)
        },
    }

    def serve(url: str, timeout: float | None = None) -> bytes:
        return pages[url]

    monkeypatch.setattr("agricatch.fetch.fetch_bytes", serve)

    class Detailed(Website):
        parser = "html"
        url_info = {"url": "https://example.com/"}
        structure = {
            "child_xpath": "//li",
            "object_url": "a/@href",
            "fields": {"name": {"xpath": "//h1/text()"}},
        }

    # 1 for the index + 3 details, so the budget dies on the fourth record.
    records = Detailed().collect(session=FetchSession(delay=0, max_pages=4))

    assert [r["name"] for r in records] == ["Post 0", "Post 1", "Post 2"]


def test_a_page_is_never_visited_twice() -> None:
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


def test_a_single_field_can_come_from_another_page() -> None:
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


def test_a_field_needing_a_fetch_without_a_session_is_dropped(
    fixture_bytes: Callable[[str], bytes],
) -> None:
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


def test_object_url_child_xpath_scopes_into_the_detail_page() -> None:
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


def test_a_missing_object_url_skips_the_record() -> None:
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


def test_session_serves_a_repeated_url_from_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_fetch(url: str, timeout: float | None = None) -> bytes:
        calls.append(url)
        return b"<html></html>"

    monkeypatch.setattr("agricatch.fetch.fetch_bytes", fake_fetch)
    session = FetchSession(delay=0)

    session.get("https://example.com/x")
    session.get("https://example.com/x")

    assert calls == ["https://example.com/x"]
    assert session.fetched == 1


def test_session_stops_at_its_page_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agricatch.fetch.fetch_bytes", lambda url, timeout=None: b"<html></html>")
    session = FetchSession(delay=0, max_pages=2)

    session.get("https://example.com/1")
    session.get("https://example.com/2")
    with pytest.raises(CrawlLimitReached):
        session.get("https://example.com/3")


def test_session_paces_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agricatch.fetch.fetch_bytes", lambda url, timeout=None: b"<html></html>")
    slept: list[float] = []
    monkeypatch.setattr("agricatch.fetch.time.sleep", slept.append)

    session = FetchSession(delay=0.5)
    session.get("https://example.com/1")
    session.get("https://example.com/2")

    assert slept and slept[0] > 0


# ---- overlapping requests --------------------------------------------


def slow_server(latency: float, starts: list[float], lock: threading.Lock) -> Callable[..., bytes]:
    def fetch(url: str, timeout: float | None = None) -> bytes:
        with lock:
            starts.append(time.monotonic())
        time.sleep(latency)
        return b"<html></html>"

    return fetch


def test_detail_pages_are_prefetched_together(kidsil_pages: dict[str, bytes]) -> None:
    session = FakeSession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    Kidsil().collect(session=session)

    assert session.prefetched, "the index's detail links should be warmed in one batch"
    assert DETAIL in session.prefetched[0]
    assert len(session.prefetched[0]) == 5


def test_a_session_without_prefetch_still_works(kidsil_pages: dict[str, bytes]) -> None:
    session = GetOnlySession({INDEX: kidsil_pages[INDEX], DETAIL: kidsil_pages[DETAIL]})
    assert len(Kidsil().collect(session=session)) == 1


def test_concurrency_never_raises_the_request_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The property that keeps this from getting anyone banned.

    Four workers may be in flight at once, but request *starts* stay spaced by
    ``delay``, so the host is knocked at exactly the serial rate.
    """
    starts: list[float] = []
    lock = threading.Lock()
    monkeypatch.setattr("agricatch.fetch.fetch_bytes", slow_server(0.15, starts, lock))

    session = FetchSession(delay=0.05, max_concurrency=4, max_pages=None)
    session.prefetch([f"https://example.com/{n}" for n in range(8)])

    assert len(starts) == 8
    ordered = sorted(starts)
    gaps = [b - a for a, b in zip(ordered, ordered[1:], strict=False)]
    assert min(gaps) >= 0.045, f"requests started {min(gaps):.3f}s apart, faster than the delay"


def test_overlapping_beats_serial_when_the_server_is_slow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [f"https://example.com/{n}" for n in range(6)]

    def run(concurrency: int) -> float:
        starts: list[float] = []
        lock = threading.Lock()
        monkeypatch.setattr("agricatch.fetch.fetch_bytes", slow_server(0.15, starts, lock))
        session = FetchSession(delay=0.0, max_concurrency=concurrency, max_pages=None)
        started = time.monotonic()
        session.prefetch(urls)
        return time.monotonic() - started

    serial = run(1)
    overlapped = run(3)
    assert overlapped < serial * 0.8, f"serial {serial:.2f}s vs overlapped {overlapped:.2f}s"


def test_prefetch_skips_what_is_already_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def counting(url: str, timeout: float | None = None) -> bytes:
        calls.append(url)
        return b"<html></html>"

    monkeypatch.setattr("agricatch.fetch.fetch_bytes", counting)
    session = FetchSession(delay=0, max_concurrency=2)

    session.get("https://example.com/a")
    session.prefetch(["https://example.com/a", "https://example.com/b"])

    assert sorted(calls) == ["https://example.com/a", "https://example.com/b"]


def test_prefetch_dedupes_repeated_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def counting(url: str, timeout: float | None = None) -> bytes:
        calls.append(url)
        return b"<html></html>"

    monkeypatch.setattr("agricatch.fetch.fetch_bytes", counting)
    session = FetchSession(delay=0, max_concurrency=3)
    session.prefetch(["https://example.com/a"] * 5)

    assert calls == ["https://example.com/a"]


def test_prefetch_swallows_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def sometimes(url: str, timeout: float | None = None) -> bytes:
        if url.endswith("bad"):
            raise FetchError("nope")
        return b"<html></html>"

    monkeypatch.setattr("agricatch.fetch.fetch_bytes", sometimes)
    session = FetchSession(delay=0, max_concurrency=2)

    session.prefetch(["https://example.com/bad", "https://example.com/good"])
    assert session.get("https://example.com/good") == b"<html></html>"


def test_the_budget_holds_under_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agricatch.fetch.fetch_bytes", lambda url, timeout=None: b"<html></html>")
    session = FetchSession(delay=0, max_concurrency=8, max_pages=5)

    session.prefetch([f"https://example.com/{n}" for n in range(20)])
    assert session.fetched == 5


# ---- fetch failures are visible, not just logged ----------------------


def test_a_fetch_failure_is_recorded_not_only_logged(kidsil_pages: dict[str, bytes]) -> None:
    """No records plus no errors means the layout moved; no records plus a 403
    means the source turned us away. A caller cannot tell those apart unless the
    failures survive the call."""
    session = FakeSession({INDEX: kidsil_pages[INDEX]})  # every detail page 404s
    importer = Kidsil()
    importer.collect(session=session)

    assert importer.errors
    assert all("no such page" in message for message in importer.errors)


class Simple(Website):
    """One page, no detail fetches, so the error list is entirely predictable."""

    parser = "html"
    url_info = {"url": "https://example.com/"}
    structure = {"child_xpath": "//li", "fields": {"name": {"xpath": "text()"}}}


ONE_PAGE = {"https://example.com/": b"<html><ul><li>only</li></ul></html>"}


def test_a_crawl_that_reaches_everything_records_no_errors() -> None:
    importer = Simple()
    records = importer.collect(session=FakeSession(ONE_PAGE))

    assert [r["name"] for r in records] == ["only"]
    assert importer.errors == []


def test_errors_from_one_run_do_not_leak_into_the_next() -> None:
    importer = Simple()

    importer.collect(session=FakeSession({}))  # nothing reachable
    assert importer.errors

    importer.collect(session=FakeSession(ONE_PAGE))  # all reachable
    assert importer.errors == []


def test_an_unreachable_seed_is_reported() -> None:
    class Unreachable(Website):
        parser = "html"
        url_info = {"url": "https://example.com/"}
        structure = {"child_xpath": "//li", "fields": {}}

    importer = Unreachable()
    assert importer.collect(session=FakeSession({})) == []
    assert importer.errors


# ---- telling "refused us" apart from "layout moved" -------------------


class Refusing(FakeSession):
    """Answers every request with a given refusal, the way a blocking site does."""

    def __init__(self, message: str) -> None:
        super().__init__({})
        self.message = message

    def get(self, url: str) -> bytes:
        self.requested.append(url)
        raise FetchError(f"could not fetch {url}: {self.message}")


def test_a_403_is_reported_as_a_refusal() -> None:
    """What CI hits weekly: gizmodo answers 403 to a datacenter IP."""
    importer = Simple()
    assert importer.collect(session=Refusing("Client error '403 Forbidden'")) == []
    assert importer.refusal is not None
    assert "403" in importer.refusal


def test_a_429_is_reported_as_a_refusal() -> None:
    importer = Simple()
    importer.collect(session=Refusing("Client error '429 Too Many Requests'"))
    assert importer.refusal is not None


def test_an_ordinary_failure_is_not_a_refusal() -> None:
    """A 404 or a timeout is not the source turning us away on purpose."""
    importer = Simple()
    importer.collect(session=Refusing("Client error '404 Not Found'"))
    assert importer.errors
    assert importer.refusal is None


def test_reaching_the_page_and_finding_nothing_is_not_a_refusal() -> None:
    """The case that SHOULD go red: we got in, the xpaths matched nothing."""
    importer = Simple()
    empty = {"https://example.com/": b"<html><ul></ul></html>"}

    assert importer.collect(session=FakeSession(empty)) == []
    assert importer.errors == []
    assert importer.refusal is None
