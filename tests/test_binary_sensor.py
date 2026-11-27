"""Behaviour tests for the shower sensors, run against real Home Assistant."""
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.shower_active.const import DOMAIN

HUM = "sensor.test_humidity"
ACTIVE = "binary_sensor.test_shower_active"
ANY = "binary_sensor.any_shower_active"


async def _setup(hass: HomeAssistant, start: float, **settings) -> None:
    hass.states.async_set(HUM, str(start), {"device_class": "humidity"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Shower Active",
        data={"title": "Shower Active"},
        options={"showers": [{"id": "t1", "name": "Test", "sensor": HUM, **settings}]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _read(hass, freezer, minutes: float, value: float) -> None:
    """Advance the clock, letting timers fire, then report a reading."""
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    hass.states.async_set(HUM, str(value), {"device_class": "humidity"})
    await hass.async_block_till_done()


async def _wait(hass, freezer, minutes: float) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def _on(hass) -> bool:
    return hass.states.get(ACTIVE).state == "on"


async def test_fast_rise_turns_on_and_drop_turns_off(hass, freezer):
    await _setup(hass, 50)
    await _read(hass, freezer, 5, 52)
    assert not _on(hass)
    await _read(hass, freezer, 1, 61)  # +11 above recent low 50
    assert _on(hass)
    assert hass.states.get(ANY).state == "on"
    await _read(hass, freezer, 2, 80)
    await _read(hass, freezer, 3, 85)
    await _read(hass, freezer, 3, 84.5)  # within tolerance, still at peak
    assert _on(hass)
    await _read(hass, freezer, 2, 81.9)  # 3.1 below peak 85
    assert not _on(hass)
    assert hass.states.get(ACTIVE).attributes["last_off_reason"] == "drop"
    assert hass.states.get(ANY).state == "off"


async def test_humid_day_drift_does_not_turn_on(hass, freezer):
    """Weather moves humidity slowly; a high but slow level is not a shower."""
    await _setup(hass, 63)
    value = 63.0
    for _ in range(24):  # +0.5 every 5 minutes for 2 hours, up to 75
        value += 0.5
        await _read(hass, freezer, 5, value)
        assert not _on(hass)


async def test_min_humidity_floor(hass, freezer):
    await _setup(hass, 30)
    await _read(hass, freezer, 2, 45)  # +15, but below 60
    assert not _on(hass)


async def test_quiet_timer_turns_off_without_new_readings(hass, freezer):
    """Battery sensors go silent when the value is steady; the timer must still end it."""
    await _setup(hass, 50)
    await _read(hass, freezer, 2, 70)
    await _read(hass, freezer, 3, 88)
    assert _on(hass)
    await _wait(hass, freezer, 14)
    assert _on(hass)
    await _wait(hass, freezer, 1.5)  # 15 min after the last peak reading
    assert not _on(hass)
    assert hass.states.get(ACTIVE).attributes["last_off_reason"] == "quiet"


async def test_plateau_at_peak_keeps_it_on(hass, freezer):
    await _setup(hass, 50)
    await _read(hass, freezer, 2, 75)
    for _ in range(5):  # saturated: 90 +/- 0.5 every 10 minutes
        await _read(hass, freezer, 10, 89.6)
        await _read(hass, freezer, 0.5, 90.0)
    assert _on(hass)


async def test_max_minutes_cap(hass, freezer):
    await _setup(hass, 50, max_minutes=30)
    await _read(hass, freezer, 2, 62)
    value = 62.0
    for _ in range(10):  # slowly keeps setting new peaks
        value += 1
        await _read(hass, freezer, 5, value)
    assert not _on(hass)
    assert hass.states.get(ACTIVE).attributes["last_off_reason"] == "max"


async def test_back_to_back_showers(hass, freezer):
    """After OFF the next fast rise counts, without falling back to a low level."""
    await _setup(hass, 55)
    await _read(hass, freezer, 2, 85)
    assert _on(hass)
    await _read(hass, freezer, 5, 78)  # drop -> off
    assert not _on(hass)
    await _read(hass, freezer, 3, 76)
    await _read(hass, freezer, 2, 86)  # +10 above 76, the low since OFF
    assert _on(hass)


async def test_no_retrigger_from_pre_shower_low(hass, freezer):
    """Readings from before the OFF don't count as the baseline afterwards."""
    await _setup(hass, 50)
    await _read(hass, freezer, 2, 85)
    await _read(hass, freezer, 3, 80)  # off by drop
    assert not _on(hass)
    await _read(hass, freezer, 2, 81)  # +31 above 50, but 50 was before the OFF
    assert not _on(hass)


async def test_on_state_restored_after_restart(hass, freezer):
    now = dt_util.utcnow()
    mock_restore_cache(hass, [State(ACTIVE, "on", {
        "started_at": (now - timedelta(minutes=5)).isoformat(),
        "peak": 85.0,
        "peak_at": (now - timedelta(minutes=2)).isoformat(),
    })])
    await _setup(hass, 84)
    assert _on(hass)
    assert hass.states.get(ANY).state == "on"
    await _wait(hass, freezer, 13.5)  # 15 min after the restored peak
    assert not _on(hass)


async def test_stale_on_state_turns_off_at_startup(hass, freezer):
    now = dt_util.utcnow()
    mock_restore_cache(hass, [State(ACTIVE, "on", {
        "started_at": (now - timedelta(hours=3)).isoformat(),
        "peak": 85.0,
        "peak_at": (now - timedelta(hours=3)).isoformat(),
    })])
    await _setup(hass, 60)
    assert not _on(hass)
    assert hass.states.get(ACTIVE).attributes["last_off_reason"] == "restart"


async def test_unavailable_readings_ignored(hass, freezer):
    await _setup(hass, 50)
    await _read(hass, freezer, 2, 75)
    hass.states.async_set(HUM, "unavailable")
    await hass.async_block_till_done()
    assert _on(hass)


async def test_old_settings_are_ignored(hass, freezer):
    """Entries saved by v1.3.0 still load; their threshold settings no longer apply."""
    await _setup(hass, 50, threshold=63.0, decline_count=2, hysteresis=5.0)
    await _read(hass, freezer, 2, 64)  # +14 above the recent low; the old threshold plays no part
    assert _on(hass)
    attrs = hass.states.get(ACTIVE).attributes
    assert attrs["rise"] == 8.0 and "threshold" not in attrs
