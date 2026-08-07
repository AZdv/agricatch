import datetime
import hashlib

from django.db import models
from django.urls import reverse


class Website(models.Model):
    name = models.CharField(max_length=64)
    slug = models.SlugField(max_length=128, unique=True)
    address = models.URLField(max_length=512, blank=True, default="")

    class Meta:
        db_table = "website"
        ordering = ["slug"]

    def __str__(self):
        return self.name or self.slug


class Article(models.Model):
    name = models.TextField()
    description = models.TextField(blank=True, default="")
    link = models.URLField(max_length=512, blank=True, default="")
    image = models.URLField(max_length=512, blank=True, default="")
    author = models.CharField(max_length=128, blank=True, default="")
    time = models.DateTimeField(null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    content_hash = models.CharField(max_length=64, unique=True, editable=False)
    website = models.ForeignKey(
        Website,
        on_delete=models.CASCADE,
        related_name="articles",
        null=True,
        blank=True,
    )

    # The identity of an article for de-duplication purposes.
    HASH_FIELDS = ("name", "link", "time")

    class Meta:
        db_table = "article"
        ordering = ["-time", "-added_at"]
        indexes = [
            models.Index(fields=["-time"]),
            models.Index(fields=["-added_at"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.content_hash:
            self.content_hash = self.build_hash(self)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("tech:article", args=[self.pk])

    @classmethod
    def build_hash(cls, values):
        """Stable digest of the identity fields, from a dict or a model instance."""
        getter = values.get if isinstance(values, dict) else lambda k: getattr(values, k, None)
        parts = []
        for name in cls.HASH_FIELDS:
            value = getter(name)
            if isinstance(value, datetime.datetime):
                value = value.isoformat()
            parts.append("" if value is None else str(value))
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
