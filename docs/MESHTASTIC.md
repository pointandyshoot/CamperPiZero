# Meshtastic setup: next hardware stage

Status: planned, not a dependency or running service in this release. The combined dashboard update works without a radio. Automatic AC-on and Syncthing are deferred. GPS-selected BOM weather follows a verified local mesh connection.

## What to prepare

Use one Seeed T1000-E dedicated to the camper and two remote T1000-E devices paired to the phones. No extra USB Bluetooth adapter or MQTT server is needed for the intended BLE design; resource use and shared-adapter reliability still need testing.

Before changing firmware or settings, record locally from the phone app:

1. Firmware version and hardware model for each radio.
2. Which radio is the camper device; its displayed node ID and Bluetooth name/address if available.
3. The two permitted remote node IDs and public keys for verification against the physical devices. Public keys are not secret keys, but still keep device identifiers out of this public repository.
4. LoRa region and modem preset for all three devices, and confirmation they already exchange messages. Use the correct Australian regional setting and compatible radio/channel parameters. Do not reset working settings merely to begin this test.
5. Whether the camper device has a current GPS fix and Bluetooth enabled; note its BLE pairing method/PIN locally.

Do not post private keys, channel QR codes/URLs, channel keys or BLE PINs in GitHub issues or commits. Preserve a private radio configuration/key backup before any firmware update. Firmware version matters: validate the actual supported authenticated direct-message path rather than assume all versions expose identical security fields to Python.

## First connection test

After reviewing those details, prepare a separate `mesh-venv` with a selected/pinned upstream Python Meshtastic version, leaving the three proven BLE environments unchanged. Supply the exact camper BLE address locally; never connect to the first discovered radio. Pair/bond through BlueZ if required by the configured firmware. Close/disconnect the camper radio's phone-app BLE session so the Pi can connect; the remote radios remain connected to their phones.

The first probe must be read-only: connect, obtain local radio identity, firmware and GPS/fix age, receive a harmless direct message from a remote radio, then close cleanly. Bound discovery, connection and process duration. Do not print keys or unrestricted protocol debug output. Only after that passes should a persistent receive connection be tested while the existing BLE service polls all three sensors. Measure RAM, recovery, missed messages and AC latency; stop the new mesh worker if it disrupts core monitoring. No radio setting or BLUETTI output should be changed by the probe.

Implementation follows the proven probe: reconnect/backoff, bounded events/nodes, private SQLite position/encounter history, verified peer identities and packet authentication, direct replies, command expiry, persistent duplicate rejection, priority integration with the existing single-operation BLE scheduler, then the two commands below. A LoRa delivery acknowledgement is not confirmation of BLUETTI state.

## Command contract

Send these as direct messages to the camper node from either permitted radio:

| Command | Result |
| --- | --- |
| `!sitrep` | BLUETTI SOC and input/output or estimated net power; Camper Battery SOC and signed charge/discharge power; Aranet4 temperature. Mark age/stale/unavailable data. |
| `!ac 1` | Set AC on; read back and report confirmation. |
| `!ac 0` | Set AC off; read back and report confirmation. |

Bare `!ac`, toggles and other arguments are rejected. Repeating `!ac 1` means on again, never off. Existing BLUETTI control already reads before writing and avoids a write when the desired state matches. The mesh dispatcher still needs its own deduplication, expiry and ordering handling: a delayed old `!ac 0` must not override a later request. No queued radio command is replayed after restart. DC is never writable because it supplies this Pi.

Verify both remote devices' public keys through the physical/app setup, pin their identities locally, and require the validated authenticated encrypted message mode. A public channel plus sender-number allowlist is insufficient. Do not substitute Meshtastic remote-admin privileges for application command authorisation: these commands belong to the Pi application, not the radio's remote administration API.

## References and credit

* [Meshtastic Python upstream](https://github.com/meshtastic/python), [BLE API](https://python.meshtastic.org/ble_interface.html): intended connection library; not installed by this dashboard installer yet. Clean disconnect is explicitly important in its Linux BLE implementation.
* [Meshtastic encryption](https://meshtastic.org/docs/overview/encryption/): distinguishes channel encryption, direct-message authentication and peer-key verification. Confirm behaviour against the chosen installed firmware/library versions.

Keep upstream licensing/notices when adopting or distributing a dependency. Add the tested version to the private dependency lock/backup and update CREDITS.md when it becomes a runtime dependency.
