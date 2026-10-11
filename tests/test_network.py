import importlib.util
from pathlib import Path
import subprocess
import tempfile
import json
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('controller',Path(__file__).parents[1]/'networking/controller.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Fake:
    def __init__(self):
        self.current='';self.associate=False;self.reachable=False;self.ap_ok=True;self.seen=None;self.calls=[];self.scans=0
    def active(self):return self.current
    def up(self,uuid):
        self.calls.append(uuid);ok=self.associate if uuid==m.STA else self.ap_ok;self.current=uuid if ok else '';return ok
    def viable(self):return self.current==m.STA and self.reachable
    def visible(self,ssid):self.scans+=1;return self.seen

class Tests(unittest.TestCase):
    def setUp(self):
        self.now=0;self.n=Fake();self.cfg={'probe_interval':180,'scan_interval':60,'maximum_backoff':600,'stability_seconds':30,'loss_seconds':60,'tick_seconds':15,'starlink_ssid':'TEST-WLAN'}
        self.c=m.Controller(self.cfg,self.n,lambda:self.now,self.advance,lambda _:None)
    def advance(self,s):self.now+=s
    def step_at(self,t):self.now=t;self.c.step()
    def test_startup_first_client(self):
        self.c.startup();self.assertEqual(self.n.calls,[m.STA,m.AP])
    def test_startup_good_client_no_ap(self):
        self.n.associate=self.n.reachable=True;self.c.startup();self.assertEqual(self.n.calls,[m.STA]);self.assertEqual(self.c.state,'STARLINK');self.assertEqual(self.now,30)
    def test_restart_good_client_preserved(self):
        self.n.current=m.STA;self.n.reachable=True;self.c.startup();self.assertEqual(self.n.calls,[])
    def test_no_lan_startup_falls_back(self):
        self.n.associate=True;self.c.startup();self.assertEqual(self.n.current,m.AP)
    def test_no_fresh_ssid_no_disruptive_trial(self):
        self.c.startup();self.n.seen=False
        for t in range(60,601,60):self.step_at(t)
        self.assertEqual(self.n.calls,[m.STA,m.AP]);self.assertEqual(self.n.scans,10)
    def test_two_fresh_sightings_promote_before_blind_dwell(self):
        self.c.startup();self.n.seen=True;self.n.associate=self.n.reachable=True
        self.step_at(60);self.assertEqual(self.n.current,m.AP)
        self.step_at(120);self.assertEqual(self.n.current,m.STA)
    def test_fleeting_ssid_not_promoted(self):
        self.c.startup();self.n.seen=True;self.step_at(60);self.n.seen=False;self.step_at(120);self.n.seen=True;self.step_at(180);self.assertEqual(self.n.current,m.AP)
    def test_unavailable_scan_blind_trial_at_three_minutes(self):
        self.c.startup();self.step_at(60);self.step_at(120);self.assertEqual(self.n.calls,[m.STA,m.AP]);self.step_at(180);self.assertEqual(self.n.calls,[m.STA,m.AP,m.STA,m.AP]);self.assertEqual(self.c.backoff,360)
    def test_failed_fresh_trial_honours_cooldown(self):
        self.c.startup();self.n.seen=True;self.step_at(60);self.step_at(120);self.assertEqual(self.c.retry_after,480)
        self.step_at(180);self.step_at(240);self.assertEqual(self.n.calls,[m.STA,m.AP,m.STA,m.AP]);self.step_at(480);self.assertEqual(self.c.backoff,600)
    def test_no_scans_on_stable_client(self):
        self.n.associate=self.n.reachable=True;self.c.startup();self.step_at(500);self.assertEqual(self.n.scans,0)
    def test_loss_debounce(self):
        self.n.associate=self.n.reachable=True;self.c.startup();self.n.reachable=False;self.step_at(40);self.step_at(85);self.assertEqual(self.n.current,m.STA);self.step_at(100);self.assertEqual(self.n.current,m.AP)
    def test_brief_loss_resets_debounce(self):
        self.n.associate=self.n.reachable=True;self.c.startup();self.n.reachable=False;self.step_at(40);self.n.reachable=True;self.step_at(70);self.n.reachable=False;self.step_at(80);self.step_at(100);self.assertEqual(self.n.current,m.STA)
    def test_ap_retry(self):
        self.n.ap_ok=False;self.c.startup();self.n.ap_ok=True;self.c.step();self.assertEqual(self.n.current,m.AP)
    def test_short_lan_stability_fails(self):
        self.n.associate=self.n.reachable=True
        def drop(s):self.advance(s);self.n.reachable=False
        self.c.sleep=drop;self.c.startup();self.assertEqual(self.n.current,m.AP)
    def test_scan_freshness(self):
        for seen,wanted in [(99,False),(100,True)]:
            n=m.Network('wlan0')
            commands=[(True,'/org/freedesktop/NetworkManager/Devices/2'),(True,''),(True,'TEST-WLAN:/org/freedesktop/NetworkManager/AccessPoint/8'),(True,f'i {seen}')]
            with patch.object(n,'last_scan',side_effect=[90000,101000]),patch.object(m,'command',side_effect=commands) as call,patch.object(m.time,'clock_gettime',return_value=100):
                self.assertEqual(n.visible('TEST-WLAN'),wanted)
                self.assertTrue(all('TEST-WLAN' not in c.args for c in call.call_args_list))
    def test_scan_refused_is_unknown(self):
        n=m.Network('wlan0')
        with patch.object(n,'last_scan',return_value=90000),patch.object(m,'command',side_effect=[(True,'/org/freedesktop/NetworkManager/Devices/2'),(False,'')]):self.assertIsNone(n.visible('TEST-WLAN'))
    def test_timeout(self):
        with patch.object(m.subprocess,'run',side_effect=subprocess.TimeoutExpired('nmcli',1)):self.assertEqual(m.command('nmcli'),(False,''))
    def test_new_config_timing_and_secret_validation(self):
        cfg={'interface':'wlan0','starlink_ssid':'TEST-WLAN','ap_ssid':'TEST-AP','starlink_password':'fake-only-password','ap_password':'fake-only-ap-password'}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'network.json';p.write_text(json.dumps(cfg));read=m.read_config(p);self.assertEqual(read['scan_interval'],60);self.assertEqual(read['probe_interval'],180)
            p.write_text('{}')
            with self.assertRaises(ValueError):m.read_config(p)
    def test_ready_after_selection(self):
        events=[];self.c.heartbeat=events.append
        with patch.object(self.c,'step',side_effect=StopIteration):
            with self.assertRaises(StopIteration):self.c.run()
        self.assertEqual(events[-1],'READY=1');self.assertEqual(self.n.current,m.AP)
    def test_rescue_does_not_race_startup(self):
        with patch.object(m,'read_config',return_value={'interface':'wlan0'}),patch.object(m,'Network',return_value=self.n),patch.object(m,'command',return_value=(True,'activating')),patch.object(m,'__name__','controller'),patch('sys.argv',['controller','--rescue']):m.main()
        self.assertEqual(self.n.calls,[])

if __name__=='__main__':unittest.main()
