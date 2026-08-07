"""Offline geocoding.

The fixture is a real slice of the GeoNames extract, so these exercise the same
shapes the full dataset has - several Springfields, a Zürich with an umlaut, and
Munich reachable under its local spelling.
"""

from pathlib import Path

import pytest

from agricatch.geocode import (
    DatasetMissing,
    NominatimGeocoder,
    OfflineGeocoder,
    geocode,
    normalize,
)

SAMPLE = Path(__file__).parent / "fixtures" / "geodata-sample.tsv.gz"


@pytest.fixture
def geocoder():
    return OfflineGeocoder(SAMPLE)


def test_normalize_folds_diacritics_case_and_punctuation():
    assert normalize("Zürich") == "zurich"
    assert normalize("  TEL-AVIV  ") == "tel aviv"
    assert normalize("St. Louis") == "st louis"
    assert normalize("") == ""


def test_lookup_returns_coordinates(geocoder):
    berlin = geocoder.lookup("Berlin")
    assert berlin.country == "DE"
    assert berlin.latitude == pytest.approx(52.52, abs=0.1)
    assert berlin.longitude == pytest.approx(13.41, abs=0.1)
    assert berlin.source == "geonames"


def test_lookup_is_case_and_accent_insensitive(geocoder):
    assert geocoder.lookup("zurich").country == "CH"
    assert geocoder.lookup("Zürich").country == "CH"


def test_local_spelling_resolves_when_alternates_are_indexed(geocoder):
    assert geocoder.lookup("München").name == "Munich"


def test_ambiguous_name_resolves_to_the_most_populous(geocoder):
    """There are several Springfields; the biggest one wins by default."""
    assert geocoder.lookup("Springfield").country == "US"


def test_country_narrows_an_ambiguous_name(geocoder):
    assert geocoder.lookup("Paris").country == "FR"
    assert geocoder.lookup("Paris", country="US").country == "US"


def test_country_with_no_match_returns_none(geocoder):
    assert geocoder.lookup("Tokyo", country="DE") is None


def test_longer_string_falls_back_to_its_parts(geocoder):
    """'Kreuzberg, Berlin' is not a key, but 'Berlin' is."""
    assert geocoder.lookup("Kreuzberg, Berlin").country == "DE"


@pytest.mark.parametrize("query", ["", "   ", None])
def test_blank_queries_return_none(geocoder, query):
    assert geocoder.lookup(query) is None


def test_unknown_place_returns_none(geocoder):
    assert geocoder.lookup("Nowhereville") is None


def test_index_is_loaded_once(geocoder):
    geocoder.lookup("Berlin")
    first = geocoder._index
    geocoder.lookup("Paris")
    assert geocoder._index is first


def test_missing_dataset_raises_on_direct_use(tmp_path):
    with pytest.raises(DatasetMissing, match="fetch_geodata"):
        OfflineGeocoder(tmp_path / "absent.tsv.gz").lookup("Berlin")


def test_geocode_helper_returns_none_when_the_dataset_is_missing(tmp_path):
    """Safe to use as a field function even before the data is built."""
    assert geocode("Berlin", geocoder=OfflineGeocoder(tmp_path / "absent.tsv.gz")) is None


def test_geocode_helper_accepts_an_explicit_geocoder(geocoder):
    assert geocode("Berlin", geocoder=geocoder).country == "DE"


@pytest.mark.live
def test_nominatim_resolves_a_street_level_place():
    """What the offline dataset cannot do: an actual venue."""
    location = NominatimGeocoder().lookup("Berghain, Berlin")
    assert location is not None
    assert location.source == "nominatim"
    assert location.latitude == pytest.approx(52.51, abs=0.05)


@pytest.mark.live
@pytest.mark.django_db
def test_the_chain_resolves_a_venue_once_then_serves_it_from_cache():
    from agricatch.geocode import CachingGeocoder
    from agricatch.models import GeocodeCache

    geocoder = CachingGeocoder()
    first = geocoder.lookup("Berghain, Berlin")

    assert first is not None
    assert first.source == "nominatim"
    assert first.latitude == pytest.approx(52.51, abs=0.05)
    assert GeocodeCache.objects.count() == 1

    # Second time round must not touch the network at all.
    assert geocoder.lookup("Berghain, Berlin") == first
    assert GeocodeCache.objects.count() == 1


@pytest.mark.live
@pytest.mark.django_db
def test_the_offline_layer_catches_what_nominatim_is_not_asked_for():
    """A plain city resolves even with the network provider removed."""
    from agricatch.geocode import CachingGeocoder

    geocoder = CachingGeocoder([OfflineGeocoder(SAMPLE)])
    assert geocoder.lookup("Berlin").source == "geonames"
