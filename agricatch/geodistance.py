"""Distance filtering on plain sqlite or MySQL.

The old version of this built a MySQL-specific string by hand. These build ORM
expressions instead, so the same query runs on whatever backend is configured,
and no PostGIS is involved.

A radius query runs in two stages: a bounding box narrows the candidates using
an ordinary index on the coordinate columns, then the trigonometry runs on
what survives. Skipping the box makes the database compute a cosine for every
row in the table.
"""

from __future__ import annotations

from math import asin, cos, degrees, radians, sin, sqrt
from typing import Any, TypeVar

from django.db.models import ExpressionWrapper, F, FloatField, QuerySet, Value
from django.db.models.functions import ACos, Cos, Greatest, Least, Radians, Sin

EARTH_RADIUS_KM = 6371.0088

# Guards the bounding box against float rounding at its own edge; see bounding_box.
EDGE_PADDING_DEGREES = 1e-9

_QS = TypeVar("_QS", bound=QuerySet[Any])


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two points already in hand."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def bounding_box(
    latitude: float, longitude: float, radius_km: float
) -> tuple[float, float, float, float]:
    """The lat/lon window that is guaranteed to contain everything within the radius.

    Returns ``(min_lat, max_lat, min_lon, max_lon)``. The longitude span widens
    towards the poles, where a degree of longitude covers less ground; near
    enough to one it gives up and returns the whole range.
    """
    lat_delta = degrees(radius_km / EARTH_RADIUS_KM)
    shrink = abs(cos(radians(latitude)))
    if shrink < 1e-9:
        lon_delta = 180.0
    else:
        lon_delta = min(180.0, degrees(radius_km / (EARTH_RADIUS_KM * shrink)))

    # A point at exactly the radius can round to a hair outside the edge, and
    # this box has to be a superset - anything it drops never reaches the
    # distance check. The padding is around a tenth of a millimetre.
    lat_delta += EDGE_PADDING_DEGREES
    lon_delta = min(180.0, lon_delta + EDGE_PADDING_DEGREES)

    return (
        max(-90.0, latitude - lat_delta),
        min(90.0, latitude + lat_delta),
        longitude - lon_delta,
        longitude + lon_delta,
    )


def distance_expression(
    latitude: float,
    longitude: float,
    lat_field: str = "latitude",
    lon_field: str = "longitude",
) -> ExpressionWrapper:
    """ORM expression giving the distance in kilometres from a fixed point.

    Spherical law of cosines rather than haversine - one fewer function for the
    backend to provide, and the two only diverge at distances of a few metres.
    """
    origin_lat = radians(latitude)
    cosine = Value(cos(origin_lat)) * Cos(Radians(F(lat_field))) * Cos(
        Radians(F(lon_field)) - Value(radians(longitude))
    ) + Value(sin(origin_lat)) * Sin(Radians(F(lat_field)))
    # Float drift can push the result a hair outside acos's domain.
    clamped = Least(Value(1.0), Greatest(Value(-1.0), cosine))
    return ExpressionWrapper(Value(EARTH_RADIUS_KM) * ACos(clamped), output_field=FloatField())


def annotate_distance(
    queryset: _QS,
    latitude: float,
    longitude: float,
    lat_field: str = "latitude",
    lon_field: str = "longitude",
    alias: str = "distance",
) -> _QS:
    """Add a distance-in-km annotation, without filtering anything out."""
    annotated: _QS = queryset.annotate(
        **{alias: distance_expression(latitude, longitude, lat_field, lon_field)}
    )
    return annotated


def filter_within(
    queryset: _QS,
    latitude: float,
    longitude: float,
    radius_km: float,
    lat_field: str = "latitude",
    lon_field: str = "longitude",
    alias: str = "distance",
) -> _QS:
    """Rows within ``radius_km``, annotated with the distance and nearest first."""
    min_lat, max_lat, min_lon, max_lon = bounding_box(latitude, longitude, radius_km)

    narrowed = queryset.filter(
        **{
            f"{lat_field}__isnull": False,
            f"{lon_field}__isnull": False,
            f"{lat_field}__gte": min_lat,
            f"{lat_field}__lte": max_lat,
        }
    )
    # A box that wraps the antimeridian cannot be expressed as one range, so in
    # that case the trigonometry below does the work alone.
    if min_lon >= -180.0 and max_lon <= 180.0:
        narrowed = narrowed.filter(**{f"{lon_field}__gte": min_lon, f"{lon_field}__lte": max_lon})

    annotated = annotate_distance(narrowed, latitude, longitude, lat_field, lon_field, alias)
    result: _QS = annotated.filter(**{f"{alias}__lte": radius_km}).order_by(alias)
    return result
