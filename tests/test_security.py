"""Guards on what a crawler is allowed to fetch and parse.

A crawler follows links somebody else wrote, so every URL it is handed is a
request from an untrusted party, and every feed it parses is untrusted bytes.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from agricatch.fetch import BlockedURL, FetchError, check_public_url, fetch_bytes
from agricatch.website import Website

PUBLIC_IP = "93.184.216.34"  # a literal, so none of this needs DNS


# ---- where the crawler may go ----------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",  # cloud instance metadata
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
def test_non_public_addresses_are_refused(url: str) -> None:
    with pytest.raises(BlockedURL):
        check_public_url(url)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/", "/just/a/path"]
)
def test_non_http_schemes_are_refused(url: str) -> None:
    with pytest.raises(BlockedURL):
        check_public_url(url)


def test_a_public_address_is_allowed() -> None:
    check_public_url(f"http://{PUBLIC_IP}/some/page")


def test_the_metadata_endpoint_is_refused_even_via_fetch_bytes() -> None:
    with pytest.raises(BlockedURL):
        fetch_bytes("http://169.254.169.254/latest/meta-data/")


# ---- redirects are re-checked, not trusted ---------------------------


class StreamedResponse:
    """Minimal stand-in for what httpx hands back from stream()."""

    def __init__(self, response: httpx.Response, chunks: Iterator[bytes] | None = None) -> None:
        self._response = response
        self._chunks = chunks

    def __enter__(self) -> Any:
        if self._chunks is not None:
            chunks = self._chunks
            self._response.iter_bytes = lambda *a, **k: chunks  # type: ignore[method-assign]
        return self._response

    def __exit__(self, *exc: Any) -> None:
        return None


class RedirectingClient:
    """Sends everything to one destination, once."""

    def __init__(self, destination: str) -> None:
        self.destination = destination
        self.requested: list[str] = []

    def stream(self, method: str, url: str, **kwargs: Any) -> StreamedResponse:
        self.requested.append(url)
        request = httpx.Request(method, url)
        if len(self.requested) == 1:
            return StreamedResponse(
                httpx.Response(302, headers={"location": self.destination}, request=request)
            )
        return StreamedResponse(httpx.Response(200, content=b"<html>ok</html>", request=request))

    def close(self) -> None:
        return None


def test_a_redirect_into_a_private_address_is_refused() -> None:
    """The first URL passes the check; the hop it bounces to must be checked too."""
    client = RedirectingClient("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(BlockedURL):
        fetch_bytes(f"http://{PUBLIC_IP}/start", client=client)


def test_a_redirect_to_another_public_address_is_followed() -> None:
    client = RedirectingClient(f"http://{PUBLIC_IP}/second")
    assert fetch_bytes(f"http://{PUBLIC_IP}/start", client=client) == b"<html>ok</html>"


def test_a_relative_redirect_resolves_against_the_current_url() -> None:
    client = RedirectingClient("/second")
    fetch_bytes(f"http://{PUBLIC_IP}/first/start", client=client)
    assert client.requested[1] == f"http://{PUBLIC_IP}/second"


def test_a_redirect_loop_gives_up() -> None:
    class Loop:
        def stream(self, method: str, url: str, **kwargs: Any) -> StreamedResponse:
            return StreamedResponse(
                httpx.Response(
                    302,
                    headers={"location": f"http://{PUBLIC_IP}/again"},
                    request=httpx.Request(method, url),
                )
            )

        def close(self) -> None:
            return None

    with pytest.raises(FetchError, match="too many redirects"):
        fetch_bytes(f"http://{PUBLIC_IP}/start", client=Loop())


# ---- how much it is willing to swallow -------------------------------


class Endless:
    """Streams forever, counting how much was actually pulled."""

    def __init__(self) -> None:
        self.chunks_served = 0

    def _forever(self) -> Iterator[bytes]:
        while True:
            self.chunks_served += 1
            yield b"x" * 1024

    def stream(self, method: str, url: str, **kwargs: Any) -> StreamedResponse:
        return StreamedResponse(
            httpx.Response(200, request=httpx.Request(method, url)), self._forever()
        )

    def close(self) -> None:
        return None


def test_an_endless_body_is_cut_off_rather_than_swallowed() -> None:
    """The point of streaming: stop pulling, rather than measure it afterwards."""
    client = Endless()
    with pytest.raises(FetchError, match="more than"):
        fetch_bytes(f"http://{PUBLIC_IP}/big", client=client, max_bytes=4096)

    # It gave up almost immediately instead of reading an unbounded body.
    assert client.chunks_served <= 6


def test_a_declared_content_length_over_the_limit_is_refused_before_reading() -> None:
    class Declares:
        def __init__(self) -> None:
            self.read = False

        def stream(self, method: str, url: str, **kwargs: Any) -> StreamedResponse:
            response = httpx.Response(
                200,
                headers={"content-length": "99999999"},
                request=httpx.Request(method, url),
            )
            return StreamedResponse(response)

        def close(self) -> None:
            return None

    with pytest.raises(FetchError, match="declares more than"):
        fetch_bytes(f"http://{PUBLIC_IP}/big", client=Declares(), max_bytes=1000)


# ---- what it is willing to parse -------------------------------------


XXE_FEED = b"""<?xml version="1.0"?>
<!DOCTYPE rss [ <!ENTITY xxe SYSTEM "file://%s"> ]>
<rss><channel><item><title>&xxe;</title><link>http://e.test/1</link>
<pubDate>Tue, 06 May 2024 10:00:00 +0000</pubDate></item></channel></rss>"""


class Feed(Website):
    url_info = {"url": "https://e.test/"}
    structure = {
        "child_xpath": "//channel/item",
        "fields": {
            "name": {"xpath": "title/text()"},
            "link": {"xpath": "link/text()"},
            "time": {"type": "time", "xpath": "pubDate/text()"},
        },
    }


def test_an_external_entity_is_not_expanded_into_a_record(tmp_path: Path) -> None:
    """A feed that tries to read a local file must come back empty, not with the file."""
    secret = tmp_path / "secret.txt"
    secret.write_text("canary-value", encoding="utf-8")

    importer = Feed()
    tree = importer.parse(XXE_FEED % str(secret).encode())
    nodes = importer.select_nodes(tree)

    record = importer.extract_record(nodes[0]) if nodes else None
    assert record is None or "canary" not in record.get("name", "")
