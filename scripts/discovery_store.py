"""Durable discovery inventory and fenced detail-job leases; no network requests."""
import argparse
import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
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
            for row in self.db.execute("SELECT id,lon,lat FROM places").fetchall():
                point = (row["lon"], row["lat"]) if row["lon"] is not None and row["lat"] is not None else None
                scope = "unknown" if point is None else "inside" if contains(geometry, point) else "outside"
                self.db.execute("UPDATE places SET scope=?,boundary=? WHERE id=?", (scope, boundary, row["id"]))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def claim(self, now=None, lease_seconds=300):
        now = time.time() if now is None else now
        if lease_seconds <= 0:
            raise ValueError("Lease duration must be positive")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            # Exhausted/crashed attempts cannot remain leased forever.
            self.db.execute("UPDATE details SET state='failed',token=NULL,lease_until=NULL WHERE state='leased' AND lease_until<=? AND attempts>=3", (now,))
            row = self.db.execute("""SELECT d.place_id,p.link FROM details d JOIN places p ON p.id=d.place_id
                WHERE p.scope='inside' AND d.attempts<3 AND
                ((d.state IN ('pending','retry') AND d.next_attempt<=?) OR (d.state='leased' AND d.lease_until<=?))
                ORDER BY d.place_id LIMIT 1""", (now, now)).fetchone()
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
        cursor = self.db.execute("""UPDATE details SET
            state=CASE WHEN ? IS NULL THEN 'done' WHEN attempts>=3 THEN 'failed' ELSE 'retry' END,
            result_json=?,fetched_at=?,last_error=?,next_attempt=?+min(3600,60*(1 << attempts)),token=NULL,lease_until=NULL
            WHERE token=? AND state='leased' AND lease_until>?""",
            (error, json.dumps(result) if result is not None else None, now if result is not None else None, error, now, token, now))
        if cursor.rowcount != 1:
            raise ValueError("Lease expired, reclaimed, or already completed")

    def stats(self):
        return {name: dict(self.db.execute(f"SELECT {column},count(*) FROM {table} GROUP BY {column}").fetchall())
                for name, table, column in (("scope", "places", "scope"), ("details", "details", "state"))} | {
                    "places": self.db.execute("SELECT count(*) FROM places").fetchone()[0],
                    "searches": self.db.execute("SELECT count(*) FROM searches").fetchone()[0],
                    "sightings": self.db.execute("SELECT count(*) FROM sightings").fetchone()[0],
                    "eligible_details": dict(self.db.execute("SELECT state,count(*) FROM details JOIN places ON place_id=id WHERE scope='inside' GROUP BY state").fetchall())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("import").add_argument("checkpoints", nargs="+")
    sub.add_parser("classify").add_argument("boundary")
    sub.add_parser("stats")
    sub.add_parser("claim")
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
            print(json.dumps(store.claim()))
            return
        elif args.command == "finish":
            store.finish(args.token, result=json.loads(Path(args.result).read_text()))
        elif args.command == "fail":
            store.finish(args.token, error=args.error)
        print(json.dumps(store.stats()))
    finally:
        store.db.close()


if __name__ == "__main__":
    main()
