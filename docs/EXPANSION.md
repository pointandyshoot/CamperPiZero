# Mesh, weather and power-aware expansion

Requirements recorded 2026-10-16. This is a staged implementation plan, not a claim that these features are running. Establish the current dashboard's overnight memory baseline first. No additional services, dependency downloads or automatic power changes are introduced by the access-mode update. ADS-B remains deferred; no SDR is required.

## Dedicated camper Meshtastic device

Use a dedicated Seeed T1000-E over onboard BLE. Keep its address, node identity, keys and the identities of the two permitted remote radios only in private configuration. The camper's own fresh GPS position supplies the camper location; do not substitute a passing node's position. BLE pairing, reconnects, GPS age and simultaneous mesh reception with the current BLE readers require real-device tests. The Python BLE interface maintains a receive thread and must be closed cleanly. Start with a bounded node cache and event queue; retained node/location history belongs in SQLite, not an unbounded Python dictionary. Position and encounter data are private.

### Requested commands

* `!sitrep`: reply directly to an authorised requester with BLUETTI SOC and power, camper battery SOC and signed charge/discharge power, and Aranet4 temperature. Use existing cached readings to avoid a scan for every message; attach age/stale markers and say unavailable rather than inventing zero. BLUETTI telemetry currently provides input/output power, not a validated battery charge-power value: report input/output or explicitly label input-minus-output as estimated net power excluding conversion losses. SmartBat signed watts are available, with negative meaning discharge in the validated sample.
* `!ac`: toggle the inverter once. Fresh-read AC state and toggle inside the same BLE operation; do not invert a stale dashboard value. Record sender/packet deduplication persistently before dispatch, bound command age and rate, and never replay an uncertain request after restart. A duplicate packet must not cause a second toggle. Reply with confirmed state only after read-back; otherwise say unconfirmed. Optional `!ac on` / `!ac off` can provide explicit alternatives. No DC command: the Pi is powered from DC.

Only the two locally configured remote radios may command the camper. Validate the appropriate authenticated encrypted direct-message mechanism for their actual firmware, and pin peer public keys where supported. A sender-number allowlist or the default shared channel alone is not strong sender authentication. Reject commands when identity cannot be verified. Dashboard login removal does not change this requirement. Meshtastic channel/direct-message security and local BLE bonding are different layers.

Acceptance: authorised request/reply, unauthorised rejection, retransmission duplicates, two rapid commands, stale cached readings, uncertain AC result, restart deduplication, missing radio, and mesh reception during all three existing readers. AC priority must not interrupt a worker midway through a BLE session.

## GPS-selected BOM forecast

After a stable Starlink association, aim to fetch within 30–60 seconds once Internet access and a fresh camper GPS fix are available. A working Starlink LAN does not prove Internet service. Never require weather success to retain the LAN connection, serve the dashboard or record BLE readings. When offline, preserve the last forecast with its fetch time, forecast issue/valid times, location and a visible stale/offline label. An old forecast must never produce a current all-clear.

Use a small server-side cached response and bounded request/response sizes and deadlines. Refresh about hourly while online, sooner after a meaningful location change; retry failures with backoff rather than continuously polling. Do not load a radar map, browser automation or another database server. Skip a location fetch when GPS is absent/stale and make that state visible. Keep coordinates/cache off public Git; requesting location-specific weather necessarily sends a location or location identifier to the provider.

Home view: a compact next-12-hours card showing rain timing/chance/amount where supplied, peak forecast wind and gust in km/h, plus highlighted rain/wind periods. Thresholds are locally configurable advisory settings, not official severe-weather warnings or an awning safety rating. Preserve unknown fields. Do not sum hourly rain probabilities into a 12-hour probability or label the highest hourly chance as a whole-window probability. Obtain actual hourly coverage before claiming the full next 12 hours; a daily summary cannot provide precise timing.

### Source decision still to validate

BOM's official app documents hourly rain, wind and gust forecasts for 72 hours. Its public data-services catalogue documents forecast products and warning feeds, but does not establish a stable, documented public hourly JSON API contract. Prefer official supported products where their granularity permits the requested display. The upstream `weather-au` project documents a reverse-engineered `api.weather.bom.gov.au` interface and explicitly cautions about future availability; this is a research lead, not a dependency adopted by this project. Validate current access, fields, coverage, terms and attribution before implementing the adapter. Do not relabel another provider's BOM-model output as BOM's official town forecast. If only coarse products are accessible, display that limitation instead of manufactured hourly alerts.

Sources checked:

* [BOM official app capabilities](https://www.bom.gov.au/bom-weather-app)
* [BOM weather data services](https://www.bom.gov.au/catalogue/data-feeds.shtml)
* [BOM public products](https://www.bom.gov.au/catalogue/anon-ftp.shtml)
* [BOM warning RSS](https://www.bom.gov.au/rss/)
* [weather-au upstream API research](https://github.com/tonyallan/weather-au)

## Optional AC-on when external AC power is detected

Not enabled by this release. Positive measured AC input is evidence of incoming power, but zero input does not prove that the plug was removed: charging can pause or the battery can be full. No validated separate mains-present field has been identified in the tested reader. Do not build a plug/unplug detector from wattage alone.

For an initial optional policy: require sustained positive input over multiple fresh samples, issue at most one AC-on request per armed arrival, verify state, and respect a manual AC-off override. Do not repeatedly turn it back on because input is still present; do not automatically switch it off when input falls. If a real presence signal is unavailable, require explicit re-arming rather than infer a new arrival from zero watts. Document which loads will energise. Solar surplus alone should not trigger inverter changes in the first version.

Useful power-available jobs: charge phones/cameras/drone or spare mesh radios; run a scheduled photo-backup session; upload an existing private backup while Starlink is online. Inverter-fed chargers need hardware or user-controlled connections: telemetry cannot independently switch individual plugged-in appliances. Software/package updates remain explicit user actions. No automatic firmware upgrades or BMS setting changes.

## Optional photo backup

Trial Syncthing only after the core-plus-mesh memory test. Its official low-resource recommendations include reducing concurrent folders, hashers/copiers and incoming buffers. A Go `GOMEMLIMIT` is a soft runtime target, not a hard process RSS guarantee. Benchmark initial indexing and a realistic photo/video transfer while BLE and AC commands continue; a quiet empty-folder test is insufficient. Pause/stop photo work under memory pressure rather than compromise the control service. This release does not install Syncthing or promise a safe fixed memory budget.

A USB disk uses the Pi's only OTG data port. Keeping future RTL-SDR support means a suitably powered OTG hub, plus checking the total power supply. Keep photo data and, preferably, its index on the disk. A missing/unmounted disk must stop the backup job instead of filling the SD card's mount-point directory. Define versioning/deletion protection and another copy: a synchronised folder by itself is not a complete backup. Phone-to-Pi LAN sync can work without Starlink Internet. Check the Android client's current maintenance and background-operation support before choosing it.

Sources: [Syncthing resource tuning](https://docs.syncthing.net/users/tuning.html), [Python Meshtastic BLE API](https://python.meshtastic.org/ble_interface.html), [Meshtastic encryption](https://meshtastic.org/docs/overview/encryption/).

## Resource acceptance

Compare host available RAM, swap, service RSS/high-water RSS, worker peaks, restart count, AC latency and database growth at warm-up, overnight and under each added load. The reported initial live baseline was roughly 249 MiB available and zero swap use; this is not a capacity guarantee. `tools/diagnose.py` reads current local values without network access. Actual Pi values must be collected on the Pi; the development environment cannot monitor it remotely. Add mesh, then weather, then optional photo work separately so regressions have a clear cause.

Pending UI feedback remains recorded separately: one-hour history, theme controls in settings/footer, Camper Battery naming, prominent temperature chart option and CO2/temperature/humidity together on home. These changes remain paused until the overnight baseline is reviewed.
