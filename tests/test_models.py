import datetime
from typing import Any

import pytest
from django.utils import timezone

from tech.models import Article

pytestmark = pytest.mark.django_db


def make(**overrides: Any) -> dict[str, Any]:
    values = {
        "name": "A title",
        "link": "https://example.com/a",
        "time": timezone.make_aware(datetime.datetime(2024, 5, 1, 12, 0)),
    }
    values.update(overrides)
    return values


def test_hash_is_set_on_save() -> None:
    article = Article.objects.create(**make())
    assert article.content_hash
    assert len(article.content_hash) == 64


def test_hash_survives_a_datetime_time_field() -> None:
    """The pre-2.0 code joined name and time directly and raised TypeError here."""
    article = Article(**make())
    article.save()
    assert article.content_hash == Article.build_hash(make())


def test_hash_handles_a_null_time() -> None:
    article = Article.objects.create(**make(time=None))
    assert article.content_hash


def test_identical_content_collides_and_differing_content_does_not() -> None:
    assert Article.build_hash(make()) == Article.build_hash(make())
    assert Article.build_hash(make()) != Article.build_hash(make(name="Another"))


def test_build_hash_accepts_a_dict_or_an_instance() -> None:
    values = make()
    assert Article.build_hash(values) == Article.build_hash(Article(**values))


def test_reimporting_the_same_article_updates_rather_than_duplicates() -> None:
    values = make()
    digest = Article.build_hash(values)

    Article.objects.update_or_create(content_hash=digest, defaults=values)
    Article.objects.update_or_create(
        content_hash=digest, defaults=dict(values, description="now filled in")
    )

    assert Article.objects.count() == 1
    assert Article.objects.get().description == "now filled in"
