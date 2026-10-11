import asyncio
import contextlib
import io
from types import SimpleNamespace
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('soak', Path(__file__).parents[1] / 'tools/ble_soak.py')
soak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)

class Tests(unittest.TestCase):
    def test_private_config_required(self):
        with self.assertRaises(ValueError):
            soak.config_check({})
        soak.config_check({'bluetti_mac':'00:00:00:00:00:01','smartbat_mac':'00:00:00:00:00:02','aranet_name':'Aranet4 DEMO'})

    def test_invalid_numeric_data_is_not_zero(self):
        for value in (None, float('nan'), float('inf'), True, -1):
            self.assertFalse(soak.finite(value, 0, 100))
        self.assertTrue(soak.finite(0, 0, 100))

    def test_aranet_freshness_uses_device_cadence(self):
        sample={'co2_ppm':591,'temperature_c':25.7,'humidity_percent':82,'pressure_hpa':1017.9,'age_seconds':218,'interval_seconds':300}
        self.assertEqual(soak.validate('aranet',sample),sample)
        with self.assertRaises(ValueError):
            soak.validate('aranet',{**sample,'age_seconds':601})

    def fixture_worker(self, source, limit):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            python=base/'venv/bin/python'
            python.parent.mkdir(parents=True)
            python.symlink_to(sys.executable)
            fake=base/'fake_worker.py'
            fake.write_text(source)
            with patch.object(soak,'__file__',str(fake)):
                return soak.run_worker('bluetti',base/'devices.json',base,limit)

    def test_worker_result(self):
        self.assertEqual(self.fixture_worker('print(\'{"ok": true, "data": {}}\')',2)['ok'],True)

    def test_worker_timeout_reaped(self):
        self.assertEqual(self.fixture_worker('import time; time.sleep(20)',.1)['error'],'hard_timeout')

    def test_worker_invalid_output(self):
        self.assertEqual(self.fixture_worker('print("not JSON")',2)['error'],'invalid_worker_output')

    def test_worker_exception_not_exposed(self):
        result=self.fixture_worker('raise RuntimeError("private")',2)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'],'worker_exit')
        self.assertNotIn('private',json.dumps(result))

    def test_failure_stage_and_safe_code(self):
        async def fail(config, progress):
            progress['stage']='discovery'
            raise soak.ReadFailure('device_not_found')
        output=io.StringIO()
        with patch.object(soak,'read_bluetti',fail),contextlib.redirect_stdout(output):
            soak.worker_main('bluetti',{})
        result=json.loads(output.getvalue())
        self.assertEqual(result['stage'],'discovery')
        self.assertEqual(result['error_code'],'device_not_found')

    def test_bluetti_uses_scanned_device_and_clean_single_session(self):
        record_device=object(); instances=[]
        class Scanner:
            @staticmethod
            async def discover(**kwargs):
                return {'record':(SimpleNamespace(address='00:00:00:00:00:01'),SimpleNamespace(manufacturer_data={}))}
        discovered=SimpleNamespace(address='00:00:00:00:00:01')
        async def scan(**kwargs):return {'record':(discovered,SimpleNamespace(manufacturer_data={}))}
        Scanner.discover=staticmethod(scan)
        class Client:
            def __init__(self,target,encrypted):
                self.target=target;self.is_ready=False;self.client=SimpleNamespace(is_connected=False);self.closed=False;instances.append(self)
            async def run(self):
                try:
                    self.is_ready=True
                    await asyncio.Event().wait()
                finally:self.closed=True
            async def perform(self,command):
                future=asyncio.get_running_loop().create_future();future.set_result(b'raw');return future
        class Command:
            def __init__(self,*args):self.function_code=3
            def parse_response(self,response):return response
        class Device:
            def __init__(self,*args):pass
            def parse(self,*args):return {'total_battery_percent':78,'dc_input_power':92,'ac_input_power':0,'ac_output_power':0,'dc_output_power':19,'ctrl_status':4}
        fake={'bleak':SimpleNamespace(BleakScanner=Scanner),'bluetti_mqtt.bluetooth':SimpleNamespace(BluetoothClient=Client),'bluetti_mqtt.bluetooth.encryption':SimpleNamespace(is_device_using_encryption=lambda _:True),'bluetti_mqtt.core':SimpleNamespace(V2Device=Device,ReadHoldingRegisters=Command)}
        with patch.dict(sys.modules,fake):
            result=asyncio.run(soak.read_bluetti({'bluetti_mac':discovered.address},{}))
        self.assertIs(instances[0].target,discovered)
        self.assertTrue(instances[0].closed)
        self.assertEqual(result['soc_percent'],78)
        with self.assertRaises(soak.ReadFailure):asyncio.run(instances[0]._disconnect())

if __name__=='__main__': unittest.main()
