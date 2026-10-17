"""Configuration loader for ventilation control system."""

import os
import yaml
from dataclasses import dataclass
from typing import Dict, Optional


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
    temperature_sensor: Optional[str]
    valve_entity: str
    humidity_curve: HumidityCurve
    valve: ValveConfig


@dataclass
class GlobalConfig:
    """Global configuration."""

    homeassistant_url: str
    homeassistant_token: str
    automatic_ventilation_switch: str
    ventilation_speed_entity: str
    minimum_fan_speed: int
    outside_weather_entity: Optional[str]
    outside_humidity_margin: float
    max_target_humidity: float


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
        automatic_ventilation_switch=global_raw["automatic_ventilation_switch"],
        ventilation_speed_entity=global_raw["ventilation_speed_entity"],
        minimum_fan_speed=global_raw["minimum_fan_speed"],
        outside_weather_entity=global_raw.get("outside_weather_entity"),
        outside_humidity_margin=global_raw.get("outside_humidity_margin", 5),
        max_target_humidity=global_raw.get("max_target_humidity", 80),
    )

    # Parse room configs
    rooms = {}
    for room_key, room_raw in raw_config["rooms"].items():
        curve_raw = room_raw["humidity_curve"]
        valve_raw = room_raw["valve"]

        rooms[room_key] = RoomConfig(
            name=room_key.replace("_", " ").title(),
            humidity_sensor=room_raw["humidity_sensor"],
            temperature_sensor=room_raw.get("temperature_sensor"),
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
