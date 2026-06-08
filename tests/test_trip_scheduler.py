from datetime import time

import pytest

from putevoy.generator.trip_scheduler import MAX_TRIPS_PER_DAY, trip_times


def test_first_trip():
    assert trip_times(0) == (time(9, 0), time(10, 0), time(11, 0), time(12, 0))


def test_last_trip_ends_at_21():
    assert trip_times(3)[-1] == time(21, 0)


def test_invalid_trip_index():
    with pytest.raises(ValueError):
        trip_times(MAX_TRIPS_PER_DAY)
    with pytest.raises(ValueError):
        trip_times(-1)
