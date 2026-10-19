import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from discovery_store import Store
from expand_neighborhood_inventory import expand
from prepare_local_basemap import prepare


class NeighborhoodExpansionTests(unittest.TestCase):
    def test_wider_scope_preserves_details_source_and_access_halt(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = Path(temporary) / 'source', Path(temporary) / 'expanded'
            source.mkdir()
            (source / 'region.json').write_text(json.dumps({'title': 'Test', 'radius_m': 1000, 'center': [52.4581966, 13.4139015]}))
            store = Store(source / 'inventory.sqlite')
            try:
                for key, lat, scope in [('done', 52.4581966, 'inside'), ('fringe', 52.48, 'outside')]:
                    store.db.execute('INSERT INTO places(id,title,lat,lon,scope) VALUES(?,?,?,?,?)', (key, key, lat, 13.4139015, scope))
                    store.db.execute('INSERT INTO details(place_id,state,result_json) VALUES(?,?,?)', (key, 'done' if key == 'done' else 'pending', '{"title":"kept"}' if key == 'done' else None))
                store.db.execute("UPDATE network_gate SET halted=1,reason='Keep existing halt' WHERE id=1")
                expand(source, target, 3000)
                expanded = Store(target / 'inventory.sqlite')
                try:
                    self.assertEqual(expanded.db.execute("SELECT scope FROM places WHERE id='fringe'").fetchone()[0], 'inside')
                    self.assertEqual(store.db.execute("SELECT scope FROM places WHERE id='fringe'").fetchone()[0], 'outside')
                    self.assertEqual(expanded.db.execute("SELECT state,result_json FROM details WHERE place_id='done'").fetchone()[:], ('done', '{"title":"kept"}'))
                    self.assertEqual(expanded.db.execute('SELECT halted FROM network_gate').fetchone()[0], 1)
                    self.assertEqual(expanded.db.execute('SELECT count(*) FROM places').fetchone()[0], 2)
                finally:
                    expanded.db.close()
                with self.assertRaises(ValueError):
                    expand(source, target, 3000)
            finally:
                store.db.close()

    def test_active_source_cannot_be_copied_into_an_independent_network_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            source.mkdir()
            (source / 'region.json').write_text(json.dumps({'radius_m': 1000, 'center': [52.4581966, 13.4139015]}))
            (source / 'inventory.sqlite.maps-lane-0-worker.lock').write_text(json.dumps({'pid': os.getpid()}))
            with self.assertRaises(RuntimeError):
                expand(source, Path(temporary) / 'target', 3000)
            self.assertFalse((Path(temporary) / 'target').exists())

    def test_local_streets_keep_real_coordinates_and_verify_source_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, provenance, region = root / 'ways.json', root / 'source.json', root / 'region.json'
            source.write_text(json.dumps({'features': [
                {'properties': {'name': 'Gottlieb-Dunkel-Straße'}, 'geometry': {'type': 'LineString', 'coordinates': [[13.4139015, 52.4581966], [13.415, 52.46]]}},
                {'properties': {'name': 'Outside'}, 'geometry': {'type': 'LineString', 'coordinates': [[11.5, 48.1], [11.6, 48.2]]}},
            ]}))
            provenance.write_text(json.dumps({'url': 'https://example.test/fixture', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}))
            region.write_text(json.dumps({'center': [52.4581966, 13.4139015], 'radius_m': 3000}))
            prepare(source, provenance, region, root / 'map')
            result = json.loads((root / 'map/basemap.geojson').read_text())
            self.assertEqual(len(result['features']), 1)
            self.assertEqual(result['features'][0]['geometry']['coordinates'][0], [13.4139, 52.4582])
            self.assertEqual(result['labels'][0]['name'], 'Gottlieb-Dunkel-Straße')
            source.write_text('{}')
            with self.assertRaises(ValueError):
                prepare(source, provenance, region, root / 'other-map')
