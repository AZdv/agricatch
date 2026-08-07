"""Turning place names into coordinates.

Geocoding is a lookup, not a calculation - there is no way to derive coordinates
from a name without reference data - so the question is only ever which dataset
you are willing to carry.

:class:`OfflineGeocoder` carries one. It reads a GeoNames extract built by
``manage.py fetch_geodata`` and answers from local disk with no network, no API
key and nothing outside the standard library. It resolves cities, towns and
regions. It will not resolve a street address or a venue, because the datasets
that can do that run to hundreds of gigabytes.

:class:`NominatimGeocoder` covers that gap when you need it, against
OpenStreetMap. It needs the network, and it is rate limited to one call a second
by OSM's usage policy.

    >>> geocode("Berlin")
    Location(name='Berlin', latitude=52.52437, longitude=13.41053, ...)

Call it from an importer's ``hydrate()`` rather than as a field ``function``: a
lookup fills in two columns, which a single field cannot express.

    def hydrate(self, record, node):
        found = geocode(record.get("city", ""))
        if found:
            record["latitude"] = found.latitude
            record["longitude"] = found.longitude
        return record

No importer in ``tech`` calls this - articles have no location. It is here for
location-bearing importers, which is where it came from.
"""

import csv
import gzip
import logging
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import NamedTuple

from django.conf import settings

logger = logging.getLogger("agricatch.geocode")

DEFAULT_DATASET = Path(settings.BASE_DIR) / "geodata" / "cities.tsv.gz"
FIELDNAMES = ("key", "name", "latitude", "longitude", "country", "population")


class Location(NamedTuple):
    name: str
    latitude: float
    longitude: float
    country: str
    source: str


def normalize(value):
    """Fold a place name to a comparable key.

    Strips diacritics so 'Zürich' and 'Zurich' collide, drops punctuation and
    collapses whitespace.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^\w\s]", " ", stripped.casefold())
    return re.sub(r"\s+", " ", cleaned).strip()


class DatasetMissing(RuntimeError):
    """Raised when the offline dataset has not been built yet."""


class OfflineGeocoder:
    """Answers from a local GeoNames extract.

    The index is loaded once on first use and held in memory: roughly 50k keys
    for the default extract, which is a few MB.
    """

    def __init__(self, path=None):
        self.path = Path(path or getattr(settings, "AGRICATCH_GEODATA", DEFAULT_DATASET))
        self._index = None
        self._lock = threading.Lock()

    def load(self):
        if self._index is not None:
            return self._index

        with self._lock:
            if self._index is not None:
                return self._index
            if not self.path.exists():
                raise DatasetMissing(f"no geodata at {self.path} - run: manage.py fetch_geodata")

            index = {}
            with gzip.open(self.path, "rt", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, fieldnames=FIELDNAMES, delimiter="\t"):
                    index.setdefault(row["key"], []).append(
                        (
                            int(row["population"] or 0),
                            Location(
                                name=row["name"],
                                latitude=float(row["latitude"]),
                                longitude=float(row["longitude"]),
                                country=row["country"],
                                source="geonames",
                            ),
                        )
                    )
            # Most populous first, so a bare "Berlin" resolves to the obvious one.
            for candidates in index.values():
                candidates.sort(key=lambda item: -item[0])

            self._index = index
            logger.info("loaded %d place keys from %s", len(index), self.path)
            return self._index

    def lookup(self, query, country=None):
        if not query or not query.strip():
            return None

        index = self.load()
        for candidate in self._candidate_keys(query):
            for _, location in index.get(candidate, ()):
                if country and location.country.casefold() != country.casefold():
                    continue
                return location
        return None

    @staticmethod
    def _candidate_keys(query):
        """Whole string first, then the comma-separated parts.

        Lets 'Kreuzberg, Berlin, Germany' fall back to 'Berlin' rather than
        failing outright.
        """
        seen = []
        whole = normalize(query)
        if whole:
            seen.append(whole)
        parts = [normalize(part) for part in query.split(",")]
        for part in parts:
            if part and part not in seen:
                seen.append(part)
        return seen


class NominatimGeocoder:
    """OpenStreetMap's geocoder. Network, no API key, one request per second."""

    ENDPOINT = "https://nominatim.openstreetmap.org/search"
    MIN_INTERVAL = 1.0

    def __init__(self, user_agent=None, timeout=20.0):
        from agricatch.fetch import USER_AGENT

        self.user_agent = user_agent or USER_AGENT
        self.timeout = timeout
        self._last_call = 0.0
        self._lock = threading.Lock()

    def _throttle(self):
        with self._lock:
            wait = self.MIN_INTERVAL - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def lookup(self, query, country=None):
        if not query or not query.strip():
            return None

        import httpx

        params = {"q": query, "format": "json", "limit": 1}
        if country:
            params["countrycodes"] = country.lower()

        self._throttle()
        try:
            response = httpx.get(
                self.ENDPOINT,
                params=params,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
            )
            response.raise_for_status()
            results = response.json()
        except Exception as exc:
            logger.warning("nominatim lookup failed for %r: %s", query, exc)
            return None

        if not results:
            return None
        top = results[0]
        return Location(
            name=top.get("display_name", query),
            latitude=float(top["lat"]),
            longitude=float(top["lon"]),
            country=(top.get("address", {}) or {}).get("country_code", "").upper(),
            source="nominatim",
        )


class CachingGeocoder:
    """Resolves through a chain of providers and remembers every answer.

    The default chain is Nominatim then the offline dataset: exact coordinates
    when the network can give them, city-level as a floor when it cannot. Since
    importing keeps meeting the same venues, a lookup costs one network call
    ever, and misses are cached too so the hopeless ones are only asked once.
    """

    def __init__(self, providers=None):
        self._providers = list(providers) if providers is not None else None

    @property
    def providers(self):
        if self._providers is None:
            self._providers = [NominatimGeocoder(), OfflineGeocoder()]
        return self._providers

    def lookup(self, query, country=None, refresh=False):
        key = normalize(query or "")
        if not key:
            return None

        from agricatch.models import GeocodeCache

        country_filter = (country or "").upper()
        if not refresh:
            cached = GeocodeCache.objects.filter(key=key, country_filter=country_filter).first()
            if cached is not None:
                return cached.as_location()

        location = self._ask_providers(query, country)
        GeocodeCache.objects.update_or_create(
            key=key,
            country_filter=country_filter,
            defaults={
                "query": query[:255],
                "found": location is not None,
                "name": location.name[:255] if location else "",
                "latitude": location.latitude if location else None,
                "longitude": location.longitude if location else None,
                "country": location.country[:2] if location else "",
                "source": location.source if location else "",
            },
        )
        return location

    def _ask_providers(self, query, country):
        for provider in self.providers:
            try:
                found = provider.lookup(query, country=country)
            except DatasetMissing:
                logger.warning("offline geodata missing; run manage.py fetch_geodata")
                continue
            if found is not None:
                return found
        return None


_default = CachingGeocoder()


def geocode(query, country=None, geocoder=None):
    """Resolve ``query`` to a :class:`Location`, or None.

    Goes through the caching chain unless given another geocoder. Returns None
    rather than raising - for an unknown place, an unbuilt dataset or an
    unreachable network alike - so a caller never has to guard it.
    """
    try:
        return (geocoder or _default).lookup(query, country=country)
    except DatasetMissing:
        logger.warning("offline geodata missing; run manage.py fetch_geodata")
        return None
