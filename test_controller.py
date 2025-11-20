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
                "bathroom": RoomState(
                    humidity=60.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should be at minimum speed (no ventilation requested)
        self.assertEqual(target.fan_speed, self.config.min_fan_speed)
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
                "bathroom": RoomState(
                    humidity=75.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should be at high speed
        self.assertEqual(target.fan_speed, 100)
        # Bathroom should need ventilation
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)
        self.assertFalse(target.rooms["living_room"].needs_ventilation)

    def test_bathroom_needs_ventilation_occupied(self):
        """Test bathroom needs ventilation but is occupied (skip_when_occupied)."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=75.0, occupied=True, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should be at minimum speed (bathroom doesn't request due to occupancy)
        self.assertEqual(target.fan_speed, 30)
        # Bathroom still needs ventilation (high humidity)
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)
        # But should not request it

    def test_living_room_needs_ventilation_occupied(self):
        """Test living room needs ventilation while occupied (should still ventilate)."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=60.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=75.0, occupied=True, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should be at high speed (living room requests ventilation even when occupied)
        self.assertEqual(target.fan_speed, 100)
        self.assertTrue(target.rooms["living_room"].needs_ventilation)

    def test_both_rooms_need_ventilation_bathroom_occupied(self):
        """Test both rooms need ventilation but bathroom is occupied."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=75.0, occupied=True, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=75.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should run for living room
        self.assertEqual(target.fan_speed, 100)
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)
        self.assertTrue(target.rooms["living_room"].needs_ventilation)

    def test_hysteresis_turn_on(self):
        """Test hysteresis when turning on ventilation."""
        current = SystemState(
            fan_speed=30,  # Not currently ventilating
            rooms={
                "bathroom": RoomState(
                    humidity=70.5, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Should turn on (humidity > 70%)
        self.assertEqual(target.fan_speed, 100)
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)

    def test_hysteresis_stay_off(self):
        """Test hysteresis keeps ventilation off when below upper threshold."""
        current = SystemState(
            fan_speed=30,  # Not currently ventilating
            rooms={
                "bathroom": RoomState(
                    humidity=69.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Should stay off (humidity <= 70%)
        self.assertEqual(target.fan_speed, 30)
        self.assertFalse(target.rooms["bathroom"].needs_ventilation)

    def test_hysteresis_stay_on(self):
        """Test hysteresis keeps ventilation on until below lower threshold."""
        current = SystemState(
            fan_speed=100,  # Currently ventilating
            rooms={
                "bathroom": RoomState(
                    humidity=67.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Should stay on (humidity >= 65%)
        self.assertEqual(target.fan_speed, 100)
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)

    def test_hysteresis_turn_off(self):
        """Test hysteresis turns off when below lower threshold."""
        current = SystemState(
            fan_speed=100,  # Currently ventilating
            rooms={
                "bathroom": RoomState(
                    humidity=64.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Should turn off (humidity < 65%)
        self.assertEqual(target.fan_speed, 30)
        self.assertFalse(target.rooms["bathroom"].needs_ventilation)

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
                    needs_ventilation=False,
                    valve_position=bathroom_default,
                ),
                "living_room": RoomState(
                    humidity=55.0,
                    occupied=False,
                    needs_ventilation=False,
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

    def test_valve_position_occupied_with_skip(self):
        """Test valve position when room is occupied with skip_when_occupied."""
        bathroom_valve = self.config.rooms["bathroom"].valve_entity
        living_room_valve = self.config.rooms["living_room"].valve_entity

        self.ha.get_attribute.side_effect = lambda entity, attr: {
            (bathroom_valve, "current_position"): 100,
            (living_room_valve, "current_position"): 50,
            (self.config.fan_entity, "percentage"): 30,
        }.get((entity, attr))

        target = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=75.0,
                    occupied=True,
                    needs_ventilation=True,
                    valve_position=100,
                ),
                "living_room": RoomState(
                    humidity=55.0,
                    occupied=False,
                    needs_ventilation=False,
                    valve_position=100,
                ),
            },
        )

        self.controller.apply_state(target)

        # Bathroom valve should be set to default to avoid breeze
        calls = self.ha.call_service.call_args_list
        valve_calls = [c for c in calls if c[0][0] == "valve"]

        self.assertIn(
            call("valve", "set_valve_position", entity_id=bathroom_valve, position=20),
            valve_calls,
        )

    def test_valve_position_primary_room(self):
        """Test valve position when room is primary (needs ventilation, not occupied)."""
        bathroom_valve = self.config.rooms["bathroom"].valve_entity
        living_room_valve = self.config.rooms["living_room"].valve_entity
        living_room_default = self.config.get_room_default_valve_position("living_room")

        self.ha.get_attribute.side_effect = lambda entity, attr: {
            (bathroom_valve, "current_position"): 20,
            (living_room_valve, "current_position"): 100,
            (self.config.fan_entity, "percentage"): 100,
        }.get((entity, attr))

        target = SystemState(
            fan_speed=100,
            rooms={
                "bathroom": RoomState(
                    humidity=75.0,
                    occupied=False,
                    needs_ventilation=True,
                    valve_position=100,
                ),
                "living_room": RoomState(
                    humidity=55.0,
                    occupied=False,
                    needs_ventilation=False,
                    valve_position=living_room_default,
                ),
            },
        )

        self.controller.apply_state(target)

        # Bathroom valve should be fully open (primary room)
        calls = self.ha.call_service.call_args_list
        valve_calls = [c for c in calls if c[0][0] == "valve"]

        self.assertIn(
            call("valve", "set_valve_position", entity_id=bathroom_valve, position=100),
            valve_calls,
        )
        # Living room should be at default (50%) since it doesn't need ventilation
        self.assertIn(
            call(
                "valve", "set_valve_position", entity_id=living_room_valve, position=50
            ),
            valve_calls,
        )

    def test_realistic_scenario_showering(self):
        """Test realistic scenario: Someone showering in bathroom."""
        # Initial state: person enters bathroom, starts showering
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=80.0, occupied=True, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=True, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should stay at minimum (bathroom occupied with skip_when_occupied)
        self.assertEqual(target.fan_speed, 30)
        # Bathroom needs ventilation but doesn't request it
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)

    def test_realistic_scenario_after_shower(self):
        """Test realistic scenario: Person leaves bathroom after shower."""
        # State after person leaves bathroom
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=80.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=True, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should turn on to ventilate bathroom
        self.assertEqual(target.fan_speed, 100)
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)

    def test_realistic_scenario_living_room_cooking(self):
        """Test realistic scenario: Humidity rises in living room while occupied (cooking)."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=60.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=75.0, occupied=True, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should run even though living room is occupied
        self.assertEqual(target.fan_speed, 100)
        self.assertTrue(target.rooms["living_room"].needs_ventilation)

    def test_realistic_scenario_both_rooms_humid(self):
        """Test realistic scenario: Both rooms humid, bathroom occupied."""
        # Bathroom: high humidity, occupied (someone showering)
        # Living room: high humidity, not occupied
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=85.0, occupied=True, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=75.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should run for living room
        self.assertEqual(target.fan_speed, 100)
        # Both need ventilation
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)
        self.assertTrue(target.rooms["living_room"].needs_ventilation)

    def test_realistic_scenario_humidity_drops_slowly(self):
        """Test realistic scenario: Humidity drops slowly after ventilation starts."""
        # Fan is running, humidity is still above off threshold
        current = SystemState(
            fan_speed=100,
            rooms={
                "bathroom": RoomState(
                    humidity=66.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should keep running (hysteresis: 66% >= 65%)
        self.assertEqual(target.fan_speed, 100)
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)

    def test_custom_room_thresholds(self):
        """Test room-specific humidity thresholds."""
        # Add custom thresholds to bathroom
        self.config.rooms["bathroom"].humidity_threshold_on = 75.0
        self.config.rooms["bathroom"].humidity_threshold_off = 70.0

        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=72.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=55.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Bathroom should not trigger (72% <= 75%)
        self.assertEqual(target.fan_speed, 30)
        self.assertFalse(target.rooms["bathroom"].needs_ventilation)

    def test_multiple_rooms_need_ventilation(self):
        """Test when multiple rooms need ventilation simultaneously."""
        current = SystemState(
            fan_speed=30,
            rooms={
                "bathroom": RoomState(
                    humidity=75.0, occupied=False, needs_ventilation=False
                ),
                "living_room": RoomState(
                    humidity=75.0, occupied=False, needs_ventilation=False
                ),
            },
        )

        target = self.controller.calculate_required_state(current)

        # Fan should run at high speed
        self.assertEqual(target.fan_speed, 100)
        # Both rooms need ventilation
        self.assertTrue(target.rooms["bathroom"].needs_ventilation)
        self.assertTrue(target.rooms["living_room"].needs_ventilation)


if __name__ == "__main__":
    unittest.main()
