#!/usr/bin/env python3
"""Create a private consistent SQLite/config backup; do not commit the output."""
import argparse
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('Run with sudo to include private network configuration')
    os.umask(0o077)
    output=args.output.expanduser().resolve()
    if output.exists():parser.error('Output already exists; choose a new filename')
    with tempfile.TemporaryDirectory(prefix='camper-backup-') as temp:
        copy=Path(temp)/'history.sqlite3'
        source=Path('/var/lib/camper-zero/history.sqlite3')
        if source.exists():
            with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as src,sqlite3.connect(copy) as dest:src.backup(dest)
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream,tarfile.open(fileobj=stream,mode='w:gz') as archive:
            for path in (Path('/etc/camper-zero'),Path('/etc/camper-ha'),Path('/etc/NetworkManager/system-connections'),Path('/usr/local/lib/camper-ha'),Path('/opt/camper-zero')):
                if path.exists():archive.add(path,arcname=str(path).lstrip('/'),filter=lambda item: None if '__pycache__' in item.name else item)
            for pattern in ('camper*.service','camper*.timer'):
                for path in Path('/etc/systemd/system').glob(pattern):archive.add(path,arcname=str(path).lstrip('/'))
            for path in Path('/usr/local/sbin').glob('camper*'):archive.add(path,arcname=str(path).lstrip('/'))
            if copy.exists():archive.add(copy,arcname='var/lib/camper-zero/history.sqlite3')
            for path in Path('/var/lib/camper-zero').glob('*-requirements.txt'):archive.add(path,arcname=str(path).lstrip('/'))
    print('Private backup created. Copy it off the microSD and keep it private.')


if __name__=='__main__':main()
