import csv
from datetime import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys

# ==============================================================================
# CONTROLLED EXPERIMENTAL PARAMETERS (Keep constant across all runs)
# ==============================================================================
PING_TARGET = "8.8.8.8"  # Fixed latency test destination
PING_COUNT = 30  # Fixed packet count (3.33% packet loss resolution)
SPEEDTEST_SERVER_ID = (
    "70709"  # Locked to your verified server ID (or set to None for auto)
)


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


def run_ping_test(os_name: str) -> dict:
    """Measure average latency (ms) and packet loss (%) using OS-appropriate ping flags."""
    result = {"avg_latency_ms": None, "packet_loss_pct": None}

    try:
        if os_name == "Windows":
            cmd = ["ping", "-n", str(PING_COUNT), PING_TARGET]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            output = proc.stdout

            loss_match = re.search(r"\((\d+(?:\.\d+)?)%\s*loss\)", output)
            avg_match = re.search(r"Average\s*=\s*(\d+(?:\.\d+)?)\s*ms", output)

            if loss_match:
                result["packet_loss_pct"] = float(loss_match.group(1))
            if avg_match:
                result["avg_latency_ms"] = float(avg_match.group(1))

        else:
            cmd = ["ping", "-c", str(PING_COUNT), "-i", "0.2", PING_TARGET]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0 and not proc.stdout:
                cmd = ["ping", "-c", str(PING_COUNT), PING_TARGET]
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


def main():
    os_name = detect_os()
    print(f"Detected OS: {os_name}")

    location = ""
    while not location:
        location = input("Enter location: ").strip()

    while True:
        occ_raw = input("Enter estimated occupancy (N): ").strip()
        try:
            occupancy_n = int(occ_raw)
            if occupancy_n < 0:
                raise ValueError
            break
        except ValueError:
            print("Please enter a valid non-negative integer for occupancy (N).")

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

    print(f"[2/3] Running ping test ({PING_COUNT} packets to {PING_TARGET})...")
    ping_data = run_ping_test(os_name)
    print(
        f"      Avg Latency: {ping_data['avg_latency_ms']} ms | Packet Loss: {ping_data['packet_loss_pct']}%"
    )

    print("[3/3] Running throughput test (Download / Upload Mbps)...")
    speed_data = run_speedtest()
    print(
        f"      Download: {speed_data['download_mbps']} Mbps | Upload: {speed_data['upload_mbps']} Mbps"
    )

    # Unique CSV per location, date, and day of week; appends new runs to existing file
    safe_loc = sanitize_filename(location)
    filename = f"{safe_loc}_{date_str}_{day_of_week}.csv"
    file_exists = os.path.isfile(filename) and os.path.getsize(filename) > 0

    fieldnames = [
        "location",
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
        "ssid",
        "bssid",
        "os_detected",
        "speedtest_server_id",
    ]

    row = {
        "location": location,
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
        "ssid": wifi_data["ssid"],
        "bssid": wifi_data["bssid"],
        "os_detected": os_name,
        "speedtest_server_id": speed_data["server_id"],
    }

    with open(filename, mode="a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    action = "Appended row to" if file_exists else "Created new log at"
    print(f"\n{action}: {os.path.abspath(filename)}")


if __name__ == "__main__":
    main()