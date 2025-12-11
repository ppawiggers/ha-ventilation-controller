"""Simplified ventilation controller with humidity-based control."""

from dataclasses import dataclass
from typing import Dict
from config import Config, RoomConfig
from ha import HomeAssistantAPI


@dataclass
class RoomState:
    """Current state of a room."""

    humidity: float
    demand: float
    valve_position: int


@dataclass
class SystemState:
    """Current state of the entire system."""

    manual_override: bool
    ventilation_speed: int
    rooms: Dict[str, RoomState]


class VentilationController:
    """Controls ventilation based on humidity levels."""

    def __init__(self, config: Config, ha: HomeAssistantAPI):
        self.config = config
        self.ha = ha

    def read_current_state(self) -> SystemState:
        """Read current state from Home Assistant."""
        gc = self.config.global_config

        # Read manual override
        manual_override_state = self.ha.get_state(gc.manual_override_switch)
        manual_override = (
            manual_override_state == "on" if manual_override_state else False
        )

        # Read current ventilation speed
        current_speed = self.ha.get_attribute(gc.ventilation_speed_entity, "percentage")
        if current_speed is None:
            current_speed = 0

        # Read room states
        rooms = {}
        for room_key, room_config in self.config.rooms.items():
            humidity = self.ha.get_state(room_config.humidity_sensor)
            if humidity is None:
                humidity = 50.0  # Default fallback

            rooms[room_key] = RoomState(
                humidity=humidity,
                demand=0.0,  # Will be calculated
                valve_position=0,  # Will be calculated
            )

        return SystemState(
            manual_override=manual_override,
            ventilation_speed=current_speed,
            rooms=rooms,
        )

    def calculate_room_demand(
        self, room_config: RoomConfig, room_humidity: float
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
        humidity_diff = room_humidity - curve.target_humidity

        # Convert to demand using the multiplier
        demand = humidity_diff * curve.multiplier

        # Only clamp below 0 (can't have negative demand)
        return max(0.0, demand)

    def calculate_ventilation_speed(self, rooms: Dict[str, RoomState]) -> int:
        """
        Calculate global ventilation speed based on room demands.

        Sums all room demands (total capacity needed), with a minimum of 25%.
        The capacity is then divided proportionally via valve positions.
        Rounded to nearest 10% to avoid frequent small changes.
        """
        if not rooms:
            return 30  # Rounded to nearest 10

        total_demand = sum(room.demand for room in rooms.values())
        # Ensure minimum 25% for baseline airflow, cap at 100%
        speed = min(100, max(25, total_demand))
        # Round to nearest 10% to avoid frequent small changes
        return int(round(speed / 10) * 10)

    def calculate_valve_positions(
        self, rooms: Dict[str, RoomState], room_configs: Dict[str, RoomConfig]
    ) -> Dict[str, int]:
        """
        Calculate proportional valve positions based on demand.

        Each room's valve position is proportional to its share of total demand,
        but respecting minimum and restricted opening constraints.
        All positions rounded to nearest 10% to avoid frequent small changes.
        """
        # Calculate total demand
        total_demand = sum(room.demand for room in rooms.values())

        valve_positions = {}

        if total_demand == 0:
            # No demand: all valves at minimal opening
            for room_key, room_config in room_configs.items():
                min_pos = room_config.valve.min_opening
                valve_positions[room_key] = int(round(min_pos / 10) * 10)
        else:
            # Proportional distribution based on demand
            for room_key, room_state in rooms.items():
                room_config = room_configs[room_key]

                if room_state.demand == 0:
                    # No demand: restricted opening (capacity needed elsewhere)
                    restricted_pos = room_config.valve.restricted_opening
                    valve_positions[room_key] = int(round(restricted_pos / 10) * 10)
                else:
                    # Proportional to demand, but at least min_opening
                    proportional = (room_state.demand / total_demand) * 100
                    position = max(room_config.valve.min_opening, proportional)
                    # Round to nearest 10%
                    valve_positions[room_key] = int(round(position / 10) * 10)

        return valve_positions

    def calculate_required_state(self, current: SystemState) -> SystemState:
        """
        Calculate required state based on current conditions.

        This is a pure function that determines what the system should be doing.
        """
        # If manual override is active, don't change anything
        if current.manual_override:
            return current

        # Calculate demand for each room
        new_rooms = {}
        for room_key, room_state in current.rooms.items():
            room_config = self.config.rooms[room_key]

            demand = self.calculate_room_demand(room_config, room_state.humidity)

            new_rooms[room_key] = RoomState(
                humidity=room_state.humidity,
                demand=demand,
                valve_position=0,  # Will be set below
            )

        # Calculate global ventilation speed
        ventilation_speed = self.calculate_ventilation_speed(new_rooms)

        # Calculate valve positions
        valve_positions = self.calculate_valve_positions(new_rooms, self.config.rooms)

        # Update room states with valve positions
        for room_key, valve_position in valve_positions.items():
            new_rooms[room_key].valve_position = valve_position

        return SystemState(
            manual_override=current.manual_override,
            ventilation_speed=ventilation_speed,
            rooms=new_rooms,
        )

    def apply_state(self, state: SystemState) -> None:
        """Apply calculated state to Home Assistant."""
        gc = self.config.global_config

        # Set ventilation speed
        self.ha.call_service(
            "fan",
            "set_percentage",
            entity_id=gc.ventilation_speed_entity,
            percentage=state.ventilation_speed,
        )

        # Set valve positions
        for room_key, room_state in state.rooms.items():
            room_config = self.config.rooms[room_key]
            self.ha.call_service(
                "valve",
                "set_valve_position",
                entity_id=room_config.valve_entity,
                position=room_state.valve_position,
            )

    def log_state(self, current: SystemState, target: SystemState) -> None:
        """Log current and target states for debugging."""
        print(f"Manual override: {current.manual_override}")
        print(
            f"Ventilation speed: {current.ventilation_speed}% -> {target.ventilation_speed}%"
        )
        print()

        for room_key in current.rooms.keys():
            current_room = current.rooms[room_key]
            target_room = target.rooms[room_key]
            room_config = self.config.rooms[room_key]

            print(f"{room_config.name}:")
            print(
                f"  Humidity: {current_room.humidity:.1f}% (target: {room_config.humidity_curve.target_humidity:.0f}%)"
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
        if not current.manual_override:
            self.apply_state(target)
            print("\nChanges applied to Home Assistant")
        else:
            print("\nManual override active - no changes applied")

        print("=" * 60)
