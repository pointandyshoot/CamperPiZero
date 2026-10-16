#!/usr/bin/env python3
"""Install the local dashboard without modifying Wi-Fi, SSH or existing BLE environments."""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from camper.app import load_config
from tools.ble_soak import config_check

PIN='50029b7ab059a854aa68dd36e59306f732e219b2'


def prepare_config(source,existing):
    if existing.exists():
        return load_config(existing),False  # Never overwrite existing private device configuration.
    cfg=json.loads(source.read_text());config_check(cfg)
    if not cfg.get('bluetti_name'):raise ValueError('Set the exact full bluetti_name first')
    cfg['theme_labels']={'camper':'Camper','rose':'Rose','cyberpunk':'Cyberpunk'}
    return cfg,True


def atomic_json(path,value,uid,gid):
    fd,temp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as file:json.dump(value,file,indent=2);file.write('\n')
        os.chmod(temp,0o600);os.chown(temp,uid,gid);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def unit_for(user,base):
    # Unit quoting is explicit; usernames and paths are checked by the installer.
    return f'''[Unit]
Description=Camper local BLE dashboard and recorder
After=bluetooth.service NetworkManager.service
Wants=bluetooth.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User={user}
WorkingDirectory=/opt/camper-zero
ExecStart=/usr/bin/python3 -u -m camper.app --config /etc/camper-zero/config.json --base "{base}" --data /var/lib/camper-zero --port 8080
Restart=on-failure
RestartSec=10
TimeoutStopSec=20
KillMode=control-group
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/camper-zero
PrivateTmp=true
TasksMax=64
Environment=PYTHONDONTWRITEBYTECODE=1

[Install]
WantedBy=multi-user.target
'''


def switch_release(stage,target,backup,unit_path,new_unit,activate,recover):
    old=target.exists()
    previous=unit_path.read_bytes() if unit_path.exists() else None
    if old:os.replace(target,backup/'code')
    try:
        os.replace(stage,target)
        unit_path.write_text(new_unit)
        activate()
    except Exception:
        if target.exists():shutil.rmtree(target)
        if old:os.replace(backup/'code',target)
        if previous is not None:unit_path.write_bytes(previous)
        else:unit_path.unlink(missing_ok=True)
        recover(old and previous is not None)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user',default=os.environ.get('SUDO_USER'))
    parser.add_argument('--base',type=Path)
    parser.add_argument('--devices',type=Path)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--rose-label',default='Rose')
    parser.add_argument('--cyberpunk-label',default='Cyberpunk')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('Run using sudo')
    if not args.user or args.user=='root':parser.error('Supply --user with your normal SSH username')
    account=pwd.getpwnam(args.user);base=(args.base or Path(account.pw_dir)/'camper-ble-test').resolve()
    source=args.devices or base/'devices.json';existing=Path('/etc/camper-zero/config.json')
    if any(c in str(base) for c in ('"','\n','\r','%','\\')):parser.error('Unsupported characters in base path')
    try:
        cfg=json.loads((existing if existing.exists() else source).read_text());config_check(cfg)
        if not cfg.get('bluetti_name'):raise ValueError('Exact BLUETTI name missing')
        if existing.exists():load_config(existing)
        rev=subprocess.check_output(['git','-C',str(base/'bluetti'),'rev-parse','HEAD'],text=True).strip()
        if rev!=PIN:raise ValueError('BLUETTI checkout must match tested revision')
        freezes={}
        for name,statement in [('venv','from bluetti_mqtt.bluetooth import BluetoothClient; from bluetti_mqtt.core import WriteSingleRegister'),('bms-venv','from aiobmsble.bms.ogt_bms import BMS'),('aranet-venv','from aranet4.client import Aranet4Advertisement')]:
            python=base/name/'bin/python'
            env=os.environ.copy();env['PYTHONPATH']=str(base/'bluetti');env['PYTHONDONTWRITEBYTECODE']='1'
            subprocess.run(['runuser','-u',args.user,'--',str(python),'-c',statement],env=env,check=True,timeout=40,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            freezes[name]=subprocess.check_output([str(python),'-m','pip','freeze'],text=True,timeout=30)
        if args.check:print('Preflight passed. No files or services changed.');return 0
        cfg,new=prepare_config(source,existing)
        if new:
            if any(not label or len(label)>32 or any(ord(c)<32 for c in label) for label in (args.rose_label,args.cyberpunk_label)):
                raise ValueError('Theme labels must have 1–32 printable characters')
            cfg['theme_labels']['rose']=args.rose_label
            cfg['theme_labels']['cyberpunk']=args.cyberpunk_label
        # Stop known read-only test services to prevent Bluetooth contention.
        for unit in ('camper-ble-soak.service','camper-ble-soak-check.service'):
            subprocess.run(['systemctl','stop',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if subprocess.run(['systemctl','is-active','--quiet','docker.service']).returncode==0:
            raise ValueError('Docker is active. Stop the previous stack before installing')
        target=Path('/opt/camper-zero');stage=Path('/opt/camper-zero.new-'+str(os.getpid()))
        backup=Path('/var/backups/camper-zero')/str(time.time_ns());backup.mkdir(parents=True,mode=0o700)
        stage.mkdir(mode=0o755)
        for name in ('camper','web','tools'):
            shutil.copytree(ROOT/name,stage/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for path in stage.rglob('*'):os.chmod(path,0o755 if path.is_dir() else 0o644)
        unit_path=Path('/etc/systemd/system/camper-zero.service')
        previous_unit=unit_path.read_bytes() if unit_path.exists() else None
        if existing.exists():shutil.copy2(existing,backup/'config.json')
        if previous_unit:(backup/'camper-zero.service').write_bytes(previous_unit)
        subprocess.run(['systemctl','stop','camper-zero.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        private=existing.parent;private.mkdir(mode=0o750,exist_ok=True);os.chown(private,0,account.pw_gid)
        if new:atomic_json(existing,cfg,account.pw_uid,account.pw_gid)
        data=Path('/var/lib/camper-zero');data.mkdir(mode=0o700,exist_ok=True);os.chown(data,account.pw_uid,account.pw_gid)
        for name,contents in freezes.items():
            file=data/(name+'-requirements.txt');file.write_text(contents);os.chmod(file,0o600);os.chown(file,account.pw_uid,account.pw_gid)
        def activate():
            subprocess.run(['systemctl','daemon-reload'],check=True)
            subprocess.run(['rfkill','unblock','bluetooth'],check=True)
            subprocess.run(['systemctl','enable','--now','bluetooth.service','camper-zero.service'],check=True)
            time.sleep(2)
            subprocess.run(['systemctl','is-active','--quiet','camper-zero.service'],check=True)
        def recover(was_running):
            subprocess.run(['systemctl','stop','camper-zero.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            subprocess.run(['systemctl','daemon-reload'])
            if was_running:subprocess.run(['systemctl','start','camper-zero.service'])
        switch_release(stage,target,backup,unit_path,unit_for(args.user,base),activate,recover)
        print('Installed. Open http://homeassistant.local:8080 or http://192.168.42.1:8080')
        print('Private rollback backup: '+str(backup))
        print('Inspect: sudo journalctl -u camper-zero.service -b --no-pager -n 30')
        return 0
    except (OSError,ValueError,subprocess.SubprocessError,json.JSONDecodeError) as exc:
        print('Installation failed: '+type(exc).__name__+'. Check private configuration, tested dependency paths and system services.',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
