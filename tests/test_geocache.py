"""The caching chain: one network call per distinct place, ever."""

import pytest

from agricatch.geocode import CachingGeocoder, DatasetMissing, Location, OfflineGeocoder
from agricatch.models import GeocodeCache

pytestmark = pytest.mark.django_db

BERLIN = Location(name="Berlin", latitude=52.5244, longitude=13.4105, country="DE", source="test")


class FakeProvider:
    """Counts calls, so the tests can prove the cache is doing its job."""

    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls = 0

    def lookup(self, query, country=None):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.result


def test_a_miss_asks_the_provider_and_stores_the_answer():
    provider = FakeProvider(BERLIN)
    found = CachingGeocoder([provider]).lookup("Berlin")

    assert found == BERLIN
    assert provider.calls == 1
    row = GeocodeCache.objects.get()
    assert (row.key, row.name, row.found) == ("berlin", "Berlin", True)
    assert row.latitude == pytest.approx(52.5244)


def test_a_hit_does_not_ask_the_provider_again():
    provider = FakeProvider(BERLIN)
    geocoder = CachingGeocoder([provider])

    first = geocoder.lookup("Berlin")
    second = geocoder.lookup("Berlin")

    assert first == second
    assert provider.calls == 1
    assert GeocodeCache.objects.count() == 1


def test_the_cache_key_is_normalised():
    provider = FakeProvider(BERLIN)
    geocoder = CachingGeocoder([provider])

    geocoder.lookup("Berlin")
    geocoder.lookup("  BERLIN  ")

    assert provider.calls == 1


def test_a_miss_is_remembered_too():
    """Otherwise every run re-asks about places that will never resolve."""
    provider = FakeProvider(None)
    geocoder = CachingGeocoder([provider])

    assert geocoder.lookup("Nowhereville") is None
    assert geocoder.lookup("Nowhereville") is None

    assert provider.calls == 1
    assert GeocodeCache.objects.get().found is False


def test_refresh_bypasses_the_cache():
    provider = FakeProvider(BERLIN)
    geocoder = CachingGeocoder([provider])

    geocoder.lookup("Berlin")
    geocoder.lookup("Berlin", refresh=True)

    assert provider.calls == 2
    assert GeocodeCache.objects.count() == 1


def test_a_different_country_filter_is_a_different_entry():
    provider = FakeProvider(BERLIN)
    geocoder = CachingGeocoder([provider])

    geocoder.lookup("Paris")
    geocoder.lookup("Paris", country="US")

    assert provider.calls == 2
    assert GeocodeCache.objects.count() == 2
    assert set(GeocodeCache.objects.values_list("country_filter", flat=True)) == {"", "US"}


def test_the_resolved_country_is_kept_apart_from_the_requested_one():
    geocoder = CachingGeocoder([FakeProvider(BERLIN)])
    geocoder.lookup("Berlin", country="DE")

    row = GeocodeCache.objects.get()
    assert row.country_filter == "DE"
    assert row.country == "DE"
    assert geocoder.lookup("Berlin", country="DE").country == "DE"


def test_the_chain_falls_through_to_the_next_provider():
    first, second = FakeProvider(None), FakeProvider(BERLIN)
    assert CachingGeocoder([first, second]).lookup("Berlin") == BERLIN
    assert (first.calls, second.calls) == (1, 1)


def test_the_chain_stops_at_the_first_hit():
    first, second = FakeProvider(BERLIN), FakeProvider(None)
    CachingGeocoder([first, second]).lookup("Berlin")
    assert (first.calls, second.calls) == (1, 0)


def test_an_unbuilt_dataset_is_skipped_rather_than_fatal():
    missing = FakeProvider(raises=DatasetMissing("no data"))
    fallback = FakeProvider(BERLIN)
    assert CachingGeocoder([missing, fallback]).lookup("Berlin") == BERLIN


def test_everything_failing_yields_a_cached_miss():
    missing = FakeProvider(raises=DatasetMissing("no data"))
    assert CachingGeocoder([missing]).lookup("Berlin") is None
    assert GeocodeCache.objects.get().found is False


@pytest.mark.parametrize("query", ["", "   ", None])
def test_blank_queries_never_reach_a_provider(query):
    provider = FakeProvider(BERLIN)
    assert CachingGeocoder([provider]).lookup(query) is None
    assert provider.calls == 0
    assert not GeocodeCache.objects.exists()


def test_the_default_chain_is_nominatim_then_offline():
    from agricatch.geocode import NominatimGeocoder

    providers = CachingGeocoder().providers
    assert [type(p) for p in providers] == [NominatimGeocoder, OfflineGeocoder]


def test_round_tripping_through_the_cache_preserves_the_location():
    geocoder = CachingGeocoder([FakeProvider(BERLIN)])
    geocoder.lookup("Berlin")

    restored = GeocodeCache.objects.get().as_location()
    assert restored.name == BERLIN.name
    assert restored.latitude == pytest.approx(BERLIN.latitude)
    assert restored.longitude == pytest.approx(BERLIN.longitude)
