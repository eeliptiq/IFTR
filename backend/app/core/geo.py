"""
Straight-line geometry for driver job offers.

No maps and no routing service: a courier deciding whether to take a job needs
"how far" and "roughly which way", and school trigonometry answers both. What it
deliberately cannot answer is *where*: a distance and a compass point are coarse
facts about a trip, while the address they were computed from stays encrypted.

The bearing is the initial great-circle heading from pickup to dropoff, so the
arrow on the card points the way the courier sets off, not the way they finish.
"""

from math import asin, atan2, cos, degrees, radians, sin, sqrt

# Mean Earth radius. Fine to a few metres at city scale, and this is a straight
# line over a road network anyway - it is an estimate, not a survey.
EARTH_RADIUS_KM = 6371.0088

# Eight wedges of 45 degrees, starting north and running clockwise.
COMPASS_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def straight_line_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres (haversine)."""
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = radians(lng2 - lng1)

    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, a)))


def bearing_degrees(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial heading from the first point to the second, 0-360 clockwise from north."""
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_lambda = radians(lng2 - lng1)

    x = sin(delta_lambda) * cos(phi2)
    y = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(delta_lambda)
    return (degrees(atan2(x, y)) + 360.0) % 360.0


def compass_point(bearing: float) -> str:
    """The eight-point name of a bearing: N, NE, E, ... NW.

    Each point owns the 45 degrees centred on it, so 337.5 rounds to N rather
    than to NW.
    """
    index = int(((bearing % 360.0) + 22.5) // 45.0) % len(COMPASS_POINTS)
    return COMPASS_POINTS[index]
