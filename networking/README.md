# Network controller patch for the existing Pi

This replaces only the controller, its unit and timing keys in the existing private `/etc/camper-ha/network.json`. It reuses existing NetworkManager profiles, DHCP, mDNS and rescue services from HomeAssist-Camper. It is not a fresh-OS networking installer. Never run the old full Home Assistant bootstrap to apply this patch.

## Behaviour

* At controller startup, immediately try Starlink. An existing Starlink association is preserved and its LAN checked. Otherwise try the saved client profile. DHCP, gateway ARP and a 30-second stability dwell must pass. No Internet/WAN test is involved.
* Failed startup restores Camper-HA. Request scans every 60 seconds while AP is active; never disable AP merely to scan. Two fresh sightings are required before a connection trial. LastScan and the matching AP's LastSeen are verified against the new scan, so cached lists cannot count as new sightings.
* If AP-mode scanning is refused/unavailable, try a bounded association after three minutes. This temporarily interrupts local AP access. Failed trials restore AP and back off to six, then at most ten minutes. Successful fresh sightings can trigger the initial trial in approximately two minutes; failed-trial cooldown is honoured.
* If a fresh scan confirms the SSID absent, keep AP active. This design assumes Starlink broadcasts its configured 2.4 GHz SSID; hidden SSIDs are not supported by the visibility path.
* Keep stable Starlink associations; restore AP after 60 seconds of unusable LAN. Normal NM association recovery can happen within that window. Startup failure/crash still has ExecStopPost AP recovery and the existing independent rescue timer.

BLE remains independent. Scans may affect latency on the shared radio, and actual AP-mode scan support is unverified until tested on the Pi. No USB radio is required. One-minute checks apply only in AP fallback; no needless discovery while joined to Starlink.

## Install

First pull this repository, then validate without changing the network:

```bash
sudo python3 "$HOME/CamperPiZero/tools/install_network_patch.py" --check
```

Use a transient service to install so a Wi-Fi/SSH interruption cannot strand a half-applied patch:

```bash
sudo systemd-run --unit=camper-network-patch \
  /usr/bin/python3 "$HOME/CamperPiZero/tools/install_network_patch.py"
```

SSH can drop for roughly one or two minutes as the old controller restores AP and the new controller tries Starlink. Reconnect over Starlink or via Camper-HA at 192.168.42.1. No reboot is needed, so the BLE test can continue.

```bash
sudo journalctl -u camper-network-patch.service --no-pager -n 20
sudo journalctl -u camper-network.service --no-pager -n 40
```

Installer creates a root-only rollback directory under `/var/backups/camper-network/` containing the previous controller, unit and private config. No secrets are printed. If activation fails it attempts to restore and restart the previous setup. A service becoming active verifies startup completion, not all future radio behaviour.

To explicitly restore the path printed by installation, replace `BACKUP_DIRECTORY` below:

```bash
sudo systemd-run --unit=camper-network-rollback \
  /usr/bin/python3 "$HOME/CamperPiZero/tools/install_network_patch.py" \
  --rollback BACKUP_DIRECTORY
```

## Checks and outstanding hardware testing

Software tests cover immediate startup with/without a usable LAN, restarting on a good client association, scan absence/unavailability, fresh versus stale visibility, confirmation count, failed associations, cooldown, transient loss, long-term loss, AP activation retries, rescue/startup exclusion and subprocess timeout handling. Installer has static checks; actual privileged installation/rollback must be verified on the Pi. Backups contain credentials and must never enter Git.

Hardware checks remain: reboot with Starlink available and absent; AP-mode scan support; failed authentication/DHCP recovery; Starlink loss/reappearance; signal fluctuations; and BLE readings during transitions. Reboot tests should wait until the current soak run finishes. The updater does not modify working SSIDs/passwords, address ranges, NAT/routing, SSH or Bluetooth settings.

Sources: [NetworkManager Wireless D-Bus API](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.Wireless.html), [AP LastSeen property](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.AccessPoint.html), [nmcli](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nmcli.html).

Controller foundation: [HomeAssist-Camper](https://github.com/pointandyshoot/HomeAssist-Camper), retained profile UUIDs and recovery arrangement. Host commands are bounded and private network values are not logged.
