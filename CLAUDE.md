# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant-controlled ventilation system that manages fan speed and room valves based on humidity levels. Valve positions are proportional to each room's demand. Runs once a minute as a Kubernetes CronJob; each run is a fresh process with no state between runs.

## Development Environment

This project uses `mise` for environment management:
- Python 3.14 with automatic venv management
- `HA_TOKEN` is loaded from `.env` (via `mise.toml`)
- Activate environment: `mise trust` then `mise install`
- Lint and format with `ruff check .` and `ruff format .`

## Running the Application

```bash
# Run single control cycle (applies changes to Home Assistant!)
python main.py

# Build image (dependencies only; code and config.yaml are mounted from a ConfigMap)
docker build --platform=linux/amd64 -t bitlayer/ventilation-controller:YYYYMMDD .
```

## Architecture

### Control Flow
1. **main.py**: Entry point, sets up logging (stdout + optional OpenTelemetry) and runs a single control cycle
2. **config.py**: Loads `config.yaml` into dataclasses; `HA_TOKEN` comes from the environment
3. **controller.py**: Core control logic:
   - State reading from Home Assistant
   - Outside air adjustment of the target humidity
   - Humidity-based demand calculation
   - Fan speed and proportional valve position calculation
   - State application back to Home Assistant
4. **ha.py**: Home Assistant REST API client wrapper
5. **config.yaml**: Declarative configuration for global settings and per-room behavior
6. **visualize_demand.py**: Dev tool that plots demand curves to `demand_curves.png`

### Key Control Logic

#### Humidity-Based Demand Calculation

The system calculates ventilation demand per room based on how far the room's humidity is above target:

```python
humidity_diff = room_humidity - target_humidity
demand = max(0, humidity_diff * multiplier)  # No upper limit!
```

**Key parameters** (configured per room):
- `target_humidity`: Base humidity target (e.g., 60%), may be raised by the outside air adjustment
- `multiplier`: How aggressively to respond (higher = more aggressive)

**Important**: Demand can exceed 100! This is intentional - demand represents "how much this room needs" and is used for proportional valve distribution. The fan speed is capped at 100%, but individual room demands are not.

**Example:**
- Bathroom: 80% humidity, target 50%, multiplier 5.0 → demand = (80-50) × 5.0 = **150**
- Living room: 75% humidity, target 55%, multiplier 2.0 → demand = (75-55) × 2.0 = **40**
- Fan speed: min(100%, 150 + 40) = **100%**
- Bathroom valve: 150/150 = **100%**
- Living room valve: 40/150 = **27% → 30%**

#### Outside Air Adjustment

`target_humidity` in config is a **base** target. Ventilating can't bring a room below the RH that outside air has once it is brought to room temperature, so `effective_target_humidity()` raises the target per room:

```python
reachable = outside_rh * es(outside_temp) / es(room_temp)  # Magnus formula
target = max(base_target, min(reachable + outside_humidity_margin, max_target_humidity))
```

Outside data is read from the `outside_weather_entity` attributes (`temperature`, `humidity`); room temperature from the room's `temperature_sensor`. If any value is missing, the base target is used. This prevents the fan running at 100% continuously in wet, mild weather. No caching is needed: Home Assistant's weather integration already caches the forecast.

#### Ventilation Speed Calculation

Global ventilation speed is the **sum of all room demands**, between `minimum_fan_speed` and 100%, rounded to 10%:

```python
total_demand = sum(room.demand for room in rooms)
ventilation_speed = min(100, max(minimum_fan_speed, total_demand))
```

This represents the total capacity needed by all rooms combined. The capacity is divided via the valve positions.

#### Proportional Valve Positioning

Valves are positioned **proportionally to each room's demand relative to the highest room demand**, rounded to 10%:

```python
max_demand = max(room.demand for room in rooms)

if max_demand == 0:
    # No demand: all valves at minimal opening
    valve_position = min_opening
else:
    proportional = (room.demand / max_demand) * 100
    if proportional < min_opening:
        # No or little demand: capacity needed elsewhere
        valve_position = restricted_opening
    else:
        valve_position = proportional
```

**Example** (shower):
- Bathroom needs 150 points, Bathroom 2 needs 22, Living room needs 5
- Bathroom valve = 150/150 = 100%
- Bathroom 2 valve = 22/150 = 15% → 10% (rounded)
- Living room valve = 5/150 = 3% < min_opening → restricted_opening (0%)

This ensures:
- The room with the highest demand always opens fully
- Airflow goes where it's needed most; the fan speed sets the total amount
- Rooms with little or no demand get restricted opening (capacity needed elsewhere)
- When no room has demand, all valves stay at min_opening for baseline airflow

### State Management Pattern

The system follows a **functional state transformation** pattern:

```python
# 1. Read current state from Home Assistant
current = read_current_state()  # → SystemState

# 2. Calculate required state (pure function)
target = calculate_required_state(current)  # → SystemState

# 3. Apply changes to Home Assistant (side effects, only for changed values)
apply_state(current, target)
```

Each room tracks:
- **humidity**: Current humidity percentage
- **temperature**: Current room temperature (optional)
- **target_humidity**: Effective target after outside air adjustment
- **demand**: Calculated ventilation demand (0 or higher, no upper limit)
- **valve_position**: Valve position (0-100%)

System state tracks:
- **automatic_ventilation**: Whether the controller may make changes
- **ventilation_speed**: Global fan speed (0-100%)
- **outside_temperature** / **outside_humidity**: From the weather entity
- **rooms**: Dictionary of room states

### Configuration

Configuration is defined in `config.yaml` with two main sections:

**Global configuration**:
- Home Assistant URL (token from `HA_TOKEN` env var)
- Automatic ventilation switch entity
- Ventilation speed entity (fan) and minimum fan speed
- Outside weather entity, margin and max target (outside air adjustment)

**Per-room configuration**:
- Humidity sensor entity
- Temperature sensor entity (optional)
- Valve entity
- Humidity curve (target, multiplier)
- Valve settings (min_opening, restricted_opening)

Example room config:
```yaml
bathroom:
  humidity_sensor: "sensor.bathroom_humidity"
  temperature_sensor: "sensor.bathroom_temperature"  # Optional
  valve_entity: "valve.bathroom"
  humidity_curve:
    target_humidity: 60      # Base target 60%
    multiplier: 5.0          # Aggressive response
  valve:
    min_opening: 10          # When no room has demand
    restricted_opening: 0    # When capacity needed elsewhere
```

### Control Algorithm Summary

For each control cycle:

1. **Read state**: Fetch automatic ventilation switch, fan speed, outside weather, and per room humidity, temperature and valve position
2. **Check switch**: If automatic ventilation is off, change nothing
3. **Calculate demands**: For each room, raise the target for outside air if needed, then calculate demand based on humidity above target
4. **Calculate fan speed**: Sum of all room demands, between minimum and 100%
5. **Calculate valve positions**: Proportional to demand relative to the highest demand
6. **Log state**: Print readable summary of current and target states
7. **Apply changes**: Send changed fan speed and valve positions to Home Assistant

## Dependencies

- `pyyaml`: YAML configuration parsing
- `requests`: Home Assistant API calls
- `opentelemetry-*`: Optional log export (when `OTEL_EXPORTER_OTLP_ENDPOINT` is set)

## Home Assistant Integration

Expects Home Assistant entities:
- Fan entity with `percentage` attribute, set via `fan.turn_on`
- Valve entities with `current_position` attribute, set via `valve.set_valve_position`
- Humidity and temperature sensors returning numeric state
- Weather entity with `temperature` and `humidity` attributes
- Automatic ventilation switch (`input_boolean`)

API calls use Bearer token authentication with `HA_TOKEN`.

## Key Design Principles

1. **Simplicity**: Single control mode (humidity only), no complex state machines
2. **Configurability**: All thresholds configurable per room
3. **Proportional control**: Gradual response, no hard on/off switching
4. **Fair distribution**: Valve positions proportional to demand
5. **Pure functions**: Core logic is a pure function for predictability
6. **Declarative config**: Easy to add new rooms without code changes
