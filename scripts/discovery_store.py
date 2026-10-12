"""Durable discovery inventory and fenced detail-job leases; no network requests."""
import argparse
import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs


def canonical_id(link):
    url = urlparse(link)
    match = re.search(r"!1s([^!/?]+)", unquote(url.path))
    if match:
        value = match[1]
        fid = re.fullmatch(r"0x[0-9a-f]+:0x([0-9a-f]+)", value, re.I)
        return "cid:" + str(int(fid[1], 16)) if fid else "place:" + value
    cid = parse_qs(url.query).get("cid", [None])[0]
    if cid and cid.isdecimal():
        return "cid:" + str(int(cid))
    return "url:" + url.scheme + "://" + url.netloc + url.path


def coordinates(link):
    match = re.search(r"!3d([-\d.]+)!4d([-\d.]+)", link)
    if not match:
        return None
    lat, lon = map(float, match.groups())
    return (lon, lat) if math.isfinite(lat) and math.isfinite(lon) and abs(lat) <= 90 and abs(lon) <= 180 else None


def ring_contains(point, ring):
    """Ray casting, including points on the ring boundary."""
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        ax, ay = a[:2]
        bx, by = b[:2]
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) < 1e-12 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def contains(geometry, point):
    if point is None:
        return False
    if geometry["type"] not in ("Polygon", "MultiPolygon"):
        raise ValueError("Expected a GeoJSON Polygon or MultiPolygon")
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return any(rings and ring_contains(point, rings[0]) and not any(ring_contains(point, hole) for hole in rings[1:]) for rings in polygons)


class Store:
    def __init__(self, filename):
        self.db = sqlite3.connect(filename, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS places (
                id TEXT PRIMARY KEY, title TEXT, link TEXT, lon REAL, lat REAL,
                first_seen TEXT, last_seen TEXT, scope TEXT NOT NULL DEFAULT 'unknown', boundary TEXT);
            CREATE TABLE IF NOT EXISTS sightings (
                search_key TEXT, place_id TEXT REFERENCES places(id), seen_at TEXT,
                PRIMARY KEY(search_key,place_id));
            CREATE TABLE IF NOT EXISTS searches (
                search_key TEXT PRIMARY KEY, params_json TEXT, end_of_list INTEGER,
                sampled_at TEXT, result_count INTEGER);
            CREATE TABLE IF NOT EXISTS details (
                place_id TEXT PRIMARY KEY REFERENCES places(id), state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, token TEXT, lease_until REAL,
                next_attempt REAL NOT NULL DEFAULT 0, result_json TEXT, fetched_at REAL, last_error TEXT);
            CREATE TABLE IF NOT EXISTS network_gate (
                id INTEGER PRIMARY KEY, next_visit REAL NOT NULL DEFAULT 0,
                halted INTEGER NOT NULL DEFAULT 0, reason TEXT, not_before REAL);
            INSERT OR IGNORE INTO network_gate(id) VALUES(1);
            CREATE TABLE IF NOT EXISTS place_filters (
                place_id TEXT PRIMARY KEY REFERENCES places(id), review_count INTEGER,
                permanently_closed INTEGER, observed_at TEXT, evidence_json TEXT);
        """)

    def import_checkpoint(self, filename):
        checkpoint = json.loads(Path(filename).read_text())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for search in checkpoint["searches"]:
                if search["status"] != "completed":
                    continue
                params = {key: search[key] for key in ("lat", "lon", "keyword", "zoom")}
                params.update(language="de", max_scrolls=checkpoint.get("maxScrolls", 4), viewport=[1920, 1080])
                params_json = json.dumps(params, sort_keys=True, ensure_ascii=False)
                key = hashlib.sha256(params_json.encode()).hexdigest()
                observed = search["startedAt"]
                self.db.execute("INSERT INTO searches VALUES(?,?,?,?,?) ON CONFLICT(search_key) DO UPDATE SET sampled_at=excluded.sampled_at,end_of_list=excluded.end_of_list,result_count=excluded.result_count WHERE excluded.sampled_at>=sampled_at",
                                (key, params_json, bool(search.get("endOfList")), observed, len(search["places"])))
                for place in search["places"]:
                    identifier = canonical_id(place["link"])
                    point = coordinates(place["link"]) or (None, None)
                    self.db.execute("""INSERT INTO places(id,title,link,lon,lat,first_seen,last_seen) VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET
                        title=CASE WHEN excluded.last_seen>=last_seen THEN excluded.title ELSE title END,
                        link=CASE WHEN excluded.last_seen>=last_seen THEN excluded.link ELSE link END,
                        scope=CASE WHEN excluded.last_seen<last_seen OR (lon IS excluded.lon AND lat IS excluded.lat) THEN scope ELSE 'unknown' END,
                        boundary=CASE WHEN excluded.last_seen<last_seen OR (lon IS excluded.lon AND lat IS excluded.lat) THEN boundary ELSE NULL END,
                        lon=CASE WHEN excluded.last_seen>=last_seen THEN excluded.lon ELSE lon END,
                        lat=CASE WHEN excluded.last_seen>=last_seen THEN excluded.lat ELSE lat END,
                        first_seen=min(first_seen,excluded.first_seen),last_seen=max(last_seen,excluded.last_seen)""",
                        (identifier, place["title"], place["link"], *point, observed, observed))
                    self.db.execute("INSERT INTO sightings VALUES(?,?,?) ON CONFLICT(search_key,place_id) DO UPDATE SET seen_at=max(seen_at,excluded.seen_at)", (key, identifier, observed))
                    self.db.execute("INSERT OR IGNORE INTO details(place_id) VALUES(?)", (identifier,))
                    if 'filter_evidence' in place:
                        self.apply_filter_evidence(identifier, place['filter_evidence'], observed)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def classify(self, filename):
        raw = Path(filename).read_bytes()
        boundary = hashlib.sha256(raw).hexdigest()
        document = json.loads(raw)
        geometry = document["geometry"] if document.get("type") == "Feature" else document
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("Supply one Polygon/MultiPolygon geometry or Feature")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for row in self.db.execute("SELECT id,lon,lat FROM places WHERE boundary IS NOT ? OR scope='unknown'", (boundary,)).fetchall():
                point = (row["lon"], row["lat"]) if row["lon"] is not None and row["lat"] is not None else None
                scope = "unknown" if point is None else "inside" if contains(geometry, point) else "outside"
                self.db.execute("UPDATE places SET scope=?,boundary=? WHERE id=?", (scope, boundary, row["id"]))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def apply_filter_evidence(self, identifier, evidence, observed):
        count = evidence.get('review_count')
        if type(count) is not int or count < 0:
            count = None
        closed = evidence.get('permanently_closed')
        closed = int(closed) if type(closed) is bool else None
        if count is None and closed is None:
            return
        self.db.execute('''INSERT INTO place_filters VALUES(?,?,?,?,?) ON CONFLICT(place_id) DO UPDATE SET
            review_count=coalesce(excluded.review_count,review_count),
            permanently_closed=coalesce(excluded.permanently_closed,permanently_closed),
            observed_at=excluded.observed_at,evidence_json=excluded.evidence_json
            WHERE excluded.observed_at>=observed_at''', (identifier, count, closed, observed, json.dumps(evidence)))
        row = self.db.execute('SELECT * FROM place_filters WHERE place_id=?', (identifier,)).fetchone()
        excluded = row['permanently_closed'] == 1 or (row['review_count'] is not None and row['review_count'] < 25)
        if excluded:
            self.db.execute("UPDATE details SET state='skipped' WHERE place_id=? AND state IN ('pending','retry')", (identifier,))
        else:
            self.db.execute("UPDATE details SET state='pending',attempts=0,next_attempt=0 WHERE place_id=? AND state='skipped'", (identifier,))

    def claim(self, now=None, lease_seconds=300, bbox=None):
        now = time.time() if now is None else now
        if lease_seconds <= 0:
            raise ValueError("Lease duration must be positive")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            # Exhausted/crashed attempts cannot remain leased forever.
            self.db.execute("UPDATE details SET state='failed',token=NULL,lease_until=NULL WHERE state='leased' AND lease_until<=? AND attempts>=3", (now,))
            row = self.db.execute("""SELECT d.place_id,p.link FROM details d JOIN places p ON p.id=d.place_id
                WHERE p.scope='inside' AND d.attempts<3 AND
                NOT EXISTS(SELECT 1 FROM place_filters f WHERE f.place_id=p.id AND (f.permanently_closed=1 OR f.review_count<25)) AND
                ((d.state IN ('pending','retry') AND d.next_attempt<=?) OR (d.state='leased' AND d.lease_until<=?))
                AND (? IS NULL OR (p.lat>=? AND p.lon>=? AND p.lat<=? AND p.lon<=?))
                ORDER BY d.place_id LIMIT 1""", (now, now, *( (None, None, None, None, None) if bbox is None else (1, *bbox)))).fetchone()
            job = None
            if row:
                token = uuid.uuid4().hex
                self.db.execute("UPDATE details SET state='leased',attempts=attempts+1,token=?,lease_until=? WHERE place_id=?", (token, now + lease_seconds, row["place_id"]))
                job = {**dict(row), "token": token, "lease_until": now + lease_seconds}
            self.db.execute("COMMIT")
            return job
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def finish(self, token, result=None, error=None, now=None):
        now = time.time() if now is None else now
        if (result is None) == (error is None):
            raise ValueError("Supply exactly one result or error")
        if result is not None and not isinstance(result, dict):
            raise ValueError("Detail result must be a JSON object")
        excluded = result is not None and result.get('detail_exclusion_reason') in ('under_25_reviews', 'permanently_closed')
        cursor = self.db.execute("""UPDATE details SET
            state=CASE WHEN ? IS NULL THEN CASE WHEN ? THEN 'skipped' ELSE 'done' END WHEN attempts>=3 THEN 'failed' ELSE 'retry' END,
            result_json=?,fetched_at=?,last_error=?,next_attempt=?+min(3600,60*(1 << attempts)),token=NULL,lease_until=NULL
            WHERE token=? AND state='leased' AND lease_until>?""",
            (error, excluded, json.dumps(result) if result is not None else None, now if result is not None else None, error, now, token, now))
        if cursor.rowcount != 1:
            raise ValueError("Lease expired, reclaimed, or already completed")

    def stats(self):
        return {name: dict(self.db.execute(f"SELECT {column},count(*) FROM {table} GROUP BY {column}").fetchall())
                for name, table, column in (("scope", "places", "scope"), ("details", "details", "state"))} | {
                    "places": self.db.execute("SELECT count(*) FROM places").fetchone()[0],
                    "searches": self.db.execute("SELECT count(*) FROM searches").fetchone()[0],
                    "sightings": self.db.execute("SELECT count(*) FROM sightings").fetchone()[0],
                    "exclusions": {'under_25_reviews': self.db.execute('SELECT count(*) FROM place_filters WHERE review_count<25').fetchone()[0],
                                   'permanently_closed': self.db.execute('SELECT count(*) FROM place_filters WHERE permanently_closed=1').fetchone()[0]},
                    "eligible_details": dict(self.db.execute("SELECT state,count(*) FROM details JOIN places ON place_id=id WHERE scope='inside' GROUP BY state").fetchall())}

    def reserve_visit(self, now=None, interval=2):
        now = time.time() if now is None else now
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError('Visit interval must be positive and finite')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            gate = self.db.execute('SELECT * FROM network_gate WHERE id=1').fetchone()
            if gate['halted']:
                raise ValueError('Global access block: ' + gate['reason'])
            reserved = max(now, gate['next_visit'])
            self.db.execute('UPDATE network_gate SET next_visit=? WHERE id=1', (reserved + interval,))
            self.db.execute('COMMIT')
            return {'wait_seconds': reserved - now, 'reserved_at': reserved}
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def halt_network(self, reason, retry_after=None, now=None):
        now = time.time() if now is None else now
        deadline = now + 900  # Cooldown floor; resumption still requires inspecting the cause.
        if retry_after:
            try:
                delay = float(retry_after)
                if math.isfinite(delay) and delay >= 0 and math.isfinite(now + delay):
                    deadline = max(deadline, now + delay)
            except ValueError:
                try:
                    deadline = max(deadline, parsedate_to_datetime(retry_after).timestamp())
                except (TypeError, ValueError, OverflowError):
                    pass
        self.db.execute('BEGIN IMMEDIATE')
        try:
            gate = self.db.execute('SELECT * FROM network_gate WHERE id=1').fetchone()
            deadline = max(deadline, gate['not_before'] or 0)
            self.db.execute('UPDATE network_gate SET halted=1,reason=?,not_before=? WHERE id=1', (reason, deadline))
            # Serialize filesystem signalling under the same transaction for all worker lanes.
            database = self.db.execute('PRAGMA database_list').fetchone()[2]
            target = Path(database + '.maps-halt.json')
            temporary = target.with_suffix('.json.tmp')
            signal = {'reason': reason, 'not_before': deadline, 'retry_after': retry_after, 'review_required': True}
            temporary.write_text(json.dumps(signal))
            temporary.replace(target)
            self.db.execute('COMMIT')
            return signal
        except Exception:
            self.db.execute('ROLLBACK')
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("import").add_argument("checkpoints", nargs="+")
    sub.add_parser("classify").add_argument("boundary")
    sub.add_parser("stats")
    sub.add_parser('reserve-visit')
    halt = sub.add_parser('halt-network')
    halt.add_argument('reason')
    halt.add_argument('--retry-after')
    claim = sub.add_parser("claim")
    claim.add_argument("--bbox", help="minLat,minLon,maxLat,maxLon; narrows eligible jobs")
    done = sub.add_parser("finish")
    done.add_argument("token")
    done.add_argument("result")
    fail = sub.add_parser("fail")
    fail.add_argument("token")
    fail.add_argument("error")
    args = parser.parse_args()
    store = Store(args.database)
    try:
        if args.command == "import":
            for filename in args.checkpoints:
                store.import_checkpoint(filename)
        elif args.command == "classify":
            store.classify(args.boundary)
        elif args.command == "claim":
            bbox = None
            if args.bbox:
                bbox = tuple(map(float, args.bbox.split(',')))
                if len(bbox) != 4 or not all(map(math.isfinite, bbox)) or not (-90 <= bbox[0] < bbox[2] <= 90 and -180 <= bbox[1] < bbox[3] <= 180):
                    raise ValueError("Invalid claim bounding box")
            print(json.dumps(store.claim(bbox=bbox)))
            return
        elif args.command == "finish":
            store.finish(args.token, result=json.loads(Path(args.result).read_text()))
        elif args.command == "fail":
            store.finish(args.token, error=args.error)
        elif args.command == 'reserve-visit':
            print(json.dumps(store.reserve_visit()))
            return
        elif args.command == 'halt-network':
            print(json.dumps(store.halt_network(args.reason, args.retry_after)))
            return
        print(json.dumps(store.stats()))
    finally:
        store.db.close()


if __name__ == "__main__":
    main()
