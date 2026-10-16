# CamperPiZero

Local BLE camper monitoring for Raspberry Pi Zero 2 W / Raspberry Pi OS Lite ARM64. First live release: mobile dashboard, local BLE monitoring, AC control and SQLite history. Home Assistant and Docker are not required.

Confirmed short hardware tests: BLUETTI Elite 200 V2 encrypted local telemetry and AC on/off with read-back; SmartBat read-only telemetry; Aranet4 CO₂, temperature, humidity, pressure and battery from advertisements. Offline BLE operation is expected from the code but not yet physically tested. Runtime estimation, simultaneous operation, long-term memory behaviour and Wi-Fi/BLE coexistence remain under test.

## Install the live dashboard

On the already-tested Pi, run:

```bash
cd ~/CamperPiZero
git pull --ff-only
sudo python3 tools/install.py --check
sudo python3 tools/install.py
```

Open **http://homeassistant.local:8080** or **http://192.168.42.1:8080** on the camper AP. No dashboard password is required: devices on the connected LAN can view readings and control AC. The existing BLE environments and networking are preserved; no package changes/downloads occur. AC commands have priority and require read-back. DC shutdown is protected. Camper, Rose and Cyberpunk themes work locally; personal labels can be set in private configuration. No SDR is required. See [local themes and optional private artwork](docs/THEMES.md).

Read [installation and real-hardware acceptance](docs/INSTALL.md), [operation, updates and private backups](docs/OPERATIONS.md), and the [database decision](docs/DATABASE.md). Meshtastic is the next hardware-tested stage. See the [mesh, weather and power-aware expansion plan](docs/EXPANSION.md).

## Thirty-minute read-only test

Keep the working networking/SSH services and leave Docker stopped. Do not disable DC: it may power the Pi. The soak harness sends only telemetry queries, never output commands or BMS configuration changes. Close device phone apps while testing.

Existing private test layout under `~/camper-ble-test/`:

* `venv/`: BLUETTI dependencies (`bleak`, `cryptography`, `pyasn1`, `crcmod`).
* `bluetti/`: upstream Elite bridge checkout at the revision in [credits](docs/CREDITS.md).
* `bms-venv/`: `aiobmsble`.
* `aranet-venv/`: `aranet4`.

Copy `devices.example.json` to `~/camper-ble-test/devices.json`, set real MAC addresses and the full advertised Aranet name locally, and chmod it to 600. Never add it to Git.

```bash
python3 tools/ble_soak.py --config ~/camper-ble-test/devices.json --minutes 30
```

To keep running across SSH/network changes, use a transient systemd service (no boot installation):

```bash
sudo systemd-run --unit=camper-ble-soak \
  --property="User=$USER" --property=UMask=0077 \
  /usr/bin/python3 "$PWD/tools/ble_soak.py" \
  --base "$HOME/camper-ble-test" \
  --output "$HOME/camper-ble-test/results" \
  --config "$HOME/camper-ble-test/devices.json" --minutes 30
sudo journalctl -u camper-ble-soak.service -f
```

Ctrl+C exits journal viewing; the test continues. Stop the test explicitly with `sudo systemctl stop camper-ble-soak.service`. For another run after completion, `sudo systemctl reset-failed camper-ble-soak.service` if needed. New results use unique filenames.

Results are private JSONL readings and a JSON summary under `~/camper-ble-test/results/`. The journal contains device labels, timing and memory, not addresses or session keys. Report successful/failed reads, recovered failures, peak worker memory, minimum host available memory and swap. Return code 0 means every device read at least once with no failed attempts; 1 means failed attempts or no successful read; 2 means a setup error. A summary is not proof of a stable production collector.

## Reliability design

Only one BLE worker operates at a time. Normal polling is approximately once per minute per device, with two-second gaps. Failing devices back off to two/four minutes without blocking the other devices indefinitely. Each worker has a cooperative deadline and a supervisor-enforced process deadline; fresh processes reset upstream encryption state between reads. The supervisor terminates/reaps stuck workers before starting another. Aranet is selected by exact locally configured name, because address-only discovery missed it in an earlier test. Its device measurement cadence is retained; repeated advertisements are not new measurements. Old samples, invalid values and absent data are failures, not zero readings.

This reconnect-focused harness deliberately reuses the three already-tested virtual environments. It measures their costs separately and avoids dependency changes. It does not measure retained connection reliability or memory growth in a persistent BLE collector. Process start/import costs are included. BLE timeout recovery may still require BlueZ investigation on actual hardware. No network state or service configuration is changed by the harness.

## Direction

The mobile dashboard uses small local HTML/CSS/JavaScript files, prioritising AC control, BLUETTI SOC and solar input. History is a separate lightweight view. SQLite with bounded multi-resolution summaries is selected: one-minute samples for 14 days, five-minute summaries for 90 days and hourly summaries for two years, subject to real measurements. Preserve min/max and gaps; cap graph responses; retain command events separately. No additional database server.

Available [networking patch](networking/README.md): try Starlink immediately at boot; check visibility roughly every minute from Camper-HA when the driver permits AP-mode scans; validate association/DHCP/local gateway before staying on Starlink; restore AP after failed trials and back off disruptive reassociation. Driver behaviour must be tested before applying frequent scans.

Meshtastic and optional 433 MHz receiver support follow stable core monitoring. An absent SDR will not block startup. ADS-B is deferred.

See [upstream credits](docs/CREDITS.md). No private device identifiers, credentials, locations or runtime data belong in this repository.

## BLUETTI diagnostic follow-up

The initial 30-minute fresh-process run had 19 successful BLUETTI reads and two failures, while SmartBat and Aranet each completed 23 reads without failure. Minimum host available memory was about 221 MiB; this is encouraging headroom, not a persistent-process benchmark. BLUETTI recovered without intervention. One failure ended before the network patch began, so both failures cannot be attributed to that update. Exception-class-only logging could not establish the precise causes.

The revised harness allows a 12-second BLUETTI discovery window, passes the discovered BLEDevice directly to the pinned upstream client (avoiding Bleak's implicit second scan), and exits failed sessions instead of letting upstream reconnect with old encryption state. Private results now distinguish discovery, connect, handshake, read and validation stages; fixed failure codes are included without printing upstream messages or encryption keys. A follow-up ten-minute run completed 8/8 reads for each device with no failures and at least 223 MiB available RAM. The new live service still needs its own sustained hardware test. See [Bleak's client guidance](https://bleak.readthedocs.io/en/latest/api/client.html).

BLUETTI identity is selected by exact MAC address only: there is no generic model-name fallback. Set optional `bluetti_name` in the private device config to the complete name from your own scan for a second exact identity check. A mismatch aborts before creating a connection. The example identifier is deliberately fake. Real serial/name/MAC values remain on the Pi; the implementation must never select a neighbour's station just because its model matches.
