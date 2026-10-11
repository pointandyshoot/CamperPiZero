# Upstream credits

This project's test harness calls these projects; it does not vendor their source.

* [JordiGrasvi/bluetti-elite200v2-mqtt](https://github.com/JordiGrasvi/bluetti-elite200v2-mqtt), MIT: Elite 200 V2 detection and MQTT bridge adaptation. Tested source revision: `50029b7ab059a854aa68dd36e59306f732e219b2`.
* [nhurman/bluetti_mqtt](https://github.com/nhurman/bluetti_mqtt), MIT: newer protocol and Python BLE encryption implementation used by the Elite bridge.
* [warhammerkid/bluetti_mqtt](https://github.com/warhammerkid/bluetti_mqtt), MIT: original communication/Modbus foundation.
* [patman15/aiobmsble](https://github.com/patman15/aiobmsble), Apache-2.0: standalone BMS library and Offgridtec/SmartBat protocol. Preserve its licence and any supplied notices if distributing its code.
* [syssi/esphome-ogt-bms](https://github.com/syssi/esphome-ogt-bms): independent SmartBat/Offgridtec reference project; not presently a runtime dependency.
* [Anrijs/Aranet4-Python](https://github.com/Anrijs/Aranet4-Python), MIT: local Aranet advertisement decoding.
* [Bleak](https://github.com/hbldh/bleak), MIT: Python BLE client and scanner used by these libraries.

Upstream authors retain their respective copyrights. Refer to each upstream LICENSE file for full terms. Keep licence texts with any future vendored or redistributed source; attribution here alone is not a substitute. Dependencies remain in private virtual environments on the Pi. The harness records installed package versions in its private JSONL output.
