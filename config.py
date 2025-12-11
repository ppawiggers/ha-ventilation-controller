"""Configuration loader for ventilation control system."""

import os
import re
import yaml
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class HumidityCurve:
    """Defines how ventilation demand changes with humidity."""

    target_humidity: float
    multiplier: float


@dataclass
class ValveConfig:
    """Valve position configuration."""

    min_opening: int
    restricted_opening: int


@dataclass
class RoomConfig:
    """Configuration for a single room."""

    name: str
    humidity_sensor: str
    valve_entity: str
    humidity_curve: HumidityCurve
    valve: ValveConfig


@dataclass
class GlobalConfig:
    """Global configuration."""

    homeassistant_url: str
    homeassistant_token: str
    manual_override_switch: str
    ventilation_speed_entity: str


@dataclass
class Config:
    """Complete configuration."""

    global_config: GlobalConfig
    rooms: Dict[str, RoomConfig]


def load_config(config_path: str = "config.yaml") -> Config:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        raw_config = yaml.safe_load(f)

    # Parse global config
    global_raw = raw_config["global"]
    global_config = GlobalConfig(
        homeassistant_url=global_raw["homeassistant"]["url"],
        homeassistant_token=os.getenv("HA_TOKEN"),
        manual_override_switch=global_raw["manual_override_switch"],
        ventilation_speed_entity=global_raw["ventilation_speed_entity"],
    )

    # Parse room configs
    rooms = {}
    for room_key, room_raw in raw_config["rooms"].items():
        curve_raw = room_raw["humidity_curve"]
        valve_raw = room_raw["valve"]

        rooms[room_key] = RoomConfig(
            name=room_key.replace("_", " ").title(),
            humidity_sensor=room_raw["humidity_sensor"],
            valve_entity=room_raw["valve_entity"],
            humidity_curve=HumidityCurve(
                target_humidity=curve_raw["target_humidity"],
                multiplier=curve_raw["multiplier"],
            ),
            valve=ValveConfig(
                min_opening=valve_raw["min_opening"],
                restricted_opening=valve_raw["restricted_opening"],
            ),
        )

    return Config(global_config=global_config, rooms=rooms)
