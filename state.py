"""State management for ventilation system."""

import logging
from dataclasses import dataclass
from typing import Dict

logger = logging.getLogger(__name__)


@dataclass
class RoomState:
    """Current state of a room."""

    humidity: float = None
    co2: float = None  # CO2 level in ppm
    occupied: bool = False
    valve_position: int = 0
    needs_ventilation: bool = False


@dataclass
class SystemState:
    """Complete system state."""

    fan_speed: int
    rooms: Dict[str, RoomState]

    def get_primary_room(self, co2_threshold_min: float = None) -> str:
        """Identify which room needs ventilation most (humidity or CO2 based)."""
        for room_key, room in self.rooms.items():
            # Check if room needs ventilation based on humidity
            if room.needs_ventilation:
                return room_key
            # Check if room needs ventilation based on CO2
            if (
                co2_threshold_min is not None
                and room.co2 is not None
                and room.co2 >= co2_threshold_min
            ):
                return room_key
        return None
