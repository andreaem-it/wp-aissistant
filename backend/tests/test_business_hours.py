from datetime import datetime

import pytest

from app.business_hours import add_business_minutes, parse_weekdays, validate_timezone


def add(start, minutes, **overrides):
    values = dict(weekdays="1,2,3,4,5", start_time="09:00", end_time="18:00", timezone_name="Europe/Rome")
    values.update(overrides)
    return add_business_minutes(start, minutes, **values)


def test_out_of_hours_start_moves_to_next_opening():
    # Friday 20:00 local -> Monday 09:00, then 30 working minutes. August uses UTC+2.
    assert add(datetime(2026, 8, 7, 18, 0), 30) == datetime(2026, 8, 10, 7, 30)


def test_working_minutes_skip_night_and_weekend():
    # Friday 17:30 local + 120 min = Monday 10:30 local.
    assert add(datetime(2026, 8, 7, 15, 30), 120) == datetime(2026, 8, 10, 8, 30)


def test_overnight_schedule_uses_previous_open_day():
    result = add(
        datetime(2026, 8, 3, 21, 30), 120,
        weekdays="1", start_time="22:00", end_time="02:00", timezone_name="UTC",
    )
    assert result == datetime(2026, 8, 4, 0, 0)


def test_dst_transition_counts_real_working_minutes():
    # The Sunday shift crosses Europe's fall-back transition; 180 actual minutes end at 03:00 CET.
    result = add(
        datetime(2026, 10, 24, 23, 0), 180,
        weekdays="7", start_time="01:00", end_time="05:00", timezone_name="Europe/Rome",
    )
    assert result == datetime(2026, 10, 25, 2, 0)


def test_validation_rejects_empty_days_and_unknown_zone():
    with pytest.raises(ValueError): parse_weekdays([])
    with pytest.raises(ValueError): validate_timezone("Mars/Olympus")


def test_wordpress_fixed_offset_timezone_is_supported():
    result = add(
        datetime(2026, 8, 3, 7, 0), 60,
        weekdays="1", start_time="09:00", end_time="18:00", timezone_name="+02:00",
    )
    assert result == datetime(2026, 8, 3, 8, 0)


def test_exceptional_closure_skips_a_normally_open_day():
    # Monday is closed: Friday 17:30 + 120 minutes ends Tuesday at 10:30 local.
    assert add(
        datetime(2026, 8, 7, 15, 30), 120, closed_dates=["2026-08-10"],
    ) == datetime(2026, 8, 11, 8, 30)


def test_overnight_shift_does_not_open_on_a_closed_date():
    assert add(
        datetime(2026, 8, 3, 21, 0), 60, weekdays="1", start_time="22:00",
        end_time="02:00", timezone_name="UTC", closed_dates=["2026-08-03"],
    ) == datetime(2026, 8, 10, 23, 0)
