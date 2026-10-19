"""Copy an inactive inventory, widen its radius and preserve completed details."""
import argparse
import json
import math
import os
import sqlite3
from pathlib import Path

from discovery_store import Store


def expand(source_directory, output_directory, radius_m, target_places=550):
    source, target = Path(source_directory).resolve(), Path(output_directory).resolve()
    region = json.loads((source / 'region.json').read_text())
    if not region['radius_m'] < radius_m <= 10000 or target_places < 1:
        raise ValueError('Choose a larger radius up to 10 km and a positive target')
    if target.exists():
        raise ValueError('Preserve existing output; resume it instead of copying again')
    for lock in source.glob('inventory.sqlite.*lock'):
        pid = json.loads(lock.read_text())['pid']
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        raise RuntimeError(f'Source PID {pid} still exists; inspect it before copying')
    target.mkdir(parents=True)
    region.update(source_radius_m=region.get('source_radius_m', region['radius_m']), previous_radius_m=region['radius_m'],
                  radius_m=radius_m, target_places=target_places, collection_mode='expand_existing_inventory')
    region['method'] = f'Previously discovered Google Maps IDs and completed details reused; candidates reclassified within {radius_m / 1000:g} km, targeting {target_places} verified food venues with 25+ known reviews. Source searches centred on the original area; this is not exhaustive coverage.'
    (target / 'region.json').write_text(json.dumps(region, ensure_ascii=False, indent=2) + '\n')
    lat, lon = map(math.radians, region['center'])
    angular, ring = radius_m / 6371000, []
    for i in range(256):
        bearing = 2 * math.pi * i / 256
        y = math.asin(math.sin(lat) * math.cos(angular) + math.cos(lat) * math.sin(angular) * math.cos(bearing))
        x = lon + math.atan2(math.sin(bearing) * math.sin(angular) * math.cos(lat), math.cos(angular) - math.sin(lat) * math.sin(y))
        ring.append([math.degrees(x), math.degrees(y)])
    ring.append(ring[0])
    boundary = target / 'boundary.geojson'
    boundary.write_text(json.dumps({'type': 'Feature', 'properties': {'radius_m': radius_m}, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}}, ensure_ascii=False) + '\n')
    original = sqlite3.connect(f'file:{source / "inventory.sqlite"}?mode=ro', uri=True)
    destination = sqlite3.connect(target / 'inventory.sqlite')
    try:
        original.backup(destination)
    finally:
        original.close()
        destination.close()
    store = Store(target / 'inventory.sqlite')
    try:
        store.classify(boundary)
        return store.stats()
    finally:
        store.db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    parser.add_argument('--radius-m', type=int, required=True)
    parser.add_argument('--target-places', type=int, default=550)
    args = parser.parse_args()
    print(json.dumps(expand(args.source, args.output, args.radius_m, args.target_places)))
