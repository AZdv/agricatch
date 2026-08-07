"""Distance filtering, exercised against the geocode cache's own coordinates."""

from math import asin, atan2, cos, degrees, radians, sin

import pytest

from agricatch.geodistance import (
    EARTH_RADIUS_KM,
    annotate_distance,
    bounding_box,
    filter_within,
    haversine,
)
from agricatch.models import GeocodeCache

BERLIN = (52.5244, 13.4105)
HAMBURG = (53.5507, 9.9930)
PARIS = (48.8566, 2.3522)
SYDNEY = (-33.8688, 151.2093)

PLACES = {
    "Berlin": BERLIN,
    "Hamburg": HAMBURG,
    "Paris": PARIS,
    "Sydney": SYDNEY,
    "Potsdam": (52.3906, 13.0645),
    "Brandenburg Gate": (52.5163, 13.3777),
}


@pytest.fixture
def places(db):
    for name, (lat, lon) in PLACES.items():
        GeocodeCache.objects.create(
            key=name.lower(), query=name, name=name, latitude=lat, longitude=lon, found=True
        )
    GeocodeCache.objects.create(key="nowhere", query="nowhere", found=False)
    return GeocodeCache.objects.all()


# ---- pure maths ------------------------------------------------------


def test_haversine_against_known_distances():
    assert haversine(*BERLIN, *HAMBURG) == pytest.approx(255, abs=5)
    assert haversine(*BERLIN, *PARIS) == pytest.approx(878, abs=8)
    assert haversine(*BERLIN, *SYDNEY) == pytest.approx(16096, abs=60)


def test_haversine_is_zero_for_the_same_point():
    assert haversine(*BERLIN, *BERLIN) == pytest.approx(0, abs=1e-9)


def test_haversine_is_symmetric():
    assert haversine(*BERLIN, *PARIS) == pytest.approx(haversine(*PARIS, *BERLIN))


def destination(latitude, longitude, distance_km, bearing_degrees):
    """Where you end up travelling ``distance_km`` on a given bearing."""
    angular = distance_km / EARTH_RADIUS_KM
    bearing = radians(bearing_degrees)
    lat, lon = radians(latitude), radians(longitude)
    end_lat = asin(sin(lat) * cos(angular) + cos(lat) * sin(angular) * cos(bearing))
    end_lon = lon + atan2(
        sin(bearing) * sin(angular) * cos(lat), cos(angular) - sin(lat) * sin(end_lat)
    )
    return degrees(end_lat), degrees(end_lon)


@pytest.mark.parametrize("radius", [1, 50, 500])
def test_bounding_box_contains_everything_within_the_radius(radius):
    """The invariant that makes the prefilter safe: the box may over-select, never under-select."""
    min_lat, max_lat, min_lon, max_lon = bounding_box(*BERLIN, radius)
    for bearing in range(0, 360, 15):
        lat, lon = destination(*BERLIN, radius, bearing)
        assert min_lat <= lat <= max_lat, f"bearing {bearing} escaped the box in latitude"
        assert min_lon <= lon <= max_lon, f"bearing {bearing} escaped the box in longitude"


def test_bounding_box_widens_towards_the_poles():
    """A degree of longitude covers less ground the further north you go."""
    _, _, equator_min, equator_max = bounding_box(0.0, 0.0, 100)
    _, _, arctic_min, arctic_max = bounding_box(80.0, 0.0, 100)
    assert (arctic_max - arctic_min) > (equator_max - equator_min)


def test_bounding_box_gives_up_at_the_pole():
    _, _, min_lon, max_lon = bounding_box(90.0, 0.0, 100)
    assert (min_lon, max_lon) == (-180.0, 180.0)


# ---- queryset helpers ------------------------------------------------


def test_annotate_distance_matches_the_python_calculation(places):
    row = annotate_distance(places, *BERLIN).get(key="paris")
    assert row.distance == pytest.approx(haversine(*BERLIN, *PARIS), rel=1e-6)


def test_distance_to_itself_is_zero(places):
    row = annotate_distance(places, *BERLIN).get(key="berlin")
    assert row.distance == pytest.approx(0, abs=1e-6)


def test_filter_within_keeps_only_what_is_close(places):
    names = set(filter_within(places, *BERLIN, 50).values_list("name", flat=True))
    assert names == {"Berlin", "Potsdam", "Brandenburg Gate"}


def test_filter_within_widens_correctly(places):
    names = set(filter_within(places, *BERLIN, 300).values_list("name", flat=True))
    assert "Hamburg" in names
    assert "Paris" not in names


def test_results_come_back_nearest_first(places):
    ordered = list(filter_within(places, *BERLIN, 1000).values_list("name", flat=True))
    assert ordered[0] == "Berlin"
    assert ordered.index("Potsdam") < ordered.index("Hamburg") < ordered.index("Paris")


def test_rows_without_coordinates_are_excluded(places):
    assert "nowhere" not in set(filter_within(places, *BERLIN, 20000).values_list("key", flat=True))


def test_a_radius_that_reaches_nothing_returns_empty(places):
    assert not filter_within(places, *BERLIN, 0.001).exclude(key="berlin").exists()


def test_antimeridian_does_not_lose_results(places):
    """A box spanning the date line cannot be one range; the trig must still work."""
    near_dateline = (-33.8688, 179.9)
    found = filter_within(places, *near_dateline, 3000)
    assert "Sydney" in set(found.values_list("name", flat=True))


def test_filter_within_still_returns_a_queryset(places):
    """Chaining has to keep working, so this must not collapse to a list."""
    result = filter_within(places, *BERLIN, 300).filter(name__startswith="Pots")
    assert [row.name for row in result] == ["Potsdam"]
