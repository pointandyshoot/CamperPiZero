"""Isolated, bounded BLE operation using an existing tested virtual environment."""
import argparse
import asyncio
import json
import logging
import resource
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from ble_soak import ReadFailure, config_check, read_bluetti, read_smartbat, read_aranet, validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--device', choices=('bluetti', 'smartbat', 'aranet'), required=True)
    parser.add_argument('--ac', choices=('on', 'off'))
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    progress = {'stage': 'setup'}
    try:
        config = json.loads(Path(args.config).read_text())
        config_check(config)
        if args.ac and args.device != 'bluetti':
            raise ValueError('AC requires BLUETTI')
        if args.device == 'bluetti':
            operation = read_bluetti(config, progress, None if not args.ac else args.ac == 'on')
        else:
            operation = {'smartbat': read_smartbat, 'aranet': read_aranet}[args.device](config, progress)
        data = asyncio.run(asyncio.wait_for(operation, timeout=85 if args.ac else {'bluetti':65,'smartbat':55,'aranet':30}[args.device]))
        result = {'ok':True, 'data':validate(args.device, data)}
    except Exception as exc:
        result = {'ok':False, 'error':type(exc).__name__, 'stage':progress['stage']}
        if isinstance(exc, ReadFailure):
            result['error_code'] = exc.code
    result['peak_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
