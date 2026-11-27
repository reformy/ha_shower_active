"""Binary sensors for Shower Active."""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    BASELINE_WINDOW_MINUTES,
    CONF_DROP,
    CONF_ID,
    CONF_MAX_MINUTES,
    CONF_MIN_HUMIDITY,
    CONF_NAME,
    CONF_QUIET_MINUTES,
    CONF_RISE,
    CONF_SENSOR,
    CONF_SHOWERS,
    DEFAULT_DROP,
    DEFAULT_MAX_MINUTES,
    DEFAULT_MIN_HUMIDITY,
    DEFAULT_QUIET_MINUTES,
    DEFAULT_RISE,
    PEAK_TOLERANCE,
    SENSOR_AGGREGATE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    showers = entry.options.get(CONF_SHOWERS, [])

    individual: list[ShowerHumiditySensor] = []
    for shower_conf in showers:
        # Showers added before per-shower ids existed fall back to the source entity_id
        shower_id = shower_conf.get(CONF_ID, shower_conf[CONF_SENSOR])
        # Settings from v1.3.0 and earlier (threshold, decline_count, hysteresis)
        # may still be stored; they are ignored.
        sensor = ShowerHumiditySensor(
            unique_id=f"{entry.entry_id}_{shower_id}",
            name=shower_conf[CONF_NAME],
            humidity_sensor=shower_conf[CONF_SENSOR],
            rise=shower_conf.get(CONF_RISE, DEFAULT_RISE),
            min_humidity=shower_conf.get(CONF_MIN_HUMIDITY, DEFAULT_MIN_HUMIDITY),
            drop=shower_conf.get(CONF_DROP, DEFAULT_DROP),
            quiet_minutes=shower_conf.get(CONF_QUIET_MINUTES, DEFAULT_QUIET_MINUTES),
            max_minutes=shower_conf.get(CONF_MAX_MINUTES, DEFAULT_MAX_MINUTES),
        )
        individual.append(sensor)

    aggregate = AnyShowerActiveSensor(
        unique_id=f"{entry.entry_id}_{SENSOR_AGGREGATE}",
        shower_sensors=individual,
    )
    for sensor in individual:
        sensor.aggregate = aggregate

    async_add_entities(individual + [aggregate])

    # Reload sensors when options change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    return dt_util.parse_datetime(value)


class ShowerHumiditySensor(BinarySensorEntity, RestoreEntity):
    """
    Binary sensor that is ON while a shower is in use.

    A shower makes humidity jump fast (typically 15-25 points in 2-5 minutes),
    while weather moves it slowly. So detection is based on rises and peaks,
    not on a fixed humidity level, which humid days can sit above all day.

    ON:  a reading is at least `rise` points above the lowest reading of the
         last BASELINE_WINDOW_MINUTES (only counting readings since the last
         OFF), and at least `min_humidity`.
    OFF, whichever comes first:
         - a reading `drop` or more points below the session's peak;
         - `quiet_minutes` with no reading at (or within PEAK_TOLERANCE of)
           the peak. This runs on a timer, so it also ends the session when
           the humidity sensor stops reporting, which battery sensors do when
           the value is steady;
         - `max_minutes` after it turned on.

    After OFF it can turn on again at the next fast rise. The ON state and
    the session's peak are restored across restarts.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        name: str,
        humidity_sensor: str,
        rise: float = DEFAULT_RISE,
        min_humidity: float = DEFAULT_MIN_HUMIDITY,
        drop: float = DEFAULT_DROP,
        quiet_minutes: float = DEFAULT_QUIET_MINUTES,
        max_minutes: float = DEFAULT_MAX_MINUTES,
    ) -> None:
        self._attr_unique_id = unique_id
        self.shower_name = name
        self._attr_name = f"{name} Shower Active"
        self._humidity_sensor = humidity_sensor
        self._rise = float(rise)
        self._min_humidity = float(min_humidity)
        self._drop = float(drop)
        self._quiet = timedelta(minutes=float(quiet_minutes))
        self._max = timedelta(minutes=float(max_minutes))
        self.aggregate: AnyShowerActiveSensor | None = None

        self._attr_is_on = False
        # Recent readings as (time, humidity), oldest first
        self._readings: deque[tuple[datetime, float]] = deque()
        self._last_humidity: float | None = None
        self._last_off: datetime | None = None
        self._last_off_reason: str | None = None
        self._started: datetime | None = None
        self._peak: float | None = None
        self._peak_at: datetime | None = None

        self._unsub_state = None
        self._unsub_timer: CALLBACK_TYPE | None = None

    # ----- lifecycle -------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        now = dt_util.utcnow()

        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_ON:
            started = _parse_time(last.attributes.get("started_at"))
            peak_at = _parse_time(last.attributes.get("peak_at"))
            peak = last.attributes.get("peak")
            if started and peak_at and isinstance(peak, (int, float)):
                self._attr_is_on = True
                self._started = started
                self._peak = float(peak)
                self._peak_at = peak_at

        # Seed the baseline with the current value, so the first reading after
        # a restart can already count as a rise.
        state = self.hass.states.get(self._humidity_sensor)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                self._last_humidity = float(state.state)
                self._readings.append((now, self._last_humidity))
            except ValueError:
                pass

        self._unsub_state = async_track_state_change_event(
            self.hass,
            [self._humidity_sensor],
            self._handle_humidity_change,
        )

        if self._attr_is_on:
            if self._deadline() <= now:
                self._turn_off(now, "restart")
            else:
                self._schedule_timer()
                self._notify_aggregate()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        self._cancel_timer()

    # ----- logic -----------------------------------------------------------

    @callback
    def _handle_humidity_change(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        try:
            humidity = float(new_state.state)
        except ValueError:
            return
        self._process(dt_util.utcnow(), humidity)

    @callback
    def _process(self, now: datetime, humidity: float) -> None:
        """Handle one humidity reading taken at `now`."""
        self._last_humidity = humidity

        if self._attr_is_on and now >= self._deadline():
            # The timer should already have handled this; be safe if it lagged.
            self._turn_off(self._deadline(), "quiet")

        if not self._attr_is_on:
            baseline = self._baseline(now)
            self._add_reading(now, humidity)
            if (
                baseline is not None
                and humidity >= self._min_humidity
                and humidity - baseline >= self._rise
            ):
                _LOGGER.debug(
                    "%s: %.1f is %.1f above recent low %.1f -> ON",
                    self._attr_name, humidity, humidity - baseline, baseline,
                )
                self._attr_is_on = True
                self._started = now
                self._peak = humidity
                self._peak_at = now
                self._schedule_timer()
                self.async_write_ha_state()
                self._notify_aggregate()
            else:
                self.async_write_ha_state()
            return

        self._add_reading(now, humidity)
        if humidity >= self._peak - PEAK_TOLERANCE:
            self._peak = max(self._peak, humidity)
            self._peak_at = now
            self._schedule_timer()
            self.async_write_ha_state()
        elif humidity <= self._peak - self._drop:
            _LOGGER.debug(
                "%s: %.1f is %.1f below peak %.1f -> OFF",
                self._attr_name, humidity, self._peak - humidity, self._peak,
            )
            self._turn_off(now, "drop")
        else:
            self.async_write_ha_state()

    def _add_reading(self, now: datetime, humidity: float) -> None:
        self._readings.append((now, humidity))
        cutoff = now - timedelta(minutes=BASELINE_WINDOW_MINUTES)
        while self._readings and self._readings[0][0] < cutoff:
            self._readings.popleft()

    def _baseline(self, now: datetime) -> float | None:
        """Lowest reading of the recent window, counting only readings since the last OFF."""
        since = now - timedelta(minutes=BASELINE_WINDOW_MINUTES)
        if self._last_off is not None and self._last_off > since:
            since = self._last_off
        values = [h for t, h in self._readings if t >= since]
        return min(values) if values else None

    def _deadline(self) -> datetime:
        return min(self._peak_at + self._quiet, self._started + self._max)

    @callback
    def _turn_off(self, when: datetime, reason: str) -> None:
        self._cancel_timer()
        self._attr_is_on = False
        self._last_off = when
        self._last_off_reason = reason
        self._started = None
        self._peak = None
        self._peak_at = None
        self.async_write_ha_state()
        self._notify_aggregate()

    def _schedule_timer(self) -> None:
        self._cancel_timer()
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass, self._handle_timer, self._deadline()
        )

    def _cancel_timer(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _handle_timer(self, now: datetime) -> None:
        self._unsub_timer = None
        if not self._attr_is_on:
            return
        deadline = self._deadline()
        reason = "max" if deadline == self._started + self._max else "quiet"
        _LOGGER.debug("%s: %s timer -> OFF", self._attr_name, reason)
        self._turn_off(deadline, reason)

    @callback
    def _notify_aggregate(self) -> None:
        if self.aggregate is not None:
            self.aggregate.async_update_from_children()

    # ----- presentation ----------------------------------------------------

    @property
    def icon(self) -> str:
        return "mdi:shower" if self.is_on else "mdi:shower-head"

    @property
    def extra_state_attributes(self):
        def iso(t: datetime | None) -> str | None:
            return t.isoformat() if t else None

        now = dt_util.utcnow()
        return {
            "humidity_sensor": self._humidity_sensor,
            "current_humidity": self._last_humidity,
            "recent_low": None if self._attr_is_on else self._baseline(now),
            "started_at": iso(self._started),
            "peak": self._peak,
            "peak_at": iso(self._peak_at),
            "last_off_reason": self._last_off_reason,
            "rise": self._rise,
            "min_humidity": self._min_humidity,
            "drop": self._drop,
            "quiet_minutes": self._quiet.total_seconds() / 60,
            "max_minutes": self._max.total_seconds() / 60,
        }


class AnyShowerActiveSensor(BinarySensorEntity):
    """Aggregate sensor: ON if any shower sensor is ON."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        shower_sensors: list[ShowerHumiditySensor],
    ) -> None:
        self._attr_unique_id = unique_id
        self._attr_name = "Any Shower Active"
        self._shower_sensors = shower_sensors
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        self._attr_is_on = any(s.is_on for s in self._shower_sensors)

    @callback
    def async_update_from_children(self) -> None:
        """Recompute state; called by individual shower sensors after they change."""
        is_on = any(s.is_on for s in self._shower_sensors)
        if is_on == self._attr_is_on:
            return
        self._attr_is_on = is_on
        # Guard against a child firing before this entity is added to hass
        # (a child restoring an ON state at startup can come first)
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()

    @property
    def icon(self) -> str:
        return "mdi:shower" if self.is_on else "mdi:shower-head"

    @property
    def extra_state_attributes(self):
        return {
            "active_showers": [
                s.shower_name for s in self._shower_sensors if s.is_on
            ],
            "monitored_showers": [s.shower_name for s in self._shower_sensors],
        }
