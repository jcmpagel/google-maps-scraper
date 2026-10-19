"""Select a local, attributed street network from published EqualStreetNames data."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def prepare(source, provenance_file, region_file, output):
    raw = Path(source).read_bytes()
    provenance = json.loads(Path(provenance_file).read_text())
    if hashlib.sha256(raw).hexdigest() != provenance['sha256']:
        raise ValueError('Street dataset differs from its recorded SHA-256')
    region = json.loads(Path(region_file).read_text())
    lat, lon = region['center']
    margin = region['radius_m'] + 1000
    dy = margin / 111320
    dx = dy / math.cos(math.radians(lat))
    bounds = [lon - dx, lat - dy, lon + dx, lat + dy]
    features, labels = [], {}
    major_names = ('Hermannstraße', 'Karl-Marx-Straße', 'Tempelhofer Damm', 'Mariendorfer Damm',
                   'Britzer Damm', 'Buschkrugallee', 'Oberlandstraße', 'Silbersteinstraße',
                   'Sonnenallee', 'Hermannplatz', 'Gottlieb-Dunkel-Straße', 'Mehringdamm',
                   'Columbiadamm', 'Hasenheide', 'Pannierstraße', 'Flughafenstraße')
    for feature in json.loads(raw)['features']:
        geometry = feature.get('geometry') or {}
        if geometry.get('type') != 'LineString':
            continue
        line = geometry['coordinates']
        if len(line) < 2:
            continue
        xs, ys = zip(*[(p[0], p[1]) for p in line])
        if max(xs) < bounds[0] or min(xs) > bounds[2] or max(ys) < bounds[1] or min(ys) > bounds[3]:
            continue
        name = feature.get('properties', {}).get('name') or ''
        coordinates = [[round(p[0], 5), round(p[1], 5)] for p in line]
        properties = {'name': name, 'major': name in major_names, 'kind': 'road'}
        features.append({'type': 'Feature', 'properties': properties,
                         'geometry': {'type': 'LineString', 'coordinates': coordinates}})
        length = sum(math.hypot((b[0] - a[0]) * math.cos(math.radians(lat)), b[1] - a[1]) * 111320 for a, b in zip(line, line[1:]))
        midpoint = coordinates[len(coordinates) // 2]
        if name and bounds[0] < midpoint[0] < bounds[2] and bounds[1] < midpoint[1] < bounds[3] and (name not in labels or length > labels[name]['length_m']):
            labels[name] = {'name': name, 'point': [midpoint[1], midpoint[0]], 'major': properties['major'], 'length_m': round(length)}
    selected = {'type': 'FeatureCollection', 'features': features,
                'labels': sorted([label for label in labels.values() if label['length_m'] >= 80 or label['major']], key=lambda label: (not label['major'], -label['length_m'])),
                'attribution': '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> · <a href="https://github.com/EqualStreetNames/equalstreetnames-berlin">EqualStreetNames Berlin</a> · ODbL'}
    provenance.update(selected_bounds=bounds, selected_features=len(features), transformations='Selected lines intersecting the local bounding box; coordinates rounded to five decimals; etymology and person data omitted; street labels derived from selected line midpoints.')
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    text = json.dumps(selected, ensure_ascii=False, separators=(',', ':'))
    (target / 'basemap.geojson').write_text(text + '\n')
    (target / 'basemap.js').write_text('window.OFFLINE_BASEMAP = ' + text.replace('<', '\\u003c') + ';\n')
    (target / 'basemap.source.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n')
    (target / 'BASEMAP-LICENSE.txt').write_text('Local street database: © OpenStreetMap contributors, published by EqualStreetNames Berlin.\nSource: ' + provenance['url'] + '\nOpen Database License (ODbL) 1.0: https://opendatacommons.org/licenses/odbl/1-0/\nThe selected, rounded derived street database is available as basemap.geojson under the same ODbL license.\nRestaurant observations are a separate dataset, not part of the derived street database.\nChanges and source checksums: basemap.source.json.\n')
    print(json.dumps({'features': len(features), 'labels': len(selected['labels']), 'bytes': len(text.encode())}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('provenance')
    parser.add_argument('region')
    parser.add_argument('output')
    args = parser.parse_args()
    prepare(args.source, args.provenance, args.region, args.output)
