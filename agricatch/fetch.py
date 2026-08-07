"""HTTP retrieval for importers."""

import logging
import threading
import time

import httpx

logger = logging.getLogger("agricatch.fetch")

DEFAULT_TIMEOUT = 20.0
DEFAULT_DELAY = 0.5
DEFAULT_MAX_PAGES = 100
USER_AGENT = "agricatch/2.0 (+https://github.com/AZdv/agricatch)"


class FetchError(RuntimeError):
    """Raised when a URL cannot be retrieved."""


class CrawlLimitReached(RuntimeError):
    """Raised when a crawl has used up its page budget."""


def fetch_bytes(url, *, timeout=DEFAULT_TIMEOUT, client=None):
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
    remembers what it already has, leaves a gap between calls, and stops at a
    page budget rather than following links forever.

    Anything with a ``get(url) -> bytes`` method can stand in for it, which is
    how importers get tested against saved pages.
    """

    def __init__(self, delay=DEFAULT_DELAY, max_pages=DEFAULT_MAX_PAGES, timeout=DEFAULT_TIMEOUT):
        self.delay = delay
        self.max_pages = max_pages
        self.timeout = timeout
        self.fetched = 0
        self._cache = {}
        self._last_request = 0.0
        self._lock = threading.Lock()

    def get(self, url):
        cached = self._cache.get(url)
        if cached is not None:
            logger.debug("already had %s", url)
            return cached

        if self.max_pages is not None and self.fetched >= self.max_pages:
            raise CrawlLimitReached(f"stopped after {self.fetched} pages at {url}")

        self._pace()
        content = fetch_bytes(url, timeout=self.timeout)
        self.fetched += 1
        self._cache[url] = content
        return content

    def _pace(self):
        if not self.delay:
            return
        with self._lock:
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
