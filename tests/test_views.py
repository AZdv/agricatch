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


# ---- paging and the two time windows ---------------------------------


@pytest.fixture
def several(db: None) -> None:
    site = Website.objects.create(name="Example", slug="example")
    now = timezone.now()
    for n in range(7):
        Article.objects.create(
            name=f"article {n}",
            link=f"https://e.test/{n}",
            time=now - datetime.timedelta(days=n),
            website=site,
        )


def test_offset_reaches_past_the_first_page(client: Client, several: None) -> None:
    first = client.get(reverse("tech:articles"), {"limit": "3"}).json()
    second = client.get(reverse("tech:articles"), {"limit": "3", "offset": "3"}).json()

    assert [r["name"] for r in first["results"]] != [r["name"] for r in second["results"]]
    assert first["offset"] == 0
    assert second["offset"] == 3


def test_offset_past_the_end_is_empty_not_an_error(client: Client, several: None) -> None:
    body = client.get(reverse("tech:articles"), {"offset": "9999"}).json()
    assert body["count"] == 0
    assert body["results"] == []


def test_a_non_numeric_offset_is_a_bad_request(client: Client, several: None) -> None:
    assert client.get(reverse("tech:articles"), {"offset": "abc"}).status_code == 400


def test_a_negative_offset_is_clamped(client: Client, several: None) -> None:
    body = client.get(reverse("tech:articles"), {"offset": "-5"}).json()
    assert body["offset"] == 0


def test_days_past_selects_the_recent_window(client: Client, several: None) -> None:
    """The news-shaped question, as opposed to days_future's events-shaped one."""
    body = client.get(reverse("tech:articles"), {"days_past": "2"}).json()
    names = {r["name"] for r in body["results"]}

    assert "article 0" in names
    assert "article 6" not in names
