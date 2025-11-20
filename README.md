# Home Assistant Ventilation Controller

Smart ventilation control based on humidity and occupancy. Manages fan speed and room valves to efficiently remove humidity while avoiding discomfort.

## Quick Start

```bash
# Setup
mise trust && mise install

# Run locally
python main.py

# Run tests
python test_controller.py
```

## Configuration

Edit `config.py`:
- Room entity IDs (valves, humidity sensors, presence sensors, CO2 sensors)
- Humidity thresholds (default: 70% on, 65% off)
- CO2 thresholds (default: 600 ppm start, 1500 ppm max)
- Room-specific settings:
  - `default_valve_position`: Valve position when no ventilation needed
  - `skip_when_occupied`: Skip ventilation when occupied (bathroom: True, living room: False)

Environment variables in `.env`:
```bash
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_token_here
```

## Deployment

```bash
# Build image
docker build --platform=linux/amd64 -t bitlayer/ventilation-controller:$(date +%Y%m%d) .

# Push to registry
docker push bitlayer/ventilation-controller:$(date +%Y%m%d)

# Deploy to K3s
kubectl apply -f k8s/cronjob.yaml
```

## How It Works

- **Hysteresis**: Prevents rapid cycling (70% to turn on, 65% to turn off)
- **CO2-based control**: Smooth fan speed adjustment based on CO2 levels (600-1500 ppm)
- **Combined demands**: Humidity and CO2 demands are added together for optimal air quality
- **Occupancy-aware**: Bathroom valve closes when occupied (no breeze while showering)
- **Smart valves**: Concentrates airflow where needed, maintains baseline positions elsewhere
- **Minimum fan speed**: Always 30% for baseline ventilation

See [CLAUDE.md](CLAUDE.md) for detailed architecture and control logic.

## Supported Scenarios

The controller intelligently handles:

**Basic Ventilation**
- No ventilation needed (all rooms normal humidity)
- Single room needs ventilation
- Multiple rooms need ventilation simultaneously

**Hysteresis Control**
- Activates when humidity exceeds upper threshold (>70%)
- Remains off when humidity stays below upper threshold (≤70%)
- Continues running when humidity above lower threshold (≥65%)
- Deactivates when humidity drops below lower threshold (<65%)
- Handles gradual humidity changes without cycling

**Occupancy-Aware Ventilation**
- Bathroom: Skips ventilation while occupied (no breeze during shower)
- Living room: Continues ventilation while occupied (e.g., during cooking)
- Mixed: Ventilates unoccupied rooms while respecting occupied room preferences

**Smart Valve Management**
- Maintains room-specific default positions (bathroom 20%, living room 50%)
- Closes occupied bathroom valve to avoid breeze
- Fully opens primary room valve (100%)
- Restricts non-primary room valves (20%) to concentrate airflow

**Real-World Use Cases**
- Showering: Detects high humidity but skips ventilation while occupied
- Post-shower: Automatically ventilates once person leaves
- Cooking: Ventilates living room even while occupied
- Simultaneous events: Manages multiple rooms with different states

**CO2-Based Ventilation**
- Monitors CO2 levels in parts per million (ppm)
- Smooth fan speed increase from 600 ppm to 1500 ppm
- Combines with humidity demands (added together, capped at 100%)
- Opens valves when CO2 exceeds threshold
- Continues ventilation even when room is occupied

**Advanced Configuration**
- Custom humidity thresholds per room
- Custom CO2 thresholds (default: 600-1500 ppm)
- Room-specific valve positioning strategies
- Light-based occupancy detection (brightness > 0% = occupied)

## Monitoring

Check logs in Home Assistant or K3s:
```bash
kubectl logs -l app=ventilation-controller --tail=100
```
