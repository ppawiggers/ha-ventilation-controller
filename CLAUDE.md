# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Simplified Home Assistant-controlled ventilation system that manages fan speed and room valves based on humidity levels. The system calculates proportional valve positions based on demand. Designed to run as a containerized cron job in Kubernetes.

## Development Environment

This project uses `mise` for environment management:
- Python 3.14 with automatic venv management
- Environment variables (HA_TOKEN) configured in `mise.toml`, secrets loaded from `.env`
- Activate environment: `mise trust` then `mise install`

## Running the Application

```bash
# Run single control cycle
python main.py

# Build image
docker build --platform=linux/amd64 -t bitlayer/ventilation-controller:YYYYMMDD .
```

## Architecture

### Control Flow
1. **main.py**: Entry point, loads config and orchestrates single control cycle
2. **config.py**: YAML configuration loader with environment variable support
3. **controller.py**: Core control logic implementing:
   - State reading from Home Assistant
   - Humidity-based demand calculation with outside humidity adjustment
   - Proportional valve position calculation
   - State application back to Home Assistant
4. **ha.py**: Home Assistant REST API client wrapper
5. **config.yaml**: Declarative configuration for global settings and per-room behavior

### Key Control Logic

#### Humidity-Based Demand Calculation

The system calculates ventilation demand per room based on how far the room's humidity is above target:

```python
# Calculate demand
humidity_diff = room_humidity - target_humidity
demand = humidity_diff * multiplier
demand = max(0, demand)  # No upper limit!
```

**Key parameters** (configured per room):
- `target_humidity`: Desired humidity level (e.g., 50%)
- `multiplier`: How aggressively to respond (higher = more aggressive)

**Important**: Demand can exceed 100! This is intentional - demand represents "how much this room needs" and is used for proportional valve distribution. The fan speed is capped at 100%, but individual room demands are not.

**Example:**
- Bathroom: 80% humidity, target 50%, multiplier 5.0 → demand = (80-50) × 5.0 = **150**
- Living room: 75% humidity, target 55%, multiplier 2.0 → demand = (75-55) × 2.0 = **40**
- Total demand: 150 + 40 = 190
- Fan speed: min(100%, 190) = **100%**
- Bathroom valve: 150/190 = **79%** of capacity
- Living room valve: 40/190 = **21%** of capacity

This ensures rooms with higher demand get proportionally more airflow.

#### Ventilation Speed Calculation

Global ventilation speed is the **sum of all room demands**, with a **minimum of 25%** and **maximum of 100%**:

```python
total_demand = sum(room.demand for room in rooms)
ventilation_speed = min(100, max(25, total_demand))
```

This represents the total capacity needed by all rooms combined. The capacity is then divided proportionally via valve positions.

Example:
- Bathroom needs 30 points, Living room needs 20 points
- Total capacity needed: 30 + 20 = 50%
- Bathroom gets 30/50 = 60% of capacity (valve position)
- Living room gets 20/50 = 40% of capacity (valve position)

#### Proportional Valve Positioning

Valves are positioned **proportionally to each room's share of total demand**:

```python
total_demand = sum(room.demand for room in rooms)

if total_demand == 0:
    # No demand: all valves at minimal opening
    valve_position = min_opening
else:
    if room.demand == 0:
        # Capacity needed elsewhere: restricted opening
        valve_position = restricted_opening
    else:
        # Proportional share, but at least min_opening
        valve_position = max(min_opening, (room.demand / total_demand) * 100)
```

**Example**:
- Bathroom needs 80 points, Living room needs 50 points
- Total = 130 points
- Bathroom valve = max(10%, 80/130 * 100%) = 62%
- Living room valve = max(15%, 50/130 * 100%) = 38%

This ensures:
- Airflow goes where it's needed most
- No room gets 100% unless it's the only one with demand
- Even low-demand rooms get minimum airflow
- Rooms without demand get restricted opening (capacity needed elsewhere)

### State Management Pattern

The system follows a **functional state transformation** pattern:

```python
# 1. Read current state from Home Assistant
current = read_current_state()  # → SystemState

# 2. Calculate required state (pure function)
target = calculate_required_state(current)  # → SystemState

# 3. Apply changes to Home Assistant (side effects)
apply_state(target)
```

Each room tracks:
- **humidity**: Current humidity percentage
- **demand**: Calculated ventilation demand (0-100)
- **valve_position**: Target valve position (0-100%)

System state tracks:
- **manual_override**: Boolean override switch state
- **ventilation_speed**: Global fan speed (0-100%)
- **rooms**: Dictionary of room states

### Configuration

Configuration is defined in `config.yaml` with two main sections:

**Global configuration**:
- Home Assistant URL and token
- Manual override switch entity
- Ventilation speed entity (fan)
- Update interval

**Per-room configuration**:
- Humidity sensor entity
- Valve entity
- Humidity curve (target, multiplier)
- Valve settings (min_opening, restricted_opening)

Example room config:
```yaml
bathroom:
  humidity_sensor: "sensor.bathroom_humidity"
  valve_entity: "climate.bathroom_valve"
  humidity_curve:
    target_humidity: 50      # Target 50%
    multiplier: 5.0          # Aggressive response
  valve:
    min_opening: 10          # Normal minimum
    restricted_opening: 5    # When capacity needed elsewhere
```

### Control Algorithm Summary

For each control cycle:

1. **Read state**: Fetch manual override, current fan speed, and room humidity levels
2. **Check override**: If manual override active, skip control logic
3. **Calculate demands**: For each room, calculate demand based on humidity above target
4. **Calculate fan speed**: Use maximum demand across all rooms
5. **Calculate valve positions**: Proportional distribution based on demand share
6. **Apply changes**: Send fan speed and valve positions to Home Assistant
7. **Log state**: Print readable summary of current and target states

## Dependencies

- `pyyaml`: YAML configuration parsing
- `requests`: Home Assistant API calls

## Home Assistant Integration

Expects Home Assistant entities:
- Fan entity with `percentage` attribute (fan domain)
- Valve entities with `number.set_value` service (number domain)
- Humidity sensors returning numeric state
- Manual override switch (input_boolean)

API calls use Bearer token authentication from config.

## Key Design Principles

1. **Simplicity**: Single control mode (humidity only), no complex state machines
2. **Configurability**: All thresholds and formulas configurable per room
3. **Proportional control**: Gradual response, no hard on/off switching
4. **Fair distribution**: Valve positions proportional to demand
5. **Pure functions**: Core logic is a pure function for predictability
6. **Declarative config**: Easy to add new rooms without code changes
