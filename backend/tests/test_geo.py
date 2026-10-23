"""
The arithmetic behind a job offer: how far, which way, and how long.

This is the one part of the offer screen that is pure calculation rather than
data flow, so it is worth pinning down on its own: a bearing off by one wedge
sends a cyclist the wrong way, and an ETA that ignores the vehicle offers an
hour's walk as if it were a ten-minute drive.
"""

from app.core.geo import bearing_degrees, compass_point, straight_line_km
from app.models.general import vehicle_eta_minutes


def test_a_degree_of_latitude_is_about_a_hundred_and_eleven_kilometres():
    """A sanity check on the distance formula against a fact everyone knows."""
    assert round(straight_line_km(40.0, -74.0, 41.0, -74.0), 1) == 111.2


def test_the_same_point_is_no_distance_at_all():
    assert straight_line_km(40.7, -74.0, 40.7, -74.0) == 0.0


def test_the_bearing_points_along_the_four_cardinals():
    assert round(bearing_degrees(40.7, -74.0, 40.8, -74.0)) == 0  # north
    assert round(bearing_degrees(40.7, -74.0, 40.7, -73.9)) == 90  # east
    assert round(bearing_degrees(40.8, -74.0, 40.7, -74.0)) == 180  # south
    assert round(bearing_degrees(40.7, -74.0, 40.7, -74.1)) == 270  # west


def test_each_compass_point_owns_the_wedges_around_it():
    """North is 337.5 to 22.5 degrees, not a single direction."""
    assert compass_point(0) == "N"
    assert compass_point(359.9) == "N"
    assert compass_point(22.4) == "N"  # still nearer north than north-east
    assert compass_point(22.6) == "NE"
    assert compass_point(90) == "E"
    assert compass_point(225) == "SW"
    assert compass_point(-90) == "W"  # an unnormalised bearing is not an error


def test_the_eta_follows_the_vehicle_not_the_distance():
    """Eight kilometres is a twenty-minute drive and a two-hour walk."""
    car = vehicle_eta_minutes("car", 8.0)
    walk = vehicle_eta_minutes("walk", 8.0)

    assert car == 24
    assert walk == 111
    assert car < walk


def test_an_unknown_vehicle_is_slow_rather_than_fatal():
    """A hand-edited row must not 500 a driver's board mid-shift."""
    assert vehicle_eta_minutes("spaceship", 8.0) == vehicle_eta_minutes("truck", 8.0)
