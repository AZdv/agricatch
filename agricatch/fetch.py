"""HTTP retrieval for importers."""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol, cast
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger("agricatch.fetch")

DEFAULT_TIMEOUT = 20.0
DEFAULT_DELAY = 0.5
DEFAULT_MAX_PAGES = 100
DEFAULT_CONCURRENCY = 4
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.0
# 5xx and dropped connections are the server having a bad moment. 403 and 429
# are decisions it made on purpose, and retrying them is just knocking harder
# after being told no.
RETRIABLE_STATUS = frozenset({500, 502, 503, 504})
ALLOWED_SCHEMES = ("http", "https")
USER_AGENT = "agricatch/2.0 (+https://github.com/AZdv/agricatch)"


class FetchError(RuntimeError):
    """Raised when a URL cannot be retrieved."""


class BlockedURL(FetchError):
    """Raised when a URL points somewhere a crawler has no business going."""


class CrawlLimitReached(RuntimeError):
    """Raised when a crawl has used up its page budget."""


class HTTPClient(Protocol):
    """The part of ``httpx.Client`` this module uses, so it can be substituted.

    ``stream`` rather than ``get``: the body has to be counted as it arrives, or
    a size limit is only checked once the bytes are already in memory.
    """

    def stream(self, method: str, url: str, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...


def check_public_url(url: str) -> None:
    """Refuse anything that is not a public http(s) address.

    A crawler follows links it was handed by somebody else, so "fetch this URL"
    is only ever a request from an untrusted party. Without this, a page could
    point at ``169.254.169.254`` and have the crawler read cloud instance
    credentials, or at ``127.0.0.1`` to reach services that trust the loopback.

    Known limit: this resolves the name, approves it, and the connection then
    resolves it again, so a domain whose DNS answers publicly on the first
    lookup and privately on the second gets through. Closing that properly means
    connecting to the vetted IP rather than the name, which breaks TLS hostname
    verification unless handled with more care than it is worth here. If you are
    crawling genuinely hostile input, put an egress firewall in front of it and
    treat this as defence in depth rather than the only defence.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise BlockedURL(f"refusing {parsed.scheme or 'scheme-less'} URL: {url}")

    host = parsed.hostname
    if not host:
        raise BlockedURL(f"no host in {url}")

    try:
        infos = socket.getaddrinfo(host, parsed.port or 0, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise FetchError(f"could not resolve {host}: {exc}") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise BlockedURL(f"refusing non-public address {address} for {url}")


class _Transient(Exception):
    """An failure worth another attempt, as opposed to an answer we were given."""


def _fetch_once(
    session: HTTPClient,
    target: str,
    headers: dict[str, str],
    timeout: float,
    max_bytes: int,
) -> tuple[bytes | None, str | None]:
    """One request. Returns ``(content, redirect_location)``; exactly one is set.

    Raises :class:`_Transient` for a dropped connection or a 5xx, which are the
    server having a bad moment. A status the server chose on purpose - 403, 429,
    404 - comes back as FetchError and is never retried, because repeating it is
    rude and will not help.
    """
    try:
        with session.stream(
            "GET", target, headers=headers, follow_redirects=False, timeout=timeout
        ) as response:
            if response.status_code in RETRIABLE_STATUS:
                raise _Transient(f"{target} returned {response.status_code}")

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise FetchError(f"redirect without a location at {target}")
                return None, location

            response.raise_for_status()

            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise FetchError(f"{target} declares more than {max_bytes} bytes")

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError(f"{target} returned more than {max_bytes} bytes")
                chunks.append(chunk)
            return b"".join(chunks), None

    except httpx.HTTPStatusError as exc:
        raise FetchError(f"could not fetch {target}: {exc}") from exc
    except httpx.HTTPError as exc:
        # Transport-level: timeouts, resets, DNS. Worth another go.
        raise _Transient(str(exc)) from exc


def fetch_bytes(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    client: HTTPClient | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_attempts: int = MAX_ATTEMPTS,
) -> bytes:
    """Return the raw body at ``url``.

    Bytes rather than text: lxml needs the undecoded body to honour the encoding
    declared in an XML prolog.

    Redirects are followed by hand rather than by httpx, so every hop gets the
    same public-address check as the original URL. Letting the client follow
    them means a permitted URL can bounce straight to a blocked one.

    The body is streamed and counted as it arrives. Reading it whole and then
    measuring it means the memory is already spent by the time the limit is
    consulted, which is no limit at all.
    """
    headers = {"User-Agent": USER_AGENT}
    owned = client is None
    # httpx.Client.stream takes explicit keyword-only arguments, so it does not
    # structurally match a **kwargs protocol even though it is exactly what we
    # want. The protocol is there for the test doubles; this is the real thing.
    session: HTTPClient = cast(
        HTTPClient, client or httpx.Client(follow_redirects=False, timeout=timeout)
    )

    try:
        target = url
        for _ in range(MAX_REDIRECTS + 1):
            check_public_url(target)

            content: bytes | None = None
            location: str | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    content, location = _fetch_once(session, target, headers, timeout, max_bytes)
                    break
                except _Transient as exc:
                    if attempt >= max_attempts:
                        raise FetchError(
                            f"could not fetch {target} after {max_attempts} attempts: {exc}"
                        ) from exc
                    logger.debug("%s: %s, retrying (%d/%d)", target, exc, attempt, max_attempts)
                    time.sleep(BACKOFF_SECONDS * attempt)

            if location is not None:
                # Relative Location headers are legal and common.
                target = urljoin(target, location)
                continue

            assert content is not None
            logger.debug("fetched %s (%d bytes)", target, len(content))
            return content

        raise FetchError(f"too many redirects starting at {url}")
    finally:
        if owned:
            session.close()


class FetchSession:
    """One import's worth of fetching.

    Following detail pages turns a single index into dozens of requests, so this
    remembers what it already has, paces itself, and stops at a page budget
    rather than following links forever.

    Requests can overlap, but **concurrency never raises the request rate**.
    ``delay`` spaces the moment each request *starts*, and that spacing is held
    under a lock, so a site sees at most one new request every ``delay`` seconds
    no matter how many workers are running. Overlapping only helps when a server
    is slow to answer: four workers against a host that takes twenty seconds to
    respond finish four times sooner while still knocking at the same speed.

    Anything with a ``get(url) -> bytes`` method can stand in for this, which is
    how importers get tested against saved pages.
    """

    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        max_pages: int | None = DEFAULT_MAX_PAGES,
        timeout: float = DEFAULT_TIMEOUT,
        max_concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        self.delay = delay
        self.max_pages = max_pages
        self.timeout = timeout
        self.max_concurrency = max(1, max_concurrency)
        self.fetched = 0
        self._cache: dict[str, bytes] = {}
        self._last_start = 0.0
        self._lock = threading.Lock()
        self._url_locks: dict[str, threading.Lock] = {}

    def get(self, url: str) -> bytes:
        cached = self._cache.get(url)
        if cached is not None:
            logger.debug("already had %s", url)
            return cached

        # One lock per URL, so two workers wanting the same page do not both
        # fetch it and charge the budget twice; the second waits and finds it
        # cached.
        with self._lock_for(url):
            cached = self._cache.get(url)
            if cached is not None:
                return cached

            self._reserve(url)
            content = fetch_bytes(url, timeout=self.timeout)
            with self._lock:
                self._cache[url] = content
                # Drop the lock entry now the answer is cached, so a long crawl
                # does not accumulate one per URL it has ever seen. Anyone
                # already blocked on it still holds a reference and will find
                # the cache populated; anyone arriving later makes a fresh lock
                # and hits the cache immediately.
                self._url_locks.pop(url, None)
            return content

    def _lock_for(self, url: str) -> threading.Lock:
        with self._lock:
            return self._url_locks.setdefault(url, threading.Lock())

    def prefetch(self, urls: Iterable[str]) -> None:
        """Warm the cache for several URLs at once.

        Failures are swallowed here; the caller meets them again on ``get``,
        where it has the context to decide what a missing page means.
        """
        pending = [url for url in dict.fromkeys(urls) if url and url not in self._cache]
        if not pending:
            return

        workers = min(self.max_concurrency, len(pending))
        if workers == 1:
            for url in pending:
                self._quietly_get(url)
            return

        logger.debug("prefetching %d urls, %d at a time", len(pending), workers)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="agricatch") as pool:
            list(pool.map(self._quietly_get, pending))

    def _quietly_get(self, url: str) -> None:
        try:
            self.get(url)
        except (FetchError, CrawlLimitReached) as exc:
            logger.debug("prefetch skipped %s: %s", url, exc)

    def _reserve(self, url: str) -> None:
        """Claim a slot in the budget and wait for this request's turn.

        The sleep happens with the lock held, which is what keeps request starts
        spaced no matter how many threads are waiting.
        """
        with self._lock:
            if self.max_pages is not None and self.fetched >= self.max_pages:
                raise CrawlLimitReached(f"stopped after {self.fetched} pages at {url}")
            self.fetched += 1

            if self.delay:
                wait = self.delay - (time.monotonic() - self._last_start)
                if wait > 0:
                    time.sleep(wait)
                self._last_start = time.monotonic()
