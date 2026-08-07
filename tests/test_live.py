"""Checks against the real sources.

Deselected by default because they need the network and the sources move.
Run them with ``pytest -m live`` when a feed is suspected of having changed.
"""

import datetime

import pytest

from agricatch.helpers.general import get_all_importers, load_importer

pytestmark = pytest.mark.live


@pytest.mark.parametrize("name", ["techcrunch", "gizmodo", "cnet", "kidsil"])
def test_source_still_yields_usable_records(name):
    importer = load_importer(name)
    # Enough to prove the layout still parses without crawling a whole blog.
    importer.max_pages = 2
    records = importer.collect(days=1)

    assert records, f"{name} returned nothing; the source layout probably changed"
    for record in records:
        assert record["name"].strip()
        assert record["link"].startswith("http")
        assert isinstance(record["time"], datetime.datetime)


def test_following_a_detail_page_beats_the_listing_excerpt():
    """kidsil's index carries a short excerpt; the post itself is far longer."""
    importer = load_importer("kidsil")
    importer.max_pages = 2
    records = importer.collect(days=1)

    assert records
    assert len(records[0]["description"]) > 1000


@pytest.mark.django_db
def test_a_real_import_is_idempotent():
    importer = load_importer("techcrunch")
    records = importer.collect(days=1)

    first = importer.persist(records)
    second = importer.persist(records)

    assert first.created == len(records)
    assert second.created == 0
    assert second.updated == len(records)


def test_every_importer_is_loadable():
    for name in get_all_importers():
        load_importer(name)
