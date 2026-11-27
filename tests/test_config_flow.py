"""Options flow: add and edit a shower with the v1.4.0 settings."""
import json
from pathlib import Path

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shower_active.const import DOMAIN

COMPONENT = Path(__file__).parent.parent / "custom_components" / DOMAIN


def test_strings_and_translations_match():
    assert json.loads((COMPONENT / "strings.json").read_text()) == json.loads(
        (COMPONENT / "translations" / "en.json").read_text()
    )


async def test_add_then_edit_shower(hass):
    hass.states.async_set("sensor.h", "50", {"device_class": "humidity"})
    entry = MockConfigEntry(domain=DOMAIN, data={"title": "x"}, options={"showers": [
        {"id": "a", "name": "Old", "sensor": "sensor.h",
         "threshold": 63.0, "decline_count": 2, "hysteresis": 5.0},
    ]})
    entry.add_to_hass(hass)

    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] == FlowResultType.MENU
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "add_shower"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "name": "New", "sensor": "sensor.h", "rise": 6,
    })
    assert r["type"] == FlowResultType.MENU
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "edit_shower"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"shower": "a"})
    defaults = {str(k): k.default() for k in r["data_schema"].schema if hasattr(k, "default")}
    assert defaults["rise"] == 8.0 and defaults["quiet_minutes"] == 15
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "name": "Old", "sensor": "sensor.h", "drop": 4,
    })
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "finish"})
    assert r["type"] == FlowResultType.CREATE_ENTRY

    showers = {s["name"]: s for s in entry.options["showers"]}
    assert showers["New"]["rise"] == 6.0 and showers["New"]["max_minutes"] == 60
    assert showers["Old"]["id"] == "a" and showers["Old"]["drop"] == 4.0
    assert "threshold" not in showers["Old"]
