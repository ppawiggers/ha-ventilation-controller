"""Configuration for ventilation control system."""

from dataclasses import dataclass
from typing import Dict


@dataclass
class RoomConfig:
    """Configuration for a single room."""

    name: str
    valve_entity: str
    humidity_sensor: str
    presence_sensor: str = None  # Optional presence detection
    co2_sensor: str = None  # Optional CO2 detection

    # Humidity points calculation (can override defaults)
    humidity_points_mode: str = None  # "step" or "linear"
    humidity_points_threshold: float = None  # Start awarding points
    humidity_points_max: float = None  # Value that gives 100 points (linear mode only)

    # CO2 points calculation (can override defaults)
    co2_points_mode: str = None  # "step" or "linear"
    co2_points_threshold: float = None  # Start awarding points
    co2_points_max: float = None  # Value that gives 100 points (linear mode only)

    default_valve_position: int = 20  # Valve position when no ventilation needed
    skip_when_occupied: bool = (
        False  # Don't ventilate when room is occupied (e.g., bathroom)
    )


@dataclass
class VentilationConfig:
    """Global ventilation system configuration."""

    # Default humidity points calculation
    humidity_points_mode: str = "step"  # "step" or "linear"
    humidity_points_threshold: float = 65.0  # Start awarding points
    humidity_points_max: float = 80.0  # Value that gives 100 points (linear mode)

    # Default CO2 points calculation (ppm)
    co2_points_mode: str = "linear"  # "step" or "linear"
    co2_points_threshold: float = 600.0  # Start awarding points
    co2_points_max: float = 1500.0  # Value that gives 100 points (linear mode)

    # Fan settings
    fan_entity: str = "fan.open_air_mini_e0e308_open_air_mini"
    min_fan_speed: int = 30
    high_fan_speed: int = 100

    # Valve positions
    valve_open: int = 100
    valve_minimal: int = 10
    valve_restricted: int = 20

    # Rooms configuration
    rooms: Dict[str, RoomConfig] = None

    def __post_init__(self):
        """Initialize default room configurations."""
        if self.rooms is None:
            self.rooms = {
                "bathroom": RoomConfig(
                    name="Bathroom",
                    valve_entity="valve.open_air_valve_2_21718c_open_air_valve_2_valve",
                    humidity_sensor="sensor.open_air_valve_2_21718c_open_air_valve_2_humidity",
                    presence_sensor="light.spots_badkamer",
                    skip_when_occupied=True,  # Don't ventilate when someone is showering
                ),
                "living_room": RoomConfig(
                    name="Living Room",
                    valve_entity="valve.open_air_valve_5_217090_open_air_valve_5_valve",
                    humidity_sensor="sensor.open_air_valve_5_217090_open_air_valve_5_humidity",
                    co2_sensor="sensor.open_air_valve_5_217090_open_air_valve_5_co2",
                    default_valve_position=50,
                ),
            }

    def get_room_humidity_config(self, room_key: str) -> tuple[str, float, float]:
        """Get humidity points configuration for a room.

        Returns:
            Tuple of (mode, threshold, max_value)
        """
        room = self.rooms[room_key]
        mode = room.humidity_points_mode or self.humidity_points_mode
        threshold = room.humidity_points_threshold or self.humidity_points_threshold
        max_value = room.humidity_points_max or self.humidity_points_max
        return mode, threshold, max_value

    def get_room_co2_config(self, room_key: str) -> tuple[str, float, float]:
        """Get CO2 points configuration for a room.

        Returns:
            Tuple of (mode, threshold, max_value)
        """
        room = self.rooms[room_key]
        mode = room.co2_points_mode or self.co2_points_mode
        threshold = room.co2_points_threshold or self.co2_points_threshold
        max_value = room.co2_points_max or self.co2_points_max
        return mode, threshold, max_value

    def get_room_default_valve_position(self, room_key: str) -> int:
        """Get default valve position for a room."""
        room = self.rooms[room_key]
        return (
            room.default_valve_position
            if room.default_valve_position is not None
            else self.valve_minimal
        )
