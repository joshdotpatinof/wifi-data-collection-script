import csv
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import math
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser

# ==============================================================================
# CONTROLLED EXPERIMENTAL PARAMETERS (Keep constant across all runs)
# ==============================================================================
PING_TARGET = "8.8.8.8"  # Fixed latency test destination
PING_COUNT = 30  # Fixed packet count (3.33% packet loss resolution)
SPEEDTEST_SERVER_ID = (
    None  # Locked to your verified server ID (or set to None for auto)
)

# Origin is set to pinned location of UP Alumni Engineers Centennial Hall (AECH)
ORIGIN_LATITUDE = 14.648702409653344  # Set the origin latitude in decimal degrees.
ORIGIN_LONGITUDE = 121.06870994812495  # Set the origin longitude in decimal degrees.
EARTH_RADIUS_METERS = 6_371_008.8


def detect_os() -> str:
    """Detect the operating system running on the laptop."""
    system = platform.system()
    if system in ("Windows", "Linux", "Darwin"):
        return system
    raise RuntimeError(f"Unsupported operating system: {system}")


def unescape_iw_ssid(raw_ssid: str) -> str:
    """Decode `iw` hex-escaped UTF-8 bytes (e.g., '\\xc3\\xb1' -> 'ñ')."""
    if "\\x" not in raw_ssid:
        return raw_ssid
    try:
        raw_bytes = re.sub(
            r"\\x([0-9a-fA-F]{2})",
            lambda m: chr(int(m.group(1), 16)),
            raw_ssid,
        ).encode("latin-1")
        return raw_bytes.decode("utf-8")
    except Exception:
        return raw_ssid


def get_wifi_signal(os_name: str) -> dict:
    """Measure Wi-Fi signal strength (dBm), SSID, and BSSID using OS-native CLI tools."""
    result = {"ssid": None, "bssid": None, "signal_dbm": None}

    try:
        if os_name == "Windows":
            output = subprocess.check_output(
                ["netsh", "wlan", "show", "interfaces"],
                text=True,
                stderr=subprocess.PIPE,
            )
            ssid_match = re.search(r"^\s*SSID\s*:\s*(.+)$", output, re.MULTILINE)
            bssid_match = re.search(
                r"^\s*(?:AP\s+)?BSSID\s*:\s*([0-9a-fA-F:]{17})",
                output,
                re.MULTILINE,
            )
            sig_match = re.search(
                r"^\s*Signal\s*:\s*(\d+)%", output, re.MULTILINE
            )

            if ssid_match:
                result["ssid"] = ssid_match.group(1).strip()
            if bssid_match:
                result["bssid"] = bssid_match.group(1).strip().lower()
            if sig_match:
                signal_pct = float(sig_match.group(1))
                result["signal_dbm"] = round((signal_pct / 2.0) - 100.0, 2)

        elif os_name == "Linux":
            iw_bin = shutil.which("iw") or (
                "/usr/sbin/iw"
                if os.path.exists("/usr/sbin/iw")
                else "/sbin/iw"
            )
            if os.path.exists(iw_bin):
                iw_dev = subprocess.check_output(
                    [iw_bin, "dev"], text=True, stderr=subprocess.PIPE
                )
                interfaces = re.findall(r"Interface\s+(\S+)", iw_dev)
                for iface in interfaces:
                    if iface.startswith("p2p"):
                        continue
                    output = subprocess.check_output(
                        [iw_bin, "dev", iface, "link"],
                        text=True,
                        stderr=subprocess.PIPE,
                    )
                    if "Connected to" in output:
                        ssid_match = re.search(r"SSID:\s*(.+)", output)
                        bssid_match = re.search(
                            r"Connected to\s+([0-9a-fA-F:]{17})", output
                        )
                        sig_match = re.search(
                            r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm", output
                        )
                        if ssid_match:
                            result["ssid"] = unescape_iw_ssid(
                                ssid_match.group(1).strip()
                            )
                        if bssid_match:
                            result["bssid"] = (
                                bssid_match.group(1).strip().lower()
                            )
                        if sig_match:
                            result["signal_dbm"] = float(sig_match.group(1))
                        break

            # Fallback 1: NetworkManager (`nmcli`)
            if result["signal_dbm"] is None and shutil.which("nmcli"):
                nm_out = subprocess.check_output(
                    [
                        "nmcli",
                        "-t",
                        "-f",
                        "IN-USE,SSID,BSSID,SIGNAL",
                        "dev",
                        "wifi",
                    ],
                    text=True,
                    stderr=subprocess.PIPE,
                )
                for line in nm_out.splitlines():
                    if line.startswith("*:"):
                        cleaned = line.replace("\\:", ":")
                        parts = cleaned.split(":")
                        if len(parts) >= 8:
                            result["ssid"] = parts[1] or None
                            result["bssid"] = ":".join(parts[2:8]).lower()
                            if len(parts) >= 9 and parts[8].isdigit():
                                sig_pct = float(parts[8])
                                result["signal_dbm"] = round(
                                    (sig_pct / 2.0) - 100.0, 2
                                )
                        break

            # Fallback 2: Kernel `/proc/net/wireless` for signal dBm
            if result["signal_dbm"] is None and os.path.exists(
                "/proc/net/wireless"
            ):
                with open("/proc/net/wireless", encoding="utf-8") as f:
                    for line in f:
                        proc_match = re.match(
                            r"^\s*\S+:\s*\d+\s+[\d.]+\s+(-?\d+(?:\.\d+)?)",
                            line,
                        )
                        if proc_match:
                            result["signal_dbm"] = float(proc_match.group(1))
                            break

            if result["signal_dbm"] is None:
                print("[Warning] No active Linux Wi-Fi link detected.")

        elif os_name == "Darwin":
            output = subprocess.check_output(
                ["system_profiler", "SPAirPortDataType"],
                text=True,
                stderr=subprocess.PIPE,
            )
            current_net_block = re.search(
                r"Current Network Information:\s*\n\s+(.+?):\n(.*?)(?:\n\s{12}\S|\Z)",
                output,
                re.DOTALL,
            )
            if current_net_block:
                result["ssid"] = current_net_block.group(1).strip()
                details = current_net_block.group(2)
                bssid_match = re.search(
                    r"BSSID:\s*([0-9a-fA-F:]{17})", details
                )
                sig_match = re.search(
                    r"Signal / Noise:\s*(-?\d+(?:\.\d+)?)\s*dBm", details
                )
                if bssid_match:
                    result["bssid"] = bssid_match.group(1).strip().lower()
                if sig_match:
                    result["signal_dbm"] = float(sig_match.group(1))

    except subprocess.CalledProcessError as exc:
        err_msg = exc.stderr.strip() if exc.stderr else str(exc)
        print(f"[Warning] Could not read Wi-Fi signal metrics: {err_msg}")
    except Exception as exc:
        print(f"[Warning] Could not read Wi-Fi signal metrics: {exc}")

    return result


def get_default_gateway(os_name: str):
    """Find the IPv4 default gateway used by the current network connection."""
    try:
        if os_name == "Windows":
            output = subprocess.check_output(
                ["route", "print", "-4"], text=True, stderr=subprocess.PIPE
            )
            routes = []
            for line in output.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 5
                    and parts[0] == "0.0.0.0"
                    and parts[1] == "0.0.0.0"
                ):
                    try:
                        gateway = str(ipaddress.IPv4Address(parts[2]))
                        metric = int(parts[4])
                    except ValueError:
                        continue
                    routes.append((metric, gateway))
            if routes:
                return min(routes)[1]
        elif os_name == "Linux":
            output = subprocess.check_output(
                ["ip", "-4", "route", "show", "default"],
                text=True,
                stderr=subprocess.PIPE,
            )
            gateway_match = re.search(
                r"^\s*default\s+via\s+(\d{1,3}(?:\.\d{1,3}){3})",
                output,
                re.MULTILINE,
            )
            if gateway_match:
                return str(ipaddress.IPv4Address(gateway_match.group(1)))
        elif os_name == "Darwin":
            output = subprocess.check_output(
                ["route", "-n", "get", "default"],
                text=True,
                stderr=subprocess.PIPE,
            )
            gateway_match = re.search(r"^\s*gateway:\s*(\S+)", output, re.MULTILINE)
            if gateway_match:
                return str(ipaddress.IPv4Address(gateway_match.group(1)))
        else:
            raise ValueError(f"Unsupported operating system: {os_name}")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"[Warning] Could not determine default gateway: {exc}")
        return None

    print("[Warning] Could not determine default gateway.")
    return None


def run_ping_test(os_name: str, target: str = PING_TARGET) -> dict:
    """Measure average latency (ms) and packet loss (%) using OS-appropriate ping flags."""
    result = {"avg_latency_ms": None, "packet_loss_pct": None}

    try:
        if os_name == "Windows":
            cmd = ["ping", "-n", str(PING_COUNT), target]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            output = proc.stdout

            loss_match = re.search(r"\((\d+(?:\.\d+)?)%\s*loss\)", output)
            avg_match = re.search(r"Average\s*=\s*(\d+(?:\.\d+)?)\s*ms", output)

            if loss_match:
                result["packet_loss_pct"] = float(loss_match.group(1))
            if avg_match:
                result["avg_latency_ms"] = float(avg_match.group(1))

        else:
            cmd = ["ping", "-c", str(PING_COUNT), "-i", "0.2", target]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0 and not proc.stdout:
                cmd = ["ping", "-c", str(PING_COUNT), target]
                proc = subprocess.run(cmd, capture_output=True, text=True)

            output = proc.stdout
            loss_match = re.search(
                r"(\d+(?:\.\d+)?)%\s*packet loss", output
            )
            rtt_match = re.search(
                r"=\s*[\d.]+/([\d.]+)/[\d.]+(?:/[\d.]+)?\s*ms", output
            )

            if loss_match:
                result["packet_loss_pct"] = float(loss_match.group(1))
            if rtt_match:
                result["avg_latency_ms"] = float(rtt_match.group(1))

    except Exception as exc:
        print(f"[Warning] Ping test failed: {exc}")

    return result


def append_csv_row(filename: str, fieldnames: list, row: dict) -> bool:
    """Append a row, extending an older CSV schema while preserving existing records."""
    file_exists = os.path.isfile(filename) and os.path.getsize(filename) > 0
    if not file_exists:
        with open(filename, mode="w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(row)
        return False

    with open(filename, mode="r", newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        existing_fieldnames = reader.fieldnames
        existing_rows = list(reader)

    if existing_fieldnames == fieldnames:
        with open(filename, mode="a", newline="", encoding="utf-8") as csvfile:
            csv.DictWriter(csvfile, fieldnames=fieldnames).writerow(row)
        return True

    if not existing_fieldnames or not set(existing_fieldnames).issubset(fieldnames):
        raise ValueError(f"CSV header in {filename} does not match expected fields.")

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=os.path.dirname(os.path.abspath(filename)),
            delete=False,
        ) as csvfile:
            temporary_path = csvfile.name
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_rows)
            writer.writerow(row)
        os.replace(temporary_path, filename)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return True


def run_speedtest() -> dict:
    """Measure download and upload throughput (Mbps) via Ookla Speedtest CLI or speedtest-cli."""
    result = {
        "download_mbps": None,
        "upload_mbps": None,
        "server_id": SPEEDTEST_SERVER_ID,
    }

    speedtest_bin = shutil.which("speedtest")
    speedtest_cli_bin = shutil.which("speedtest-cli")

    try:
        if speedtest_bin:
            version_out = subprocess.check_output(
                [speedtest_bin, "--version"], text=True, stderr=subprocess.STDOUT
            )
            if "Ookla" in version_out:
                cmd = [
                    speedtest_bin,
                    "--format=json",
                    "--accept-license",
                    "--accept-gdpr",
                ]
                if SPEEDTEST_SERVER_ID:
                    cmd.extend(["--server-id", str(SPEEDTEST_SERVER_ID)])

                output = subprocess.check_output(
                    cmd, text=True, stderr=subprocess.PIPE
                )
                data = json.loads(output)
                result["download_mbps"] = round(
                    (data["download"]["bandwidth"] * 8) / 1_000_000, 4
                )
                result["upload_mbps"] = round(
                    (data["upload"]["bandwidth"] * 8) / 1_000_000, 4
                )
                result["server_id"] = data.get("server", {}).get(
                    "id", SPEEDTEST_SERVER_ID
                )
                return result
            else:
                speedtest_cli_bin = speedtest_bin

        if speedtest_cli_bin:
            cmd = [speedtest_cli_bin, "--json"]
            if SPEEDTEST_SERVER_ID:
                cmd.extend(["--server", str(SPEEDTEST_SERVER_ID)])
            output = subprocess.check_output(
                cmd, text=True, stderr=subprocess.PIPE
            )
            data = json.loads(output)
            result["download_mbps"] = round(data["download"] / 1_000_000, 4)
            result["upload_mbps"] = round(data["upload"] / 1_000_000, 4)
            result["server_id"] = data.get("server", {}).get(
                "id", SPEEDTEST_SERVER_ID
            )
            return result

        cmd = [sys.executable, "-m", "speedtest", "--json"]
        if SPEEDTEST_SERVER_ID:
            cmd.extend(["--server", str(SPEEDTEST_SERVER_ID)])
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)
        data = json.loads(output)
        result["download_mbps"] = round(data["download"] / 1_000_000, 4)
        result["upload_mbps"] = round(data["upload"] / 1_000_000, 4)
        result["server_id"] = data.get("server", {}).get(
            "id", SPEEDTEST_SERVER_ID
        )

    except subprocess.CalledProcessError as exc:
        err_msg = exc.stderr.strip() if exc.stderr else str(exc)
        print(f"[Warning] Speedtest failed: {err_msg}")
    except Exception as exc:
        print(f"[Warning] Speedtest failed: {exc}")

    return result


def get_time_slot(hour: int) -> str:
    """Map hour (8..18) to proposal time slots s1..s11 (8:00 AM - 7:00 PM)."""
    if 8 <= hour <= 18:
        return f"s{hour - 7}"
    return "outside_window"


def sanitize_filename(name: str) -> str:
    """Sanitize location string so it is safe across Windows, macOS, and Linux filesystems."""
    cleaned = re.sub(r'[\\/*?:"<>|]+', "", name).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "Unknown_Location"


def get_device_coordinates(timeout_seconds: int = 90) -> tuple[float, float]:
    """Request the device's current coordinates through the default browser."""
    completed = threading.Event()
    result = {}
    request_path = f"/{secrets.token_urlsafe(24)}"

    page = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wi-Fi data collection location</title>
<p id="status">Requesting device location. Allow location access in your browser.</p>
<script>
const statusElement = document.getElementById("status");
const endpoint = window.location.pathname;
function sendResult(payload) {
  return fetch(endpoint, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  });
}
if (!navigator.geolocation) {
  statusElement.textContent = "This browser does not support device location.";
  sendResult({error: "This browser does not support device location."});
} else {
  navigator.geolocation.getCurrentPosition(
    async (position) => {
      const response = await sendResult({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude
      });
      statusElement.textContent = response.ok
        ? "Location received. You can close this tab."
        : "Could not send location to the script.";
    },
    async (error) => {
      statusElement.textContent = `Location unavailable: ${error.message}`;
      await sendResult({error: error.message});
    },
    {enableHighAccuracy: true, timeout: 60000, maximumAge: 0}
  );
}
</script>
</html>"""

    class LocationRequestHandler(BaseHTTPRequestHandler):
        def _respond(self, status_code: int, body: str) -> None:
            encoded_body = body.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded_body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Permissions-Policy", "geolocation=(self)")
            self.end_headers()
            self.wfile.write(encoded_body)

        def do_GET(self) -> None:
            if self.path != request_path:
                self._respond(404, "Not found.")
                return
            self._respond(200, page)

        def do_POST(self) -> None:
            if self.path != request_path:
                self._respond(404, "Not found.")
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if not 0 < content_length <= 2048:
                    raise ValueError("Invalid location response size.")
                payload = json.loads(self.rfile.read(content_length))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid location response.")

                if "error" in payload:
                    result["error"] = str(payload["error"])
                    completed.set()
                    self._respond(200, "Location was not provided.")
                    return

                latitude = float(payload["latitude"])
                longitude = float(payload["longitude"])
                if (
                    not math.isfinite(latitude)
                    or not math.isfinite(longitude)
                    or not -90 <= latitude <= 90
                    or not -180 <= longitude <= 180
                ):
                    raise ValueError("Browser returned invalid coordinates.")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                result["error"] = str(exc)
                completed.set()
                self._respond(400, "Invalid location response.")
                return

            result["coordinates"] = (latitude, longitude)
            completed.set()
            self._respond(200, "Location received. You can close this tab.")

        def log_message(self, format: str, *args) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), LocationRequestHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    location_url = f"http://127.0.0.1:{server.server_port}{request_path}"

    try:
        if not webbrowser.open(location_url):
            raise RuntimeError(
                "Could not open a browser. Set a default browser and try again."
            )
        if not completed.wait(timeout_seconds):
            raise TimeoutError(
                "Timed out waiting for browser location permission. "
                "Allow location access and try again."
            )
        if "error" in result:
            raise RuntimeError(f"Could not retrieve device location: {result['error']}")
        return result["coordinates"]
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()


def coordinates_to_xy(
    latitude: float,
    longitude: float,
    origin_latitude: float,
    origin_longitude: float,
) -> tuple[float, float]:
    """Translate geographic coordinates to local east/north meters from an origin."""
    values = (latitude, longitude, origin_latitude, origin_longitude)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Latitude and longitude must be finite numbers.")
    if not all(-90 <= value <= 90 for value in (latitude, origin_latitude)):
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not all(-180 <= value <= 180 for value in (longitude, origin_longitude)):
        raise ValueError("Longitude must be between -180 and 180 degrees.")

    longitude_delta = (longitude - origin_longitude + 180) % 360 - 180
    x_coordinate = (
        EARTH_RADIUS_METERS
        * math.radians(longitude_delta)
        * math.cos(math.radians(origin_latitude))
    )
    y_coordinate = EARTH_RADIUS_METERS * math.radians(
        latitude - origin_latitude
    )
    return x_coordinate, y_coordinate


def main():
    os_name = detect_os()
    print(f"Detected OS: {os_name}")

    if ORIGIN_LATITUDE is None or ORIGIN_LONGITUDE is None:
        raise ValueError(
            "Set ORIGIN_LATITUDE and ORIGIN_LONGITUDE in data.py before running."
        )

    location = ""
    while not location:
        location = input("Enter location label: ").strip()

    while True:
        occ_raw = input("Enter estimated occupancy (N): ").strip()
        try:
            occupancy_n = int(occ_raw)
            if occupancy_n < 0:
                raise ValueError
            break
        except ValueError:
            print("Please enter a valid non-negative integer for occupancy (N).")

    latitude, longitude = get_device_coordinates()
    x_coordinate, y_coordinate = coordinates_to_xy(
        latitude,
        longitude,
        ORIGIN_LATITUDE,
        ORIGIN_LONGITUDE,
    )
    print(
        f"Device location: latitude={latitude:.6f}, longitude={longitude:.6f}"
    )
    print(
        f"Translated coordinates: x={x_coordinate:.3f} m east, "
        f"y={y_coordinate:.3f} m north"
    )

    now = datetime.now()
    date_str = now.strftime("%m-%d-%Y")
    day_of_week = now.strftime("%A")
    time_recorded_iso = now.strftime("%H:%M:%S")
    t_minutes = round(now.hour * 60 + now.minute + now.second / 60.0, 2)
    time_slot = get_time_slot(now.hour)

    print("\n[1/3] Measuring Wi-Fi signal strength (dBm)...")
    wifi_data = get_wifi_signal(os_name)
    print(
        f"      SSID: {wifi_data['ssid']} | BSSID: {wifi_data['bssid']} | Signal: {wifi_data['signal_dbm']} dBm"
    )

    gateway = get_default_gateway(os_name)
    print(
        f"[2/3] Running ping tests ({PING_COUNT} packets to the gateway "
        f"and {PING_TARGET})..."
    )
    gateway_ping_data = (
        run_ping_test(os_name, gateway)
        if gateway
        else {"avg_latency_ms": None, "packet_loss_pct": None}
    )
    ping_data = run_ping_test(os_name, PING_TARGET)
    print(
        f"      Gateway ({gateway}): {gateway_ping_data['avg_latency_ms']} ms, "
        f"{gateway_ping_data['packet_loss_pct']}% loss | "
        f"Internet ({PING_TARGET}): {ping_data['avg_latency_ms']} ms, "
        f"{ping_data['packet_loss_pct']}% loss"
    )

    print("[3/3] Running throughput test (Download / Upload Mbps)...")
    speed_data = run_speedtest()
    print(
        f"      Download: {speed_data['download_mbps']} Mbps | Upload: {speed_data['upload_mbps']} Mbps"
    )

    # Unique CSV per location, date, and day of week; appends new runs to existing file
    safe_loc = sanitize_filename(location)
    filename = f"{safe_loc}_{date_str}_{day_of_week}.csv"
    fieldnames = [
        "location",
        "latitude",
        "longitude",
        "x-coordinate",
        "y-coordinate",
        "date",
        "day_of_week",
        "time_recorded",
        "t_minutes_after_midnight",
        "time_slot",
        "estimated_occupancy_N",
        "signal_strength_dBm",
        "avg_latency_ms",
        "download_throughput_Mbps",
        "upload_throughput_Mbps",
        "packet_loss_pct",
        "gateway_avg_latency_ms",
        "gateway_packet_loss_pct",
        "ssid",
        "bssid",
        "os_detected",
        "speedtest_server_id",
    ]

    row = {
        "location": location,
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "x-coordinate": round(x_coordinate, 3),
        "y-coordinate": round(y_coordinate, 3),
        "date": date_str,
        "day_of_week": day_of_week,
        "time_recorded": time_recorded_iso,
        "t_minutes_after_midnight": t_minutes,
        "time_slot": time_slot,
        "estimated_occupancy_N": occupancy_n,
        "signal_strength_dBm": wifi_data["signal_dbm"],
        "avg_latency_ms": ping_data["avg_latency_ms"],
        "download_throughput_Mbps": speed_data["download_mbps"],
        "upload_throughput_Mbps": speed_data["upload_mbps"],
        "packet_loss_pct": ping_data["packet_loss_pct"],
        "gateway_avg_latency_ms": gateway_ping_data["avg_latency_ms"],
        "gateway_packet_loss_pct": gateway_ping_data["packet_loss_pct"],
        "ssid": wifi_data["ssid"],
        "bssid": wifi_data["bssid"],
        "os_detected": os_name,
        "speedtest_server_id": speed_data["server_id"],
    }

    file_exists = append_csv_row(filename, fieldnames, row)

    action = "Appended row to" if file_exists else "Created new log at"
    print(f"\n{action}: {os.path.abspath(filename)}")


if __name__ == "__main__":
    main()