# First live release validation

Completed in the development environment:

* 44 standard-library Python tests: existing network state-machine/rollback/soak tests plus live HTTP login/access control, same-origin enforcement, AC command priority/duplicate rejection/expiry, unknown/stale values, no DC endpoint, SQLite min/max/count-weighted rollups, gaps, trusted-clock retention and offline row caps, archive query limits, process hard deadlines/reaping and installer release rollback.
* Mock BLUETTI protocol test: initial read, one AC write to register 2011, acknowledgement and read-back, DC unchanged, clean disconnect; no write if the requested state already matches.
* Python compilation and JavaScript syntax validation.
* Frontend interaction checks using an HTML-derived DOM fixture: login, live rendering, three themes, pending-command lock, stale-control lock and SVG chart gaps. This is not a browser rendering test.
* Generated systemd unit syntax checked with systemd-analyze. The development fixture used a placeholder account; installation generates the actual normal SSH username.
* Privacy scan: no real MAC, device serial/name, location, passwords or personal theme labels in public source. GitHub project/upstream usernames in source links are intentional public attribution. Private identifiers remain in installed local configuration.

Repeat Python checks with `python3 -m unittest discover -s tests -v`. Use `node --check web/app.js` if Node is available on a development computer; Node is not required on the Pi. There are no shell scripts or Compose files in the new runtime to validate.

Browser visual QA could not be completed because the development Chromium download was unavailable. The CSS/layout comes from the approved demo, but actual Android layout and hardware interaction require review on the Pi.

Still to verify on physical hardware:

1. Installer execution and systemd restrictions against the actual Pi's BlueZ/dependency environment.
2. Live monitoring, protected DC state, AC on/off acknowledgement and physical read-back through the web API.
3. At least overnight collector/database/server memory stability and AC latency under normal BLE traffic.
4. Recovery from a missing/reappearing device, failed association, Bluetooth connection loss and reboot.
5. AP-mode scan support, unavailable-Starlink boot fallback and return to Starlink. The network patch's immediate Starlink attempt was already verified on service restart, but reboot/AP transitions remain untested.
6. Deliberate offline recording/graphs/AC operation when turning Starlink off is convenient; source contains no runtime cloud requirement.
7. Consistent private backup creation and restoration to a spare SD card, with complete network provisioning.

Previous real-hardware ten-minute reconnect check: BLUETTI 8/8, SmartBat 8/8, Aranet 8/8, no failures, minimum available RAM about 223 MiB. That test used fresh readers and did not include the live web service/database. It supports this architecture but does not certify this release for unattended use.
