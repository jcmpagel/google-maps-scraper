import csv
import json
import tempfile
import unittest
from pathlib import Path

from build_neighborhood_map import build, distance_m
from discovery_store import Store


class NeighborhoodMapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.region = self.root / 'region.json'
        self.region.write_text(json.dumps({'title': 'Test map', 'center': [52.4581966, 13.4139015], 'radius_m': 2000, 'minimum_reviews': 25}))
        self.store = Store(self.root / 'data.sqlite')
        self.addCleanup(self.store.db.close)
        self.store.db.execute('CREATE TABLE campaign_jobs(status TEXT)')
        self.store.db.execute("INSERT INTO campaign_jobs VALUES('done')")

    def seed(self, identifier, *, count=25, lat=52.4581966, category='Restaurant', status='done', notice='not_present', minimum=0, maximum=0, rating=4.5):
        entry = {'title': '<img src=x onerror=alert(1)>', 'latitude': lat, 'longtitude': 13.4139015,
                 'category': category, 'categories': [category], 'review_count': count, 'review_count_available': count is not None,
                 'review_rating': rating, 'removed_reviews_status': notice, 'removed_reviews_min': minimum,
                 'removed_reviews_max': maximum, 'detail_observations': [], 'reviews_per_rating_available': False}
        self.store.db.execute("INSERT INTO places(id,title,lat,lon,scope,link) VALUES(?,?,?,?,?,?)", (identifier, entry['title'], lat, 13.4139015, 'inside', 'https://www.google.com/maps?cid=1'))
        self.store.db.execute('INSERT INTO details(place_id,state,result_json) VALUES(?,?,?)', (identifier, status, json.dumps(entry)))

    def test_threshold_location_category_and_unknown_notice(self):
        self.seed('valid')
        self.seed('low', count=24)
        self.seed('outside', lat=52.50)
        self.seed('irrelevant', category='Barber shop')
        self.seed('skipped', status='skipped')
        result = build(self.root / 'data.sqlite', self.region, self.root / 'map')
        self.assertEqual([row['id'] for row in result['rows']], ['valid'])
        self.assertEqual(result['rows'][0]['removal_status'], 'not_present')
        self.assertIsNone(result['rows'][0]['removed_min'])
        self.assertIsNone(result['rows'][0]['removed_max'])
        self.assertIsNone(result['rows'][0]['histogram'])
        self.assertFalse(result['meta']['coverage_complete'])
        self.assertNotIn('<img', (self.root / 'map/data.js').read_text())
        self.assertIn('\\u003cimg', (self.root / 'map/data.js').read_text())

    def test_missing_counts_and_empty_dataset_never_create_scores(self):
        self.seed('unknown', count=None)
        result = build(self.root / 'data.sqlite', self.region, self.root / 'map')
        self.assertIsNone(result['rows'][0]['review_count'])
        self.assertIsNone(result['rows'][0]['rating'])
        self.assertIsNone(result['rows'][0]['bayesian'])
        self.assertIsNone(result['rows'][0]['base_score'])
        self.assertIsNone(result['meta']['mean_rating'])
        self.assertEqual(distance_m(52.4581966, 13.4139015, [52.4581966, 13.4139015]), 0)

    def test_food_categories_without_restaurant_suffix_are_not_lost(self):
        categories = ['Pizzeria', 'Steakhaus', 'Patisserie', 'Kneipe', 'Frühstückslokal']
        for category in categories:
            self.seed(category, category=category)
        self.seed('manufacturer', category='Hersteller')
        self.seed('supermarket', category='Supermarkt')
        self.seed('supplies', category='Gaststättenbedarf')
        self.seed('factory', category='Hersteller')
        # A supermarket with a bakery tag still has supermarket reviews.
        self.seed('shop', category='Supermarkt')
        raw = json.loads(self.store.db.execute("SELECT result_json FROM details WHERE place_id='shop'").fetchone()[0])
        raw['categories'] = ['Supermarkt', 'Bäckerei']
        self.store.db.execute("UPDATE details SET result_json=? WHERE place_id='shop'", (json.dumps(raw),))
        result = build(self.root / 'data.sqlite', self.region, self.root / 'map')
        self.assertEqual({row['id'] for row in result['rows']}, set(categories))

    def test_base_score_shrinks_small_samples_and_kml_keeps_safe_coordinates(self):
        self.seed('small', count=25, rating=5)
        self.seed('established', count=1000, rating=4.8)
        self.seed('background', count=1000, rating=4)
        self.seed('unknown', count=None)
        result = build(self.root / 'data.sqlite', self.region, self.root / 'map')
        rows = {r['id']: r for r in result['rows']}
        mean = (25 * 5 + 1000 * 4.8 + 1000 * 4) / 2025
        self.assertAlmostEqual(rows['small']['base_score'], (25 * 5 + 100 * mean) / 125, places=4)
        self.assertLess(rows['small']['base_score'], rows['established']['base_score'])
        self.assertEqual(rows['small']['base_score'], rows['small']['bayesian'])
        self.assertIsNone(rows['unknown']['base_score'])
        import xml.etree.ElementTree as ET
        tree = ET.parse(self.root / 'map/restaurants.kml')
        points = tree.findall('.//{http://www.opengis.net/kml/2.2}Placemark')
        self.assertEqual(len(points), 3)
        self.assertEqual(points[0].find('{http://www.opengis.net/kml/2.2}name').text, '<img src=x onerror=alert(1)>')
        self.assertTrue(all(p.find('.//{http://www.opengis.net/kml/2.2}coordinates').text.startswith('13.4139015,52.4581966,') for p in points))

    def test_exports_keep_unknown_and_unbounded_removals_distinct(self):
        self.seed('absent')
        self.seed('unsupported', notice='unrecognized')
        self.seed('open', notice='parsed', minimum=251)
        self.seed('bounded', notice='parsed', minimum=21, maximum=50)
        self.seed('one', notice='parsed', minimum=1, maximum=1)
        result = build(self.root / 'data.sqlite', self.region, self.root / 'map')
        rows = {row['id']: row for row in result['rows']}
        self.assertEqual((rows['absent']['removed_min'], rows['absent']['removed_max']), (None, None))
        self.assertIsNone(rows['unsupported']['removed_min'])
        self.assertEqual((rows['open']['removed_min'], rows['open']['removed_max']), (251, None))
        self.assertEqual((rows['bounded']['removed_min'], rows['bounded']['removed_max']), (21, 50))
        self.assertEqual((rows['one']['removed_min'], rows['one']['removed_max']), (1, 1))
        with (self.root / 'map/restaurants.csv').open(encoding='utf-8-sig', newline='') as stream:
            exported = {row['id']: row for row in csv.DictReader(stream)}
        self.assertEqual(exported['absent']['removed_min'], '')
        self.assertEqual(exported['open']['removed_max'], '')
