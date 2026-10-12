import asyncio
import contextlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from camper.app import Core, Server, password_hash, load_config, run_operation
from camper.history import History
from tools.install import prepare_config, unit_for, switch_release
import ble_soak

CONFIG={'bluetti_mac':'00:00:00:00:00:01','bluetti_name':'Elite 200 V20000000000000','smartbat_mac':'00:00:00:00:00:02','aranet_name':'Aranet4 DEMO','auth_salt':'00'*16}
CONFIG['auth_hash']=password_hash('fake-example-password',CONFIG['auth_salt'])
DATA={'soc_percent':78,'solar_w':92,'ac_input_w':0,'ac_output_w':0,'dc_output_w':19,'ac_on':False,'dc_on':True}


class HistoryTests(unittest.TestCase):
    def setUp(self):self.history=History(':memory:')
    def tearDown(self):self.history.close()
    def test_rollup_is_weighted_by_observation_count_and_preserves_extrema(self):
        for t,value in [(0,10),(10,20),(20,30),(300,100)]:self.history.record('bluetti',{'solar_w':value},t,True)
        # Force archives via >14-day chart; multiple archives combined into one output bucket.
        chart=self.history.chart('bluetti.solar_w',0,15*86400,max_points=1)
        p=chart['points'][0];self.assertEqual(p['count'],4);self.assertEqual(p['mean'],40)
        self.assertEqual((p['min'],p['max']),(10,100))
    def test_missing_readings_remain_gaps_and_duplicates_do_not_count_twice(self):
        self.history.record('bluetti',{'solar_w':0},0);self.history.record('bluetti',{'solar_w':999},0)
        points=self.history.chart('bluetti.solar_w',0,180)['points']
        self.assertEqual(points[0]['mean'],0);self.assertEqual(points[0]['count'],1)
        self.assertIsNone(points[1]['mean'])
    def test_retention_requires_trusted_clock_and_keeps_long_archive(self):
        self.history.record('bluetti',{'solar_w':20},0)
        self.history.purge(20*86400,False);self.assertEqual(self.history.db.execute('SELECT count(*) FROM points').fetchone()[0],1)
        self.history.purge(20*86400,True);self.assertEqual(self.history.db.execute('SELECT count(*) FROM points').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT count(*) FROM buckets').fetchone()[0],2)
    def test_untrusted_clock_still_has_insertion_order_row_cap(self):
        self.history.row_limits['points']=2
        for t in (1000,10,20):self.history.record('bluetti',{'solar_w':t},t,False)
        self.history.purge(99999999999,False)
        self.assertEqual(self.history.db.execute('SELECT t FROM points ORDER BY t').fetchall(),[(10,),(20,)])
    def test_graph_limits_and_out_of_order_last(self):
        self.history.record('bluetti',{'solar_w':80},120);self.history.record('bluetti',{'solar_w':10},60)
        last=self.history.db.execute('SELECT last FROM buckets WHERE resolution=300').fetchone()[0];self.assertEqual(last,80)
        self.assertLessEqual(len(self.history.chart('bluetti.solar_w',0,730*86400)['points']),400)
        with self.assertRaises(ValueError):self.history.chart('bluetti.solar_w',0,800*86400)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name);self.config=self.path/'devices.json';self.config.write_text(json.dumps(CONFIG))
        self.core=Core(self.config,self.path,self.path/'data')
    def tearDown(self):self.core.history.close();self.temp.cleanup()
    def test_command_priority_duplicate_rejection_and_expiry(self):
        job=self.core.enqueue(True)
        with self.assertRaises(RuntimeError):self.core.enqueue(False)
        device,selected=self.core.next_operation({'bluetti':0,'smartbat':0,'aranet':0},time.monotonic())
        self.assertEqual(device,'bluetti');self.assertEqual(selected['id'],job['id'])
        self.assertEqual(selected['status'],'running')
        selected['status']='confirmed';job=self.core.enqueue(False)
        self.core.jobs[job['id']]['created']-=121
        device,selected=self.core.next_operation({'bluetti':1000000000,'smartbat':0,'aranet':0},time.monotonic())
        self.assertIsNone(selected);self.assertEqual(self.core.jobs[job['id']]['status'],'expired')
    def test_unknown_and_old_values_are_stale_and_not_zero(self):
        snapshot=self.core.snapshot();self.assertIsNone(snapshot['devices']['bluetti']['data']);self.assertTrue(snapshot['devices']['bluetti']['stale'])
        self.core.devices['bluetti'].update(data=DATA,updated_mono=time.monotonic()-181)
        self.assertTrue(self.core.snapshot()['devices']['bluetti']['stale'])
    def test_authentication_and_no_identifier_exposure(self):
        self.assertIsNone(self.core.authenticate('wrong','test'))
        token=self.core.authenticate('fake-example-password','test');self.assertTrue(self.core.authorised('camper_session='+token))
        snapshot=json.dumps(self.core.snapshot());self.assertNotIn(CONFIG['bluetti_mac'],snapshot);self.assertNotIn(CONFIG['auth_hash'],snapshot)
    def test_scheduler_confirms_commands_and_records_poll(self):
        def operation(device,path,base,stop,desired):
            return {'ok':True,'data':{**DATA,'ac_on':desired if desired is not None else False,'command_confirmed':True}}
        self.core.operation=operation;job=self.core.enqueue(True)
        # Stop after the command completion, before other fake device operations.
        thread=threading.Thread(target=self.core.collect);thread.start()
        deadline=time.monotonic()+2
        while self.core.jobs[job['id']]['status']!='confirmed' and time.monotonic()<deadline:time.sleep(.01)
        self.core.stop.set()
        with self.core.condition:self.core.condition.notify_all()
        thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(self.core.jobs[job['id']]['status'],'confirmed')
        self.assertTrue(self.core.snapshot()['devices']['bluetti']['data']['ac_on'])
    def test_http_auth_csrf_control_and_absent_optional_hardware(self):
        server=Server(('127.0.0.1',0),self.core);thread=threading.Thread(target=server.serve_forever);thread.start()
        host='127.0.0.1:'+str(server.server_port)
        conn=http.client.HTTPConnection(host,timeout=2)
        try:
            conn.request('GET','/api/status');response=conn.getresponse();self.assertEqual(response.status,401);response.read()
            body=json.dumps({'password':'fake-example-password'});headers={'Content-Type':'application/json','Origin':'http://'+host}
            conn.request('GET','/theme-assets/power.webp');response=conn.getresponse();self.assertEqual(response.status,401);response.read()
            conn.request('POST','/api/login',body,headers);response=conn.getresponse();self.assertEqual(response.status,200);cookie=response.getheader('Set-Cookie').split(';')[0];response.read();headers['Cookie']=cookie
            conn.request('GET','/api/status',headers={'Cookie':cookie});response=conn.getresponse();self.assertEqual(response.status,200);snapshot=json.loads(response.read());self.assertEqual(set(snapshot['devices']),{'bluetti','smartbat','aranet'})
            conn.request('POST','/api/ac','{"on":true}',{**headers,'Origin':'http://other.example'});response=conn.getresponse();self.assertEqual(response.status,403);response.read()
            with patch('camper.app.THEME_ASSETS',self.path/'art'):
                art=self.path/'art';art.mkdir();(art/'power.webp').write_bytes(b'example-webp')
                self.assertEqual(self.core.snapshot()['theme_artwork_available'],['power'])
                conn.request('GET','/theme-assets/power.webp',headers={'Cookie':cookie});response=conn.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.getheader('Content-Type'),'image/webp');self.assertEqual(response.read(),b'example-webp')
                conn.request('GET','/theme-assets/../config.json',headers={'Cookie':cookie});response=conn.getresponse();self.assertEqual(response.status,404);response.read()
                conn.request('GET','/theme-assets/air.webp',headers={'Cookie':cookie});response=conn.getresponse();self.assertEqual(response.status,404);response.read()
            conn.request('POST','/api/dc','{"on":false}',headers);response=conn.getresponse();self.assertEqual(response.status,404);response.read()
            conn.request('POST','/api/ac','{"on":true}',headers);response=conn.getresponse();self.assertEqual(response.status,202);self.assertEqual(json.loads(response.read())['status'],'queued')
            conn.request('POST','/api/ac','{"on":false}',headers);response=conn.getresponse();self.assertEqual(response.status,409);response.read()
            conn.request('GET','/api/history?metric=bad&hours=24',headers={'Cookie':cookie});response=conn.getresponse();self.assertEqual(response.status,400);response.read()
            conn.request('GET','/');response=conn.getresponse();html=response.read().decode();self.assertNotIn('Mock data',html);self.assertIn('DC-off protected',html)
        finally:conn.close();server.shutdown();thread.join();server.server_close()
    def test_missing_secrets_and_repeat_config_preserved(self):
        self.config.write_text('{}')
        with self.assertRaises(ValueError):load_config(self.config)
        self.config.write_text(json.dumps(CONFIG));cfg,new=prepare_config(self.path/'does-not-exist',self.config,'different-password')
        self.assertFalse(new);self.assertEqual(cfg,CONFIG)
        cfg,new=prepare_config(self.config,self.path/'new-config','new-example-password')
        self.assertTrue(new);self.assertEqual(cfg['bluetti_mac'],CONFIG['bluetti_mac']);self.assertNotIn('new-example-password',json.dumps(cfg))
    def test_hard_worker_deadline_reaps_process(self):
        base=self.path;python=base/'venv/bin/python';python.parent.mkdir(parents=True);python.symlink_to(sys.executable)
        fake=base/'worker.py';fake.write_text('import time; time.sleep(20)')
        with patch('camper.app.__file__',str(base/'app.py')),patch.dict('camper.app.WORKER_LIMIT',{'bluetti':.05}):
            result=run_operation('bluetti',self.config,base,threading.Event())
        self.assertEqual(result['error'],'hard_timeout')


class InstallerTests(unittest.TestCase):
    def test_repeat_release_and_activation_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'installed';unit=root/'service';target.mkdir();(target/'version').write_text('old');unit.write_text('old unit')
            def stage(version):
                p=root/('stage-'+version);p.mkdir();(p/'version').write_text(version);return p
            backup=root/'backup1';backup.mkdir()
            switch_release(stage('new'),target,backup,unit,'new unit',lambda:None,lambda _:None)
            self.assertEqual((target/'version').read_text(),'new');self.assertEqual((backup/'code/version').read_text(),'old')
            backup2=root/'backup2';backup2.mkdir();recovered=[]
            def fail():raise RuntimeError('activation failed')
            with self.assertRaises(RuntimeError):switch_release(stage('broken'),target,backup2,unit,'broken unit',fail,recovered.append)
            self.assertEqual((target/'version').read_text(),'new');self.assertEqual(unit.read_text(),'new unit');self.assertEqual(recovered,[True])


class ACTests(unittest.TestCase):
    def test_one_ac_write_and_readback_never_dc(self):
        calls=[];clients=[]
        class Scanner:
            @staticmethod
            async def discover(**kw):return {'x':(SimpleNamespace(address=CONFIG['bluetti_mac'],name=CONFIG['bluetti_name']),SimpleNamespace(manufacturer_data={},local_name=CONFIG['bluetti_name']))}
        class Command:
            function_code=3
            def __init__(self,*args):pass
            def parse_response(self,raw):return raw
        class Write:
            function_code=6
            def __init__(self,address,value):self.address=address;self.value=value
            def __bytes__(self):return bytes([self.value])
        class Client:
            def __init__(self,*args):self.is_ready=False;self.client=SimpleNamespace(is_connected=False);self.on=False;self.closed=False;clients.append(self)
            async def run(self):
                try:self.is_ready=True;await asyncio.Event().wait()
                finally:self.closed=True
            async def perform(self,cmd):
                calls.append(cmd);future=asyncio.get_running_loop().create_future()
                if cmd.function_code==6:self.on=bool(cmd.value);future.set_result(bytes(cmd))
                else:future.set_result(self.on)
                return future
        class Device:
            def __init__(self,*args):pass
            def parse(self,address,raw):return {'total_battery_percent':78,'dc_input_power':92,'ac_input_power':0,'ac_output_power':0,'dc_output_power':19,'ctrl_status':6 if raw else 4}
        modules={'bleak':SimpleNamespace(BleakScanner=Scanner),'bluetti_mqtt.bluetooth':SimpleNamespace(BluetoothClient=Client),'bluetti_mqtt.bluetooth.encryption':SimpleNamespace(is_device_using_encryption=lambda _:True),'bluetti_mqtt.core':SimpleNamespace(V2Device=Device,ReadHoldingRegisters=Command,WriteSingleRegister=Write)}
        with patch.dict(sys.modules,modules):result=asyncio.run(ble_soak.read_bluetti(CONFIG,{},True))
        writes=[cmd for cmd in calls if cmd.function_code==6];self.assertEqual(len(writes),1);self.assertEqual(writes[0].address,2011)
        self.assertTrue(result['command_confirmed']);self.assertTrue(result['ac_on']);self.assertTrue(result['dc_on']);self.assertTrue(clients[0].closed)
        with patch.dict(sys.modules,modules):
            calls.clear();result=asyncio.run(ble_soak.read_bluetti(CONFIG,{},False))
            self.assertFalse(any(c.function_code==6 for c in calls));self.assertTrue(result['command_confirmed'])


if __name__=='__main__':unittest.main()
