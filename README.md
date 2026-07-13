# Shower Active — Home Assistant Integration

A Home Assistant custom integration that exposes `binary_sensor` entities indicating when a shower is in use, based on a humidity sensor.

## How it works

| Event | Trigger |
|-------|---------|
| **Shower starts** (ON) | Humidity rises **above the configured threshold** (default 63%) |
| **Shower ends** (OFF) | Humidity begins to **decline** — N consecutive lower readings in a row (default 2), regardless of absolute value |

The "decline to turn off" logic means the sensor stays ON while humidity is still rising or plateauing after a shower, and flips OFF as soon as a sustained downward trend is detected — not waiting for it to drop back to some baseline.

## Sensors created

For each configured shower:
- `binary_sensor.<shower_name>` — ON while that shower is in use

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

1. Go to **Settings → Devices & Services → Helpers → Create Helper → Shower Active** (on older HA versions: **Add Integration → Shower Active**)
2. Give it a name and create the entry
3. Click **Configure** (Options) to add each shower:
   - **Name**: e.g. `Kids Shower`
   - **Humidity sensor**: pick from your entities (filtered to `humidity` device class)
   - **Threshold**: humidity % to activate on (default `63`)
   - **Decline readings**: how many consecutive drops before turning off (default `2`)

You can add multiple showers and return to Options any time to add/remove.

## Attributes

Each individual sensor exposes:
```yaml
humidity_sensor: sensor.second_floor_shower_humidity
threshold: 63.0
current_humidity: 71.4
decline_readings_required: 2
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
