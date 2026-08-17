# Shower Active — Home Assistant Integration

A Home Assistant custom integration that exposes `binary_sensor` entities indicating when a shower is in use, based on a humidity sensor.

## How it works

| Event | Trigger |
|-------|---------|
| **Shower starts** (ON) | Humidity rises **above the configured threshold** (default 63%) |
| **Shower ends** (OFF) | Humidity begins to **decline** — N consecutive lower readings in a row (default 2), regardless of absolute value |

The "decline to turn off" logic means the sensor stays ON while humidity is still rising or plateauing after a shower, and flips OFF as soon as a sustained downward trend is detected — not waiting for it to drop back to some baseline.

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
- **Threshold**: humidity % to activate on (default `63`)
- **Decline readings**: how many consecutive drops before turning off (default `2`)
- **Hysteresis**: how many points humidity must drop *below* the threshold before the sensor is allowed to re-activate (default `5`)

The hysteresis setting exists to stop flapping when humidity hovers right around the threshold — without it, a reading that dips just barely below the threshold (e.g. 62.5% with a 63% threshold) immediately re-arms the sensor, so the very next noisy reading above threshold flips it back ON, producing two ON/OFF cycles for what was really one shower. With the default of 5, the sensor won't re-arm until humidity drops to 58% or below, so a single shower session stays as a single ON/OFF cycle. Raise it if you still see flapping; lower it (toward 0) if showers feel slow to re-detect back-to-back.

Repeat for as many showers as you like, then **Save and finish**.

### Edit a shower

Choose **Edit a shower**, pick the shower, and the form opens pre-filled with its current settings — handy for tuning the threshold or hysteresis per bathroom. The entity and its history are preserved; only the settings change.

### Remove a shower

Choose **Remove a shower** and pick the shower. Its entity is deleted on save (recorded history remains in the database until purged, but the entity is gone). The aggregate sensor always stays.

## Attributes

Each individual sensor exposes:
```yaml
humidity_sensor: sensor.second_floor_shower_humidity
threshold: 63.0
hysteresis: 5.0
current_humidity: 71.4
decline_readings_required: 2
armed: true
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
