"""Checkpointed city campaign with rate-budgeted parallel discovery and details."""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from discovery_store import Store, contains

KEYWORDS = ["Restaurant", "Café", "Döner", "Imbiss", "Pizzeria", "Bar", "Bäckerei"]


def resource_pressure():
    """Optional Linux container measurements; absence does not block other hosts."""
    memory_fraction = 0
    try:
        memory = int(Path('/sys/fs/cgroup/memory.current').read_text())
        maximum = Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if maximum != 'max':
            memory_fraction = memory / int(maximum)
    except (OSError, ValueError):
        pass
    cpus = os.cpu_count() or 1
    try:
        quota = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota[0] != 'max':
            cpus = int(quota[0]) / int(quota[1])
    except (OSError, ValueError):
        pass
    load = os.getloadavg()[0] if hasattr(os, 'getloadavg') else 0
    return memory_fraction, load, cpus


def segment_hits_box(a, b, box):
    low, high = 0.0, 1.0
    for axis in range(2):
        delta = b[axis] - a[axis]
        if delta == 0:
            if not box[axis] <= a[axis] <= box[axis + 2]:
                return False
        else:
            start, end = sorted(((box[axis] - a[axis]) / delta, (box[axis + 2] - a[axis]) / delta))
            low, high = max(low, start), min(high, end)
            if low > high:
                return False
    return True


def intersects(geometry, box):
    corners = [(box[0], box[1]), (box[0], box[3]), (box[2], box[1]), (box[2], box[3])]
    if any(contains(geometry, corner) for corner in corners):
        return True
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return any(segment_hits_box(a, b, box) for polygon in polygons for ring in polygon for a, b in zip(ring, ring[1:] + ring[:1]))


def geometry_bounds(geometry):
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    points = [point for polygon in polygons for ring in polygon for point in ring]
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def cell_tasks(geometry, keywords=None):
    west, south, east, north = geometry_bounds(geometry)
    lat_step = 1 / 111.32
    lon_step = 1 / (111.32 * math.cos(math.radians((south + north) / 2)))
    # Quarter-kilometre margin avoids dropping discoveries along the preliminary border.
    south -= lat_step / 4
    west -= lon_step / 4
    rows = math.ceil((north + lat_step / 4 - south) / lat_step)
    columns = math.ceil((east + lon_step / 4 - west) / lon_step)
    tasks = []
    for row in range(rows):
        for column in range(columns):
            box = [west + column * lon_step, south + row * lat_step,
                   west + (column + 1) * lon_step, south + (row + 1) * lat_step]
            expanded = [box[0] - lon_step / 4, box[1] - lat_step / 4, box[2] + lon_step / 4, box[3] + lat_step / 4]
            if intersects(geometry, expanded):
                for keyword in (keywords or KEYWORDS):
                    tasks.append({"name": f"munich-{row}-{column}", "lat": (box[1] + box[3]) / 2,
                                  "lon": (box[0] + box[2]) / 2, "zoom": 16, "keyword": keyword,
                                  "box": box, "depth": 0})
    return tasks


def children(task):
    west, south, east, north = task["box"]
    mid_lon, mid_lat = (west + east) / 2, (south + north) / 2
    return [{**task, "name": f"{task['name']}-{i}", "lat": (box[1] + box[3]) / 2,
             "lon": (box[0] + box[2]) / 2, "box": box, "zoom": task["zoom"] + 1,
             "depth": task["depth"] + 1}
            for i, box in enumerate([[west, south, mid_lon, mid_lat], [mid_lon, south, east, mid_lat],
                                     [west, mid_lat, mid_lon, north], [mid_lon, mid_lat, east, north]])]


class Campaign:
    def __init__(self, database, output, boundary, profile='city'):
        self.store = Store(database)
        self.db = self.store.db
        self.database = str(Path(database).resolve())
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.boundary = str(Path(boundary).resolve())
        self.profile = profile
        raw = Path(boundary).read_bytes()
        document = json.loads(raw)
        geometry = document.get("geometry", document)
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("Invalid campaign boundary")
        self.bounds = geometry_bounds(geometry)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS campaign_config(id INTEGER PRIMARY KEY, config_json TEXT);
          CREATE TABLE IF NOT EXISTS campaign_jobs(
            id TEXT PRIMARY KEY, task_json TEXT, parent TEXT, status TEXT DEFAULT 'pending',
            attempts INTEGER DEFAULT 0, next_attempt REAL DEFAULT 0, count INTEGER,
            saturated INTEGER, last_error TEXT, finished_at REAL);
        """)
        config = {"version": 1, "boundary_sha256": hashlib.sha256(raw).hexdigest(),
                  "boundary_status": "preliminary", "keywords": KEYWORDS, "base_cell_km": 1,
                  "max_depth": 2, "min_cell_km": 0.25, "scroll_budget": 20}
        if profile == 'neighborhood':
            config.update(keywords=['Restaurant', 'Café', 'Imbiss', 'Döner', 'Pizzeria', 'Bäckerei'],
                          max_depth=0, min_cell_km=1, boundary_status='user_requested_radius')
        self.config = config
        existing = self.db.execute("SELECT config_json FROM campaign_config WHERE id=1").fetchone()
        previous = json.loads(existing[0]) if existing else None
        if previous:
            previous.pop('single_worker', None)  # Legacy runtime setting, not a search-plan change.
        if existing and previous != config:
            raise ValueError("Existing campaign config differs; preserve it and use another database")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("INSERT OR IGNORE INTO campaign_config VALUES(1,?)", (json.dumps(config, sort_keys=True),))
            self.db.execute("UPDATE campaign_config SET config_json=? WHERE id=1", (json.dumps(config, sort_keys=True),))
            if not existing:
                for task in cell_tasks(geometry, config['keywords']):
                    self.enqueue(task)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def enqueue(self, task, parent=None):
        encoded = json.dumps(task, sort_keys=True, ensure_ascii=False)
        identifier = hashlib.sha256(encoded.encode()).hexdigest()
        self.db.execute("INSERT OR IGNORE INTO campaign_jobs(id,task_json,parent) VALUES(?,?,?)", (identifier, encoded, parent))

    def complete(self, identifier, task, count, end_of_list):
        saturated = count >= 120 or not end_of_list
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if saturated and task["depth"] < self.config["max_depth"]:
                for child in children(task):
                    self.enqueue(child, identifier)
            self.db.execute("UPDATE campaign_jobs SET status='done',count=?,saturated=?,finished_at=? WHERE id=?", (count, saturated, time.time(), identifier))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def status(self):
        return {"campaign": dict(self.db.execute("SELECT status,count(*) FROM campaign_jobs GROUP BY status").fetchall()),
                "saturated_at_minimum": self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status='done' AND saturated=1 AND json_extract(task_json,'$.depth')=?", (self.config['max_depth'],)).fetchone()[0],
                "inventory": self.store.stats(), "config": self.config,
                "network": dict(self.db.execute('SELECT * FROM network_gate WHERE id=1').fetchone())}

    def claim_search(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute("SELECT * FROM campaign_jobs WHERE status='pending' AND attempts<3 AND next_attempt<=? ORDER BY json_extract(task_json,'$.depth'),id LIMIT 1", (time.time(),)).fetchone()
            if row:
                self.db.execute("UPDATE campaign_jobs SET status='running',attempts=attempts+1 WHERE id=?", (row['id'],))
            self.db.execute('COMMIT')
            return dict(row) if row else None
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def parallel_lane(self, lane, stopping, parser, worker_limit=None):
        scripts = Path(__file__).resolve().parent
        captured_searches = 0
        while not stopping.is_set():
            if worker_limit is not None and lane >= worker_limit['workers']:
                stopping.wait(3)
                continue
            if self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status='paused'").fetchone()[0]:
                stopping.set()
                return
            if self.db.execute('SELECT halted FROM network_gate WHERE id=1').fetchone()[0]:
                stopping.set()
                return
            job = self.claim_search()
            if job:
                task = json.loads(job['task_json'])
                directory = self.output / 'searches' / job['id']
                directory.mkdir(parents=True, exist_ok=True)
                plan = directory / 'plan.json'
                plan.write_text(json.dumps({'plan': [task], 'maxScrolls': 20}, ensure_ascii=False))
                command = ['node', str(scripts / 'munich_discovery_pilot.cjs'), str(directory), '--plan', str(plan), '--store', self.database, '--boundary', self.boundary, '--lane', str(lane)]
                with (directory / 'worker.log').open('a') as log:
                    result = subprocess.run(command, stdout=log, stderr=log)
                if result.returncode:
                    # Only inspect this attempt's checkpoint; logs can include older failures.
                    error = (directory / 'worker.log').read_text()[-1500:]
                    checkpoint = directory / 'discovery.json'
                    if checkpoint.exists():
                        records = json.loads(checkpoint.read_text())['searches']
                        if records:
                            error = json.dumps(records[-1], ensure_ascii=False)[-3000:]
                    blocked = any(word in error.lower() for word in ('challenge', 'access block', 'rate limit', '"status": 403', '"status": 429', 'eexist'))
                    attempts = job['attempts'] + 1
                    state = 'paused' if blocked else 'failed' if attempts >= 3 else 'pending'
                    self.db.execute("UPDATE campaign_jobs SET status=?,next_attempt=?,last_error=? WHERE id=?", (state, time.time() + 120 * attempts, error, job['id']))
                    if blocked:
                        stopping.set()
                        return
                    stopping.wait(15)
                    continue
                record = next(r for r in json.loads((directory / 'discovery.json').read_text())['searches'] if r['status'] == 'completed')
                self.complete(job['id'], task, len(record['places']), record.get('endOfList', False))
                captured_searches += 1
                if self.profile == 'neighborhood' and captured_searches % 4 == 0 and not stopping.is_set():
                    # Small-area maps become useful before the entire search pass ends.
                    # The lane's browser lock is released; detail leases remain global.
                    west, south, east, north = self.bounds
                    directory = self.output / 'details' / f'lane-{lane}'
                    directory.mkdir(parents=True, exist_ok=True)
                    with (directory / 'worker.log').open('a') as log:
                        result = subprocess.run(['node', str(scripts / 'munich_detail_worker.cjs'), self.database, str(directory), str(Path(parser).resolve()), '--limit', '5', '--bbox', f'{south},{west},{north},{east}', '--lane', str(lane)], stdout=log, stderr=log)
                    if result.returncode and self.db.execute('SELECT halted FROM network_gate WHERE id=1').fetchone()[0]:
                        stopping.set()
                        return
                stopping.wait(15)
                continue
            remaining = self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status IN ('pending','running')").fetchone()[0]
            if remaining:
                stopping.wait(3)
                continue
            west, south, east, north = self.bounds
            directory = self.output / 'details' / f'lane-{lane}'
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / 'worker.log').open('a') as log:
                result = subprocess.run(['node', str(scripts / 'munich_detail_worker.cjs'), self.database, str(directory), str(Path(parser).resolve()), '--limit', '20', '--bbox', f'{south},{west},{north},{east}', '--lane', str(lane)], stdout=log, stderr=log)
            if result.returncode:
                error = (directory / 'worker.log').read_text()[-1500:].lower()
                if self.db.execute('SELECT halted FROM network_gate WHERE id=1').fetchone()[0] or any(word in error for word in ('identity', 'different place', 'eexist', 'lease expired')):
                    stopping.set()
                    return
                stopping.wait(15)  # Failed detail job already has durable retry backoff.
                continue
            report = json.loads((directory / 'run.json').read_text())
            if not report['completed']:
                pending = self.db.execute("SELECT count(*) FROM details JOIN places ON id=place_id WHERE scope='inside' AND state IN ('pending','retry','leased')").fetchone()[0]
                if not pending:
                    return
                stopping.wait(15)

    def run_parallel(self, parser, workers, initial_workers=None):
        if not 2 <= workers <= 50:
            raise ValueError('Worker count must be 2–50')
        if not 2 <= (initial_workers or workers) <= workers:
            raise ValueError('Initial workers must be between 2 and the worker ceiling')
        lock = self.database + '.campaign.lock'
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, json.dumps({'pid': os.getpid()}).encode())
        stopping = threading.Event()
        worker_limit = {'workers': initial_workers or workers}
        baseline_done = self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status='done'").fetchone()[0]
        prior_retries = self.db.execute('SELECT coalesce(sum(max(attempts-1,0)),0) FROM campaign_jobs').fetchone()[0]
        last_adjusted = time.time()
        interrupted = False

        def stop(signum, frame):
            nonlocal interrupted
            interrupted = True
            stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        def lane_work(lane):
            campaign = Campaign(self.database, self.output, self.boundary, self.profile)
            try:
                campaign.parallel_lane(lane, stopping, parser, worker_limit)
            except Exception:
                stopping.set()
                raise
            finally:
                campaign.db.close()

        try:
            if self.db.execute('SELECT halted FROM network_gate WHERE id=1').fetchone()[0]:
                self.write_status('paused', workers=workers)
                return
            # Recover only when no prior browser worker remains alive.
            for worker_lock in Path(self.database).parent.glob(Path(self.database).name + '.maps*-worker.lock'):
                worker_pid = json.loads(worker_lock.read_text())['pid']
                try:
                    os.kill(worker_pid, 0)
                except ProcessLookupError:
                    worker_lock.unlink()
                else:
                    raise RuntimeError(f'Existing browser worker {worker_pid}; preserve its jobs')
            self.db.execute("UPDATE campaign_jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END WHERE status='running'")
            if self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status='paused'").fetchone()[0]:
                self.write_status('paused', workers=workers)
                return
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(lane_work, lane) for lane in range(workers)]
                while not all(f.done() for f in futures):
                    searching = self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status IN ('pending','running')").fetchone()[0]
                    memory_fraction, load, cpus = resource_pressure()
                    done = self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status='done'").fetchone()[0]
                    retries = self.db.execute('SELECT coalesce(sum(max(attempts-1,0)),0) FROM campaign_jobs').fetchone()[0]
                    if (memory_fraction > .85 or retries > prior_retries) and time.time() - last_adjusted >= 15:
                        worker_limit['workers'] = max(2, worker_limit['workers'] // 2)
                        last_adjusted = time.time()
                    elif done - baseline_done >= (initial_workers or workers) and memory_fraction < .65 and time.time() - last_adjusted >= 90:
                        worker_limit['workers'] = workers
                        last_adjusted = time.time()
                    prior_retries = retries
                    # Idle lanes exit once the active lanes finish every phase.
                    if not searching and not self.db.execute("SELECT count(*) FROM details JOIN places ON id=place_id WHERE scope='inside' AND state IN ('pending','retry','leased')").fetchone()[0]:
                        worker_limit['workers'] = workers
                    self.write_status('stopping' if stopping.is_set() else 'discovery' if searching else 'details', workers=worker_limit['workers'], worker_ceiling=workers, memory_fraction=memory_fraction, cpu_load_1m=load, cpu_quota=cpus, retry_count=retries)
                    time.sleep(3)
                for future in futures:
                    future.result()
            paused = self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status='paused'").fetchone()[0]
            gaps = self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status!='done'").fetchone()[0] + self.db.execute("SELECT count(*) FROM details WHERE state='failed'").fetchone()[0]
            self.write_status('stopped' if interrupted else 'paused' if paused or stopping.is_set() else 'finished_with_gaps' if gaps or self.status()['saturated_at_minimum'] else 'planned_jobs_finished', workers=workers)
        finally:
            os.close(descriptor)
            os.unlink(lock)

    def write_status(self, state, **extra):
        value = {"state": state, "pid": os.getpid(), "updated_at": time.time(), **self.status(), **extra}
        target = self.output / "status.json"
        temporary = target.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temporary.replace(target)

    def run(self, parser):
        lock = self.database + '.campaign.lock'
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, json.dumps({"pid": os.getpid()}).encode())
        stopping = False

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        scripts = Path(__file__).resolve().parent
        try:
            if self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status='paused'").fetchone()[0]:
                self.write_status('paused')
                return
            self.db.execute("UPDATE campaign_jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END WHERE status='running'")
            self.store.classify(self.boundary)
            while not stopping:
                job = self.db.execute("SELECT * FROM campaign_jobs WHERE status='pending' AND attempts<3 AND next_attempt<=? ORDER BY json_extract(task_json,'$.depth'),id LIMIT 1", (time.time(),)).fetchone()
                if job:
                    task = json.loads(job['task_json'])
                    directory = self.output / 'searches' / job['id']
                    directory.mkdir(parents=True, exist_ok=True)
                    plan = directory / 'plan.json'
                    plan.write_text(json.dumps({"plan": [task], "maxScrolls": 20}, ensure_ascii=False))
                    self.db.execute("UPDATE campaign_jobs SET status='running',attempts=attempts+1 WHERE id=?", (job['id'],))
                    self.write_status('discovery', active_search=task)
                    command = ['node', str(scripts / 'munich_discovery_pilot.cjs'), str(directory), '--plan', str(plan), '--store', self.database, '--boundary', self.boundary]
                    with (directory / 'worker.log').open('a') as log:
                        result = subprocess.run(command, stdout=log, stderr=log)
                    if result.returncode:
                        error = (directory / 'worker.log').read_text()[-3000:]
                        checkpoint = directory / 'discovery.json'
                        if checkpoint.exists():
                            failed = json.loads(checkpoint.read_text())['searches']
                            if failed:
                                error += '\n' + json.dumps(failed[-1].get('deniedResponses', []))
                        blocked = any(word in error.lower() for word in ('challenge', 'access block', 'rate limit', '"status": 403', '"status": 429', 'eexist'))
                        attempts = job['attempts'] + 1
                        state = 'paused' if blocked else 'failed' if attempts >= 3 else 'pending'
                        self.db.execute("UPDATE campaign_jobs SET status=?,next_attempt=?,last_error=? WHERE id=?", (state, time.time() + 120 * attempts, error, job['id']))
                        self.write_status('paused' if blocked else 'retry_wait', last_error=error)
                        if blocked:
                            return
                        continue
                    checkpoint = json.loads((directory / 'discovery.json').read_text())
                    record = next(r for r in checkpoint['searches'] if r['status'] == 'completed')
                    self.complete(job['id'], task, len(record['places']), record.get('endOfList', False))
                    self.write_status('discovery')
                    # One search at a time; each browser search itself takes ~70 seconds.
                    for _ in range(15):
                        if stopping:
                            break
                        time.sleep(1)
                    continue
                remaining = self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status IN ('pending','running','paused')").fetchone()[0]
                if remaining:
                    if self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status='paused'").fetchone()[0]:
                        self.write_status('paused')
                        return
                    self.write_status('retry_wait')
                    time.sleep(15)
                    continue
                # Detail phase runs only after discovery, sharing its browser lock/pacing file.
                west, south, east, north = self.bounds
                bbox = f'{south},{west},{north},{east}'
                self.write_status('details')
                directory = self.output / 'details'
                directory.mkdir(exist_ok=True)
                with (directory / 'worker.log').open('a') as log:
                    result = subprocess.run(['node', str(scripts / 'munich_detail_worker.cjs'), self.database, str(directory), str(Path(parser).resolve()), '--limit', '20', '--bbox', bbox], stdout=log, stderr=log)
                if result.returncode:
                    self.write_status('paused', last_error=(directory / 'worker.log').read_text()[-3000:])
                    return
                report = json.loads((directory / 'run.json').read_text())
                if not report['completed']:
                    pending = self.db.execute("SELECT count(*) FROM details JOIN places ON id=place_id WHERE scope='inside' AND state IN ('pending','retry','leased')").fetchone()[0]
                    if pending:
                        time.sleep(15)
                        continue
                    unresolved = self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status!='done'").fetchone()[0]
                    failed_details = self.db.execute("SELECT count(*) FROM details WHERE state='failed'").fetchone()[0]
                    self.write_status('finished_with_gaps' if unresolved or failed_details or self.status()['saturated_at_minimum'] else 'planned_jobs_finished')
                    return
            self.write_status('stopped')
        finally:
            os.close(descriptor)
            os.unlink(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    parser.add_argument('output')
    parser.add_argument('boundary')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--parser', default='bin/parse-place')
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--initial-workers', type=int)
    parser.add_argument('--profile', choices=['city', 'neighborhood'], default='city')
    args = parser.parse_args()
    campaign = Campaign(args.database, args.output, args.boundary, args.profile)
    try:
        if args.run:
            if args.workers == 1:
                campaign.run(args.parser)
            else:
                campaign.run_parallel(args.parser, args.workers, args.initial_workers)
        else:
            print(json.dumps(campaign.status(), ensure_ascii=False))
    finally:
        campaign.db.close()


if __name__ == '__main__':
    main()
