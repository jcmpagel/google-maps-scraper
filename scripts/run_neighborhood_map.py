"""Collect a small-area map and continuously publish local static artifacts."""
import argparse
import json
import os
import signal
import subprocess
import time
import zipfile
from pathlib import Path

from discovery_store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--target-places', type=int, help='Use already discovered candidates until this many verified food venues meet the review threshold')
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        raise ValueError('Choose 1–16 workers')
    if args.target_places is not None and args.target_places < 1:
        raise ValueError('Target count must be positive')
    root = Path(__file__).resolve().parent.parent
    directory = Path(args.directory).resolve()
    database = directory / 'inventory.sqlite'
    # Resume only after proving that earlier queue/worker owners are gone.
    for lock in directory.glob(database.name + '.*lock'):
        pid = json.loads(lock.read_text())['pid']
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            lock.unlink()
        else:
            raise RuntimeError(f'Existing owner {pid} for {lock.name}; preserve its jobs')
    descriptor = os.open(str(database) + '.neighborhood-run.lock', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(descriptor, json.dumps({'pid': os.getpid()}).encode())
    stopping = False
    children = []

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        for process in children:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def render(stage):
        with (directory / 'build.log').open('a') as log:
            subprocess.run(['python3', str(root / 'scripts/build_neighborhood_map.py'), str(database), str(directory / 'region.json'), str(directory / 'map'), '--template', str(root / 'web/neighborhood-map')], cwd=root, stdout=log, stderr=log, check=True)
        (directory / 'collection-status.json').write_text(json.dumps({'stage': stage, 'pid': os.getpid(), 'updated_at': time.time()}, indent=2))

    def wait(stage):
        while any(process.poll() is None for process in children):
            render('stopping' if stopping else stage)
            time.sleep(10)
        render(stage)

    def archive_map():
        archive = directory / 'tempelhof-restaurant-karte.zip'
        temporary = archive.with_suffix('.zip.tmp')
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
            for file in (directory / 'map').rglob('*'):
                if file.is_file():
                    target.write(file, file.relative_to(directory / 'map'))
        temporary.replace(archive)
        return archive

    try:
        if args.target_places:
            store = Store(database)
            try:
                polygon = json.loads((directory / 'boundary.geojson').read_text())['geometry']['coordinates'][0]
                bbox = f"{min(p[1] for p in polygon)},{min(p[0] for p in polygon)},{max(p[1] for p in polygon)},{max(p[0] for p in polygon)}"
                while not stopping:
                    render('expanding_details')
                    dataset = json.loads((directory / 'map/data.json').read_text())
                    visible = sum(row['detail_checked'] and row['review_count'] is not None and row['review_count'] >= dataset['meta']['minimum_reviews'] for row in dataset['rows'])
                    if visible >= args.target_places:
                        render('target_reached')
                        print(json.dumps({'state': 'target_reached', 'verified_places': visible, 'archive': str(archive_map())}), flush=True)
                        return
                    if store.db.execute('SELECT halted FROM network_gate WHERE id=1').fetchone()[0]:
                        render('paused'); archive_map()
                        return
                    pending = store.db.execute("SELECT count(*) FROM details JOIN places ON id=place_id WHERE scope='inside' AND state IN ('pending','retry','leased')").fetchone()[0]
                    if not pending:
                        render('inventory_exhausted'); archive_map()
                        return
                    children.clear()
                    for lane in range(args.workers):
                        target = directory / 'details' / f'lane-{lane}'
                        target.mkdir(parents=True, exist_ok=True)
                        with (target / 'worker.log').open('a') as log:
                            children.append(subprocess.Popen(['node', str(root / 'scripts/munich_detail_worker.cjs'), str(database), str(target), str(root / 'bin/parse-place'), '--limit', '5', '--bbox', bbox, '--lane', str(lane)], cwd=root, stdout=log, stderr=log))
                    wait('expanding_details')
                    if not any(json.loads((directory / 'details' / f'lane-{lane}' / 'run.json').read_text()).get('completed') for lane in range(args.workers)):
                        time.sleep(15)  # Durable retry timestamps remain authoritative.
                render('stopped'); archive_map()
                return
            finally:
                store.db.close()
        # Start with a few completed details so the gift map is usable immediately.
        for lane in range(args.workers):
            target = directory / 'warm-details' / f'lane-{lane}'
            target.mkdir(parents=True, exist_ok=True)
            boundary = json.loads((directory / 'boundary.geojson').read_text())['geometry']['coordinates'][0]
            bbox = f"{min(p[1] for p in boundary)},{min(p[0] for p in boundary)},{max(p[1] for p in boundary)},{max(p[0] for p in boundary)}"
            with (target / 'worker.log').open('a') as log:
                children.append(subprocess.Popen(['node', str(root / 'scripts/munich_detail_worker.cjs'), str(database), str(target), str(root / 'bin/parse-place'), '--limit', '4', '--bbox', bbox, '--lane', str(lane)], cwd=root, stdout=log, stderr=log))
        wait('initial_details')
        if stopping:
            return
        if Path(str(database) + '.maps-halt.json').exists():
            render('paused')
            return
        children.clear()
        with (directory / 'campaign/campaign.log').open('a') as log:
            children.append(subprocess.Popen(['python3', '-u', str(root / 'scripts/munich_campaign.py'), str(database), str(directory / 'campaign'), str(directory / 'boundary.geojson'), '--profile', 'neighborhood', '--run', '--parser', str(root / 'bin/parse-place'), '--workers', str(args.workers)], cwd=root, stdout=log, stderr=log))
        wait('collecting')
        if stopping:
            render('stopped')
            return
        failed = any(process.returncode for process in children)
        state = json.loads((directory / 'campaign/status.json').read_text()).get('state')
        render('paused' if failed or state == 'paused' else 'finished_with_gaps' if state == 'finished_with_gaps' else 'finished')
        archive = archive_map()
        print(json.dumps({'map': str(directory / 'map/index.html'), 'archive': str(archive), 'state': state}), flush=True)
    finally:
        os.close(descriptor)
        os.unlink(str(database) + '.neighborhood-run.lock')


if __name__ == '__main__':
    main()
