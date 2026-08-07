import datetime

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from tech.models import Article, Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def article() -> Article:
    site = Website.objects.create(name="Example", slug="example")
    return Article.objects.create(
        name="A title",
        link="https://example.com/a",
        time=timezone.now(),
        website=site,
    )


def test_articles_returns_json(client: Client, article: Article) -> None:
    response = client.get(reverse("tech:articles"))
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["link"] == "https://example.com/a"
    assert body["results"][0]["website"] == "example"


def test_sort_by_accepts_a_known_field(client: Client, article: Article) -> None:
    assert client.get(reverse("tech:articles"), {"sort_by": "-time"}).status_code == 200


@pytest.mark.parametrize("value", ["password", "website__name", "id; DROP TABLE", "?"])
def test_sort_by_rejects_anything_else(client: Client, article: Article, value: str) -> None:
    response = client.get(reverse("tech:articles"), {"sort_by": value})
    assert response.status_code == 400


def test_non_numeric_days_future_is_a_bad_request_not_a_crash(
    client: Client, article: Article
) -> None:
    assert client.get(reverse("tech:articles"), {"days_future": "abc"}).status_code == 400


def test_days_future_filters_to_the_window(client: Client, article: Article) -> None:
    Article.objects.create(
        name="Far future",
        link="https://example.com/b",
        time=timezone.now() + datetime.timedelta(days=30),
    )
    body = client.get(reverse("tech:articles"), {"days_future": "7"}).json()
    assert [r["name"] for r in body["results"]] == ["A title"]


def test_limit_is_capped(client: Client, article: Article) -> None:
    response = client.get(reverse("tech:articles"), {"limit": "99999"})
    assert response.status_code == 200


def test_last_update_reports_the_newest_row(client: Client, article: Article) -> None:
    body = client.get(reverse("tech:articles"), {"last_update": "1"}).json()
    assert body["last_update"] is not None


def test_article_detail_renders(client: Client, article: Article) -> None:
    response = client.get(reverse("tech:article", args=[article.pk]))
    assert response.status_code == 200
    assert b"A title" in response.content


def test_missing_article_is_a_404(client: Client) -> None:
    assert client.get(reverse("tech:article", args=[999])).status_code == 404


def test_importform_is_closed_to_anonymous_users(client: Client) -> None:
    response = client.get(reverse("tech:importform"))
    assert response.status_code == 302
    assert "/admin/login" in response["Location"]


def test_importform_is_closed_to_non_staff(client: Client) -> None:
    get_user_model().objects.create_user("bob", password="hunter2hunter2")
    client.login(username="bob", password="hunter2hunter2")
    response = client.get(reverse("tech:importform"))
    assert response.status_code == 302


def test_importform_opens_for_staff(client: Client) -> None:
    get_user_model().objects.create_user("root", password="hunter2hunter2", is_staff=True)
    client.login(username="root", password="hunter2hunter2")
    assert client.get(reverse("tech:importform")).status_code == 200
