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
    records = load_importer(name).collect(days=1)

    assert records, f"{name} returned nothing; the source layout probably changed"
    for record in records:
        assert record["name"].strip()
        assert record["link"].startswith("http")
        assert isinstance(record["time"], datetime.datetime)


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
