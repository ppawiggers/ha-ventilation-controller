# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant-controlled ventilation system that manages fan speed and room valves based on humidity levels, CO2 levels, and occupancy. Designed to run as a containerized cron job in Kubernetes.

## Development Environment

This project uses `mise` for environment management:
- Python 3.14 with automatic venv management
- Environment variables (HA_URL, HA_TOKEN) configured in `mise.toml`, secrets loaded from `.env`
- Activate environment: `mise trust` then `mise install`

## Running the Application

```bash
# Run single control cycle
python main.py

# Run tests
python test_controller.py

# Build image
docker build --platform=linux/amd64 -t bitlayer/ventilation-controller:YYYYMMDD .
```

## Architecture

### Control Flow
1. **main.py**: Entry point, orchestrates single control cycle
2. **controller.py**: Core control logic implementing:
   - State reading from Home Assistant (humidity rounded to 1 decimal, CO2 rounded to integer)
   - Ventilation need calculation with hysteresis (humidity) and smooth formula (CO2)
   - Valve position calculation based on room needs (humidity and CO2)
   - State application back to Home Assistant
3. **ha.py**: Home Assistant REST API client wrapper
4. **state.py**: Data structures for system and room states
5. **config.py**: Configuration with room definitions and thresholds
6. **test_controller.py**: Comprehensive unit tests covering all scenarios

### Key Control Logic

#### Hysteresis-Based Control (Humidity)
The system implements **hysteresis** to prevent rapid on/off cycling:
- `humidity_threshold_on` (70%): Activates ventilation when exceeded
- `humidity_threshold_off` (65%): Deactivates when humidity drops below
- Current system state determines which threshold applies
- Room-specific thresholds can override global defaults

#### CO2-Based Control
The system implements **smooth proportional control** for CO2 levels:
- `co2_threshold_min` (600 ppm): Start increasing fan speed
- `co2_threshold_max` (1500 ppm): Maximum fan speed demand
- **Linear interpolation**: Fan demand = `((CO2 - 600) / (1500 - 600)) * 100%`
- Below 600 ppm: 0% demand
- Above 1500 ppm: 100% demand
- **Combined demands**: Humidity and CO2 demands are added together, capped at 100%
- **Valve control**: Valves open when CO2 exceeds minimum threshold
- **No occupancy override**: CO2 ventilation continues even when room is occupied

#### Occupancy-Aware Ventilation
Rooms can be configured with `skip_when_occupied` flag:
- **Bathroom** (skip_when_occupied=True): Valve closes when occupied to avoid breeze during showering
- **Living room** (skip_when_occupied=False): Ventilates even when occupied (e.g., during cooking)
- When a room with skip_when_occupied is occupied and needs ventilation:
  - The room doesn't request fan activation
  - Its valve goes to default position (avoiding breeze)
  - Other rooms can still be ventilated normally

#### Valve Position Logic
Each room has a **configurable default valve position** used when no ventilation is needed:
- Bathroom default: 20%
- Living room default: 50%

**Runtime valve positioning**:
1. **Room doesn't need ventilation** (humidity and CO2 both OK): Default position (room-specific)
2. **Room needs ventilation** (humidity OR CO2) **and is primary**: Fully open (100%)
3. **Room needs ventilation but another is primary**: Restricted (20%) to concentrate airflow
4. **Room needs ventilation but occupied with skip_when_occupied** (humidity only): Default position (avoiding breeze)
5. **Room needs ventilation but fan off**: Minimal (10%)

**Primary room**: The first room (alphabetically) that needs ventilation (humidity-based or CO2-based) and is actively being ventilated.

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
- **humidity**: Current humidity percentage (rounded to 1 decimal)
- **co2**: Current CO2 level in ppm (rounded to integer)
- **occupied**: Boolean from presence sensor or light brightness
- **valve_position**: Target valve position (0-100%)
- **needs_ventilation**: Boolean indicating if humidity exceeds threshold (separate from CO2)

### Configuration

Room configurations in `config.py` specify:
- **Entity IDs**: valve, humidity sensor, presence sensor (optional), CO2 sensor (optional)
- **Thresholds**: Optional room-specific humidity thresholds (override defaults)
- **default_valve_position**: Valve position when room doesn't need ventilation
- **skip_when_occupied**: Whether to skip ventilation when room is occupied (applies to humidity only, not CO2)

**Global settings**:
- `min_fan_speed`: 30% (constant baseline airflow)
- `high_fan_speed`: 100% (active ventilation)
- `humidity_threshold_on`: 70% (turn on threshold)
- `humidity_threshold_off`: 65% (turn off threshold)
- `co2_threshold_min`: 600 ppm (start increasing fan speed)
- `co2_threshold_max`: 1500 ppm (maximum fan speed demand)
- `valve_open`: 100% (full airflow)
- `valve_restricted`: 20% (reduced flow to non-primary rooms)
- `valve_minimal`: 10% (minimum opening when fan is off)

### Fan Speed Calculation

Fan speed is determined by **combining humidity-based and CO2-based demands**:

**Humidity-based demand**:
- **100% demand**: At least one room requests ventilation
  - Room needs ventilation (humidity exceeds threshold) AND
  - Room is not (occupied with skip_when_occupied)
- **0% demand**: No humidity-based ventilation requested

**CO2-based demand**:
- **Calculated per room**: Linear interpolation between thresholds
  - `demand = ((CO2 - 600) / (1500 - 600)) * 100`
- **System CO2 demand**: Maximum across all rooms with CO2 sensors

**Combined fan speed**:
- `combined_demand = humidity_demand + co2_demand` (capped at 100%)
- `actual_speed = max(30%, combined_demand)` (minimum 30% for baseline airflow)

### Control Algorithm Summary

For each control cycle:

1. **Read state**: Fetch humidity, CO2, occupancy, and current positions from Home Assistant
2. **Determine needs**: Apply hysteresis logic to decide if each room needs ventilation (humidity-based)
3. **Calculate valve positions**: Set initial positions (open if needs ventilation OR high CO2, default otherwise)
4. **Calculate fan speed**: Combine humidity-based demand and CO2-based demand (added together, capped at 100%)
5. **Adjust valve positions**: Apply runtime adjustments for occupancy, primary room, etc.
6. **Apply changes**: Send commands to Home Assistant (only for changed values)

## Dependencies

Single external dependency: `requests` for Home Assistant API calls.

## Home Assistant Integration

Expects Home Assistant entities:
- Fan entity with `percentage` attribute (fan domain)
- Valve entities with `current_position` attribute and `set_valve_position` service (valve domain)
- Humidity sensors returning numeric state (rounded to 1 decimal for logging/control)
- Optional CO2 sensors returning numeric state in ppm (rounded to integer for logging/control)
- Optional presence sensors returning 'on'/'off' state
- Optional light entities with `brightness` attribute for occupancy detection (brightness > 0 = occupied)

API calls use Bearer token authentication specified in environment.

## Testing

The project includes comprehensive unit tests in `test_controller.py`:
- Basic ventilation scenarios (no demand, single room, multiple rooms)
- Hysteresis behavior (turn on, turn off, stay on, stay off)
- Occupancy handling (skip_when_occupied vs normal operation)
- Valve positioning (default, primary room, occupied, restricted)
- CO2-based ventilation (low/medium/high CO2, combined with humidity, valve opening)
- Realistic scenarios (showering, cooking, post-shower ventilation, high CO2 while occupied)
- Custom room thresholds

Tests use the actual configuration from `config.py` to maintain DRY principle and ensure consistency.

Run tests: `python test_controller.py`

## Key Design Principles

1. **Separation of concerns**: State reading, calculation, and application are distinct phases
2. **Pure functions**: Core logic (calculate_required_state) is a pure function for testability
3. **Configuration-driven**: Room-specific behavior through declarative configuration
4. **Fail-safe**: Minimum fan speed ensures baseline airflow even when no ventilation needed
5. **User comfort**: Occupancy awareness prevents unwanted airflow (configurable per room)
6. **Efficiency**: Valve restriction concentrates airflow where most needed
