"""Local web UI, priority BLE scheduler and SQLite recorder. No third-party server."""
import argparse
from collections import deque
import contextlib
import hashlib
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

from camper.history import History
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from ble_soak import config_check, validate, memory, WORKER_LIMIT

THEME_ASSETS=Path('/etc/camper-zero/theme-assets')
ARTWORK_FILES={'power':'power.webp','solar':'solar.webp','air':'air.webp'}

METRICS = {'bluetti.soc_percent','bluetti.solar_w','bluetti.ac_input_w','bluetti.ac_output_w',
           'bluetti.dc_output_w','smartbat.soc_percent','smartbat.voltage_v','smartbat.current_a',
           'smartbat.power_w','smartbat.temperature_c','aranet.co2_ppm','aranet.temperature_c',
           'aranet.humidity_percent','aranet.pressure_hpa'}


def load_config(path):
    cfg=json.loads(Path(path).read_text())
    config_check(cfg)
    if not cfg.get('bluetti_name'):
        raise ValueError('Full BLUETTI name is required for live control')
    for key in ('auth_salt','auth_hash'):
        if not isinstance(cfg.get(key),str) or len(cfg[key]) != {'auth_salt':32,'auth_hash':64}[key]:
            raise ValueError('Missing web authentication; run the installer')
        bytes.fromhex(cfg[key])
    return cfg


def password_hash(password,salt):
    return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),200000).hex()


def run_operation(device, config_path, base, stop, desired=None):
    env=os.environ.copy();env.pop('PYTHONPATH',None)
    venv={'bluetti':'venv','smartbat':'bms-venv','aranet':'aranet-venv'}[device]
    if device=='bluetti':env['PYTHONPATH']=str(base/'bluetti')
    command=[str(base/venv/'bin/python'),'-u',str(Path(__file__).with_name('worker.py')),
             '--config',str(config_path),'--device',device]
    if desired is not None:command += ['--ac','on' if desired else 'off']
    try:
        proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,start_new_session=True)
    except OSError:
        return {'ok':False,'error':'worker_start_failed'}
    deadline=time.monotonic()+(95 if desired is not None else WORKER_LIMIT[device])
    try:
        while not stop.is_set():
            if time.monotonic()>=deadline:return {'ok':False,'error':'hard_timeout'}
            try:
                out,_=proc.communicate(timeout=min(1,max(.01,deadline-time.monotonic())))
                if proc.returncode:return {'ok':False,'error':'worker_exit'}
                result=json.loads(out)
                if type(result.get('ok')) is not bool:raise ValueError()
                if result['ok']:
                    validate(device,result['data'])
                    if desired is not None and (result['data'].get('command_confirmed') is not True or result['data'].get('ac_on') is not desired):
                        return {'ok':False,'error':'ac_readback_mismatch'}
                return result
            except subprocess.TimeoutExpired:continue
            except (ValueError,TypeError,AttributeError,KeyError):return {'ok':False,'error':'invalid_worker_output'}
        return {'ok':False,'error':'stopped'}
    finally:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):os.killpg(proc.pid,signal.SIGTERM)
            try:proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):os.killpg(proc.pid,signal.SIGKILL)
                proc.communicate()


class Core:
    def __init__(self,config_path,base,data_dir,operation=run_operation):
        self.config_path=Path(config_path);self.cfg=load_config(config_path);self.base=Path(base)
        self.data_dir=Path(data_dir);self.data_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.history=History(self.data_dir/'history.sqlite3')
        self.condition=threading.Condition();self.stop=threading.Event();self.operation=operation
        self.devices={d:{'data':None,'updated_mono':None,'failures':0,'error':None} for d in WORKER_LIMIT}
        self.jobs={};self.pending=deque();self.active=None;self.started=time.monotonic()
        self.last_aranet=None;self.clock_trusted=False
        self.sessions={};self.login_attempts=deque(maxlen=100)

    def enqueue(self,desired):
        if type(desired) is not bool:raise ValueError('Boolean state required')
        with self.condition:
            if self.pending or any(j['status']=='running' for j in self.jobs.values()):
                raise RuntimeError('An AC command is already pending')
            job={'id':secrets.token_hex(12),'desired':desired,'status':'queued','created':time.monotonic()}
            self.jobs[job['id']]=job;self.pending.append(job['id'])
            self.history.event(job,time.time());self.condition.notify_all()
            return self.public_job(job)

    @staticmethod
    def public_job(job):
        return {k:v for k,v in job.items() if k in ('id','desired','status','error')}

    def next_operation(self,due,now):
        # Called with condition held. Commands do not leapfrog an active BLE operation.
        while self.pending:
            job=self.jobs[self.pending.popleft()]
            if now-job['created']>120:
                job['status']='expired';self.history.event(job,time.time());continue
            job['status']='running';return 'bluetti',job
        device=min(due,key=due.get)
        return (device,None) if due[device]<=now else (None,None)

    def collect(self):
        due={d:time.monotonic() for d in self.devices}
        while not self.stop.is_set():
            with self.condition:
                now=time.monotonic()
                for key,job in list(self.jobs.items()):
                    if now-job['created']>3600 and job['status'] not in ('queued','running'):del self.jobs[key]
                device,job=self.next_operation(due,now)
                if device is None:
                    self.condition.wait(timeout=min(1,max(.05,min(due.values())-now)));continue
                self.active=device
            result=self.operation(device,self.config_path,self.base,self.stop,None if job is None else job['desired'])
            now=time.monotonic();wall=time.time()
            # This marker is created when systemd-timesyncd has synchronised this boot.
            self.clock_trusted=self.clock_trusted or Path('/run/systemd/timesync/synchronized').exists()
            with self.condition:
                state=self.devices[device]
                if result.get('ok'):
                    data=result['data'];state.update(data=data,updated_mono=now,failures=0,error=None)
                    sample_time=wall
                    record=True
                    if device=='aranet':
                        sample_time-=data['age_seconds']
                        if self.last_aranet is not None and abs(sample_time-self.last_aranet)<data['interval_seconds']/2:
                            record=False
                        else:self.last_aranet=sample_time
                    if record:self.history.record(device,data,sample_time,self.clock_trusted)
                    due[device]=now+{'bluetti':60,'smartbat':90,'aranet':60}[device]
                else:
                    state['failures']+=1
                    state['error']=result.get('error_code') or result.get('error','read_failed')
                    due[device]=now+min(300,60*2**min(state['failures'],3))
                if job:
                    job['status']='confirmed' if result.get('ok') else 'unconfirmed'
                    if not result.get('ok'):job['error']='State not confirmed. Check the device before trying again.'
                    self.history.event(job,wall)
                self.active=None
                print(f'{device}: {"OK" if result.get("ok") else "read failed"}'+(' · AC '+job['status'] if job else ''),flush=True)
            self.history.purge(wall,self.clock_trusted)
            # Give BlueZ time to finish disconnecting; queued commands can shorten this gap.
            with self.condition:self.condition.wait(timeout=2)

    def snapshot(self):
        with self.condition:
            now=time.monotonic();devices={}
            for name,state in self.devices.items():
                age=None if state['updated_mono'] is None else max(0,now-state['updated_mono'])
                measurement_age=age
                if name=='aranet' and age is not None:measurement_age+=state['data']['age_seconds']
                limit=180 if name=='bluetti' else 300 if name=='smartbat' else (2*state['data']['interval_seconds'] if state['data'] else 600)
                devices[name]={'data':state['data'],'age_seconds':age,'measurement_age_seconds':measurement_age,
                               'stale':measurement_age is None or measurement_age>limit,
                               'failures':state['failures'],'error':state['error']}
            jobs=[self.public_job(j) for j in self.jobs.values()]
        host=memory();disk=shutil.disk_usage(self.data_dir)
        try:temperature=int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000
        except (OSError,ValueError):temperature=None
        return {'devices':devices,'active':self.active,'jobs':jobs,'clock_synchronised':self.clock_trusted,
                'system':{**host,'load':os.getloadavg()[0],'temperature_c':temperature,'disk_free_gb':round(disk.free/1e9,1),
                          'uptime_seconds':int(time.monotonic()-self.started)},
                'theme_artwork_available':[key for key,name in ARTWORK_FILES.items() if (THEME_ASSETS/name).is_file()],
                'theme_labels':self.cfg.get('theme_labels',{'camper':'Camper','rose':'Rose','cyberpunk':'Cyberpunk'})}

    def authenticate(self,password,address):
        now=time.monotonic()
        with self.condition:
            while self.login_attempts and self.login_attempts[0][0]<now-60:self.login_attempts.popleft()
            if sum(a==address for _,a in self.login_attempts)>=5:return None
            self.login_attempts.append((now,address))
        valid=hmac.compare_digest(password_hash(password,self.cfg['auth_salt']),self.cfg['auth_hash'])
        if not valid:return None
        with self.condition:
            self.sessions={k:v for k,v in self.sessions.items() if v>now}
            if len(self.sessions)>=32:self.sessions.pop(next(iter(self.sessions)))
            token=secrets.token_urlsafe(32);self.sessions[token]=now+12*3600
        return token

    def authorised(self,cookie):
        try:
            parsed=SimpleCookie();parsed.load(cookie or '');token=parsed['camper_session'].value
        except (KeyError,TypeError):return False
        with self.condition:return self.sessions.get(token,0)>time.monotonic()


class Server(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=8
    def __init__(self,address,core):
        self.core=core;self.slots=threading.BoundedSemaphore(8)
        super().__init__(address,Handler)
    def service_actions(self):
        if hasattr(self,"collector") and not self.collector.is_alive():
            raise RuntimeError("BLE collector stopped; restart required")

    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
        try:super().process_request(request,client_address)
        except BaseException:self.slots.release();raise
    def handle_error(self,request,client_address):
        print("HTTP request interrupted",flush=True)

    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version='CamperPiZero'
    def setup(self):
        super().setup();self.connection.settimeout(10)
    def log_message(self,*args):pass  # No identifiers, passwords, request bodies or session cookies in logs.
    def send(self,status,payload,content_type='application/json',cookie=None):
        raw=json.dumps(payload,allow_nan=False).encode() if content_type=='application/json' else payload
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        path=urlsplit(self.path).path;core=self.server.core
        if path in ('/','/index.html','/style.css','/app.js'):
            name='index.html' if path=='/' else path[1:]
            mime={'index.html':'text/html; charset=utf-8','style.css':'text/css; charset=utf-8','app.js':'text/javascript; charset=utf-8'}[name]
            return self.send(200,(Path(__file__).resolve().parents[1]/'web'/name).read_bytes(),mime)
        if not core.authorised(self.headers.get('Cookie')):return self.send(401,{'error':'Sign in required'})
        if path.startswith('/theme-assets/'):
            filename=path.removeprefix('/theme-assets/')
            if filename not in ARTWORK_FILES.values():return self.send(404,{'error':'Not found'})
            try:return self.send(200,(THEME_ASSETS/filename).read_bytes(),'image/webp')
            except OSError:return self.send(404,{'error':'Artwork not installed'})
        if path=='/api/status':return self.send(200,core.snapshot())
        if path=='/api/history':
            query=parse_qs(urlsplit(self.path).query)
            try:
                metric=query['metric'][0];hours=int(query.get('hours',['24'])[0])
                if metric not in METRICS or hours not in (24,168,720,2160,17520):raise ValueError()
                end=int(time.time());return self.send(200,core.history.chart(metric,end-hours*3600,end))
            except (ValueError,KeyError):return self.send(400,{'error':'Invalid history request'})
        return self.send(404,{'error':'Not found'})
    def do_POST(self):
        core=self.server.core
        if self.headers.get('Origin')!='http://'+self.headers.get('Host',''):
            return self.send(403,{'error':'Same-origin request required'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=2048 or self.headers.get('Content-Type')!='application/json':raise ValueError()
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError()
        except (ValueError,TypeError):return self.send(400,{'error':'Invalid request'})
        path=urlsplit(self.path).path
        if path=='/api/login':
            password=data.get('password')
            if not isinstance(password,str) or len(password)>256:return self.send(400,{'error':'Invalid password'})
            token=core.authenticate(password,self.client_address[0])
            if token is None:return self.send(403,{'error':'Incorrect password or too many attempts. Wait one minute.'})
            return self.send(200,{'ok':True},cookie=f'camper_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200')
        if not core.authorised(self.headers.get('Cookie')):return self.send(401,{'error':'Sign in required'})
        if path=='/api/ac':
            try:return self.send(202,core.enqueue(data.get('on')))
            except ValueError:return self.send(400,{'error':'AC state must be boolean'})
            except RuntimeError:return self.send(409,{'error':'An AC command is already pending'})
        return self.send(404,{'error':'Not found'})


def main():
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('--config',required=True,type=Path)
    p.add_argument('--base',required=True,type=Path);p.add_argument('--data',required=True,type=Path)
    p.add_argument('--port',type=int,default=8080);p.add_argument('--check',action='store_true')
    args=p.parse_args()
    try:
        cfg=load_config(args.config)
        for name in ('venv','bms-venv','aranet-venv'):
            if not (args.base/name/'bin/python').is_file():raise ValueError('Missing BLE virtual environment')
        if args.check:print('Configuration and environment paths ready');return
        core=Core(args.config,args.base,args.data)
        server=Server(('0.0.0.0',args.port),core)
    except (ValueError,OSError,json.JSONDecodeError):
        print('Setup failed. Check private config, environment paths and port.',file=sys.stderr);return 2
    collector=threading.Thread(target=core.collect,name='BLE collector',daemon=True)
    collector.start()
    server.collector=collector
    def stop(*_):
        core.stop.set()
        with core.condition:core.condition.notify_all()
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    print(f'Local dashboard listening on port {args.port}',flush=True)
    try:
        server.serve_forever(poll_interval=.5)
    finally:
        core.stop.set()
        with core.condition:core.condition.notify_all()
        collector.join(timeout=10);server.server_close()
        if not collector.is_alive():core.history.close()
    # A dead collector must make systemd restart the complete service.
    return 1 if not collector.is_alive() and not core.stop.is_set() else 0


if __name__=='__main__':raise SystemExit(main())
