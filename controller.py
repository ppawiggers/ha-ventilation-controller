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

        co2 = None
        if room_config.co2_sensor:
            raw_co2 = self.ha.get_state(room_config.co2_sensor)
            co2 = round(float(raw_co2), 0) if raw_co2 is not None else None

        occupied = False
        if room_config.presence_sensor:
            if room_config.presence_sensor.startswith("light."):
                # For lights, check brightness attribute (0 = off, >0 = on/occupied)
                brightness = self.ha.get_attribute(
                    room_config.presence_sensor, "brightness"
                )
                occupied = brightness is not None and brightness > 0
            else:
                # For other sensors (e.g., input_boolean), check state
                occupied = self.ha.get_state(room_config.presence_sensor) == "on"

        valve_position = self._get_valve_position(room_config.valve_entity)

        co2_str = f", CO2={co2}ppm" if co2 is not None else ""
        logger.info(
            f"{room_config.name}: Humidity={humidity}%{co2_str}, "
            f"Occupied={occupied}, Valve={valve_position}%"
        )

        return RoomState(
            humidity=humidity, co2=co2, occupied=occupied, valve_position=valve_position
        )

    def calculate_required_state(self, current: SystemState) -> SystemState:
        """Calculate required ventilation settings."""
        logger.info("Calculating required ventilation state")

        # Calculate ventilation points for each room
        new_rooms = {}
        for room_key, room in current.rooms.items():
            # Calculate points from humidity and CO2 (use max)
            humidity_points = self._calculate_humidity_points(room_key, room.humidity)
            co2_points = self._calculate_co2_points(room_key, room.co2)
            ventilation_points = max(humidity_points, co2_points)

            room_config = self.config.rooms[room_key]
            if ventilation_points > 0:
                logger.info(
                    f"{room_config.name}: Total ventilation points = {ventilation_points} "
                    f"(humidity={humidity_points}, CO2={co2_points})"
                )

            new_rooms[room_key] = RoomState(
                humidity=room.humidity,
                co2=room.co2,
                occupied=room.occupied,
                valve_position=0,  # Will be calculated after fan speed
                ventilation_points=ventilation_points,
            )

        # Calculate fan speed (sum of all points)
        fan_speed = self._calculate_fan_speed(new_rooms)

        # Calculate valve positions based on proportional distribution
        max_room, max_points = SystemState(
            fan_speed=fan_speed, rooms=new_rooms
        ).get_max_points_room()

        for room_key, room in new_rooms.items():
            room.valve_position = self._calculate_valve_position(
                room_key, room, max_room, max_points, fan_speed
            )

        return SystemState(fan_speed=fan_speed, rooms=new_rooms)


    def _calculate_points(
        self, value: float, mode: str, threshold: float, max_value: float
    ) -> int:
        """Calculate ventilation points based on sensor value and configuration.

        Args:
            value: Sensor value (humidity % or CO2 ppm)
            mode: "step" or "linear"
            threshold: Value at which points start being awarded
            max_value: Value that gives 100 points (linear mode only)

        Returns:
            Points from 0 to 100
        """
        if value is None or value < threshold:
            return 0

        if mode == "step":
            # Step function: below threshold = 0, at/above threshold = 100
            return 100
        elif mode == "linear":
            # Linear interpolation between threshold and max_value
            if value >= max_value:
                return 100

            ratio = (value - threshold) / (max_value - threshold)
            return int(ratio * 100)
        else:
            raise ValueError(f"Unknown points mode: {mode}")

    def _calculate_humidity_points(self, room_key: str, humidity: float) -> int:
        """Calculate humidity-based ventilation points for a room."""
        mode, threshold, max_value = self.config.get_room_humidity_config(room_key)
        points = self._calculate_points(humidity, mode, threshold, max_value)

        if points > 0:
            room_config = self.config.rooms[room_key]
            logger.info(
                f"{room_config.name}: Humidity {humidity}% → {points} points "
                f"({mode} mode, threshold={threshold}%)"
            )

        return points

    def _calculate_co2_points(self, room_key: str, co2: float) -> int:
        """Calculate CO2-based ventilation points for a room."""
        mode, threshold, max_value = self.config.get_room_co2_config(room_key)
        points = self._calculate_points(co2, mode, threshold, max_value)

        if points > 0:
            room_config = self.config.rooms[room_key]
            logger.info(
                f"{room_config.name}: CO2 {co2}ppm → {points} points "
                f"({mode} mode, threshold={threshold}ppm)"
            )

        return points

    def _calculate_fan_speed(self, rooms: Dict[str, RoomState]) -> int:
        """Calculate required fan speed as sum of all room ventilation points."""
        # Sum all room points, excluding occupied rooms with skip_when_occupied
        total_points = 0
        for room_key, room in rooms.items():
            room_config = self.config.rooms[room_key]

            # Skip points from occupied rooms with skip_when_occupied flag
            if room.occupied and room_config.skip_when_occupied:
                if room.ventilation_points > 0:
                    logger.info(
                        f"{room_config.name}: {room.ventilation_points} points ignored "
                        f"(room occupied, skip_when_occupied=True)"
                    )
                continue

            total_points += room.ventilation_points

        # Cap at high_fan_speed
        fan_speed = min(total_points, self.config.high_fan_speed)

        # Apply minimum fan speed
        fan_speed = max(self.config.min_fan_speed, fan_speed)

        # Round to nearest 10% to prevent constant adjustments
        fan_speed = round(fan_speed / 10) * 10

        if total_points > 0:
            logger.info(
                f"Fan speed: {total_points} total points → {fan_speed}% "
                f"(rounded to nearest 10%, min={self.config.min_fan_speed}%, max={self.config.high_fan_speed}%)"
            )
        else:
            logger.info(f"No ventilation points, fan at minimum speed {fan_speed}%")

        return fan_speed

    def _calculate_valve_position(
        self,
        room_key: str,
        room: RoomState,
        max_room: str,
        max_points: int,
        fan_speed: int,
    ) -> int:
        """Calculate valve position based on proportional distribution of points.

        Args:
            room_key: Key of the room
            room: Current room state with ventilation points
            max_room: Room with the highest points
            max_points: Highest points among all rooms
            fan_speed: Current fan speed

        Returns:
            Valve position (0-100%)
        """
        room_config = self.config.rooms[room_key]

        # If room has no ventilation points, use default position
        if room.ventilation_points == 0:
            position = self.config.get_room_default_valve_position(room_key)
            logger.info(
                f"{room_config.name}: No ventilation points, valve at {position}%"
            )
            return position

        # If occupied with skip_when_occupied, use default position (avoid breeze)
        if room.occupied and room_config.skip_when_occupied:
            position = self.config.get_room_default_valve_position(room_key)
            logger.info(
                f"{room_config.name}: Occupied (skip_when_occupied), "
                f"valve at {position}% (avoiding breeze)"
            )
            return position

        # If no room has points, use default
        if max_points == 0:
            position = self.config.get_room_default_valve_position(room_key)
            return position

        # Proportional valve position based on points
        # Room with max points gets 100%, others get proportional
        if room_key == max_room:
            position = 100
            logger.info(
                f"{room_config.name}: Highest demand ({room.ventilation_points} points), "
                f"valve at {position}%"
            )
        else:
            # Calculate proportional position
            ratio = room.ventilation_points / max_points
            position = int(ratio * 100)
            # Round to nearest 10% to prevent constant adjustments
            position = round(position / 10) * 10
            logger.info(
                f"{room_config.name}: {room.ventilation_points}/{max_points} points "
                f"({ratio:.0%}), valve at {position}% (rounded to nearest 10%)"
            )

        return position

    def apply_state(self, target: SystemState):
        """Apply calculated state to Home Assistant."""
        logger.info("Applying ventilation state")
        changes_made = False

        # Get current fan speed before changes
        current_fan = self._get_fan_speed()

        # Collect current valve positions before changes
        current_valves = {}
        for room_key, room_state in target.rooms.items():
            room_config = self.config.rooms[room_key]
            current_valves[room_key] = self._get_valve_position(room_config.valve_entity)

        # Update fan speed
        if current_fan != target.fan_speed:
            logger.info(f"Fan speed {current_fan}% → {target.fan_speed}%")
            self.ha.call_service(
                "fan",
                "set_percentage",
                entity_id=self.config.fan_entity,
                percentage=target.fan_speed,
            )
            changes_made = True

        # Update room valves (positions are already calculated)
        for room_key, room_state in target.rooms.items():
            room_config = self.config.rooms[room_key]
            current_valve = current_valves[room_key]
            target_valve = room_state.valve_position

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

        # Log comprehensive state overview
        logger.info("=" * 60)
        logger.info("STATE OVERVIEW")
        logger.info("=" * 60)
        logger.info(
            f"Fan Speed:  {current_fan}% → {target.fan_speed}% "
            f"{'(changed)' if current_fan != target.fan_speed else '(unchanged)'}"
        )
        logger.info("-" * 60)
        logger.info(f"{'Room':<20} {'Points':<10} {'Valve Position':<20}")
        logger.info("-" * 60)

        for room_key, room_state in target.rooms.items():
            room_config = self.config.rooms[room_key]
            current_valve = current_valves[room_key]
            target_valve = room_state.valve_position
            points = room_state.ventilation_points

            valve_change = "→" if current_valve != target_valve else "="
            logger.info(
                f"{room_config.name:<20} {points:<10} "
                f"{current_valve}% {valve_change} {target_valve}%"
            )

        logger.info("=" * 60)

    def _get_valve_position(self, entity_id: str) -> int:
        """Get current valve position."""
        return int(self.ha.get_attribute(entity_id, "current_position"))

    def _get_fan_speed(self) -> int:
        """Get current fan speed."""
        return int(self.ha.get_attribute(self.config.fan_entity, "percentage"))
