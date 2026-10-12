"""Checkpointed single-worker city campaign: discovery, subdivision, then details."""
import argparse
import hashlib
import json
import math
import os
import signal
import subprocess
import time
from pathlib import Path

from discovery_store import Store, contains

KEYWORDS = ["Restaurant", "Café", "Döner", "Imbiss", "Pizzeria", "Bar", "Bäckerei"]


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


def cell_tasks(geometry):
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
                for keyword in KEYWORDS:
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
    def __init__(self, database, output, boundary):
        self.store = Store(database)
        self.db = self.store.db
        self.database = str(Path(database).resolve())
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.boundary = str(Path(boundary).resolve())
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
                  "max_depth": 2, "min_cell_km": 0.25, "scroll_budget": 20, "single_worker": True}
        self.config = config
        existing = self.db.execute("SELECT config_json FROM campaign_config WHERE id=1").fetchone()
        if existing and json.loads(existing[0]) != config:
            raise ValueError("Existing campaign config differs; preserve it and use another database")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("INSERT OR IGNORE INTO campaign_config VALUES(1,?)", (json.dumps(config, sort_keys=True),))
            if not existing:
                for task in cell_tasks(geometry):
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
                "saturated_at_minimum": self.db.execute("SELECT count(*) FROM campaign_jobs WHERE status='done' AND saturated=1 AND json_extract(task_json,'$.depth')=2").fetchone()[0],
                "inventory": self.store.stats(), "config": self.config}

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
    args = parser.parse_args()
    campaign = Campaign(args.database, args.output, args.boundary)
    try:
        if args.run:
            campaign.run(args.parser)
        else:
            print(json.dumps(campaign.status(), ensure_ascii=False))
    finally:
        campaign.db.close()


if __name__ == '__main__':
    main()
