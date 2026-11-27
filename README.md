# Shower Active — Home Assistant Integration

A Home Assistant custom integration that exposes `binary_sensor` entities indicating when a shower is in use, based on a humidity sensor.

## How it works

A shower makes humidity jump fast, typically 15–25 points in 2–5 minutes. Weather moves it slowly, and on humid days a bathroom can sit above 70% all day with nobody in it. So detection is based on rises and peaks, not on a fixed humidity level.

| Event | Rule (defaults) |
|-------|-----------------|
| **Shower starts** (ON) | A reading is **8+ points above the lowest reading of the last 20 minutes**, and at least **60%** |
| **Shower ends** (OFF) | Whichever comes first: a reading **3+ points below the shower's peak**; **15 minutes with no new peak**; **60 minutes** after it turned on |

- "No new peak" runs on a timer, so the shower ends even when the humidity sensor stops reporting. Battery sensors such as Aqara only report when the value changes, and go quiet when it's steady.
- A reading within 1 point of the peak counts as still at the peak, so a saturated bathroom (steady ~90%) stays ON while the water runs.
- After OFF, the next fast rise counts as a new shower straight away (only readings since the OFF count as the "lowest reading"), so back-to-back showers are both detected.
- The ON state, start time and peak survive an HA restart.

### Why not a fixed threshold (v1.3.0 and earlier)

Up to v1.3.0 the sensor turned ON above a fixed level (63%) and OFF after 2 consecutive falling readings. With real Aqara data that failed three ways: humid weather alone crossed 63% and kept sensors ON for 90–110 minutes; noisy, sparse readings delayed the OFF by up to an hour after the shower ended; and after a false trigger the sensor waited for humidity to fall to 58% before it could trigger again, so real showers on humid days were missed. Replaying 10 days of data from three bathrooms, v1.4.0 cut total ON time from 1,566 to 889 minutes and caught the missed showers. Detection speed was unchanged: a median of under a minute after the first rising reading.

## Sensors created

For each configured shower (e.g. named "Master"):
- `binary_sensor.master_shower_active` ("Master Shower Active") — ON while that shower is in use

Plus one aggregate:
- `binary_sensor.any_shower_active` — ON if **any** configured shower is active

## Installation

### Via HACS (recommended)
1. In HACS → Integrations → ⋮ → Custom repositories
2. Add this repo URL, category: **Integration**
3. Install "Shower Active", restart HA

### Manual
1. Copy `custom_components/shower_active/` into your HA `custom_components/` folder
2. Restart Home Assistant

## Configuration

### Create the entry

1. Go to **Settings → Devices & Services → Helpers** tab → **+ Create Helper** → search for **Shower Active**
   (on older HA versions it appears under the **Integrations** tab via **+ Add Integration** instead)
2. Give the entry a title (the default "Shower Active" is fine) and create it

This immediately creates the aggregate `binary_sensor.any_shower_active` — it stays off until you add showers.

### Open the shower manager

This is a helper-type integration, so it has **no card on the Integrations tab**. To manage showers:

1. Go to **Settings → Devices & Services → Helpers**
2. Click the **Any Shower Active** row

The Shower Active menu opens with four options: **Add a shower**, **Edit a shower**, **Remove a shower**, and **Save and finish**.

Nothing is applied until you choose **Save and finish** — the integration then reloads itself, so changes take effect immediately with no HA restart.

### Add a shower

Choose **Add a shower** and fill in:

- **Name**: e.g. `Master` — creates `binary_sensor.master_shower_active` ("Master Shower Active")
- **Humidity sensor**: pick from your entities (filtered to `humidity` device class)
- **Rise** (default `8`): points above the lowest reading of the last 20 minutes that mean a shower started. Lower it if gentle showers are missed; raise it if steam from a sink or the weather triggers it.
- **Minimum humidity** (default `60`): never turn ON below this %, whatever the rise.
- **Drop** (default `3`): points below the shower's peak that mean it ended.
- **Quiet minutes** (default `15`): minutes with no new peak that mean it ended.
- **Max minutes** (default `60`): always turn OFF this long after turning ON.

Repeat for as many showers as you like, then **Save and finish**.

### Edit a shower

Choose **Edit a shower**, pick the shower, and the form opens pre-filled with its current settings — handy for tuning the settings per bathroom. The entity and its history are preserved; only the settings change.

### Remove a shower

Choose **Remove a shower** and pick the shower. Its entity is deleted on save (recorded history remains in the database until purged, but the entity is gone). The aggregate sensor always stays.

## Attributes

Each individual sensor exposes:
```yaml
humidity_sensor: sensor.second_floor_shower_humidity
current_humidity: 86.7
recent_low: null          # lowest reading of the last 20 min (while OFF)
started_at: "2026-11-26T09:57:06+00:00"   # while ON
peak: 91.6                                # while ON
peak_at: "2026-11-26T10:37:12+00:00"      # while ON
last_off_reason: drop     # drop, quiet, max or restart
rise: 8.0
min_humidity: 60.0
drop: 3.0
quiet_minutes: 15.0
max_minutes: 60.0
```

The aggregate sensor exposes:
```yaml
active_showers:
  - Kids Shower
monitored_showers:
  - Kids Shower
  - Master Shower
```

## Example automation

```yaml
automation:
  - alias: "Don't use hot water while shower is running"
    trigger:
      - platform: state
        entity_id: binary_sensor.any_shower_active
        to: "on"
    action:
      - action: script.ai_notify
        data:
          message: "Someone is showering — avoid running hot water in the kitchen"
```

## Upgrading from v1.3.0

Nothing to do: existing showers keep their entities and history and get the new default settings. The old `threshold`, `decline_count` and `hysteresis` settings are ignored, and are removed the next time you edit that shower. The `armed` and `threshold`-related attributes are gone.

## Icon

The integration ships its own icon in `custom_components/shower_active/brand/` (`icon.png` 256×256, `icon@2x.png` 512×512), which Home Assistant 2026.3 and later serve without the central brands repository. The source is `assets/icon.svg`.

## Development

Tests run against real Home Assistant:

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```
