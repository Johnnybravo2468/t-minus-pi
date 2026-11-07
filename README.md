# t-minus-pi

The Raspberry Pi drives an LED departure board for the MBTA. A phone on the same network can change the station. The older HDMI dashboard is still in this repo and is described further down.

## LED board

Two chained 64x64 panels sit on an Adafruit Triple Bonnet on a Raspberry Pi 4. On boot, the `t-minus-pi-led` service starts the board as root, loads every subway line, and opens on Green-D Fenway. It asks the MBTA API for predictions and draws them about every 15 seconds. The phone page starts with the board.

The pipeline is MBTA API, then `MBTAClient`, then `transit_service`, then `StationManager` for which stop is selected, then `render_station_board`, then `RaspberryPiLEDDisplay`. Phone taps enter through the same button events as the keyboard (`src/phone_control.py`, `src/app_controller.py`).

### What the board shows

The station name is drawn in that line's color. Every Green stop includes the branch being cycled, so Fenway reads `Fenway (D)` and the D copy of a trunk stop reads `Park Street (D)`. The clock in the top right is white, in 12-hour time. Below that are inbound and outbound departures.

Green B, C, D, and E each cycle as their own line, the same way Red, Orange, and Blue do. Next and previous stay on the current line. A trunk Green stop is stored once per branch. Each copy lists every branch that serves it, so the board merges those trains.

If a refresh fails, a short fault code appears under the station name and the last good departures stay up.

| Code | Meaning |
|---|---|
| `NO LINK` | The Pi has no default route. |
| `NO DNS` | A route exists, but `api-v3.mbta.com` does not resolve. |
| `API DOWN` | The request times out, the connection fails, or the API returns a server error. |
| `RATE LIMIT` | MBTA returns HTTP 429. |
| `API KEY` | MBTA returns HTTP 401 or 403. |
| `API ERROR` | Any other fetch failure. |

A real empty schedule says `NO SERVICE` and leaves that row blank.

Bus is a separate mode. The stops live in `BUS_STOPS` in `src/line_stations.py`. Add a line there to include another stop: route id, stop id, and the name to show.

| Route | Stop | On the board |
|---|---|---|
| 47 | Park Dr @ Fenway Station (`1807`) | Park Dr at Fenway (47) |
| 47 | Brookline Ave @ The Fenway (`1806`) | Brookline Ave at Fenway (47) |
| 9 | Boylston St @ Dartmouth St, Copley (`175`) | Copley (9) |

Bus names are white, with the route number at the end. Next and previous move along that route. Next route moves to the next bus route. Pressing Subway returns to the subway stop that was on screen.

### Phone page

While the service is running, join the phone to the same network as the Pi and open:

```text
http://t-minus-pi.local:8080
```

The page shows the stop that is on the board, the line in plain words (`Green D`, `Route 47`), and a fault code when a refresh fails. Subway and Bus switch modes. The other buttons are previous, next, and next line. In bus mode those read Previous stop, Next stop, and Next route.

`t-minus-pi.local` is announced only while the program is running. If the phone cannot open that name, the numeric address printed at startup still works. On the Pi:

```bash
journalctl -u t-minus-pi-led -n 40 --no-pager
```

Look for `Phone controls:` or `Current address:`.

### SSH, stop, and update

`t-minus-pi.local` is announced only while the board program is running. When the panels are dark, SSH to the Pi's own hostname or the address from the router:

```bash
ssh johnnybravo2468@raspberrypi.local
```

The account is `johnnybravo2468`. The repo is `/home/johnnybravo2468/t-minus-pi`. If the hostname does not resolve, use the Pi's `192.168.0.x` address.

The display is the `t-minus-pi-led` service. Stopping it turns the panels off and takes the phone page down:

```bash
sudo systemctl stop t-minus-pi-led
pgrep -af src.led_display_app
```

The second command should print nothing. A leftover copy is stopped with `sudo pkill -f src.led_display_app`.

Start the board again:

```bash
sudo systemctl start t-minus-pi-led
systemctl status t-minus-pi-led
```

To run it in the SSH session with the keyboard, leave the service stopped and use:

```bash
cd /home/johnnybravo2468/t-minus-pi
sudo .venv/bin/python -m src.led_display_app --gpio-mapping regular --interactive --all-lines
```

Only one copy can drive the panels. After a keyboard session, press `Ctrl+C`, then `sudo systemctl start t-minus-pi-led` if boot startup should resume.

`git checkout` does not refresh a branch that is already on the Pi. After new code is on `main`:

```bash
cd /home/johnnybravo2468/t-minus-pi
sudo systemctl stop t-minus-pi-led
git fetch origin
git checkout main
git pull --ff-only origin main
sudo systemctl start t-minus-pi-led
```

Install the boot service the first time, or reinstall it after the unit file changes:

```bash
cd /home/johnnybravo2468/t-minus-pi
sudo cp systemd/t-minus-pi-led.service.example /etc/systemd/system/t-minus-pi-led.service
sudo systemctl daemon-reload
sudo systemctl enable --now t-minus-pi-led
```

Turn boot startup off with `sudo systemctl disable --now t-minus-pi-led`.

If a power cycle leaves the panels dark and the phone page does not open, the service is stopped or it exited. SSH in with `raspberrypi.local` (the phone name is down with the board) and check:

```bash
systemctl status t-minus-pi-led --no-pager
journalctl -u t-minus-pi-led -n 60 --no-pager
```

`Unit t-minus-pi-led.service could not be found` means the unit was never installed. `status=203/EXEC` means the installed unit still points at `/home/pi` or a Python path that is not there. Copy the unit again and enable it:

```bash
cd /home/johnnybravo2468/t-minus-pi
git fetch origin
git checkout main
git pull --ff-only origin main
sudo cp systemd/t-minus-pi-led.service.example /etc/systemd/system/t-minus-pi-led.service
sudo systemctl daemon-reload
sudo systemctl enable --now t-minus-pi-led
systemctl status t-minus-pi-led --no-pager
```

The panel refresh is noisy and can knock the Pi's onboard Wi-Fi off the air. The service waits for a connection before lighting the panels, refreshes them slower, and keeps that work off the cores that handle the network. If the link still drops, plug the Pi into the router with Ethernet, then:

```bash
ssh johnnybravo2468@raspberrypi.local
sudo systemctl stop t-minus-pi-led
```

Wait until `ping -c 3 192.168.0.1` works, then `sudo systemctl start t-minus-pi-led`. The phone and the Pi have to be on the same network.

### Notes for a later coding session

```text
Project: Johnnybravo2468/t-minus-pi, branch main.
Pi: user johnnybravo2468, repo /home/johnnybravo2468/t-minus-pi.
Hardware: Raspberry Pi 4, two chained 64x64 panels, Adafruit Triple Bonnet.
Always pass --gpio-mapping regular. Do not use user "pi" or /home/pi.

The board is systemd unit t-minus-pi-led
(systemd/t-minus-pi-led.service.example). It starts on boot as root, loads
every subway line (--all-lines), opens on Green-D Fenway, and serves
http://t-minus-pi.local:8080. The service does not use --interactive.
Stop it with: sudo systemctl stop t-minus-pi-led
Start it with: sudo systemctl start t-minus-pi-led
Never run a second copy while the service is active.

On the Pi, git checkout does not update an existing branch. Use git fetch
and git pull --ff-only. Python is .venv/bin/python. An API key, if any, is in .env.

Green B/C/D/E cycle as separate lines. Trunk stops are duplicated per branch
and merge departures. Header is the colored station name. Green stops include
the branch letter. The clock is white 12-hour time. Fault codes keep the last
good board. Bus stops are BUS_STOPS in src/line_stations.py: 47 at Park Dr @
Fenway Station (1807) and Brookline Ave @ The Fenway (1806), and 9 at Copley,
Boylston St @ Dartmouth St (175). Bus names are white with the route number.

The panel refresh can knock onboard Wi-Fi offline. The service waits for a
route, caps the refresh, and pins the panels to CPUs 2 and 3. Ethernet from
the Pi to the router is the fallback when Wi-Fi still drops. Stop the service
before expecting Wi-Fi to return.
```

## Dashboard

![t-minus-pi dashboard showing MBTA departures](docs/assets/dashboard.png)

## Overview

t-minus-pi connects to the MBTA V3 API to retrieve real-time departure predictions, vehicle positions, and service alerts across subway, commuter rail, and bus routes. The dashboard is designed to run in fullscreen kiosk mode on a Raspberry Pi connected to an HDMI display, providing an at-a-glance departure board for daily transit tracking.

Tracked stops, routes, directions, and display names are fully customizable through a simple configuration file.

## Target Hardware and Environment

- Device used: CanaKit Raspberry Pi 4 Starter PRO Kit - 4GB RAM, running Raspberry Pi OS.
- Display used: InnoView 15.6 Inch Portable Monitor, 1080p (1920x1080).
- Display Mode: Fullscreen Chromium kiosk mode with screen blanking disabled.

These are the parts used for this build, but t-minus-pi should work on similar Raspberry Pi hardware and HDMI displays.

## Hardware Setup

![t-minus-pi Raspberry Pi dashboard mounted on a wall](docs/assets/Wall_Mounted_t-minus-pi.jpeg)

The dashboard is intended for a small always-on display mounted where commute information is useful at a glance. In my setup, I changed the Raspberry Pi display to a vertical orientation and mounted the display vertically on the wall. The Raspberry Pi runs the backend locally and Chromium opens the dashboard in fullscreen kiosk mode.

## Getting Started

### Prerequisites

- Python 3.10 or higher
- MBTA API key (free at https://api-v3.mbta.com/register)

### Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd t-minus-pi
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install project dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Environment Configuration

Store secrets such as your MBTA API key in a `.env` file in the root directory. Copy the sample file:

```bash
cp .env.example .env
```

Set your API key in `.env`:

```env
MBTA_API_KEY=your_api_key_here
```

### Route Configuration

Define the routes and stops you want to display in `config.yaml`. Copy the sample configuration:

```bash
cp config.example.yaml config.yaml
```

Example configuration structure:

```yaml
server:
  host: "127.0.0.1"
  port: 8000
  refresh_seconds: 10

display:
  title: "MBTA Transit Departures"
  clock_format_24h: false
  max_predictions_per_direction: 3
  show_alerts: true
  primary_text_scale: 1.0

routes:
  # Subway Example: Red Line
  - id: "red_line"
    type: "subway"
    route_id: "Red"
    stop_id: "place-dwnxg"
    name: "Downtown Crossing - Red Line"
    directions:
      - direction_id: 1
        headsign: "Alewife (Northbound)"
      - direction_id: 0
        headsign: "Ashmont / Braintree (Southbound)"

  # Commuter Rail Example: Fitchburg Line at North Station
  - id: "fitchburg_line"
    type: "commuter_rail"
    route_id: "CR-Fitchburg"
    stop_id: "place-north"
    name: "North Station - Fitchburg Line"
    directions:
      - direction_id: 0
        headsign: "Fitchburg (Outbound)"
      - direction_id: 1
        headsign: "North Station (Inbound)"

  # Bus Example: target-specific live ETAs
  - id: "local_buses"
    type: "bus"
    stop_id: "place-andrw"
    name: "Local Buses"
    bus_targets:
      - route_id: "10"
        route_name: "10"
        stop_id: "place-andrw"
        stop_name: "Andrew"
        direction_id: 0
        direction_name: "Outbound"
      - route_id: "10"
        route_name: "10"
        stop_id: "place-andrw"
        stop_name: "Andrew"
        direction_id: 1
        direction_name: "Inbound"
      - route_id: "708"
        route_name: "CT3"
        stop_id: "place-andrw"
        stop_name: "Andrew"
        direction_id: 0
        direction_name: "Outbound"
```

Use `display.primary_text_scale` to enlarge the station names and ETA values without changing the header title or clock. The default is `1.0`; values below `0.8` are raised to `0.8`, and invalid values fall back to `1.0`. There is no enforced maximum, so choose large values carefully: values above `1.8` can cause unexpected layout behavior, including clipping, overflow, or content being pushed off screen.

### Running the Application

Start the local web server:

```bash
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000 --reload
```

The dashboard will be accessible at `http://localhost:8000`.

## Deployment

The repository includes an example systemd service for the backend and a kiosk setup script for Chromium. The bundled service template assumes the project is installed at `/home/pi/t-minus-pi` and runs as user `pi`. If your Pi uses a different user or project path, copy the example service into `/etc/systemd/system`, then edit the installed service file so `User`, `WorkingDirectory`, `ExecStart`, and `EnvironmentFile` match your device.

Install and start the backend service:

```bash
cd /home/pi/t-minus-pi
sudo cp systemd/t-minus-pi.service.example /etc/systemd/system/t-minus-pi.service
sudo nano /etc/systemd/system/t-minus-pi.service # Edit the paths in the service file, if necessary
sudo systemctl daemon-reload
sudo systemctl enable t-minus-pi
sudo systemctl start t-minus-pi
systemctl status t-minus-pi
curl http://localhost:8000/api/health
```

Configure Chromium kiosk autostart:

```bash
bash scripts/setup_kiosk.sh
sudo reboot
```

The service binds Uvicorn to `127.0.0.1:8000`, so the dashboard is only exposed on the device itself by default. The kiosk script opens `http://localhost:8000` in fullscreen Chromium after desktop login.

To temporarily exit kiosk mode, press `Alt+F4`, or switch to a text console with `Ctrl+Alt+F2`. Return to the desktop with `Ctrl+Alt+F7` or `Ctrl+Alt+F1`, depending on the Raspberry Pi OS version.

To adjust the dashboard size on the Pi, use Chromium's normal zoom controls while the dashboard is open:

```text
Ctrl++  zoom in
Ctrl+-  zoom out
```

Chromium preserves the zoom setting for the dashboard URL, so the chosen zoom level will persist across reboots.

To turn kiosk mode off:

```bash
rm ~/.config/autostart/t-minus-pi-kiosk.desktop
sudo systemctl disable --now t-minus-pi
```

To shut down the Pi while preserving kiosk startup for the next boot:

```bash
sudo poweroff
```

### Deployment Troubleshooting

If `systemctl status t-minus-pi` shows `status=203/EXEC`, systemd could not execute the command in `ExecStart`. Confirm the venv path exists and that the service uses Python from the venv:

```bash
ls -l /home/pi/t-minus-pi/.venv/bin/python
sudo systemctl cat t-minus-pi
```

If you edit the installed service file, reload systemd before restarting:

```bash
sudo systemctl daemon-reload
sudo systemctl restart t-minus-pi
sudo systemctl cat t-minus-pi
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
