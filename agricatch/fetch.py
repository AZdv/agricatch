"""HTTP retrieval for importers."""

import logging

import httpx

logger = logging.getLogger("agricatch.fetch")

DEFAULT_TIMEOUT = 20.0
USER_AGENT = "agricatch/2.0 (+https://github.com/AZdv/agricatch)"


class FetchError(RuntimeError):
    """Raised when a URL cannot be retrieved."""


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
