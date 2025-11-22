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
    ventilation_points: int = 0  # 0-100 points indicating ventilation demand


@dataclass
class SystemState:
    """Complete system state."""

    fan_speed: int
    rooms: Dict[str, RoomState]

    def get_max_points_room(self) -> tuple[str, int]:
        """Identify which room has the highest ventilation points.

        Returns:
            Tuple of (room_key, max_points), or (None, 0) if no rooms have points.
        """
        max_points = 0
        max_room = None

        for room_key, room in self.rooms.items():
            if room.ventilation_points > max_points:
                max_points = room.ventilation_points
                max_room = room_key

        return max_room, max_points
