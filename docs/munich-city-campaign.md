# Munich city campaign

The full-area campaign has been prepared and started in the cloud workspace. It uses the existing SQLite inventory, preserves the pilot's completed details, and runs one Maps browser worker at a time. This is an ongoing collection campaign, not a claim that all Munich businesses have been found.

Initial plan: **402 one-kilometre cells × seven keywords = 2,814 searches**. Keywords are Restaurant, Café, Döner, Imbiss, Pizzeria, Bar and Bäckerei. Cells intersect the preliminary city polygon with a small border margin. Capture scrolls at most twenty times per search. Lists with at least 120 results or an exhausted scroll budget spawn four smaller searches at the next zoom. Refinement stops at 250-metre cells (zoom 18); still-capped cells remain explicitly flagged as unresolved coverage. Parent results remain in the inventory.

The initial searches alone take roughly 2.8 days if searches last about seventy seconds plus the fifteen-second gap observed in the pilot. Adaptive searches, retries and detail collection add time. This is a measured extrapolation, not an end-date guarantee; dense results can make the whole run substantially longer.

Search jobs are stored transactionally in `campaign_jobs` inside `gmaps-output/munich-inventory.sqlite`. Each successful search is imported immediately. Stable Maps identities avoid duplicate place/detail jobs; query provenance and outside discoveries are retained. Checkpoints survive process restarts. The coordinator first drains discovery, including adaptive children, then consumes detail jobs in bounded batches. It does not run search and detail traffic concurrently.

Both workers use `.maps-worker.lock` and `.maps-pacing.json` beside the database, sharing a minimum fifteen-second gap between page visits. Searches additionally wait between scrolls. Transport failures receive limited retries with delay; access blocks, rate limits, challenges and conflicting worker locks pause the campaign. Paused campaigns remain paused across restart and require inspection of the recorded cause before rescheduling. Failed attempts and capped minimum-size cells remain visible. The coordinator's `.campaign.lock` prevents duplicate coordinators.

## Boundary and runtime limits

The current polygon is the archived third-party `Munich Städte` feature used in the pilot. **Municipal inclusion remains preliminary.** Official portals `opendata.muenchen.de` and `geodaten.bayern.de` returned proxy-denied 403 responses in this environment. New source access must be applied through environment settings before obtaining a current authoritative polygon. Do not silently substitute the surrounding Munich rural district. All candidates are preserved for reclassification; outside/unknown places are excluded from detail jobs by the supplied polygon.

A detached process runs only while the selected cloud environment remains alive. `nohup`/detachment does not provide an external service, prevent environment suspension, or survive environment replacement. Processes do not survive publication. The durable queue makes the campaign resumable when the same workspace/database is restored; fresh-environment restoration has not been independently verified. A guaranteed multiweek execution host would require a separately configured persistent runner.

## Inspect and resume

Live status: `gmaps-output/munich-city-campaign/status.json`. Coordinator log: `gmaps-output/munich-city-campaign/campaign.log`. Per-search logs and source captures are under its `searches/` directory; detail reports are under `details/`. `pid` records the launched coordinator PID. Check its command line and status before signalling it or considering lock cleanup.

```bash
source /workspace/.setup/google-maps-scraper/activate.sh
export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
python3 scripts/munich_campaign.py \
  gmaps-output/munich-inventory.sqlite \
  gmaps-output/munich-city-campaign \
  /workspace/.setup/google-maps-scraper/munich-pilot-boundary.geojson
```

That command prints status and initializes only a missing plan; it does not browse Maps or reset an existing campaign. To resume after verifying no coordinator/browser worker is active, add `--run --parser bin/parse-place` and launch it under a managed or detached process with logs. Do not run a second coordinator. A SIGTERM/SIGINT requests stopping after the current job has checkpointed. After a hard crash, verify processes and clean only truly stale locks before resuming. Runtime crashes count towards the search attempt ceiling.

Configuration changes, including a different boundary hash, are rejected for an existing campaign. Keep its original records and create a reviewed follow-up campaign for a new polygon/plan; reclassifying the retained inventory separately can update inclusion without deleting discoveries.

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
node --test scripts/test_detail_worker.cjs
```

Tests cover polygon/rectangle intersection, border coverage, all keyword seeds, restart preservation, idempotent subdivision, minimum-size saturation flags, transactional detail claims and worker pacing. Google Maps result lists remain ranked and bounded; completion of planned jobs does not establish universal business coverage or zero removals for absent notices.
