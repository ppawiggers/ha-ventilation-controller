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

    # Room-specific thresholds (can override defaults)
    humidity_threshold_on: float = None
    humidity_threshold_off: float = None
    default_valve_position: int = 20  # Valve position when no ventilation needed
    skip_when_occupied: bool = (
        False  # Don't ventilate when room is occupied (e.g., bathroom)
    )


@dataclass
class VentilationConfig:
    """Global ventilation system configuration."""

    # Default humidity thresholds
    humidity_threshold_on: float = 70.0  # Turn on fan when exceeded
    humidity_threshold_off: float = 65.0  # Turn off fan when below

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
                    default_valve_position=50,
                ),
            }

    def get_room_threshold_on(self, room_key: str) -> float:
        """Get humidity on threshold for a room."""
        room = self.rooms[room_key]
        return room.humidity_threshold_on or self.humidity_threshold_on

    def get_room_threshold_off(self, room_key: str) -> float:
        """Get humidity off threshold for a room."""
        room = self.rooms[room_key]
        return room.humidity_threshold_off or self.humidity_threshold_off

    def get_room_default_valve_position(self, room_key: str) -> int:
        """Get default valve position for a room."""
        room = self.rooms[room_key]
        return (
            room.default_valve_position
            if room.default_valve_position is not None
            else self.valve_minimal
        )
