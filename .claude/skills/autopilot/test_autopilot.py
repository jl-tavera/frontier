#!/usr/bin/env python3
"""python skills/autopilot/test_autopilot.py -- the launch gate and the flag parsing, nothing that needs gh or git."""

import unittest

import autopilot

RUNNING = {51: object()}


class Headroom(unittest.TestCase):
    def test_nothing_running_always_starts_one(self):
        self.assertTrue(autopilot.headroom({"five_hour": 0.95, "seven_day": 0.1}, None, set(), {}))

    def test_waits_for_the_newest_session_to_report(self):
        self.assertFalse(autopilot.headroom({"five_hour": None, "seven_day": None}, 51, set(), RUNNING))

    def test_no_reading_counts_as_headroom_once_reported(self):
        self.assertTrue(autopilot.headroom({"five_hour": None, "seven_day": None}, 51, {51}, RUNNING))

    def test_holds_at_the_ceiling(self):
        self.assertFalse(autopilot.headroom({"five_hour": 0.85, "seven_day": 0.2}, 51, {51}, RUNNING))

    def test_starts_under_the_ceiling(self):
        self.assertTrue(autopilot.headroom({"five_hour": 0.5, "seven_day": 0.79}, 51, {51}, RUNNING))


class Parse(unittest.TestCase):
    def test_serial_range_and_max(self):
        self.assertEqual(autopilot.parse(["--serial", "51-55,", "58", "--max", "2"]),
                         ([51, 52, 53, 54, 55, 58], 2, True))

    def test_default_is_parallel(self):
        self.assertEqual(autopilot.parse(["52 and 53"]), ([52, 53], None, False))


if __name__ == "__main__":
    unittest.main()
