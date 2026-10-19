"""Build a portable, honest restaurant map from a scoped discovery store."""
import argparse
import csv
import io
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FOOD = re.compile(r'restaurant|caf[eé]|coffee|kaffee|bakery|bäck|baeck|bistro|imbiss|snack|kebab|kebap|döner|doener|pizza|pizzer|steakhaus|steakhouse|patisser|kneipe|frühstück|fruehstueck|sushi|burger|gastst|gastr|grill|diner|fast.food|sandwich|brunch|kantine|konditor|dessert|ice.cream|eisdiele|eiscaf|take.?away|liefer|biergarten|brauhaus|\bpub\b|\bbar\b', re.I)


def write_snapshot(path, content):
    """Readers see either the previous complete export or the new one."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def distance_m(lat, lon, centre):
    phi, target = math.radians(lat), math.radians(centre[0])
    delta_lat = phi - target
    delta_lon = math.radians(lon - centre[1])
    a = math.sin(delta_lat / 2) ** 2 + math.cos(phi) * math.cos(target) * math.sin(delta_lon / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0, 1 - a)))


def build(database, region_file, output, template=None):
    region = json.loads(Path(region_file).read_text())
    connection = sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    candidates = connection.execute('''SELECT p.*, d.state detail_state,d.result_json,d.fetched_at,
        f.review_count card_reviews,f.permanently_closed FROM places p JOIN details d ON d.place_id=p.id
        LEFT JOIN place_filters f ON f.place_id=p.id WHERE p.scope='inside' ''').fetchall()
    rows = []
    excluded_category = 0
    for candidate in candidates:
        if candidate['detail_state'] == 'skipped' or candidate['permanently_closed'] == 1:
            continue
        entry = json.loads(candidate['result_json']) if candidate['result_json'] else None
        point = [entry.get('latitude'), entry.get('longtitude')] if entry else [candidate['lat'], candidate['lon']]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in point):
            continue
        distance = distance_m(*point, region['center'])
        if distance > region['radius_m']:
            continue
        count = entry['review_count'] if entry and entry.get('review_count_available') else candidate['card_reviews']
        if count is not None and count < region['minimum_reviews']:
            continue
        if entry and re.search(r'permanently closed|dauerhaft geschlossen|CLOSED_PERMANENTLY', entry.get('status', ''), re.I):
            continue
        category = entry.get('category', '') if entry else ''
        categories = entry.get('categories', []) if entry else []
        if entry and (category or categories) and not FOOD.search(' '.join([category, *categories])):
            excluded_category += 1
            continue
        verified = entry is not None and candidate['detail_state'] == 'done'
        parsed_notice = verified and entry.get('removed_reviews_status') == 'parsed' and not entry.get('detail_removal_conflict')
        observations = entry.get('detail_observations', []) if entry else []
        rating = entry.get('review_rating') if entry and entry.get('review_count_available') else None
        if type(rating) not in (int, float) or not 1 <= rating <= 5:
            rating = None
        rows.append({'id': candidate['id'], 'title': entry['title'] if entry else candidate['title'],
                     'lat': point[0], 'lon': point[1], 'distance_m': round(distance),
                     'category': category, 'categories': categories, 'address': entry.get('address', '') if entry else '',
                     'link': candidate['link'], 'website': entry.get('web_site', '') if entry else '',
                     'review_count': count, 'review_count_available': bool(entry and entry.get('review_count_available')),
                     'rating': rating,
                     'histogram': entry.get('reviews_per_rating') if entry and entry.get('reviews_per_rating_available') else None,
                     'removal_status': entry.get('removed_reviews_status', 'not_fetched') if verified else 'not_fetched',
                     'removed_min': entry.get('removed_reviews_min') if parsed_notice else None,
                     'removed_max': (entry.get('removed_reviews_max') or None) if parsed_notice else None,
                     'notice': entry.get('removed_reviews_notice', '') if verified else '',
                     'notice_conflict': bool(entry and entry.get('detail_removal_conflict')),
                     'languages': [o['language'] for o in observations], 'detail_checked': verified,
                     'fetched_at': datetime.fromtimestamp(candidate['fetched_at'], timezone.utc).isoformat() if candidate['fetched_at'] else None})
    rated = [r for r in rows if r['rating'] is not None and r['review_count_available'] and r['review_count'] > 0]
    mean = sum(r['rating'] * r['review_count'] for r in rated) / sum(r['review_count'] for r in rated) if rated else None
    for row in rows:
        row['bayesian'] = round((row['rating'] * row['review_count'] + 100 * mean) / (row['review_count'] + 100), 4) if row in rated else None
    status = {key: value for key, value in connection.execute('SELECT status,count(*) FROM campaign_jobs GROUP BY status')}
    unfinished_lists = connection.execute('SELECT count(*) FROM searches WHERE end_of_list=0').fetchone()[0]
    details = {key: value for key, value in connection.execute("SELECT state,count(*) FROM details JOIN places ON id=place_id WHERE scope='inside' GROUP BY state")}
    network = dict(connection.execute('SELECT * FROM network_gate WHERE id=1').fetchone())
    manifest = {**region, 'generated_at': datetime.now(timezone.utc).isoformat(), 'mean_rating': mean,
                'campaign_jobs': status, 'detail_jobs': details, 'data_paused': bool(network['halted']),
                'searches_without_confirmed_end': unfinished_lists,
                'inside_discoveries': len(candidates), 'shown_candidates': len(rows),
                'checked_details': sum(r['detail_checked'] for r in rows),
                'excluded_non_food': excluded_category, 'coverage_complete': False,
                'method': 'One-kilometre grid, six food keywords; ranked Google Maps lists, at most 20 scrolls. No universal completeness claim.',
                'bayesian_method': 'Rating shrunk towards the local review-weighted mean with 100 prior reviews; no removal-count penalty.'}
    connection.close()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if template:
        shutil.copytree(template, output, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('data.js', 'data.json', 'coverage.json', 'restaurants.csv'))
    dataset = {'meta': manifest, 'rows': sorted(rows, key=lambda r: r['title'].casefold())}
    encoded = json.dumps(dataset, ensure_ascii=False, allow_nan=False)
    write_snapshot(output / 'data.json', encoded + '\n')
    write_snapshot(output / 'data.js', 'window.RESTAURANT_DATA = ' + encoded.replace('<', '\\u003c') + ';\n')
    write_snapshot(output / 'coverage.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    columns = ['id', 'title', 'category', 'address', 'lat', 'lon', 'distance_m', 'rating', 'bayesian', 'review_count', 'review_count_available', 'detail_checked', 'removal_status', 'removed_min', 'removed_max', 'notice_conflict', 'notice', 'link', 'fetched_at']
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    # CSV may be opened in a spreadsheet; venue-controlled text is never a formula.
    writer.writerows({key: ("'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value)
                     for key, value in row.items()} for row in dataset['rows'])
    write_snapshot(output / 'restaurants.csv', '\ufeff' + buffer.getvalue())
    print(json.dumps(manifest, ensure_ascii=False))
    return dataset


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    parser.add_argument('region')
    parser.add_argument('output')
    parser.add_argument('--template', default='web/neighborhood-map')
    arguments = parser.parse_args()
    build(arguments.database, arguments.region, arguments.output, arguments.template)
