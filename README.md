# wifi-data-collection-script

This is a script used for data collection on WiFi metrics.

Run

```bash
python3 data.py
```

Then input the following when prompted:
```bash
Enter location: 
```
- location (string)
    - The name of the current location you're in

```bash
Enter estimated occupancy (N):
```
- Estimated Occupancy (N) (integer) 
    - The estimated number of people in the closed space you're in (do a headcount) 

The result will be a .csv file with file name:
`<location>_<date>_<day of the week>.csv`

A new .csv file is created with that name, unless an existing one already exists, in that case the log is appended to the existing file.