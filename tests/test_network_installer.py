import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('installer',ROOT/'tools/install_network_patch.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def test_repeat_install_preserves_secrets_and_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            targets={name:base/name for name in m.TARGETS}
            cfg={'interface':'wlan0','starlink_ssid':'TEST-WLAN','ap_ssid':'TEST-AP','starlink_password':'fake-only-password','ap_password':'fake-only-ap-password'}
            targets['controller.py'].write_text('# old controller\n')
            targets['camper-network.service'].write_text('# old unit\n')
            targets['network.json'].write_text(json.dumps(cfg))
            def paths(value):
                return base/'backups' if str(value)=='/var/backups/camper-network' else Path(value)
            with patch.object(m,'TARGETS',targets),patch.object(m,'Path',side_effect=paths),patch.object(m.os,'geteuid',return_value=0),patch.object(m.shutil,'which',return_value='/bin/fake'),patch.object(m,'run'):
                with patch('sys.argv',['installer','--check']):m.main()
                self.assertEqual(json.loads(targets['network.json'].read_text()),cfg)
                with patch('sys.argv',['installer']):m.main();m.main()
                current=json.loads(targets['network.json'].read_text())
                for k,v in cfg.items():self.assertEqual(current[k],v)
                self.assertEqual(current['probe_interval'],180)
                self.assertEqual(current['scan_interval'],60)
                self.assertEqual(current['maximum_backoff'],600)
                self.assertEqual(targets['network.json'].stat().st_mode & 0o777,0o600)
                backups=sorted((base/'backups').iterdir())
                self.assertEqual(len(backups),2)
                m.restore(backups[0])
                self.assertEqual(json.loads(targets['network.json'].read_text()),cfg)
                self.assertEqual(targets['controller.py'].read_text(),'# old controller\n')

if __name__=='__main__':unittest.main()
