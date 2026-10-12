import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path

from discovery_store import Store, canonical_id, contains


class DiscoveryStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root / "inventory.sqlite"
        self.store = Store(self.database)
        self.addCleanup(self.store.db.close)
        self.checkpoint = self.root / "checkpoint.json"
        self.checkpoint.write_text(json.dumps({"maxScrolls": 20, "searches": [{
            "status": "completed", "lat": 48.13, "lon": 11.57, "zoom": 16,
            "keyword": "Restaurant", "startedAt": "2026-10-12T09:00:00.000Z",
            "endOfList": True, "places": [{"title": "Example", "link":
                "https://www.google.com/maps/place/Example/data=!1s0x123:0x456!8m2!3d48.13!4d11.57"}]}]}))
        self.store.import_checkpoint(self.checkpoint)
        self.boundary = self.root / "boundary.json"
        self.boundary.write_text(json.dumps({"type": "Polygon", "coordinates": [
            [[11, 48], [12, 48], [12, 49], [11, 49], [11, 48]]]}))

    def test_identity_aliases_and_case(self):
        self.assertEqual(canonical_id("https://www.google.com/maps?cid=1110"),
                         canonical_id("https://www.google.com/maps/place/X/data=!1s0x123:0x456"))
        self.assertNotEqual(canonical_id("https://www.google.com/maps/data=!1sChIJAb"),
                            canonical_id("https://www.google.com/maps/data=!1sChIJab"))

    def test_restart_import_and_done_not_requeued(self):
        self.assertIsNone(self.store.claim(now=0))  # Unknown geography excluded.
        self.store.classify(self.boundary)
        job = self.store.claim(now=0)
        self.store.finish(job["token"], result={"removed_reviews_status": "not_present"}, now=1)
        self.store.import_checkpoint(self.checkpoint)
        another = Store(self.database)
        try:
            self.assertEqual(another.stats()["places"], 1)
            self.assertEqual(another.stats()["sightings"], 1)
            self.assertIsNone(another.claim(now=2))
        finally:
            another.db.close()

    def test_two_connections_only_one_claim(self):
        self.store.classify(self.boundary)

        def claim():
            store = Store(self.database)
            try:
                return store.claim(now=0)
            finally:
                store.db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            jobs = list(executor.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(job is not None for job in jobs), 1)

    def test_claim_bbox_cannot_include_outside_or_unknown_scope(self):
        self.assertIsNone(self.store.claim(now=0, bbox=(48, 11, 49, 12)))
        self.store.classify(self.boundary)
        self.assertIsNone(self.store.claim(now=0, bbox=(48.5, 11.5, 49, 12)))
        self.assertIsNotNone(self.store.claim(now=0, bbox=(48, 11, 49, 12)))

    def test_expired_worker_cannot_overwrite_reclaimed_job(self):
        self.store.classify(self.boundary)
        old = self.store.claim(now=0, lease_seconds=10)
        new = self.store.claim(now=11, lease_seconds=10)
        with self.assertRaises(ValueError):
            self.store.finish(old["token"], result={}, now=12)
        self.store.finish(new["token"], result={}, now=12)

    def test_backoff_and_retry_exhaustion(self):
        self.store.classify(self.boundary)
        job = self.store.claim(now=0)
        self.store.finish(job["token"], error="temporary", now=1)
        self.assertIsNone(self.store.claim(now=2))
        job = self.store.claim(now=122)
        self.store.finish(job["token"], error="temporary", now=123)
        job = self.store.claim(now=364)
        self.store.finish(job["token"], error="temporary", now=365)
        self.assertIsNone(self.store.claim(now=10000))
        self.assertEqual(self.store.stats()["details"], {"failed": 1})

    def test_polygon_holes_multipolygon_and_edges(self):
        polygon = json.loads(self.boundary.read_text())
        polygon["coordinates"].append([[11.6, 48.6], [11.8, 48.6], [11.8, 48.8], [11.6, 48.8]])
        self.assertTrue(contains(polygon, (11, 48.5)))
        self.assertFalse(contains(polygon, (11.7, 48.7)))
        self.assertFalse(contains(polygon, None))
        self.assertFalse(contains(polygon, (13, 48.5)))
        self.assertTrue(contains({"type": "MultiPolygon", "coordinates": [polygon["coordinates"]]}, (11.57, 48.13)))

    def test_older_import_does_not_move_latest_coordinates(self):
        checkpoint = json.loads(self.checkpoint.read_text())
        checkpoint["searches"][0]["startedAt"] = "2026-10-12T10:00:00.000Z"
        checkpoint["searches"][0]["places"][0]["link"] = checkpoint["searches"][0]["places"][0]["link"].replace("!4d11.57", "!4d11.58")
        later = self.root / "later.json"
        later.write_text(json.dumps(checkpoint))
        self.store.import_checkpoint(later)
        self.store.classify(self.boundary)
        self.store.import_checkpoint(self.checkpoint)
        row = self.store.db.execute("SELECT lon,scope FROM places").fetchone()
        self.assertEqual(row["lon"], 11.58)
        self.assertEqual(row["scope"], "inside")

    def test_failed_import_rolls_back_and_failed_search_is_not_imported(self):
        checkpoint = json.loads(self.checkpoint.read_text())
        checkpoint["searches"][0]["status"] = "failed"
        checkpoint["searches"][0]["places"] = [{"title": "Excluded", "link": "https://www.google.com/maps?cid=99"}]
        failed = self.root / "failed.json"
        failed.write_text(json.dumps(checkpoint))
        self.store.import_checkpoint(failed)
        self.assertEqual(self.store.stats()["places"], 1)
        checkpoint["searches"][0]["status"] = "completed"
        checkpoint["searches"].append({"status": "completed"})
        failed.write_text(json.dumps(checkpoint))
        with self.assertRaises(KeyError):
            self.store.import_checkpoint(failed)
        self.assertEqual(self.store.stats()["places"], 1)

    def test_repeated_worker_crashes_stop_at_attempt_limit(self):
        self.store.classify(self.boundary)
        for now in (0, 301, 602):
            self.assertIsNotNone(self.store.claim(now=now))
        self.assertIsNone(self.store.claim(now=903))
        self.assertEqual(self.store.stats()["details"], {"failed": 1})


if __name__ == "__main__":
    unittest.main()
