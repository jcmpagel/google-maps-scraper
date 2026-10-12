import json
import tempfile
import unittest
from pathlib import Path

from munich_campaign import Campaign, cell_tasks, intersects


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.geometry = {"type": "Polygon", "coordinates": [
            [[11.57, 48.13], [11.59, 48.13], [11.59, 48.15], [11.57, 48.15], [11.57, 48.13]]]}
        self.boundary = self.root / 'boundary.json'
        self.boundary.write_text(json.dumps(self.geometry))
        self.campaign = Campaign(self.root / 'inventory.sqlite', self.root / 'output', self.boundary)
        self.addCleanup(self.campaign.db.close)

    def test_grid_covers_boundary_vertices_and_has_all_categories(self):
        tasks = cell_tasks(self.geometry)
        self.assertTrue(tasks)
        for x, y in self.geometry['coordinates'][0]:
            self.assertTrue(any(t['box'][0] <= x <= t['box'][2] and t['box'][1] <= y <= t['box'][3] for t in tasks))
        categories = {t['keyword'] for t in tasks}
        self.assertEqual(len(categories), 7)
        for name in {t['name'] for t in tasks}:
            self.assertEqual({t['keyword'] for t in tasks if t['name'] == name}, categories)

    def test_restart_does_not_reset_completed_jobs(self):
        row = self.campaign.db.execute('SELECT id,task_json FROM campaign_jobs LIMIT 1').fetchone()
        self.campaign.complete(row['id'], json.loads(row['task_json']), 30, True)
        total = self.campaign.db.execute('SELECT count(*) FROM campaign_jobs').fetchone()[0]
        second = Campaign(self.root / 'inventory.sqlite', self.root / 'output', self.boundary)
        try:
            self.assertEqual(second.db.execute('SELECT count(*) FROM campaign_jobs').fetchone()[0], total)
            self.assertEqual(second.db.execute('SELECT status FROM campaign_jobs WHERE id=?', (row['id'],)).fetchone()[0], 'done')
        finally:
            second.db.close()

    def test_saturated_parent_adds_four_children_only_once(self):
        row = self.campaign.db.execute('SELECT id,task_json FROM campaign_jobs LIMIT 1').fetchone()
        task = json.loads(row['task_json'])
        for _ in range(2):
            self.campaign.complete(row['id'], task, 120, True)
        rows = self.campaign.db.execute('SELECT task_json FROM campaign_jobs WHERE parent=?', (row['id'],)).fetchall()
        self.assertEqual(len(rows), 4)
        self.assertEqual({json.loads(r[0])['depth'] for r in rows}, {1})

    def test_truncated_list_refines_and_minimum_cell_remains_flagged(self):
        row = self.campaign.db.execute('SELECT id,task_json FROM campaign_jobs LIMIT 1').fetchone()
        self.campaign.complete(row['id'], json.loads(row['task_json']), 36, False)
        self.assertEqual(self.campaign.db.execute('SELECT count(*) FROM campaign_jobs WHERE parent=?', (row['id'],)).fetchone()[0], 4)
        task = json.loads(row['task_json']) | {'depth': 2, 'zoom': 18, 'name': 'minimum'}
        self.campaign.enqueue(task)
        row = self.campaign.db.execute("SELECT id FROM campaign_jobs WHERE json_extract(task_json,'$.name')='minimum'").fetchone()
        self.campaign.complete(row['id'], task, 120, True)
        self.assertEqual(self.campaign.status()['saturated_at_minimum'], 1)
        self.assertEqual(self.campaign.db.execute('SELECT count(*) FROM campaign_jobs WHERE parent=?', (row['id'],)).fetchone()[0], 0)

    def test_edge_crossing_and_hole_without_boundary_touch(self):
        # Both polygon vertices and rectangle corners can be outside each other.
        strip = {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 1], [0, 1], [0, 0]]]}
        self.assertTrue(intersects(strip, [4, -1, 5, 2]))
        self.assertFalse(intersects(strip, [4, 2, 5, 3]))
        strip['coordinates'].append([[4, .2], [6, .2], [6, .8], [4, .8], [4, .2]])
        self.assertFalse(intersects(strip, [4.5, .3, 5.5, .7]))


if __name__ == '__main__':
    unittest.main()
