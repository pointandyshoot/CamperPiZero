# Operation, updates, backups and recovery

## What is recorded

BLUETTI: SOC, solar/DC input, AC input, AC output, DC output and AC/DC states in the current view. Runtime is deliberately hidden until its wire encoding is validated. Net power is input minus output, excluding inverter/conversion losses.

SmartBat: SOC, voltage, signed current and power, temperature, cycles, BMS problem status and reported runtime. It is read-only. Cell detail and remaining/design capacity have not yet been validated for this unit and are not invented. Aranet: CO₂, temperature, humidity, pressure, battery, measurement interval and age. It is read from advertisements; repeated advertisements are not counted as new measurements. Aranet Smart Home integration must be enabled.

Numeric history stores real successful observations, not interpolated zeroes. One-minute-class polling is not an exact one-minute sampling guarantee. Five-minute and hourly archives accumulate count, sum, min/max and latest value. Charts average sums/counts, never average averages, and include min/max ranges. Raw numeric readings retain 14 days; five-minute buckets 90 days; hourly buckets two years; command events 90 days. Charts are capped at 400 buckets. Actual observation count is displayed; it is not a time-weighted energy estimate. Energy integration/threshold-duration calculations are deferred until coverage semantics are validated. SQLite uses a 2 MiB cache, WAL and normal synchronisation (a power cut can lose recent transactions); take backups and use clean shutdown. No periodic full VACUUM is used. SQLite can reuse freed pages; file size need not shrink after purge.

Freshness is measured with the monotonic clock. Offline wall-clock timestamps are marked uncertain until systemd-timesyncd synchronises this boot, and time-based retention is disabled while time is uncertain. This avoids deleting history because a wrong clock jumped forwards. Independent insertion-order row caps (750,000 raw values, 1,200,000 summary buckets, 100,000 observations and 10,000 commands) still bound storage when the clock remains uncertain; reaching a cap shortens history coverage. A Pi without an RTC can have uncertain chronological ordering across offline boots; charts cannot correct that retrospectively. History remains recorded. For dependable off-grid absolute timestamps, a future RTC/GPS clock source is preferable. The current clock indicator is specific to systemd-timesyncd.

Only one BLE worker runs at a time. BLUETTI polling delay is 60 seconds after a completed read, SmartBat 90, Aranet 60; failures back off up to five minutes. Two-second disconnect gaps allow BlueZ to settle. Every operation gets fresh encryption state and a hard process deadline. A failed device does not stop recording others. The web server stays responsive during BLE work. Last valid values remain visible with stale/retry indicators. Full-name and exact-MAC checks stop accidental selection of a neighbouring BLUETTI. This is identity checking, not cryptographic authentication against malicious impersonation.

## Inspect and stop

```bash
sudo systemctl status camper-zero --no-pager
sudo journalctl -u camper-zero -b --no-pager -n 40
free -h
sudo du -h /var/lib/camper-zero/history.sqlite3*
sudo systemctl stop camper-zero
sudo systemctl start camper-zero
```

The service's entire process group is stopped cleanly, with forced termination after its deadline. Do not run standalone BLE tests while it is active. Stop it first, then restart afterwards. Journal logs contain generic device labels/status, not BLE identifiers, tokens or upstream encryption messages. OS journald retention remains an OS setting; use `SystemMaxUse=32M` in a local journald drop-in if persistent journalling is enabled. No disk swap changes are made by this installer.

## Explicit updates

Update OS packages separately when stable power and Starlink are available. Network packages can drop SSH; the network controller should recover. Check `sudo dpkg --audit` when reconnected. Do not launch a second apt operation while one is still active.

For this application: `cd ~/CamperPiZero`, `git pull --ff-only`, run tests with `python3 -m unittest discover -s tests`, then `sudo python3 tools/install.py`. The installer preserves config/password/database and saves the previous code/unit privately under `/var/backups/camper-zero/`. Never update dependency packages automatically while travelling. To trial dependency updates, back up first, stop the service, save each environment's pip freeze, update one environment explicitly and run its read/soak test before resuming. BLUETTI source must retain the tested revision unless a reviewed change updates the compatibility gate. This project does not update Docker, Home Assistant or old custom integrations; that disabled stack remains separate.

For application rollback: stop `camper-zero`; restore `/opt/camper-zero` from the chosen backup's `code/` and `/etc/systemd/system/camper-zero.service` from that backup; run `sudo systemctl daemon-reload`, then start. Check the backup exists before moving directories. The current private config and history are compatible with this release. Failed activation during installation automatically attempts restoration of the previous code/unit. Saved dependency freezes describe versions, not copies of wheels; cache wheels separately before travelling if offline rebuilding is required.

## Private backup

```bash
sudo python3 tools/backup.py /var/backups/camper-private-backup.tar.gz
```

Choose a new filename each time. SQLite's backup API takes a consistent database snapshot while recording continues. The archive includes installed code, private app/network config, NetworkManager profiles, current app/network unit files, network controller code and the three dependency freezes. **It contains passwords and private identifiers. Copy it off the Pi; never upload it to the public repository.** Store on an encrypted computer/drive. The old Home Assistant configuration is not included; this release does not use its cloud keys.

To rebuild: flash OS with the proven SSH/Wi-Fi provisioning; clone this public repo; extract the private archive into a temporary directory on the Pi; recreate BLE environments from saved freezes and the pinned BLUETTI checkout; restore private app/network configs with their original permissions. The backup includes camper-prefixed activation/rescue units and helpers as well as the controller. Inspect their ExecStart paths and restore the corresponding scripts/configuration before enabling them; additional locally installed helpers outside these paths need a separate copy. This is a configuration backup, not a full OS image. Run the appropriate networking installer before enabling the controller, and run this dashboard installer. Restore `history.sqlite3` while `camper-zero` is stopped, chown it to the service user, chmod 600, and start. Do not extract an archive blindly over a running OS. Keep a full SD-card image once networking and this release pass their real hardware acceptance.

## Known scope

No RTL-SDR is accessed and no 433 MHz process runs, so an absent receiver cannot crash startup. Meshtastic, GPS/node encounter history and authenticated mesh commands are planned for a separate first-device test. ADS-B is deferred. A persistent BLUETTI connection may improve AC latency later; this release intentionally uses the proven fresh-session mechanism. Offline BLE reads/AC are supported by the dependency code and require no cloud service, but a deliberate physical offline test is still outstanding.
