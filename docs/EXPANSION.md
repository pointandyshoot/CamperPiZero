# Mesh, weather and power-aware expansion

Requirements recorded 2026-10-16. This is a staged implementation plan, not a claim that these features are running. Establish the current dashboard's overnight memory baseline first. No additional services, dependency downloads or automatic power changes are introduced by the access-mode update. ADS-B remains deferred; no SDR is required.

## Dedicated camper Meshtastic device

Use a dedicated Seeed T1000-E over onboard BLE. Keep its address, node identity, keys and the identities of the two permitted remote radios only in private configuration. The camper's own fresh GPS position supplies the camper location; do not substitute a passing node's position. BLE pairing, reconnects, GPS age and simultaneous mesh reception with the current BLE readers require real-device tests. The Python BLE interface maintains a receive thread and must be closed cleanly. Start with a bounded node cache and event queue; retained node/location history belongs in SQLite, not an unbounded Python dictionary. Position and encounter data are private.

### Requested commands

* `!sitrep`: reply directly to an authorised requester with BLUETTI SOC and power, camper battery SOC and signed charge/discharge power, and Aranet4 temperature. Use existing cached readings to avoid a scan for every message; attach age/stale markers and say unavailable rather than inventing zero. BLUETTI telemetry currently provides input/output power, not a validated battery charge-power value: report input/output or explicitly label input-minus-output as estimated net power excluding conversion losses. SmartBat signed watts are available, with negative meaning discharge in the validated sample.
* `!ac 1`: request AC on. `!ac 0`: request AC off. These are explicit desired states, never toggles. Reject bare `!ac` and malformed/other arguments. Read the state first, do not write when it already matches, otherwise send one write and verify the acknowledgement and read-back. Record sender/packet deduplication persistently before dispatch, bound command age and rate, and never replay an uncertain request after restart. Retrying the same desired state cannot invert it again; delayed old commands must also be rejected so they cannot override a newer request. Reply with confirmed state only after read-back; otherwise say unconfirmed. No DC command: the Pi is powered from DC.

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

## Deferred power automation

Automatic AC-on is out of the current implementation scope. Do not infer plug/unplug state from AC input watts: zero input can occur while external AC is still connected. Any future automation needs a separate reviewed design that respects manual control. Software/package updates remain explicit user actions.

## Optional photo backup

Syncthing remains in the ideas pool, with no implementation scheduled. Consider a trial only after the core-plus-mesh memory test. Its official low-resource recommendations include reducing concurrent folders, hashers/copiers and incoming buffers. A Go `GOMEMLIMIT` is a soft runtime target, not a hard process RSS guarantee. Benchmark initial indexing and a realistic photo/video transfer while BLE and AC commands continue; a quiet empty-folder test is insufficient. Pause/stop photo work under memory pressure rather than compromise the control service. This release does not install Syncthing or promise a safe fixed memory budget.

A USB disk uses the Pi's only OTG data port. Keeping future RTL-SDR support means a suitably powered OTG hub, plus checking the total power supply. Keep photo data and, preferably, its index on the disk. A missing/unmounted disk must stop the backup job instead of filling the SD card's mount-point directory. Define versioning/deletion protection and another copy: a synchronised folder by itself is not a complete backup. Phone-to-Pi LAN sync can work without Starlink Internet. Check the Android client's current maintenance and background-operation support before choosing it.

Sources: [Syncthing resource tuning](https://docs.syncthing.net/users/tuning.html), [Python Meshtastic BLE API](https://python.meshtastic.org/ble_interface.html), [Meshtastic encryption](https://meshtastic.org/docs/overview/encryption/).

## Resource acceptance

Compare host available RAM, swap, service RSS/high-water RSS, worker peaks, restart count, AC latency and database growth at warm-up, overnight and under each added load. The reported initial live baseline was roughly 249 MiB available and zero swap use; this is not a capacity guarantee. `tools/diagnose.py` reads current local values without network access. Actual Pi values must be collected on the Pi; the development environment cannot monitor it remotely. Add mesh, then weather, then optional photo work separately so regressions have a clear cause.

The UI feedback is included in the combined access/UI update: one-hour history, theme controls inside Settings, Camper Battery naming, a prominent temperature chart button and Aranet CO2/temperature/humidity/pressure together on home. No new service or chart library is required.

The reported overnight run completed about 15 hours without a service restart. Available RAM was 246 MiB, coordinator RSS 28.5 MiB (high-water 29.3 MiB), and about 12 MiB swap was occupied with no swapping during the sampled interval. SQLite quick_check returned OK. This supports proceeding to mesh testing, not a guarantee of capacity for photo indexing. See [mesh setup prerequisites](MESHTASTIC.md).
