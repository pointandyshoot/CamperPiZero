# CamperPiZero: local history decision

Decision date: 12 October 2026 (Australia/Brisbane)
Status: selected for first implementation; hardware benchmarking outstanding.

## Decision

Use Python's built-in SQLite database support, with indexed numeric samples and small precomputed summary tables. No separate database daemon, Docker, Grafana or cloud requirement. This choice replaces the Home Assistant Recorder design for the standalone collector; it does not require running Home Assistant.

The user approved the mobile mock-up as the direction for the first Pi dashboard: AC output control first, BLUETTI SOC second, solar input third. Home-screen charts are optional; detailed history stays on its own screen. Reuse plain HTML/CSS/JavaScript and compact browser-rendered SVG charts.

## Alternatives considered

- RRDtool: built-in time-based consolidation, fixed-size archives, average/minimum/maximum/last aggregation. Strong numeric-history option. Not chosen because events, future node encounters, GPS and command records still need a different store; schema/interval constraints add complexity.
- Whisper (Graphite): Python file-based time-series database with fixed-size archives and multiple retention resolutions; retrieval selects an archive covering the requested period. Can be used without deploying the full Graphite stack. A credible alternative to RRDtool and potentially the database the user remembers. Not chosen because each metric is a separate archive file, aggregation is configured per series, and non-numeric/event records need another store.
- InfluxDB: purpose-built time-series server; v2 supports scheduled downsampling tasks. Not chosen: unnecessary service, provisioning and operational overhead for a handful of devices; different generations have different APIs/rollup features. No measured idle-memory figure is asserted here.
- TimescaleDB: PostgreSQL-based continuous aggregates and retention. Strong feature match but a separate PostgreSQL deployment is unnecessary for this constrained local appliance.
- DuckDB: embedded analytical SQL engine, excellent for larger analytical scans. Not selected for this small operational recorder; additional dependency and analytical memory behaviour need more management. Its documentation suggests 125 MB per thread as an analytical sizing rule, not an idle-memory minimum.
- TinyFlux: Python CSV-based time-series store with append-only writes and indexing. Not chosen over SQLite's indexed SQL, transactions and recovery facilities; would still require implementing retention and rollups.
- VictoriaMetrics: efficient single-node time-series server. Native age-based multi-level storage downsampling is Enterprise; OSS streaming aggregation is a different feature. Additional service and event-store complexity bring little benefit here.
- TickTockDB: lightweight C++ time-series server whose upstream explicitly targets small Raspberry Pis. A credible low-resource alternative, not dismissed as inherently too heavy. Still adds a service/build/update path plus a separate event store; SQLite wins on total system simplicity for this workload.

## Planned history policy (adjust after measurements)

- Record numeric samples at roughly one-minute resolution for 14 days. Device polling may be faster when needed for responsive controls; UI freshness and history cadence are separate.
- Keep five-minute summaries for 90 days, hourly summaries for two years.
- Summary rows retain count, sum/weighted totals where applicable, minimum, maximum, last value and coverage. Do not average averages without weights.
- Chart endpoint selects an appropriate tier and returns at most about 400 time buckets per metric, with optional min/max envelopes; browser renders charts.
- Store output command requests/results and actual state changes as events, separately from periodic telemetry.
- Never write missing samples as zero or silently carry stale readings across outages. Mark gaps and last-success times.
- Store timestamps in UTC, display in the configured local timezone. Offline cold boots without RTC may have an unreliable clock: retain boot/session and monotonic timing metadata and expose clock uncertainty; avoid destructive retention on an untrusted clock.
- Integrate power into energy only across valid bounded sample gaps. Do not label input-minus-output as true battery power; conversion losses are excluded.
- Keep threshold-duration/energy summaries separately if exact historical totals must survive raw-data expiry. Min/max/average alone cannot recover time above a threshold.
- Use batched transactions, bounded cache, safe checkpoint/retention behaviour, bounded event/node tables and reuse freed database pages. No routine full VACUUM or swap-heavy analytics. Define file-size guard and benchmark before committing final storage limits.
- Verify rollup correctness, retention, restart/power interruption recovery, chart query latency, RSS and database growth on the actual Pi. No specific memory or disk figure is promised until measured.

## Sources checked

- https://www.sqlite.org/whentouse.html
- https://oss.oetiker.ch/rrdtool/doc/rrdtool.en.html
- https://graphite.readthedocs.io/en/stable/whisper.html
- https://docs.influxdata.com/influxdb/v2/process-data/common-tasks/downsample-data/
- https://docs.timescale.com/use-timescale/latest/data-retention/data-retention-with-continuous-aggregates/
- https://duckdb.org/docs/stable/guides/performance/environment.html
- https://tinyflux.readthedocs.io/en/latest/internals.html
- https://docs.victoriametrics.com/victoriametrics/
- https://docs.victoriametrics.com/victoriametrics/stream-aggregation/
- https://github.com/ytyou/ticktock

## Next hardware test

Confirm the host's Python/ARM64 environment, Bluetooth service/rfkill/controller status, then briefly scan for the three BLE devices. No Internet is required for this readiness test. Home Assistant/Docker remain stopped. Do not require re-pairing or change the working networking configuration. Then create an isolated Python virtual environment for a read-only BLUETTI protocol test before trying AC/DC writes.

## First release implementation

SQLite raw points, independent five-minute/hourly aggregates, command events and per-service-session observation metadata are implemented. Charts report observation-count-weighted means, min/max and explicit empty buckets. They do not yet compute time-weighted energy/threshold duration or coverage percentages. Observation metadata retains session identity, elapsed monotonic time, observed wall-clock time and clock confidence; uncertain cross-boot timestamps cannot yet be corrected in the chart UI. Time-based retention runs hourly only after systemd-timesyncd confirms this boot's clock; insertion-order row caps also limit storage without a trusted clock. See OPERATIONS.md for current semantics and hardware acceptance requirements.
