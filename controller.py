"""Core ventilation control logic."""

import logging
from typing import Dict

from ha import HomeAssistantAPI
from config import VentilationConfig, RoomConfig
from state import RoomState, SystemState

logger = logging.getLogger(__name__)


class VentilationController:
    """Manages ventilation system based on humidity and occupancy."""

    def __init__(self, ha: HomeAssistantAPI, config: VentilationConfig):
        self.ha = ha
        self.config = config

    def read_current_state(self) -> SystemState:
        """Read current state from Home Assistant."""
        logger.info("Fetching current conditions from Home Assistant")

        rooms = {}
        for room_key, room_config in self.config.rooms.items():
            rooms[room_key] = self._read_room_state(room_key, room_config)

        fan_speed = self._get_fan_speed()

        logger.info(f"Current fan speed: {fan_speed}%")
        return SystemState(fan_speed=fan_speed, rooms=rooms)

    def _read_room_state(self, room_key: str, room_config: RoomConfig) -> RoomState:
        """Read state for a single room."""
        humidity = None
        if room_config.humidity_sensor:
            raw_humidity = self.ha.get_state(room_config.humidity_sensor)
            humidity = (
                round(float(raw_humidity), 1) if raw_humidity is not None else None
            )

        occupied = False
        if room_config.presence_sensor:
            occupied = self.ha.get_state(room_config.presence_sensor) == "on"

        valve_position = self._get_valve_position(room_config.valve_entity)

        logger.info(
            f"{room_config.name}: Humidity={humidity}%, "
            f"Occupied={occupied}, Valve={valve_position}%"
        )

        return RoomState(
            humidity=humidity, occupied=occupied, valve_position=valve_position
        )

    def calculate_required_state(self, current: SystemState) -> SystemState:
        """Calculate required ventilation settings."""
        logger.info("Calculating required ventilation state")

        # Determine which rooms need ventilation
        new_rooms = {}
        for room_key, room in current.rooms.items():
            needs_ventilation = self._room_needs_ventilation(
                room_key, room, current.fan_speed
            )
            new_rooms[room_key] = RoomState(
                humidity=room.humidity,
                occupied=room.occupied,
                valve_position=self._calculate_valve_position(
                    room_key, needs_ventilation
                ),
                needs_ventilation=needs_ventilation,
            )

        # Calculate fan speed
        fan_speed = self._calculate_fan_speed(new_rooms)

        return SystemState(fan_speed=fan_speed, rooms=new_rooms)

    def _room_needs_ventilation(
        self, room_key: str, room: RoomState, current_fan_speed: int
    ) -> bool:
        """Determine if room needs ventilation with hysteresis."""
        if room.humidity is None:
            return False

        threshold_on = self.config.get_room_threshold_on(room_key)
        threshold_off = self.config.get_room_threshold_off(room_key)
        room_config = self.config.rooms[room_key]

        # Apply hysteresis based on current state
        if current_fan_speed >= self.config.high_fan_speed:
            # Currently ventilating, only stop if humidity drops below lower threshold
            needs = room.humidity >= threshold_off
            if not needs:
                logger.info(
                    f"{room_config.name}: Humidity {room.humidity}% dropped below "
                    f"{threshold_off}%, no longer needs ventilation"
                )
            else:
                logger.info(
                    f"{room_config.name}: Humidity {room.humidity}% still elevated, "
                    f"needs continued ventilation"
                )
        else:
            # Not currently ventilating, only start if humidity exceeds upper threshold
            needs = room.humidity > threshold_on
            if needs:
                logger.info(
                    f"{room_config.name}: Humidity {room.humidity}% exceeds "
                    f"{threshold_on}%, needs ventilation"
                )
            else:
                logger.info(
                    f"{room_config.name}: Humidity {room.humidity}% within normal range"
                )

        return needs

    def _calculate_fan_speed(self, rooms: Dict[str, RoomState]) -> int:
        """Calculate required fan speed."""
        # Check if any room requests ventilation (needs it and should be ventilated when occupied)
        ventilation_requested = any(
            room.needs_ventilation
            and not (room.occupied and self.config.rooms[room_key].skip_when_occupied)
            for room_key, room in rooms.items()
        )

        target_speed = self.config.high_fan_speed if ventilation_requested else 0
        actual_speed = max(self.config.min_fan_speed, target_speed)

        if ventilation_requested:
            logger.info(f"Ventilation requested, setting fan speed to {actual_speed}%")
        else:
            logger.info(
                f"No ventilation requested, fan at minimum speed {actual_speed}%"
            )

        return actual_speed

    def _calculate_valve_position(self, room_key: str, needs_ventilation: bool) -> int:
        """Calculate valve position for a room."""
        room_config = self.config.rooms[room_key]

        if needs_ventilation:
            position = self.config.valve_open
            logger.info(f"{room_config.name}: Needs ventilation, valve at {position}%")
        else:
            position = self.config.get_room_default_valve_position(room_key)
            logger.info(
                f"{room_config.name}: No ventilation needed, valve at {position}%"
            )

        return position

    def apply_state(self, target: SystemState):
        """Apply calculated state to Home Assistant."""
        logger.info("Applying ventilation state")
        changes_made = False

        # Update fan speed
        current_fan = self._get_fan_speed()
        if current_fan != target.fan_speed:
            logger.info(f"Fan speed {current_fan}% → {target.fan_speed}%")
            self.ha.call_service(
                "fan",
                "set_percentage",
                entity_id=self.config.fan_entity,
                percentage=target.fan_speed,
            )
            changes_made = True

        # Determine primary ventilation room for valve restriction logic
        primary_room = target.get_primary_room()

        # Update room valves
        for room_key, room_state in target.rooms.items():
            room_config = self.config.rooms[room_key]
            current_valve = self._get_valve_position(room_config.valve_entity)

            # Start with calculated position, then apply runtime adjustments
            target_valve = room_state.valve_position

            # Only adjust valves for rooms needing ventilation
            if room_state.needs_ventilation:
                if room_state.occupied and room_config.skip_when_occupied:
                    # Occupied room with skip_when_occupied: close valve to avoid breeze
                    target_valve = self.config.get_room_default_valve_position(room_key)
                    logger.info(
                        f"{room_config.name}: Occupied, valve at {target_valve}% (avoiding breeze)"
                    )
                elif (
                    target.fan_speed == 0
                    or target.fan_speed == self.config.min_fan_speed
                ):
                    # Fan not running: minimize valve
                    target_valve = self.config.valve_minimal
                    logger.info(
                        f"{room_config.name}: Fan off, valve at {target_valve}%"
                    )
                elif primary_room and primary_room != room_key:
                    # Another room is primary: restrict this valve to concentrate airflow
                    target_valve = self.config.valve_restricted
                    logger.info(
                        f"{room_config.name}: Non-primary room, valve at {target_valve}%"
                    )

            if current_valve != target_valve:
                logger.info(
                    f"{room_config.name}: Valve {current_valve}% → {target_valve}%"
                )
                self.ha.call_service(
                    "valve",
                    "set_valve_position",
                    entity_id=room_config.valve_entity,
                    position=target_valve,
                )
                changes_made = True

        logger.info("Applied changes" if changes_made else "No changes needed")

    def _get_valve_position(self, entity_id: str) -> int:
        """Get current valve position."""
        return int(self.ha.get_attribute(entity_id, "current_position"))

    def _get_fan_speed(self) -> int:
        """Get current fan speed."""
        return int(self.ha.get_attribute(self.config.fan_entity, "percentage"))
