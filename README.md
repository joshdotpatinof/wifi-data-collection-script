# wifi-data-collection-script

This is a script used for data collection on WiFi metrics.

Run

```bash
python3 data.py
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

Packet loss and latency are recorded for two destinations:
- `gateway_avg_latency_ms` and `gateway_packet_loss_pct` measure the local
  connection to the default gateway, which helps identify Wi-Fi/local-network
  problems.
- `avg_latency_ms` and `packet_loss_pct` measure the end-to-end path to
  `8.8.8.8`, which better reflects internet connectivity.

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