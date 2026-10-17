"""Humidity-based ventilation controller."""

import math
from dataclasses import dataclass
from typing import Dict, Optional
from config import Config, RoomConfig
from ha import HomeAssistantAPI


def saturation_vapor_pressure(temperature: float) -> float:
    """Saturation vapor pressure in hPa (Magnus formula)."""
    return 6.112 * math.exp(17.62 * temperature / (243.12 + temperature))


def outside_humidity_indoors(
    outside_temperature: float, outside_humidity: float, room_temperature: float
) -> float:
    """RH that outside air gets when it is heated (or cooled) to room temperature."""
    return (
        outside_humidity
        * saturation_vapor_pressure(outside_temperature)
        / saturation_vapor_pressure(room_temperature)
    )


def effective_target_humidity(
    base_target: float,
    outside_temperature: Optional[float],
    outside_humidity: Optional[float],
    room_temperature: Optional[float],
    margin: float,
    max_target: float,
) -> float:
    """
    Target humidity that ventilation can actually reach.

    Ventilating can't push a room below the RH of the outside air at room
    temperature, so the target is raised to that level plus a margin (capped
    at max_target). Falls back to the base target when data is missing.
    """
    if None in (outside_temperature, outside_humidity, room_temperature):
        return base_target

    reachable = outside_humidity_indoors(
        outside_temperature, outside_humidity, room_temperature
    )
    return max(base_target, min(reachable + margin, max_target))


@dataclass
class RoomState:
    """Current state of a room."""

    humidity: float
    demand: float
    valve_position: int
    temperature: Optional[float] = None
    target_humidity: Optional[float] = None


@dataclass
class SystemState:
    """Current state of the entire system."""

    automatic_ventilation: bool
    ventilation_speed: int
    rooms: Dict[str, RoomState]
    outside_temperature: Optional[float] = None
    outside_humidity: Optional[float] = None


class VentilationController:
    """Controls ventilation based on humidity levels."""

    def __init__(self, config: Config, ha: HomeAssistantAPI):
        self.config = config
        self.ha = ha

    def read_current_state(self) -> SystemState:
        """Read current state from Home Assistant."""
        gc = self.config.global_config

        # Read automatic ventilation switch (off = leave everything as is)
        automatic_ventilation = (
            self.ha.get_state(gc.automatic_ventilation_switch) == "on"
        )

        # Read current ventilation speed (an off fan keeps reporting its last
        # percentage, so treat it as 0 to make sure it gets turned back on)
        fan_on = self.ha.get_state(gc.ventilation_speed_entity) == "on"
        current_speed = self.ha.get_attribute(gc.ventilation_speed_entity, "percentage")
        if not fan_on or current_speed is None:
            current_speed = 0

        # Read outside air (None when unavailable: falls back to base targets)
        outside_temperature = None
        outside_humidity = None
        if gc.outside_weather_entity:
            outside_temperature = self.ha.get_attribute(
                gc.outside_weather_entity, "temperature"
            )
            outside_humidity = self.ha.get_attribute(
                gc.outside_weather_entity, "humidity"
            )

        # Read room states
        rooms = {}
        for room_key, room_config in self.config.rooms.items():
            humidity = self.ha.get_state(room_config.humidity_sensor)
            if humidity is None:
                humidity = 50.0  # Default fallback

            temperature = None
            if room_config.temperature_sensor:
                temperature = self.ha.get_state(room_config.temperature_sensor)
                if not isinstance(temperature, float):
                    temperature = None

            # Read current valve position
            current_valve_position = self.ha.get_attribute(
                room_config.valve_entity, "current_position"
            )
            if current_valve_position is None:
                current_valve_position = 0

            rooms[room_key] = RoomState(
                humidity=humidity,
                demand=0.0,  # Will be calculated
                valve_position=current_valve_position,
                temperature=temperature,
            )

        return SystemState(
            automatic_ventilation=automatic_ventilation,
            ventilation_speed=current_speed,
            rooms=rooms,
            outside_temperature=outside_temperature,
            outside_humidity=outside_humidity,
        )

    def calculate_room_demand(
        self, room_config: RoomConfig, room_humidity: float, target_humidity: float
    ) -> float:
        """
        Calculate ventilation demand for a room.

        Calculates demand proportionally to how far above target we are.
        Demand can exceed 100 - it's used for proportional valve distribution,
        not directly as fan speed.

        Returns: Demand (0 or higher, no upper limit)
        """
        curve = room_config.humidity_curve

        # Calculate how far we are above the target
        humidity_diff = room_humidity - target_humidity

        # Convert to demand using the multiplier
        demand = humidity_diff * curve.multiplier

        # Only clamp below 0 (can't have negative demand)
        return max(0.0, demand)

    def calculate_ventilation_speed(self, rooms: Dict[str, RoomState]) -> int:
        """
        Calculate global ventilation speed based on room demands.

        Sums all room demands (total capacity needed), with a configurable minimum.
        The capacity is then divided proportionally via valve positions.
        Rounded to nearest 10% to avoid frequent small changes.
        """
        min_speed = self.config.global_config.minimum_fan_speed

        if not rooms:
            # Round minimum to nearest 10
            return int(round(min_speed / 10) * 10)

        total_demand = sum(room.demand for room in rooms.values())
        # Ensure minimum for baseline airflow, cap at 100%
        speed = min(100, max(min_speed, total_demand))
        # Round to nearest 10% to avoid frequent small changes
        return int(round(speed / 10) * 10)

    def calculate_valve_positions(
        self, rooms: Dict[str, RoomState], room_configs: Dict[str, RoomConfig]
    ) -> Dict[str, int]:
        """
        Calculate proportional valve positions based on demand.

        Each room's valve position is proportional to its demand relative to the
        highest room demand, so the room that needs the most air opens fully.
        Rooms that would end up below min_opening get restricted_opening instead,
        so capacity goes to the rooms that need it.
        All positions rounded to nearest 10% to avoid frequent small changes.
        """
        max_demand = max((room.demand for room in rooms.values()), default=0)

        valve_positions = {}

        if max_demand == 0:
            # No demand: all valves at minimal opening
            for room_key, room_config in room_configs.items():
                min_pos = room_config.valve.min_opening
                valve_positions[room_key] = int(round(min_pos / 10) * 10)
        else:
            # Proportional distribution relative to the highest demand
            for room_key, room_state in rooms.items():
                room_config = room_configs[room_key]
                proportional = (room_state.demand / max_demand) * 100

                if proportional < room_config.valve.min_opening:
                    # No or little demand: restricted opening (capacity needed elsewhere)
                    position = room_config.valve.restricted_opening
                else:
                    position = proportional

                # Round to nearest 10%
                valve_positions[room_key] = int(round(position / 10) * 10)

        return valve_positions

    def calculate_required_state(self, current: SystemState) -> SystemState:
        """
        Calculate required state based on current conditions.

        This is a pure function that determines what the system should be doing.
        """
        # If automatic ventilation is off, don't change anything
        if not current.automatic_ventilation:
            return current

        gc = self.config.global_config

        # Calculate demand for each room
        new_rooms = {}
        for room_key, room_state in current.rooms.items():
            room_config = self.config.rooms[room_key]

            target_humidity = effective_target_humidity(
                room_config.humidity_curve.target_humidity,
                current.outside_temperature,
                current.outside_humidity,
                room_state.temperature,
                gc.outside_humidity_margin,
                gc.max_target_humidity,
            )
            demand = self.calculate_room_demand(
                room_config, room_state.humidity, target_humidity
            )

            new_rooms[room_key] = RoomState(
                humidity=room_state.humidity,
                demand=demand,
                valve_position=0,  # Will be set below
                temperature=room_state.temperature,
                target_humidity=target_humidity,
            )

        # Calculate global ventilation speed
        ventilation_speed = self.calculate_ventilation_speed(new_rooms)

        # Calculate valve positions
        valve_positions = self.calculate_valve_positions(new_rooms, self.config.rooms)

        # Update room states with valve positions
        for room_key, valve_position in valve_positions.items():
            new_rooms[room_key].valve_position = valve_position

        return SystemState(
            automatic_ventilation=current.automatic_ventilation,
            ventilation_speed=ventilation_speed,
            rooms=new_rooms,
            outside_temperature=current.outside_temperature,
            outside_humidity=current.outside_humidity,
        )

    def apply_state(self, current: SystemState, target: SystemState) -> None:
        """Apply calculated state to Home Assistant (only when changed)."""
        gc = self.config.global_config
        changes_made = False

        # Set ventilation speed (only if changed); turn_on also starts an off fan
        if current.ventilation_speed != target.ventilation_speed:
            self.ha.call_service(
                "fan",
                "turn_on",
                entity_id=gc.ventilation_speed_entity,
                percentage=target.ventilation_speed,
            )
            print(
                f"  ✓ Fan speed updated: {current.ventilation_speed}% -> {target.ventilation_speed}%"
            )
            changes_made = True
        else:
            print(f"  - Fan speed unchanged: {current.ventilation_speed}%")

        # Set valve positions (only if changed)
        for room_key, target_room in target.rooms.items():
            current_room = current.rooms[room_key]
            room_config = self.config.rooms[room_key]

            if current_room.valve_position != target_room.valve_position:
                self.ha.call_service(
                    "valve",
                    "set_valve_position",
                    entity_id=room_config.valve_entity,
                    position=target_room.valve_position,
                )
                print(
                    f"  ✓ {room_config.name} valve updated: {current_room.valve_position}% -> {target_room.valve_position}%"
                )
                changes_made = True
            else:
                print(
                    f"  - {room_config.name} valve unchanged: {current_room.valve_position}%"
                )

        if not changes_made:
            print("  (No HA calls needed - system already at target state)")

    def log_state(self, current: SystemState, target: SystemState) -> None:
        """Log current and target states for debugging."""
        print(f"Automatic ventilation: {current.automatic_ventilation}")
        if (
            current.outside_temperature is not None
            and current.outside_humidity is not None
        ):
            print(
                f"Outside: {current.outside_temperature:.1f}°C, {current.outside_humidity:.0f}%"
            )
        else:
            print("Outside: unavailable (using base targets)")
        print(
            f"Ventilation speed: {current.ventilation_speed}% -> {target.ventilation_speed}%"
        )
        print()

        for room_key in current.rooms.keys():
            current_room = current.rooms[room_key]
            target_room = target.rooms[room_key]
            room_config = self.config.rooms[room_key]

            base_target = room_config.humidity_curve.target_humidity
            target_humidity = target_room.target_humidity
            if target_humidity is None:
                target_text = f"{base_target:.0f}%"
            elif target_humidity > base_target:
                target_text = f"{target_humidity:.0f}%, raised from {base_target:.0f}% for outside air"
            else:
                target_text = f"{target_humidity:.0f}%"
            temperature_text = (
                f", {current_room.temperature:.1f}°C"
                if current_room.temperature is not None
                else ""
            )

            print(f"{room_config.name}:")
            print(
                f"  Humidity: {current_room.humidity:.1f}%{temperature_text} (target: {target_text})"
            )
            print(f"  Demand: {target_room.demand:.1f}")
            print(
                f"  Valve: {current_room.valve_position}% -> {target_room.valve_position}%"
            )

    def run_control_cycle(self) -> None:
        """Execute a single control cycle."""
        print("=" * 60)
        print("Ventilation Control Cycle")
        print("=" * 60)

        # Read current state
        current = self.read_current_state()

        # Calculate required state
        target = self.calculate_required_state(current)

        # Log for debugging
        self.log_state(current, target)

        # Apply changes
        if current.automatic_ventilation:
            self.apply_state(current, target)
            print("\nChanges applied to Home Assistant")
        else:
            print("\nAutomatic ventilation disabled - no changes applied")

        print("=" * 60)
