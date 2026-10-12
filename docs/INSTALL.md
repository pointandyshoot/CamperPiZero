# First live version

This version runs the three proven readers, a local mobile dashboard, authenticated AC control and SQLite history. There is no Docker, Home Assistant, MQTT broker or external database service. The existing NetworkManager controller remains responsible for Wi-Fi. No SDR or Meshtastic is required or opened by this release. Meshtastic integration is a subsequent hardware-tested stage.

## On the already-tested Pi

Keep the old Home Assistant/Docker stack stopped and close the BLUETTI/SmartBat phone applications. This installs using the three existing working virtual environments, without downloading or changing their packages. The full advertised BLUETTI name must be present in the private `~/camper-ble-test/devices.json`; it is checked along with the MAC before connecting. Do not use a neighbour's model name as a substitute.

```bash
cd ~/CamperPiZero
git pull --ff-only
sudo python3 tools/install.py --check
sudo python3 tools/install.py
```

The last command asks for a new dashboard password, at least 12 characters, twice. It does not ask again on a repeat install. It stops the two known soak services before starting the live service, copies code to `/opt/camper-zero`, stores private configuration in `/etc/camper-zero/config.json`, and stores history in `/var/lib/camper-zero`. It preserves existing credentials and network configuration. Passwords are salted PBKDF2 hashes, not stored in plaintext. The service runs as your normal SSH user, with write access confined to its data directory. It starts again on reboot.

Open **http://homeassistant.local:8080** from the phone on the same WLAN. Fallback AP: **http://192.168.42.1:8080**. On Starlink, use the Pi's LAN address if Android mDNS fails. Bookmark either URL; the browser remembers its theme. This is a local HTTP dashboard intended for the private camper/Starlink LAN; do not port-forward it to the Internet. Browser sessions expire after 12 hours or a service restart. Direct-IP and hostname sessions are separate.

The dashboard starts with empty values and disabled AC control until BLUETTI is read. No demonstration values are used. Initial sequential discovery may take a minute or two. A queued AC command waits for an active BLE read to finish, then runs before further scheduled polling. Typical hardware reconnects were about 10–30 seconds; an in-progress failed operation can take up to 75 seconds before the command starts. The command itself has a 95-second hard deadline. Requests older than 120 seconds expire before execution. Only one command is accepted at a time; it writes AC register 2011 once, verifies the acknowledgement and reads back the state. A failed acknowledgement/read-back is **unconfirmed**, even if the physical output changed. Check the device before requesting again. Commands are never restored/replayed across restart. DC has no writable API; disabling DC would shut down this Pi.

## Private theme labels

The public source uses Camper, Rose and Cyberpunk. On first installation, optional `--rose-label` and `--cyberpunk-label` arguments set personal labels only in the private config; repeat installation preserves existing labels. To give the rose/cyberpunk options your preferred names, edit only the installed private config:

```bash
sudo nano /etc/camper-zero/config.json
```

Change `theme_labels` values, keep valid JSON, then `sudo systemctl restart camper-zero`. Do not commit this file.

## Fresh SD card later

Flash Raspberry Pi OS Lite 64-bit with SSH and 2.4 GHz Wi-Fi configured in Imager. Keep the working network setup/backup: this dashboard installer deliberately does not replace networking. Install `git`, `python3-venv`, `bluetooth` and `bluez` from Raspberry Pi OS. Clone this repository and create three virtual environments as in the previous compatibility tests:

* `~/camper-ble-test/venv`: `bleak`, `cryptography`, `pyasn1`, `crcmod`.
* `~/camper-ble-test/bms-venv`: `aiobmsble`.
* `~/camper-ble-test/aranet-venv`: `aranet4`.
* Clone https://github.com/JordiGrasvi/bluetti-elite200v2-mqtt to `~/camper-ble-test/bluetti` and check out `50029b7ab059a854aa68dd36e59306f732e219b2`.

Use the private `*-requirements.txt` files saved by installation/backup to recreate the tested dependency versions (`python -m pip install -r ...` inside each corresponding environment). They are separate because the tested dependency combinations are separate. BLUETTI needs `PYTHONPATH` pointing at the pinned checkout, which the live service sets itself. Copy `devices.example.json` outside the repository, fill in your actual device information and chmod 600, then follow the installation commands above. A missing secret/dependency fails installation before changing the running service. Initial package downloads need Internet; normal recording, graphs and commands do not.

## First hardware acceptance

```bash
sudo journalctl -u camper-zero.service -b --no-pager -n 40
python3 tools/diagnose.py
```

Confirm all three device badges report readings, compare SOC/CO₂ to the physical displays, and check charts after several minutes. Test AC on/off while observing the hardware; do not test DC off. Leave it running overnight and compare `free -h`, journal recovery behaviour, database size and AC latency. After stable operation, test a reboot and AP/Starlink return when interruption is convenient. This live collector, HTTP layer and database have been tested locally with simulated BLE; sustained operation on the actual Pi remains to be verified. The earlier 10-minute reconnect check achieved 8/8 reads for each device with zero failures and at least 223 MiB available RAM. This is not a production memory/leak benchmark.
