"""Library-level tables.

The domain models live in the app named by ``AGRICATCH_APP``; this holds only
what the library itself needs.
"""

from django.db import models


class GeocodeCache(models.Model):
    """One resolved (or unresolved) place lookup.

    Geocoding happens at import time and the same venues recur constantly, so a
    permanent cache turns a rate-limited network call into a single lookup per
    distinct place, for the lifetime of the database. Misses are cached too -
    otherwise every run re-asks about the places that will never resolve.
    """

    key = models.CharField(max_length=255, help_text="normalised query")
    country_filter = models.CharField(
        max_length=2, blank=True, default="", help_text="country asked for, if any"
    )
    query = models.CharField(max_length=255, help_text="what was originally asked")

    found = models.BooleanField(default=True)
    name = models.CharField(max_length=255, blank=True, default="")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    country = models.CharField(max_length=2, blank=True, default="", help_text="country resolved")
    source = models.CharField(max_length=32, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "geocode_cache"
        constraints = [
            models.UniqueConstraint(
                fields=["key", "country_filter"], name="geocode_cache_key_country"
            )
        ]
        indexes = [models.Index(fields=["latitude", "longitude"])]

    def __str__(self):
        if not self.found:
            return f"{self.query} (not found)"
        return f"{self.name} ({self.latitude}, {self.longitude})"

    def as_location(self):
        """Return the cached :class:`~agricatch.geocode.Location`, or None for a miss."""
        if not self.found:
            return None

        from agricatch.geocode import Location

        return Location(
            name=self.name,
            latitude=self.latitude,
            longitude=self.longitude,
            country=self.country,
            source=self.source,
        )
