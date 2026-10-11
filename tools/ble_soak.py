#!/usr/bin/env python3
"""Read-only BLE soak test. Supervisor uses only the Python standard library."""
import argparse
import asyncio
import contextlib
import importlib.metadata
import json
import logging
import math
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time

DEVICES = ("bluetti", "smartbat", "aranet")
WORKER_LIMIT = {"bluetti": 75, "smartbat": 65, "aranet": 35}


def memory():
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        if key in ("MemAvailable", "SwapTotal", "SwapFree"):
            values[key] = int(rest.split()[0])
    return {"available_kib": values["MemAvailable"],
            "swap_used_kib": values["SwapTotal"] - values["SwapFree"],
            "supervisor_peak_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def config_check(config):
    if not isinstance(config, dict):
        raise ValueError("Private configuration must be an object")
    for key in ("bluetti_mac", "smartbat_mac"):
        if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", config.get(key, "")):
            raise ValueError(f"Missing or invalid {key} in private configuration")
    if not config.get("aranet_name", "").startswith("Aranet4"):
        raise ValueError("Set aranet_name to the name shown by your scan")


def finite(value, low, high):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


def validate(device, data):
    required = {
        "bluetti": {"soc_percent": (0, 100), "solar_w": (0, 10000), "ac_input_w": (0, 10000),
                    "ac_output_w": (0, 10000), "dc_output_w": (0, 10000)},
        "smartbat": {"soc_percent": (0, 100), "voltage_v": (1, 100), "current_a": (-2000, 2000),
                     "temperature_c": (-60, 120), "power_w": (-200000, 200000)},
        "aranet": {"co2_ppm": (1, 100000), "temperature_c": (-60, 100),
                   "humidity_percent": (0, 100), "pressure_hpa": (300, 1200)},
    }
    for key, bounds in required[device].items():
        if not finite(data.get(key), *bounds):
            raise ValueError(f"Invalid or missing telemetry field: {key}")
    if device == "aranet":
        age, interval = data.get("age_seconds"), data.get("interval_seconds")
        if not finite(age, 0, 86400) or not finite(interval, 1, 86400):
            raise ValueError("Invalid Aranet measurement timing")
        if age > 2 * interval:
            raise ValueError("Stale Aranet measurement")
    return data


async def read_bluetti(config):
    from bleak import BleakScanner
    from bluetti_mqtt.bluetooth import BluetoothClient
    from bluetti_mqtt.bluetooth.encryption import is_device_using_encryption
    from bluetti_mqtt.core import V2Device, ReadHoldingRegisters
    address = config["bluetti_mac"].upper()
    found = await BleakScanner.discover(timeout=8, return_adv=True)
    record = next((r for r in found.values() if r[0].address.upper() == address), None)
    if record is None:
        raise RuntimeError("device_not_found")
    client = BluetoothClient(address, is_device_using_encryption(record[1].manufacturer_data))
    device = V2Device(address, "0", "Elite 200 V2")
    worker = asyncio.create_task(client.run())
    try:
        while not client.is_ready:
            if worker.done():
                await worker
                raise RuntimeError("worker_stopped")
            await asyncio.sleep(.2)
        command = ReadHoldingRegisters(100, 67)
        assert command.function_code == 3  # No device configuration/output writes.
        response = await asyncio.wait_for(await client.perform(command), timeout=20)
        data = device.parse(100, command.parse_response(response))
        status = data.get("ctrl_status")
        return {"soc_percent": data.get("total_battery_percent"),
                "solar_w": data.get("dc_input_power"), "ac_input_w": data.get("ac_input_power"),
                "ac_output_w": data.get("ac_output_power"), "dc_output_w": data.get("dc_output_power"),
                "ac_on": bool(status & 2) if status is not None else None,
                "dc_on": bool(status & 4) if status is not None else None}
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(worker, timeout=5)


async def read_smartbat(config):
    from bleak import BleakScanner
    from aiobmsble.bms.ogt_bms import BMS
    device = await BleakScanner.find_device_by_address(config["smartbat_mac"], timeout=12)
    if device is None:
        raise RuntimeError("device_not_found")
    async with BMS(ble_device=device) as bms:
        data = await bms.async_update()
    return {"soc_percent": data.get("battery_level"), "voltage_v": data.get("voltage"),
            "current_a": data.get("current"), "power_w": data.get("power"),
            "temperature_c": data.get("temperature"), "cycles": data.get("cycles"),
            "problem": data.get("problem"), "runtime_seconds": data.get("runtime")}


async def read_aranet(config):
    from bleak import BleakScanner
    from aranet4.client import Aranet4Advertisement
    ready, result = asyncio.Event(), {}

    def receive(device, advertisement):
        if (advertisement.local_name or device.name or "") != config["aranet_name"]:
            return
        try:
            reading = Aranet4Advertisement(device, advertisement).readings
            if reading is None:
                return
            candidate = {"co2_ppm": reading.co2, "temperature_c": reading.temperature,
                         "humidity_percent": reading.humidity, "pressure_hpa": reading.pressure,
                         "battery_percent": reading.battery, "age_seconds": reading.ago,
                         "interval_seconds": reading.interval}
            validate("aranet", candidate)
            result.update(candidate)
            ready.set()
        except (ValueError, TypeError, IndexError):
            return  # Ignore incomplete/invalid advertisements; deadline remains bounded.

    async with BleakScanner(detection_callback=receive):
        await asyncio.wait_for(ready.wait(), timeout=25)
    return result


def worker_main(device, config):
    logging.disable(logging.CRITICAL)  # Upstream BLUETTI logs can contain session keys.
    try:
        function = {"bluetti": read_bluetti, "smartbat": read_smartbat, "aranet": read_aranet}[device]
        data = asyncio.run(asyncio.wait_for(function(config), timeout=WORKER_LIMIT[device] - 10))
        payload = {"ok": True, "data": validate(device, data)}
    except Exception as exc:
        payload = {"ok": False, "error": type(exc).__name__}  # Never print raw packets/keys/IDs.
    payload["peak_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    payload["versions"] = {}
    for package in ("bleak", "aiobmsble", "aranet4"):
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            payload["versions"][package] = importlib.metadata.version(package)
    print(json.dumps(payload), flush=True)


def run_worker(device, config_path, base, limit):
    env_name = {"bluetti": "venv", "smartbat": "bms-venv", "aranet": "aranet-venv"}[device]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    if device == "bluetti":
        env["PYTHONPATH"] = str(base / "bluetti")
    command = [str(base / env_name / "bin/python"), "-u", str(Path(__file__).resolve()),
               "--config", str(config_path), "--worker", device]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=env, start_new_session=True)
    deadline = time.monotonic() + limit
    minimum_available, maximum_swap, sampled_peak = memory()["available_kib"], 0, 0

    def finish(result):
        result["minimum_available_kib"] = minimum_available
        result["maximum_swap_used_kib"] = maximum_swap
        result["peak_kib"] = max(sampled_peak, result.get("peak_kib", 0))
        return result

    try:
        while True:
            host = memory()
            minimum_available = min(minimum_available, host["available_kib"])
            maximum_swap = max(maximum_swap, host["swap_used_kib"])
            with contextlib.suppress(OSError, ValueError, IndexError):
                for line in Path(f"/proc/{process.pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        sampled_peak = max(sampled_peak, int(line.split()[1]))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, limit)
            try:
                output, _ = process.communicate(timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
        if process.returncode != 0:
            return finish({"ok": False, "error": "worker_exit"})
        result = json.loads(output)
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise ValueError("Invalid result")
        return finish(result)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        return finish({"ok": False, "error": "hard_timeout"})
    except (ValueError, TypeError):
        return finish({"ok": False, "error": "invalid_worker_output"})
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()


def supervise(args, config_path, base):
    for name in ("venv", "bms-venv", "aranet-venv"):
        if not (base / name / "bin/python").exists():
            raise ValueError(f"Missing test environment: {name}")
    start = time.monotonic()
    end = start + args.minutes * 60
    due = {device: start for device in DEVICES}
    stats = {device: {"success": 0, "failed": 0, "recoveries": 0,
                      "consecutive_failed": 0, "peak_worker_kib": 0} for device in DEVICES}
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_id = str(time.time_ns())
    log_path = args.output / (run_id + ".jsonl")
    summary_path = args.output / (run_id + "-summary.json")
    initial_memory = memory()
    min_available = initial_memory["available_kib"]
    max_swap = initial_memory["swap_used_kib"]
    print(f"Read-only test: {args.minutes:g} minutes. One BLE worker at a time.", flush=True)
    try:
        with log_path.open("x") as log:
            while time.monotonic() < end:
                device = min(due, key=due.get)
                now = time.monotonic()
                if now >= end:
                    break
                if due[device] > now:
                    time.sleep(min(1, due[device] - now, end - now))
                    continue
                remaining = end - now
                if remaining < 5:
                    break
                before = time.monotonic()
                try:
                    result = run_worker(device, config_path, base, min(WORKER_LIMIT[device], remaining))
                except OSError:
                    result = {"ok": False, "error": "worker_start_failed"}
                elapsed = round(time.monotonic() - before, 2)
                state = stats[device]
                if result.get("ok"):
                    state["success"] += 1
                    if state["consecutive_failed"]:
                        state["recoveries"] += 1
                    state["consecutive_failed"] = 0
                else:
                    state["failed"] += 1
                    state["consecutive_failed"] += 1
                state["peak_worker_kib"] = max(state["peak_worker_kib"], result.get("peak_kib", 0))
                delay = min(240, 60 * 2 ** min(state["consecutive_failed"], 2))
                due[device] = time.monotonic() + delay
                host = memory()
                min_available = min(min_available, host["available_kib"])
                min_available = min(min_available, result.get("minimum_available_kib", min_available))
                max_swap = max(max_swap, host["swap_used_kib"], result.get("maximum_swap_used_kib", 0))
                row = {"elapsed_seconds": round(time.monotonic() - start, 1), "device": device,
                       "duration_seconds": elapsed, **result, "memory": host}
                log.write(json.dumps(row) + "\n")
                log.flush()
                status = "OK" if result.get("ok") else "FAIL " + result.get("error", "unknown")
                print(f"{device}: {status} ({elapsed}s); available={host['available_kib']//1024} MiB; "
                      f"swap={host['swap_used_kib']//1024} MiB", flush=True)
                time.sleep(min(2, max(0, end - time.monotonic())))
    finally:
        summary = {"duration_seconds": round(time.monotonic() - start, 1), "devices": stats,
                   "initial_memory": initial_memory, "final_memory": memory(),
                   "minimum_available_kib": min_available,
                   "maximum_swap_used_kib": max_swap,
                   "scope": "Fresh-process reconnect test; no switching or persistent collector tested"}
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        print("SUMMARY " + json.dumps(summary), flush=True)
        print(f"Private results: {summary_path}", flush=True)
    return 0 if all(v["success"] > 0 and v["failed"] == 0 for v in stats.values()) else 1


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--base", type=Path, default=Path.home() / "camper-ble-test")
    parser.add_argument("--output", type=Path, default=Path.home() / "camper-ble-test/results")
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--worker", choices=DEVICES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not math.isfinite(args.minutes) or not 0 < args.minutes <= 120:
        parser.error("minutes must be between 0 and 120")
    config_path, base = args.config.expanduser().resolve(), args.base.expanduser().resolve()
    try:
        config = json.loads(config_path.read_text())
        config_check(config)
        if args.worker:
            worker_main(args.worker, config)
            return 0
        return supervise(args, config_path, base)
    except (ValueError, OSError) as exc:
        print(f"Setup failed: {type(exc).__name__}. Check private config and test environments.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
