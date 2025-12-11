# Home Assistant Ventilation Controller

Simplified smart ventilation control based on humidity levels. Manages fan speed and room valves with proportional control and per-room customization.

## Quick Start

```bash
# Setup
mise trust && mise install

# Configure
cp config.yaml.example config.yaml
# Edit config.yaml with your entity IDs

# Run locally
python main.py
```

## Configuration

Edit `config.yaml`:

**Global settings:**
- Home Assistant URL and token
- Manual override switch
- Ventilation fan entity

**Per-room settings:**
- Humidity sensor entity
- Valve entity
- Humidity curve (target, multiplier)
- Valve positions (min_opening, restricted_opening)

Environment variables in `.env`:
```bash
HA_TOKEN=your_long_lived_access_token
```

### Example Room Configuration

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

## How It Works

### Humidity-Based Demand
Each room calculates ventilation demand based on how far above target:
```
demand = max(0, (current_humidity - target_humidity) * multiplier)
```

- Higher `multiplier` = more aggressive ventilation (e.g., bathroom: 5.0)
- Lower `multiplier` = gentler ventilation (e.g., living room: 2.0)
- **Demand can exceed 100%** - it's used for proportional distribution, not directly as fan speed

### Ventilation Speed
Global fan speed is the **sum of all room demands**, representing total capacity needed:
```
fan_speed = min(100%, max(25%, bathroom_demand + living_room_demand + ...))
```

- Minimum 25% for baseline airflow
- Maximum 100% (capped)
- Capacity is divided proportionally via valve positions

### Proportional Valve Positioning
Valves open proportionally to each room's share of total demand:
- Bathroom needs 80 points, Living room needs 50 points
- Total = 130 points
- Bathroom valve: 62% (80/130)
- Living room valve: 38% (50/130)

This ensures airflow goes where it's needed most, while respecting minimum opening constraints.

### Manual Override
When the manual override switch is enabled, the system reads state but doesn't make any changes.

## Deployment

```bash
# Build image
docker build --platform=linux/amd64 -t bitlayer/ventilation-controller:$(date +%Y%m%d) .

# Push to registry
docker push bitlayer/ventilation-controller:$(date +%Y%m%d)

# Deploy to K3s
kubectl apply -f k8s/cronjob.yaml
```

## Key Features

- **Simple & Predictable**: Linear relationship between humidity and ventilation
- **Per-Room Control**: Each room has its own target and response curve
- **Proportional Distribution**: Valve positions based on demand share
- **No Complex State**: No hysteresis, no occupancy detection, no CO2
- **Declarative Config**: Add rooms without touching code

## Monitoring

Check logs in Home Assistant or K3s:
```bash
kubectl logs -l app=ventilation-controller --tail=100
```

## Architecture

See [CLAUDE.md](CLAUDE.md) for detailed architecture, control algorithms, and design principles.
