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

    def test_shared_visit_slots_are_spaced_across_connections(self):
        def reserve(_):
            store = Store(self.database)
            try:
                return store.reserve_visit(now=100)['reserved_at']
            finally:
                store.db.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            slots = sorted(pool.map(reserve, range(8)))
        self.assertEqual(slots, list(range(100, 116, 2)))

    def test_retry_after_halts_all_workers_and_never_shortens_cooldown(self):
        result = self.store.halt_network('HTTP 429', '3600', now=100)
        self.assertEqual(result['not_before'], 3700)
        self.assertTrue(Path(str(self.database) + '.maps-halt.json').exists())
        self.assertEqual(self.store.halt_network('HTTP 429', '1', now=101)['not_before'], 3700)
        with self.assertRaisesRegex(ValueError, 'Global access block'):
            self.store.reserve_visit(now=5000)

    def test_http_date_retry_after_and_invalid_delay(self):
        from email.utils import formatdate
        result = self.store.halt_network('HTTP 429', formatdate(5000, usegmt=True), now=100)
        self.assertEqual(result['not_before'], 5000)
        self.assertEqual(self.store.halt_network('HTTP 429', 'inf', now=101)['not_before'], 5000)

    def test_search_filters_skip_only_confirmed_low_counts_and_permanent_closure(self):
        self.store.classify(self.boundary)
        identifier = 'cid:1110'
        self.store.apply_filter_evidence(identifier, {'review_count': 24}, '2026-10-12T10:00:00Z')
        self.assertIsNone(self.store.claim(now=0))
        self.assertEqual(self.store.stats()['details'], {'skipped': 1})
        self.store.apply_filter_evidence(identifier, {'review_count': 25}, '2026-10-12T11:00:00Z')
        self.store.apply_filter_evidence(identifier, {'review_count': 1}, '2026-10-12T09:00:00Z')
        self.assertEqual(self.store.stats()['details'], {'pending': 1})
        self.store.apply_filter_evidence(identifier, {'permanently_closed': True}, '2026-10-12T12:00:00Z')
        self.assertIsNone(self.store.claim(now=0))

    def test_unknown_filter_and_cached_detail_exclusion(self):
        self.store.classify(self.boundary)
        self.store.apply_filter_evidence('cid:1110', {'review_count': None}, '2026-10-12T10:00:00Z')
        job = self.store.claim(now=0)
        self.assertIsNotNone(job)
        self.store.finish(job['token'], result={'detail_exclusion_reason': 'under_25_reviews'}, now=1)
        self.assertEqual(self.store.stats()['details'], {'skipped': 1})
        self.assertIsNone(self.store.claim(now=2))


if __name__ == "__main__":
    unittest.main()
