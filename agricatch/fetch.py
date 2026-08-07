"""HTTP retrieval for importers."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

import httpx

logger = logging.getLogger("agricatch.fetch")

DEFAULT_TIMEOUT = 20.0
DEFAULT_DELAY = 0.5
DEFAULT_MAX_PAGES = 100
DEFAULT_CONCURRENCY = 4
USER_AGENT = "agricatch/2.0 (+https://github.com/AZdv/agricatch)"


class FetchError(RuntimeError):
    """Raised when a URL cannot be retrieved."""


class CrawlLimitReached(RuntimeError):
    """Raised when a crawl has used up its page budget."""


def fetch_bytes(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.Client | None = None,
) -> bytes:
    """Return the raw body at ``url``.

    Bytes rather than text: lxml needs the undecoded body to honour the encoding
    declared in an XML prolog.
    """
    headers = {"User-Agent": USER_AGENT}
    try:
        if client is not None:
            response = client.get(url, headers=headers, follow_redirects=True, timeout=timeout)
        else:
            response = httpx.get(url, headers=headers, follow_redirects=True, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc

    logger.debug("fetched %s (%d bytes)", url, len(response.content))
    return response.content


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

    def get(self, url: str) -> bytes:
        cached = self._cache.get(url)
        if cached is not None:
            logger.debug("already had %s", url)
            return cached

        self._reserve(url)
        content = fetch_bytes(url, timeout=self.timeout)
        with self._lock:
            self._cache[url] = content
        return content

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
