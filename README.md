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
- Room entity IDs (valves, humidity sensors, presence sensors)
- Humidity thresholds (default: 70% on, 65% off)
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
- **Occupancy-aware**: Bathroom valve closes when occupied (no breeze while showering)
- **Smart valves**: Concentrates airflow where needed, maintains baseline positions elsewhere
- **Minimum fan speed**: Always 30% for baseline ventilation

See [CLAUDE.md](CLAUDE.md) for detailed architecture and control logic.

## Monitoring

Check logs in Home Assistant or K3s:
```bash
kubectl logs -l app=ventilation-controller --tail=100
```
