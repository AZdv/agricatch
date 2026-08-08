"""The small connective bits: the import form's POST path, do_import, __str__.

Not glamorous, but the import form is the one place a human triggers a crawl,
and do_import is the entire public entry point of the library.
"""

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from agricatch.helpers.general import load_importer
from agricatch.models import GeocodeCache
from agricatch.website import ImportResult, Website
from agricatch.xpath_functions import _as_text
from tech.models import Article, Author
from tech.models import Website as WebsiteModel

pytestmark = pytest.mark.django_db


class Recorder(Website):
    """Stands in for a real importer without any network."""

    collected: list[dict[str, Any]] = [{"name": "One"}, {"name": "Two"}]
    url_info = {"url": "https://example.com/"}
    structure = {"child_xpath": "//item", "fields": {}}

    def collect(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.collected)

    def persist(self, records: Any) -> ImportResult:
        return ImportResult(created=len(list(records)), updated=1)


# ---- the import form, which is how a human starts a crawl ------------


@pytest.fixture
def staff_client(client: Client) -> Client:
    get_user_model().objects.create_user("root", password="hunter2hunter2", is_staff=True)
    client.login(username="root", password="hunter2hunter2")
    return client


def test_posting_the_form_runs_the_importer_and_shows_the_result(
    staff_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tech.views.load_importer", lambda name: Recorder())

    response = staff_client.post(
        reverse("tech:importform"), {"importer_type": "techcrunch", "num_of_days": 1}
    )

    assert response.status_code == 200
    assert response.context["result"]["created"] == 2
    assert response.context["result"]["updated"] == 1
    assert response.context["result"]["total"] == 3


def test_posting_something_invalid_reports_it_rather_than_importing(
    staff_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(name: str) -> Website:
        raise AssertionError("an invalid form must not reach the importer")

    monkeypatch.setattr("tech.views.load_importer", explode)

    response = staff_client.post(
        reverse("tech:importform"), {"importer_type": "not-real", "num_of_days": 99}
    )

    assert response.status_code == 200
    assert response.context["result"] is None
    assert response.context["form"].errors


# ---- the top-level entry point ---------------------------------------


def test_do_import_collects_then_persists() -> None:
    result = Recorder().do_import(days=3)
    assert (result.created, result.updated) == (2, 1)


def test_import_result_reports_a_total_and_a_dict() -> None:
    result = ImportResult(created=2, updated=3, skipped=1)
    assert result.total == 5
    assert result.as_dict() == {
        "created": 2,
        "updated": 3,
        "skipped": 1,
        "total": 5,
        "errors": [],
    }


# ---- the bits Django shows people ------------------------------------


def test_models_render_themselves() -> None:
    site = WebsiteModel.objects.create(name="Example", slug="example")
    author = Author.objects.create(name="Ada Lovelace")
    assert str(site) == "Example"
    assert str(WebsiteModel(name="", slug="fallback")) == "fallback"
    assert str(author) == "Ada Lovelace"

    article = Article.objects.create(name="A title", link="https://e.test/a", website=site)
    assert str(article) == "A title"
    assert article.get_absolute_url() == f"/agricatch/article/{article.pk}"


def test_a_cache_row_renders_hit_and_miss() -> None:
    hit = GeocodeCache.objects.create(
        key="berlin", query="Berlin", name="Berlin", latitude=52.5, longitude=13.4
    )
    miss = GeocodeCache.objects.create(key="nowhere", query="Nowhere", found=False)
    assert "52.5" in str(hit)
    assert "not found" in str(miss)


def test_a_cache_row_without_coordinates_is_treated_as_a_miss() -> None:
    """found=True but no coordinates must not yield a Location at (None, None)."""
    row = GeocodeCache.objects.create(key="odd", query="Odd", found=True)
    assert row.as_location() is None


def test_the_admin_counts_an_authors_articles() -> None:
    from tech.admin import AuthorAdmin

    site = WebsiteModel.objects.create(name="Example", slug="example")
    author = Author.objects.create(name="Grace Hopper")
    for n in range(3):
        Article.objects.create(
            name=f"a{n}", link=f"https://e.test/{n}", website=site, author=author
        )

    admin = AuthorAdmin(Author, None)  # type: ignore[arg-type]
    assert admin.article_count(author) == 3


# ---- error paths that should not be reachable only in theory ---------


def test_loading_a_module_without_its_class_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tech.websites.techcrunch as module

    monkeypatch.delattr(module, "Techcrunch")
    with pytest.raises(LookupError, match="defines no Techcrunch"):
        load_importer("techcrunch")


@pytest.mark.parametrize(
    "value,expected",
    [(None, ""), ([], ""), (["first", "second"], "first"), ("plain", "plain"), (7, "7")],
)
def test_xpath_values_are_coerced_to_text(value: Any, expected: str) -> None:
    assert _as_text(value) == expected


def test_xpath_text_coercion_handles_an_element() -> None:
    from lxml import etree

    assert _as_text(etree.fromstring("<p>hello</p>")) == "hello"
