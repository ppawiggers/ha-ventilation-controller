"""Unit tests for ventilation controller."""

import unittest
from unittest.mock import Mock, call
from controller import VentilationController
from config import VentilationConfig
from state import RoomState, SystemState


class TestVentilationController(unittest.TestCase):
    """Test suite for VentilationController."""

    def setUp(self):
        """Set up test fixtures."""
        self.ha = Mock()
        # Use actual configuration from config.py
        self.config = VentilationConfig()
        self.controller = VentilationController(self.ha, self.config)

    def test_no_rooms_need_ventilation(self):
        """Test when no rooms need ventilation."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=60.0, occupied=False),
                "living_room": RoomState(humidity=55.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # No points, fan should be at minimum speed
        self.assertEqual(target.fan_speed, self.config.min_fan_speed)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 0)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 0)
        # All valves should be at their room-specific default positions
        self.assertEqual(
            target.rooms["bathroom"].valve_position,
            self.config.get_room_default_valve_position("bathroom"),
        )
        self.assertEqual(
            target.rooms["living_room"].valve_position,
            self.config.get_room_default_valve_position("living_room"),
        )

    def test_bathroom_needs_ventilation_not_occupied(self):
        """Test bathroom needs ventilation and is not occupied."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=75.0, occupied=False),
                "living_room": RoomState(humidity=55.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom: 75% > 65% threshold = 100 points (step mode)
        # Fan speed = 100 points (capped at 100%)
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 0)
        # Bathroom has max points, valve at 100%
        self.assertEqual(target.rooms["bathroom"].valve_position, 100)
        # Living room has no points, valve at default
        self.assertEqual(
            target.rooms["living_room"].valve_position,
            self.config.get_room_default_valve_position("living_room"),
        )

    def test_bathroom_needs_ventilation_occupied(self):
        """Test bathroom needs ventilation but is occupied (skip_when_occupied)."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=75.0, occupied=True),
                "living_room": RoomState(humidity=55.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom has 100 points but is occupied with skip_when_occupied
        # Points are ignored for fan speed calculation
        self.assertEqual(target.fan_speed, 30)  # Minimum
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)
        # Valve should be at default (avoiding breeze)
        self.assertEqual(
            target.rooms["bathroom"].valve_position,
            self.config.get_room_default_valve_position("bathroom"),
        )

    def test_living_room_needs_ventilation_occupied(self):
        """Test living room needs ventilation while occupied (should still ventilate)."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=60.0, occupied=False),
                "living_room": RoomState(humidity=75.0, occupied=True),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Living room: 75% > 65% = 100 points, not skipped when occupied
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 100)
        # Living room valve at 100% (has max points)
        self.assertEqual(target.rooms["living_room"].valve_position, 100)

    def test_both_rooms_need_ventilation_bathroom_occupied(self):
        """Test both rooms need ventilation but bathroom is occupied."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=75.0, occupied=True),
                "living_room": RoomState(humidity=75.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom: 100 points (ignored due to occupancy)
        # Living room: 100 points
        # Fan speed = 100 (living room only)
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 100)
        # Living room has active points, gets 100% valve
        self.assertEqual(target.rooms["living_room"].valve_position, 100)
        # Bathroom occupied, valve at default
        self.assertEqual(
            target.rooms["bathroom"].valve_position,
            self.config.get_room_default_valve_position("bathroom"),
        )

    def test_threshold_boundary_below(self):
        """Test humidity just below threshold (65%)."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=64.9, occupied=False),
                "living_room": RoomState(humidity=55.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Below threshold = 0 points
        self.assertEqual(target.fan_speed, 30)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 0)

    def test_threshold_boundary_at(self):
        """Test humidity at threshold (65%)."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=65.0, occupied=False),
                "living_room": RoomState(humidity=55.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # At threshold = 100 points (step mode)
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)

    def test_threshold_boundary_above(self):
        """Test humidity just above threshold (65%)."""
        current = SystemState(
            fan_speed=100,
            rooms={
                "bathroom": RoomState(humidity=65.1, occupied=False),
                "living_room": RoomState(humidity=55.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Above threshold = 100 points (step mode)
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)

    def test_valve_position_no_ventilation_needed(self):
        """Test valve position when room doesn't need ventilation."""
        bathroom_valve = self.config.rooms["bathroom"].valve_entity
        living_room_valve = self.config.rooms["living_room"].valve_entity
        bathroom_default = self.config.get_room_default_valve_position("bathroom")
        living_room_default = self.config.get_room_default_valve_position("living_room")

        self.ha.get_attribute.side_effect = lambda entity, attr: {
            (bathroom_valve, "current_position"): 100,
            (living_room_valve, "current_position"): 100,
            (self.config.fan_entity, "percentage"): 30,
        }.get((entity, attr))

        target = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=60.0,
                    occupied=False,
                    ventilation_points=0,
                    valve_position=bathroom_default,
                ),
                "living_room": RoomState(
                    humidity=55.0,
                    occupied=False,
                    ventilation_points=0,
                    valve_position=living_room_default,
                ),
            },
        )

        self.controller.apply_state(target)

        # Both valves should be set to default positions
        calls = self.ha.call_service.call_args_list
        valve_calls = [c for c in calls if c[0][0] == "valve"]

        # Check bathroom valve set to default (20%)
        self.assertIn(
            call("valve", "set_valve_position", entity_id=bathroom_valve, position=20),
            valve_calls,
        )
        # Check living room valve set to default (50%)
        self.assertIn(
            call(
                "valve", "set_valve_position", entity_id=living_room_valve, position=50
            ),
            valve_calls,
        )

    def test_proportional_valve_positions(self):
        """Test proportional valve positions with different point values."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=75.0, occupied=False),  # 100 points
                "living_room": RoomState(humidity=55.0, co2=1050.0, occupied=False),  # 50 points
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom: 100 points (max) -> fan speed includes both
        # Living room: CO2 1050 = (1050-600)/(1500-600) * 100 = 50 points
        # Fan speed = 100 + 50 = 150, capped at 100, rounded to 100
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 50)

        # Bathroom has max points (100), valve at 100%
        self.assertEqual(target.rooms["bathroom"].valve_position, 100)
        # Living room has 50/100 points = 50% valve (rounded to 50%)
        self.assertEqual(target.rooms["living_room"].valve_position, 50)

    def test_realistic_scenario_showering(self):
        """Test realistic scenario: Someone showering in bathroom."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=80.0, occupied=True),
                "living_room": RoomState(humidity=55.0, occupied=True),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom has points but is occupied with skip_when_occupied
        # Fan should stay at minimum
        self.assertEqual(target.fan_speed, 30)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)
        # Valve at default to avoid breeze
        self.assertEqual(
            target.rooms["bathroom"].valve_position,
            self.config.get_room_default_valve_position("bathroom"),
        )

    def test_realistic_scenario_after_shower(self):
        """Test realistic scenario: Person leaves bathroom after shower."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=80.0, occupied=False),
                "living_room": RoomState(humidity=55.0, occupied=True),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom has 100 points, not occupied -> fan runs
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)
        self.assertEqual(target.rooms["bathroom"].valve_position, 100)

    def test_realistic_scenario_living_room_cooking(self):
        """Test realistic scenario: Humidity rises in living room while occupied (cooking)."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=60.0, occupied=False),
                "living_room": RoomState(humidity=75.0, occupied=True),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Living room has 100 points and is not skipped when occupied
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 100)

    def test_realistic_scenario_both_rooms_humid(self):
        """Test realistic scenario: Both rooms humid, bathroom occupied."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=85.0, occupied=True),
                "living_room": RoomState(humidity=75.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom: 100 points (ignored)
        # Living room: 100 points
        # Fan speed = 100
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 100)

    def test_custom_room_humidity_config(self):
        """Test room-specific humidity points configuration."""
        # Configure bathroom to use linear mode with custom thresholds
        self.config.rooms["bathroom"].humidity_points_mode = "linear"
        self.config.rooms["bathroom"].humidity_points_threshold = 70.0
        self.config.rooms["bathroom"].humidity_points_max = 90.0

        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=80.0, occupied=False),  # Midpoint
                "living_room": RoomState(humidity=55.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom: 80% humidity with 70-90 range = (80-70)/(90-70) * 100 = 50 points
        # Fan speed = 50 points, rounded to 50%
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 50)
        self.assertEqual(target.fan_speed, 50)

    def test_co2_low_no_ventilation(self):
        """Test CO2 below threshold doesn't trigger ventilation."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=60.0, occupied=False),
                "living_room": RoomState(humidity=55.0, co2=550.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # CO2 below threshold = 0 points
        self.assertEqual(target.fan_speed, 30)  # Minimum
        self.assertEqual(target.rooms["living_room"].ventilation_points, 0)

    def test_co2_medium_partial_ventilation(self):
        """Test CO2 at medium level triggers proportional fan speed."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=60.0, occupied=False),
                "living_room": RoomState(humidity=55.0, co2=1050.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # CO2 1050 ppm = (1050-600)/(1500-600) * 100 = 50 points
        # Fan speed = 50 points
        self.assertEqual(target.fan_speed, 50)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 50)
        # Living room valve at 100% (has the only points)
        self.assertEqual(target.rooms["living_room"].valve_position, 100)

    def test_co2_high_full_ventilation(self):
        """Test high CO2 triggers maximum fan speed."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=60.0, occupied=False),
                "living_room": RoomState(humidity=55.0, co2=1600.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # CO2 above max threshold = 100 points
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 100)

    def test_co2_and_humidity_different_rooms(self):
        """Test CO2 in one room and humidity in another."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=75.0, occupied=False),  # 100 points
                "living_room": RoomState(humidity=55.0, co2=1050.0, occupied=False),  # 50 points
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan speed = 100 + 50 = 150, capped at 100, rounded to 100
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 100)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 50)
        # Bathroom has max points, valve at 100%
        self.assertEqual(target.rooms["bathroom"].valve_position, 100)
        # Living room has 50/100 = 50% valve (rounded to 50%)
        self.assertEqual(target.rooms["living_room"].valve_position, 50)

    def test_co2_and_humidity_same_room(self):
        """Test when same room has both CO2 and humidity demands."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=60.0, occupied=False),
                "living_room": RoomState(humidity=75.0, co2=1050.0, occupied=False),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Living room: humidity = 100 points, CO2 = 50 points
        # Room takes max = 100 points
        # Fan speed = 100
        self.assertEqual(target.fan_speed, 100)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 100)
        self.assertEqual(target.rooms["living_room"].valve_position, 100)

    def test_realistic_scenario_high_co2_while_occupied(self):
        """Test realistic scenario: High CO2 in occupied living room."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=60.0, occupied=False),
                "living_room": RoomState(humidity=55.0, co2=1300.0, occupied=True),
            },
        )

        target = self.controller.calculate_required_state(current)

        # CO2 1300 = (1300-600)/(1500-600) * 100 = 77 points
        # Living room not skipped when occupied (skip_when_occupied=False)
        # Fan speed = 77, rounded to 80%
        self.assertEqual(target.fan_speed, 80)
        # Living room valve should be open
        self.assertEqual(target.rooms["living_room"].valve_position, 100)

    def test_multiple_rooms_different_points(self):
        """Test multiple rooms with different point values."""
        # Configure bathroom to use linear mode for this test
        self.config.rooms["bathroom"].humidity_points_mode = "linear"
        self.config.rooms["bathroom"].humidity_points_threshold = 65.0
        self.config.rooms["bathroom"].humidity_points_max = 85.0

        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(humidity=75.0, occupied=False),  # 50 points
                "living_room": RoomState(humidity=55.0, co2=900.0, occupied=False),  # 33 points
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom: (75-65)/(85-65) * 100 = 50 points
        # Living room: (900-600)/(1500-600) * 100 = 33 points
        # Fan speed = 50 + 33 = 83, rounded to 80%
        self.assertEqual(target.rooms["bathroom"].ventilation_points, 50)
        self.assertEqual(target.rooms["living_room"].ventilation_points, 33)
        self.assertEqual(target.fan_speed, 80)
        # Bathroom has max points (50), valve at 100%
        self.assertEqual(target.rooms["bathroom"].valve_position, 100)
        # Living room has 33/50 = 66% valve, rounded to 70%
        self.assertEqual(target.rooms["living_room"].valve_position, 70)


if __name__ == "__main__":
    unittest.main()
