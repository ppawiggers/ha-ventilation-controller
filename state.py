"""State management for ventilation system."""

import logging
from dataclasses import dataclass
from typing import Dict

logger = logging.getLogger(__name__)


@dataclass
class RoomState:
    """Current state of a room."""

    humidity: float = None
    occupied: bool = False
    valve_position: int = 0
    needs_ventilation: bool = False


@dataclass
class SystemState:
    """Complete system state."""

    fan_speed: int
    rooms: Dict[str, RoomState]

    def get_primary_room(self) -> str:
        """Identify which room needs ventilation most."""
        for room_key, room in self.rooms.items():
            if room.needs_ventilation:
                return room_key
        return None
