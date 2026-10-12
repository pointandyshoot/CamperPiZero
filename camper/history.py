"""SQLite time series with composable count/sum/min/max summaries and gaps."""
import math
import sqlite3
import threading
import time
import uuid


class History:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.executescript('''
          PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
          PRAGMA cache_size=-2048; PRAGMA wal_autocheckpoint=256;
          CREATE TABLE IF NOT EXISTS points (
            metric TEXT, t INTEGER, value REAL, trusted INTEGER,
            PRIMARY KEY(metric,t));
          CREATE TABLE IF NOT EXISTS buckets (
            resolution INTEGER, metric TEXT, t INTEGER, n INTEGER, total REAL,
            low REAL, high REAL, last_t INTEGER, last REAL, trusted INTEGER,
            PRIMARY KEY(resolution,metric,t));
          CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, t INTEGER, desired INTEGER, status TEXT);
          CREATE TABLE IF NOT EXISTS observations (
            session TEXT, device TEXT, elapsed REAL, wall REAL, trusted INTEGER,
            PRIMARY KEY(session,device,elapsed));
          CREATE INDEX IF NOT EXISTS observations_time ON observations(wall);
          CREATE INDEX IF NOT EXISTS points_time ON points(t);
          CREATE INDEX IF NOT EXISTS buckets_time ON buckets(resolution,t);
        ''')
        self.last_purge = float("-inf")
        self.last_clock_trusted = False
        self.row_limits = {"points":750000,"buckets":1200000,"observations":100000,"events":10000}
        self.session = uuid.uuid4().hex
        self.started = time.monotonic()

    def record(self, device, data, timestamp, trusted=False):
        t = int(timestamp)
        with self.lock, self.db:
            self.db.execute("INSERT INTO observations VALUES (?,?,?,?,?)",(self.session,device,time.monotonic()-self.started,t,int(trusted)))
            for key, value in data.items():
                if isinstance(value, bool) or not isinstance(value, (float,int)) or not math.isfinite(value):
                    continue
                if key in ('age_seconds','interval_seconds','runtime_seconds'):
                    continue
                metric = device + '.' + key
                changed = self.db.execute('INSERT OR IGNORE INTO points VALUES (?,?,?,?)',
                                          (metric,t,value,int(trusted))).rowcount
                if not changed:
                    continue
                for resolution in (300,3600):
                    self.db.execute('''INSERT INTO buckets VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(resolution,metric,t) DO UPDATE SET
                       n=n+1, total=total+excluded.total, low=min(low,excluded.low),
                       high=max(high,excluded.high),
                       last=CASE WHEN excluded.last_t>=last_t THEN excluded.last ELSE last END,
                       last_t=max(last_t,excluded.last_t), trusted=min(trusted,excluded.trusted)''',
                       (resolution,metric,t//resolution*resolution,1,value,value,value,t,value,int(trusted)))

    def purge(self, now, trusted):
        # Time-based deletion needs a trusted wall clock; row caps do not.
        mono=time.monotonic()
        if mono-self.last_purge < 3600 and not (trusted and not self.last_clock_trusted):
            return
        with self.lock, self.db:
            if trusted:
                self.db.execute('DELETE FROM points WHERE t<?',(int(now)-14*86400,))
                self.db.execute('DELETE FROM buckets WHERE resolution=300 AND t<?',(int(now)-90*86400,))
                self.db.execute('DELETE FROM buckets WHERE resolution=3600 AND t<?',(int(now)-730*86400,))
                self.db.execute('DELETE FROM events WHERE t<?',(int(now)-90*86400,))
                self.db.execute('DELETE FROM observations WHERE wall<?',(int(now)-14*86400,))
            for table,limit in self.row_limits.items():
                # Table names/limits are fixed program constants, never HTTP input.
                self.db.execute(f'DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} ORDER BY rowid DESC LIMIT -1 OFFSET ?)',(limit,))
            self.last_purge = mono
            self.last_clock_trusted = trusted

    def chart(self, metric, start, end, max_points=400):
        if not 1 <= max_points <= 400 or not start < end or end-start > 730*86400:
            raise ValueError('Invalid chart range')
        span = end-start
        resolution = 0 if span <= 14*86400 else 300 if span <= 90*86400 else 3600
        width = max(60 if not resolution else resolution, math.ceil(span/max_points))
        with self.lock:
            if not resolution:
                rows = self.db.execute('SELECT t,1,value,value,value,t,value,trusted FROM points WHERE metric=? AND t>=? AND t<=? ORDER BY t',(metric,start,end)).fetchall()
            else:
                rows = self.db.execute('SELECT t,n,total,low,high,last_t,last,trusted FROM buckets WHERE resolution=? AND metric=? AND t>=? AND t<=? ORDER BY t',(resolution,metric,start,end)).fetchall()
        grouped = {}
        for t,n,total,low,high,last_t,last,trusted in rows:
            index = min(max_points-1, int((t-start)//width))
            bucket = grouped.setdefault(index, {'t':int(start+index*width),'count':0,'sum':0.,'min':low,'max':high,'last':last,'last_t':last_t,'trusted':True})
            bucket['count'] += n
            bucket['sum'] += total
            bucket['min'] = min(bucket['min'],low)
            bucket['max'] = max(bucket['max'],high)
            if last_t >= bucket['last_t']:
                bucket['last_t'],bucket['last'] = last_t,last
            bucket['trusted'] = bucket['trusted'] and bool(trusted)
        result=[]
        for index in range(min(max_points,math.ceil(span/width))):
            b=grouped.get(index)
            if b:
                b['mean']=b.pop('sum')/b['count']
                result.append(b)
            else:
                result.append({'t':int(start+index*width),'mean':None,'min':None,'max':None,'count':0,'trusted':True})
        return {'metric':metric,'bucket_seconds':width,'points':result}

    def event(self, job, timestamp):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO events VALUES (?,?,?,?)',(job['id'],int(timestamp),int(job['desired']),job['status']))

    def close(self):
        with self.lock:
            self.db.close()
