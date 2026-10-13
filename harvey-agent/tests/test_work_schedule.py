"""Work schedule: Harvey only works inside its configured shifts."""

from datetime import datetime

import pytest
import pytz

from harvey.config import HarveyConfig, WorkScheduleConfig
from harvey.main import next_shift_start, off_shift

NY = pytz.timezone("America/New_York")


def _config(**schedule) -> HarveyConfig:
    return HarveyConfig(
        persona={"name": "A", "company": "B", "role": "C", "email": "a@b.co",
                 "linkedin": "", "tone": ""},
        product={"name": "P", "description": "D", "pricing": "",
                 "key_benefits": [], "objection_responses": {}},
        icp={"industries": [], "company_size": "", "titles": [], "geography": []},
        usage={"work_schedule": schedule},
    )


def _ny(y, m, d, hh, mm=0):
    return NY.localize(datetime(y, m, d, hh, mm))


WEEKDAY_SHIFT = {
    "enabled": True,
    "timezone": "America/New_York",
    "shifts": [{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:30", "end": "17:30"}],
}


def test_disabled_schedule_never_rests():
    config = _config(enabled=False)
    assert off_shift(config, _ny(2026, 10, 18, 3)) is False  # Sunday 3am
    assert next_shift_start(config) is None


def test_inside_and_outside_weekday_shift():
    config = _config(**WEEKDAY_SHIFT)
    assert off_shift(config, _ny(2026, 10, 13, 9)) is False      # Tue 09:00
    assert off_shift(config, _ny(2026, 10, 13, 8, 29)) is True    # before start
    assert off_shift(config, _ny(2026, 10, 13, 17, 30)) is True   # end is exclusive
    assert off_shift(config, _ny(2026, 10, 17, 11)) is True       # Saturday


def test_next_shift_skips_weekend():
    config = _config(**WEEKDAY_SHIFT)
    nxt = next_shift_start(config, _ny(2026, 10, 16, 18))  # Fri 18:00
    assert nxt == _ny(2026, 10, 19, 8, 30)                  # Mon 08:30


def test_multiple_shifts_and_other_timezone_input():
    config = _config(
        enabled=True,
        timezone="America/New_York",
        shifts=[
            {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:30", "end": "12:00"},
            {"days": "sat", "start": "10:00", "end": "13:00"},
        ],
    )
    # Saturday 15:30 UTC == 11:30 New York (EDT)
    sat_utc = pytz.utc.localize(datetime(2026, 10, 17, 15, 30))
    assert off_shift(config, sat_utc) is False
    assert off_shift(config, _ny(2026, 10, 13, 13)) is True  # weekday afternoon


def test_shift_across_dst_change():
    config = _config(**WEEKDAY_SHIFT)
    # US DST ends Sun Nov 1 2026; Monday's shift is still 08:30 local.
    assert next_shift_start(config, _ny(2026, 10, 31, 12)) == _ny(2026, 11, 2, 8, 30)


@pytest.mark.parametrize(
    "bad",
    [
        {"shifts": [{"days": ["funday"]}]},
        {"shifts": [{"days": []}]},
        {"shifts": [{"start": "18:00", "end": "09:00"}]},
        {"shifts": [{"start": "25:00"}]},
        {"timezone": "Mars/Base"},
    ],
)
def test_rejects_bad_schedule(bad):
    with pytest.raises(ValueError):
        WorkScheduleConfig(enabled=True, **bad)


def test_day_names_are_forgiving():
    ws = WorkScheduleConfig(enabled=True, shifts=[{"days": ["Monday", "TUE"]}])
    assert ws.shifts[0].days == ["mon", "tue"]
