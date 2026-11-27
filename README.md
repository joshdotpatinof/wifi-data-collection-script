# wifi-data-collection-script

This is a script used for data collection on WiFi metrics.

## Requirements

Install these dependencies before running the script:

- Python 3
- A web browser with location services enabled
- `ping` (included with Windows, Linux, and macOS)
- A speed test tool:
  - Recommended: `speedtest-cli`
  - Ookla's `speedtest` command is also supported
- Wi-Fi/network tools used by the script:
  - Windows: built-in `netsh`
  - Linux: `iw` or `nmcli` for Wi-Fi details, and `iproute2` (`ip`) for the
    default gateway
  - macOS: built-in `system_profiler` and `route`

Install `speedtest-cli` with Python:

```bash
# Linux or macOS
python3 -m pip install --user speedtest-cli

# Windows
py -m pip install --user speedtest-cli
# or
python -m pip install --user speedtest-cli
```

On Linux, `iw` and `iproute2` can be installed with the distribution package
manager. For Debian/Ubuntu:

```bash
sudo apt update
sudo apt install iw iproute2
```

Verify the required tools are available:

```bash
python3 --version
ping -c 1 8.8.8.8
speedtest-cli --version
# Linux only
iw dev
ip route show default
```

On Windows, use `speedtest-cli --version` and `ping -n 1 8.8.8.8` to verify
the commands. Ookla's Speedtest CLI can be used instead of `speedtest-cli`.
If neither a `speedtest` nor `speedtest-cli` command is available, the script
still tries `python -m speedtest`; otherwise download and upload throughput
measurements are left blank and the script displays a warning.

Run from the repository directory:

```bash
# Linux or macOS
python3 data.py

# Windows (use whichever command is available)
py data.py
# or
python data.py
```

When prompted, enter:
```bash
Enter location label:
```
- location label (string)
    - A name for the place, used in the CSV and output filename

```bash
Enter estimated occupancy (N):
```
- Estimated Occupancy (N) (integer) 
    - The estimated number of people in the closed space you're in (do a headcount) 

The result will be a .csv file with file name:
`<location>_<date>_<day of the week>.csv`

A new .csv file is created with that name, unless an existing one already exists, in that case the log is appended to the existing file.

## CSV columns

The CSV contains the following measurements and context for each collection:

| Column | Description | Possible values / range |
| --- | --- | --- |
| `location` | Label entered by the user to identify the place; it does not determine the device coordinates. | Any non-empty text |
| `latitude` | Device latitude reported by the browser's location service. | -90 to 90 degrees; blank if location is unavailable |
| `longitude` | Device longitude reported by the browser's location service. | -180 to 180 degrees; blank if location is unavailable |
| `x-coordinate` | East/west position in meters relative to the configured origin; east is positive. | No fixed range; depends on the device and origin |
| `y-coordinate` | North/south position in meters relative to the configured origin; north is positive. | No fixed range; depends on the device and origin |
| `date` | Local date when the row was recorded. | `MM-DD-YYYY` |
| `day_of_week` | Local day of the week when the row was recorded. | `Monday` through `Sunday` |
| `time_recorded` | Local time when the row was recorded. | `HH:MM:SS` (24-hour clock) |
| `t_minutes_after_midnight` | Time of day expressed as minutes after local midnight. | 0 to less than 1440 |
| `time_slot` | Hour-based collection slot. | `s1`–`s8` for 9:00 AM–4:59 PM; `outside_window` at other hours |
| `estimated_occupancy_N` | User's estimated headcount for the space. | Non-negative integer |
| `signal_strength_dBm` | Wi-Fi signal strength reported by the operating system; values closer to 0 generally indicate a stronger signal. | Typically about -100 to 0 dBm; hardware-dependent, or blank if unavailable |
| `avg_latency_ms` | Average ping round-trip time to `8.8.8.8`, reflecting the path to the internet. | 0 ms or higher; no fixed upper bound, or blank if unavailable |
| `download_throughput_Mbps` | Measured download data rate from the speed test. | 0 Mbps or higher; no fixed upper bound, or blank if unavailable |
| `upload_throughput_Mbps` | Measured upload data rate from the speed test. | 0 Mbps or higher; no fixed upper bound, or blank if unavailable |
| `packet_loss_pct` | Percentage of ping packets lost when testing `8.8.8.8`. | 0–100%; with 30 packets, approximately 3.33 percentage-point increments |
| `gateway_avg_latency_ms` | Average ping round-trip time to the local default gateway; helps identify Wi-Fi/local-network problems. | 0 ms or higher; no fixed upper bound, or blank if unavailable |
| `gateway_packet_loss_pct` | Percentage of ping packets lost when testing the local default gateway. | 0–100%; with 30 packets, approximately 3.33 percentage-point increments; blank if no gateway is found |
| `ssid` | Name of the connected Wi-Fi network. | Network-provided text; may be blank if unavailable |
| `bssid` | MAC address identifying the connected Wi-Fi access point. | Usually six hexadecimal byte pairs; may be blank if unavailable |
| `os_detected` | Operating system used for collection. | `Windows`, `Linux`, or `Darwin` (macOS) |
| `speedtest_server_id` | Identifier of the server used by the speed test. | Server-provided identifier; may be blank if unavailable |

Latency and packet loss are measured separately for the internet destination
(`8.8.8.8`) and the local default gateway. The former reflects internet
connectivity; the latter helps identify local Wi-Fi/network problems. Ranges
above describe expected or valid values; some measurements have no fixed
maximum, and unavailable measurements are left blank.

If a gateway cannot be determined, its measurements are left blank. When new
columns are added to an existing CSV, earlier rows are preserved and the new
columns are left blank for those rows.

The CSV records the device's `latitude` and `longitude`, plus `x-coordinate`
and `y-coordinate` in meters (east is positive x; north is positive y). Before
measurement, the script opens a local page in the default browser. Allow the
browser's location permission to read the device's current position. The
location label you enter is only used to identify the place in the CSV and
filename; it is not used to calculate coordinates.

The script translates the device coordinates to a local plane relative to
`ORIGIN_LATITUDE` and `ORIGIN_LONGITUDE` in `data.py`. Set both origin values
in decimal degrees before running; the origin is (0, 0). This local
equirectangular approximation is intended for locations relatively near the
origin. The browser and operating system must have location services enabled
and permission granted. This location workflow does not use Google Maps
Geocoding API or require an API key.