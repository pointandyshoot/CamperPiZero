# First live release validation

Completed in the development environment:

* 44 standard-library Python tests: existing network state-machine/rollback/soak tests plus password-free LAN HTTP access, Host validation, same-origin enforcement, AC command priority/duplicate rejection/expiry, unknown/stale values, no DC endpoint, SQLite min/max/count-weighted rollups, gaps, trusted-clock retention and offline row caps, archive query limits, process hard deadlines/reaping and installer release rollback.
* Mock BLUETTI protocol test: initial read, one AC write to register 2011, acknowledgement and read-back, DC unchanged, clean disconnect; no write if the requested state already matches.
* Python compilation and JavaScript syntax validation.
* Frontend interaction checks using an HTML-derived DOM fixture (before login removal): live rendering, three themes, pending-command lock, stale-control lock and SVG chart gaps. This is not a browser rendering test.
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


Access-mode update: all 44 Python tests and JavaScript syntax checks pass after removing login. HTTP integration checks exercise status without a cookie, rejection of an unrelated Host (GET and POST), cross-origin AC rejection, removal of the login endpoint, artwork whitelist, command conflict and missing optional hardware. Existing private configuration is preserved; a new configuration needs no dashboard hash. This update has not been applied to the user's Pi by the development environment.

The initial live hardware report showed successful sequential reads for all three devices after closing the phone's BLUETTI app, about 249 MiB available RAM, no swap used and zero service restarts. Overnight results remain pending. Mesh commands, GPS, BOM fetching, automatic AC-on and photo backup are requirements in EXPANSION.md, not implemented runtime features.


Combined UI update: the HTTP integration check now records an Aranet temperature sample and retrieves it through the one-hour history endpoint, checking 60 one-minute buckets and the recorded value. All 44 Python tests pass. JavaScript syntax is valid; a static HTML check confirms display choices occur only under Settings, the one-hour/temperature choices exist, Camper Battery naming is used and Aranet temperature/humidity/CO2 remain on Overview. Axis labels use time-of-day for both one-hour and 24-hour ranges. Actual Android rendering is still a hardware review item. No new runtime dependencies/services were added.

User-supplied overnight result (about 15 hours, before the combined update): zero service restarts, 246 MiB available RAM, coordinator RSS 28.5 MiB and high-water 29.3 MiB, 12 MiB swap occupied but no swapping in the sample, SQLite quick_check OK. Eleven BLUETTI and six SmartBat failures were logged over the boot; all readers were successful in the recent log window. One BLUETTI failure was a known phone-app conflict. Per-failure recovery times and causes were not established by that report.
