import csv
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
import urllib.request
from unittest.mock import patch

import data


class PingMeasurementTests(unittest.TestCase):
    @patch("data.subprocess.check_output")
    def test_get_default_gateway_on_linux(self, check_output):
        check_output.return_value = "default via 192.168.1.1 dev wlan0\n"

        gateway = data.get_default_gateway("Linux")

        self.assertEqual(gateway, "192.168.1.1")
        check_output.assert_called_once_with(
            ["ip", "-4", "route", "show", "default"],
            text=True,
            stderr=data.subprocess.PIPE,
        )

    @patch("data.subprocess.check_output")
    def test_get_default_gateway_on_windows_chooses_lowest_metric(
        self, check_output
    ):
        check_output.return_value = (
            "IPv4 Route Table\n"
            "Network Destination Netmask Gateway Interface Metric\n"
            "0.0.0.0 0.0.0.0 192.168.1.254 192.168.1.20 40\n"
            "0.0.0.0 0.0.0.0 192.168.1.1 192.168.1.20 10\n"
        )

        self.assertEqual(data.get_default_gateway("Windows"), "192.168.1.1")

    @patch("data.subprocess.run")
    def test_run_ping_test_uses_requested_target(self, run):
        run.return_value = SimpleNamespace(
            stdout=(
                "30 packets transmitted, 29 received, 3.3% packet loss\n"
                "rtt min/avg/max/mdev = 1.0/2.0/3.0/0.5 ms"
            ),
            returncode=0,
        )

        result = data.run_ping_test("Linux", "192.168.1.1")

        self.assertEqual(result["packet_loss_pct"], 3.3)
        self.assertEqual(result["avg_latency_ms"], 2.0)
        self.assertEqual(run.call_args.args[0][-1], "192.168.1.1")


class TimeSlotTests(unittest.TestCase):
    def test_time_slots_use_9_am_to_4_pm_window(self):
        self.assertEqual(data.get_time_slot(9), "s1")
        self.assertEqual(data.get_time_slot(12), "s4")
        self.assertEqual(data.get_time_slot(16), "s8")

    def test_time_slots_outside_collection_window(self):
        self.assertEqual(data.get_time_slot(8), "outside_window")
        self.assertEqual(data.get_time_slot(17), "outside_window")


class CsvAppendTests(unittest.TestCase):
    def test_appending_new_fields_preserves_existing_rows(self):
        old_fields = ["location", "packet_loss_pct"]
        new_fields = ["location", "packet_loss_pct", "gateway_packet_loss_pct"]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "measurements.csv")
            with open(path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=old_fields)
                writer.writeheader()
                writer.writerow({"location": "library", "packet_loss_pct": "0.0"})

            data.append_csv_row(
                path,
                new_fields,
                {
                    "location": "library",
                    "packet_loss_pct": 1.0,
                    "gateway_packet_loss_pct": 0.0,
                },
            )

            with open(path, newline="", encoding="utf-8") as csvfile:
                rows = list(csv.DictReader(csvfile))

        self.assertEqual(rows[0]["packet_loss_pct"], "0.0")
        self.assertEqual(rows[0]["gateway_packet_loss_pct"], "")
        self.assertEqual(rows[1]["gateway_packet_loss_pct"], "0.0")


class LocationCoordinateTests(unittest.TestCase):
    def test_coordinates_to_xy_uses_east_and_north_meters(self):
        x_coordinate, y_coordinate = data.coordinates_to_xy(
            latitude=0.001,
            longitude=0.001,
            origin_latitude=0.0,
            origin_longitude=0.0,
        )

        self.assertAlmostEqual(x_coordinate, 111.195, places=2)
        self.assertAlmostEqual(y_coordinate, 111.195, places=2)

    def test_coordinates_to_xy_wraps_longitude_across_antimeridian(self):
        x_coordinate, _ = data.coordinates_to_xy(
            latitude=0.0,
            longitude=-179.9,
            origin_latitude=0.0,
            origin_longitude=179.9,
        )

        self.assertAlmostEqual(x_coordinate, 22_239.016, places=0)

    def test_get_device_coordinates_accepts_browser_location(self):
        def simulate_browser(url):
            with urllib.request.urlopen(url) as response:
                page = response.read().decode("utf-8")
            self.assertIn("navigator.geolocation", page)

            request = urllib.request.Request(
                url,
                data=json.dumps(
                    {"latitude": 49.2, "longitude": -123.1}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 200)
            return True

        with patch("data.webbrowser.open", side_effect=simulate_browser):
            coordinates = data.get_device_coordinates(timeout_seconds=5)

        self.assertEqual(coordinates, (49.2, -123.1))

    def test_get_device_coordinates_reports_browser_permission_error(self):
        def simulate_denied_permission(url):
            request = urllib.request.Request(
                url,
                data=json.dumps({"error": "Permission denied"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 200)
            return True

        with patch("data.webbrowser.open", side_effect=simulate_denied_permission):
            with self.assertRaisesRegex(RuntimeError, "Permission denied"):
                data.get_device_coordinates(timeout_seconds=5)

    def test_get_device_coordinates_rejects_out_of_range_location(self):
        def simulate_invalid_location(url):
            request = urllib.request.Request(
                url,
                data=json.dumps({"latitude": 91, "longitude": 0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
            return True

        with patch("data.webbrowser.open", side_effect=simulate_invalid_location):
            with self.assertRaisesRegex(RuntimeError, "invalid coordinates"):
                data.get_device_coordinates(timeout_seconds=5)


if __name__ == "__main__":
    unittest.main()
