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
result=subprocess.run(['systemctl','show','camper-zero','-p','MainPID','-p','NRestarts'],capture_output=True,text=True)
properties=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
print('Service restarts: '+properties.get('NRestarts','unknown'))
try:
    pid=int(properties.get('MainPID','0'))
    if pid>0:
        status=Path(f'/proc/{pid}/status').read_text().splitlines()
        for line in status:
            if line.startswith(('VmRSS:','VmHWM:')):print('Coordinator '+line)
except (OSError,ValueError):print('Coordinator RSS unavailable')
print('Coordinator RSS excludes short-lived BLE workers; inspect host available RAM and swap too.')
print('Recent readings: sudo journalctl -u camper-zero -b --no-pager -n 30')
