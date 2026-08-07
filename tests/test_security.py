"""Guards on what a crawler is allowed to fetch and parse.

A crawler follows links somebody else wrote, so every URL it is handed is a
request from an untrusted party, and every feed it parses is untrusted bytes.
"""

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


class RedirectingClient:
    """Sends everything to one destination, once."""

    def __init__(self, destination: str) -> None:
        self.destination = destination
        self.requested: list[str] = []

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requested.append(url)
        request = httpx.Request("GET", url)
        if len(self.requested) == 1:
            return httpx.Response(302, headers={"location": self.destination}, request=request)
        return httpx.Response(200, content=b"<html>ok</html>", request=request)

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


def test_a_redirect_loop_gives_up() -> None:
    class Loop:
        def get(self, url: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"location": f"http://{PUBLIC_IP}/again"},
                request=httpx.Request("GET", url),
            )

        def close(self) -> None:
            return None

    with pytest.raises(FetchError, match="too many redirects"):
        fetch_bytes(f"http://{PUBLIC_IP}/start", client=Loop())


# ---- how much it is willing to swallow -------------------------------


def test_an_oversized_response_is_refused() -> None:
    class Huge:
        def get(self, url: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 5000, request=httpx.Request("GET", url))

        def close(self) -> None:
            return None

    with pytest.raises(FetchError, match="more than"):
        fetch_bytes(f"http://{PUBLIC_IP}/big", client=Huge(), max_bytes=1000)


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
