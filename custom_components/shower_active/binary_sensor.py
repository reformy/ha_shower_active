"""Binary sensors for Shower Active."""
from __future__ import annotations

import logging
from collections import deque

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DOMAIN,
    CONF_SHOWERS,
    CONF_SENSOR,
    CONF_NAME,
    CONF_THRESHOLD,
    CONF_DECLINE_COUNT,
    DEFAULT_THRESHOLD,
    DEFAULT_DECLINE_COUNT,
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
        sensor = ShowerHumiditySensor(
            hass=hass,
            unique_id=f"{entry.entry_id}_{shower_conf[CONF_SENSOR]}",
            name=shower_conf[CONF_NAME],
            humidity_sensor=shower_conf[CONF_SENSOR],
            threshold=shower_conf.get(CONF_THRESHOLD, DEFAULT_THRESHOLD),
            decline_count=shower_conf.get(CONF_DECLINE_COUNT, DEFAULT_DECLINE_COUNT),
        )
        individual.append(sensor)

    aggregate = AnyShowerActiveSensor(
        hass=hass,
        unique_id=f"{entry.entry_id}_{SENSOR_AGGREGATE}",
        shower_sensors=individual,
    )

    async_add_entities(individual + [aggregate], update_before_add=True)

    # Reload sensors when options change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


class ShowerHumiditySensor(BinarySensorEntity):
    """
    Binary sensor that is ON when a shower is in use.

    Turn ON logic:  humidity rises above `threshold`
    Turn OFF logic: humidity starts declining (N consecutive lower readings
                    while already ON), regardless of absolute value.
    """

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        name: str,
        humidity_sensor: str,
        threshold: float,
        decline_count: int,
    ) -> None:
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._humidity_sensor = humidity_sensor
        self._threshold = threshold
        self._decline_count = decline_count

        self._attr_is_on = False
        self._last_humidity: float | None = None
        # Rolling window of recent readings to detect consistent decline
        self._recent: deque[float] = deque(maxlen=decline_count + 1)
        self._unsub = None

    async def async_added_to_hass(self) -> None:
        # Bootstrap from current state
        state = self.hass.states.get(self._humidity_sensor)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                self._last_humidity = float(state.state)
                self._recent.append(self._last_humidity)
            except ValueError:
                pass

        self._unsub = async_track_state_change_event(
            self.hass,
            [self._humidity_sensor],
            self._handle_humidity_change,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()

    @callback
    def _handle_humidity_change(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return

        try:
            humidity = float(new_state.state)
        except ValueError:
            return

        self._recent.append(humidity)
        prev = self._last_humidity
        self._last_humidity = humidity

        if not self._attr_is_on:
            # Turn ON when humidity crosses threshold
            if humidity > self._threshold:
                _LOGGER.debug(
                    "%s: humidity %.1f > threshold %.1f → shower ON",
                    self._attr_name, humidity, self._threshold,
                )
                self._attr_is_on = True
                self.async_write_ha_state()
        else:
            # Turn OFF when we see consistent decline
            if self._is_declining():
                _LOGGER.debug(
                    "%s: humidity declining (recent=%s) → shower OFF",
                    self._attr_name, list(self._recent),
                )
                self._attr_is_on = False
                self._recent.clear()
                if self._last_humidity is not None:
                    self._recent.append(self._last_humidity)
                self.async_write_ha_state()

    def _is_declining(self) -> bool:
        """Return True if the last `decline_count` readings are all lower than the one before them."""
        readings = list(self._recent)
        if len(readings) < self._decline_count + 1:
            return False
        # Check that each of the last decline_count readings is lower than the previous
        tail = readings[-(self._decline_count + 1):]
        return all(tail[i] > tail[i + 1] for i in range(len(tail) - 1))

    @property
    def extra_state_attributes(self):
        return {
            "humidity_sensor": self._humidity_sensor,
            "threshold": self._threshold,
            "current_humidity": self._last_humidity,
            "decline_readings_required": self._decline_count,
        }


class AnyShowerActiveSensor(BinarySensorEntity):
    """Aggregate sensor: ON if any shower sensor is ON."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        shower_sensors: list[ShowerHumiditySensor],
    ) -> None:
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_name = "Any Shower Active"
        self._shower_sensors = shower_sensors
        self._attr_is_on = False
        self._unsubs = []

    async def async_added_to_hass(self) -> None:
        # Track state changes of the individual shower sensors
        sensor_entity_ids = [s.entity_id for s in self._shower_sensors if s.entity_id]

        @callback
        def _update(_event=None):
            self._attr_is_on = any(s.is_on for s in self._shower_sensors)
            self.async_write_ha_state()

        if sensor_entity_ids:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, sensor_entity_ids, _update
                )
            )

        # Also update whenever a shower sensor writes state (they share hass)
        # We register a listener after a tick so entity_ids are registered
        self.hass.async_create_task(self._delayed_subscribe())

    async def _delayed_subscribe(self):
        """Subscribe after individual sensors have registered their entity_ids."""
        import asyncio
        await asyncio.sleep(0)
        sensor_entity_ids = [s.entity_id for s in self._shower_sensors if s.entity_id]
        if sensor_entity_ids:
            @callback
            def _update(event=None):
                self._attr_is_on = any(s.is_on for s in self._shower_sensors)
                self.async_write_ha_state()

            for unsub in self._unsubs:
                unsub()
            self._unsubs = [
                async_track_state_change_event(
                    self.hass, sensor_entity_ids, _update
                )
            ]
            _update()

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubs:
            unsub()

    @property
    def extra_state_attributes(self):
        return {
            "active_showers": [
                s.name for s in self._shower_sensors if s.is_on
            ],
            "monitored_showers": [s.name for s in self._shower_sensors],
        }
