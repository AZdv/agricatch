import datetime

import pytest

from agricatch.helpers.general import get_all_importers, load_importer
from agricatch.website import Website
from tech.websites.techcrunch import Techcrunch


def test_all_four_importers_are_discovered():
    assert get_all_importers() == ["cnet", "gizmodo", "kidsil", "techcrunch"]


def test_load_importer_returns_an_instance():
    assert isinstance(load_importer("techcrunch"), Techcrunch)


@pytest.mark.parametrize("name", ["os", "../settings", "tech.settings", "nope"])
def test_load_importer_refuses_anything_off_the_list(name):
    """The old import form fed user input straight to __import__."""
    with pytest.raises(LookupError):
        load_importer(name)


def test_instances_do_not_share_structure():
    first, second = Techcrunch(), Techcrunch()
    first.structure["fields"]["name"]["xpath"] = "changed"
    assert second.structure["fields"]["name"]["xpath"] == "title/text()"


def test_undated_url_is_fetched_once_regardless_of_days():
    """A feed URL has no date placeholder, so crawling 7 days must not refetch it 7 times."""
    importer = Techcrunch()
    planned = list(importer._urls_to_crawl(7, datetime.date(2024, 5, 1)))
    assert planned == [("https://techcrunch.com/feed/", datetime.date(2024, 5, 1))]


def test_dated_url_expands_one_entry_per_step():
    class Dated(Website):
        url_info = {"url": "https://example.com/%Y-%m-%d", "days_on_page": 2}
        structure = {"child_xpath": "//item", "fields": {}}

    planned = list(Dated()._urls_to_crawl(6, datetime.date(2024, 5, 1)))
    assert [url for url, _ in planned] == [
        "https://example.com/2024-05-01",
        "https://example.com/2024-05-03",
        "https://example.com/2024-05-05",
    ]


def test_missing_child_xpath_is_reported():
    class Broken(Website):
        url_info = {"url": "https://example.com/"}
        structure = {"fields": {}}

    with pytest.raises(ValueError, match="child_xpath"):
        Broken().select_nodes(object())
