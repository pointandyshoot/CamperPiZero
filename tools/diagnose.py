#!/usr/bin/env python3
"""Non-identifying host/service checks; no Internet required."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from ble_soak import memory
print(json.dumps(memory(),indent=2))
disk=shutil.disk_usage('/');print(f'Disk available: {disk.free/1e9:.1f} GB')
for service in ('camper-zero','bluetooth','NetworkManager','camper-network','ssh'):
    result=subprocess.run(['systemctl','is-active',service],capture_output=True,text=True)
    print(service+': '+result.stdout.strip())
print('Recent readings: sudo journalctl -u camper-zero -b --no-pager -n 30')
