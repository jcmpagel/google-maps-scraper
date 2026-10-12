# Munich city campaign

The full-area campaign has been prepared and started in the cloud workspace. It uses the existing SQLite inventory, preserves the pilot's completed details, and supports parallel Maps workers with transactional claims and a shared page-start budget. This is an ongoing collection campaign, not a claim that all Munich businesses have been found.

Initial plan: **402 one-kilometre cells × seven keywords = 2,814 searches**. Keywords are Restaurant, Café, Döner, Imbiss, Pizzeria, Bar and Bäckerei. Cells intersect the preliminary city polygon with a small border margin. Capture scrolls at most twenty times per search. Lists with at least 120 results or an exhausted scroll budget spawn four smaller searches at the next zoom. Refinement stops at 250-metre cells (zoom 18); still-capped cells remain explicitly flagged as unresolved coverage. Parent results remain in the inventory.

The initial searches alone take roughly 2.8 days if searches last about seventy seconds plus the fifteen-second gap observed in the pilot. Adaptive searches, retries and detail collection add time. That was the single-worker baseline; parallel throughput must be measured separately. Dense results can make the whole run substantially longer, so five-hour completion is not established.

Search jobs are stored transactionally in `campaign_jobs` inside `gmaps-output/munich-inventory.sqlite`. Each successful search is imported immediately. Stable Maps identities avoid duplicate place/detail jobs; query provenance and outside discoveries are retained. Checkpoints survive process restarts. The coordinator first drains discovery, including adaptive children, then consumes detail jobs in bounded batches. Search runs in parallel first; detail workers then consume distinct leased jobs in parallel.

Serial workers use `.maps-worker.lock`; coordinated parallel workers use numbered lane locks. Each lane retains a fifteen-second page gap. SQLite `network_gate` additionally reserves page starts globally at least two seconds apart, across both worker types. Searches additionally wait between scrolls. Transport failures receive limited retries with delay; access blocks, rate limits, challenges and conflicting worker locks pause the campaign. Paused campaigns remain paused across restart and require inspection of the recorded cause before rescheduling. Failed attempts and capped minimum-size cells remain visible. The coordinator's `.campaign.lock` prevents duplicate coordinators.

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

Tests cover polygon/rectangle intersection, border coverage, all keyword seeds, restart preservation, idempotent subdivision, minimum-size saturation flags, parallel unique search/detail claims, global visit reservations, persistent cooldown and worker pacing. Google Maps result lists remain ranked and bounded; completion of planned jobs does not establish universal business coverage or zero removals for absent notices.


## Parallel iteration — 12 October 2026

The upstream [README](https://github.com/gosom/google-maps-scraper/blob/d0b51bcf3cd56d9a3f71e049cb6e226554e24162/README.md) recommends measuring concurrency 4, 8 or 16 and describes browser/page pools. It does not guarantee that 50 workers will avoid limits on every machine. Our TLS-verifying checkpointed capture workers use their own lanes rather than silently changing the pinned Go dependency or losing the custom removal fields.

This cloud container has a four-CPU quota and 32 GiB memory limit. An eight-worker live test completed fourteen additional searches without new access blocks, increasing the inventory from 2,492 to 3,033 Maps IDs. Observed memory usage was about 9 GiB. The initial client-script 403 was independently verified as a proxy-denied CONNECT to `apis.google.com/js/client.js`, not a Google Maps rate-limit response. That specific optional script is skipped; denied core data requests are not ignored.

Run with `--workers 16 --initial-workers 8` to start eight lanes and permit sixteen after a successful initial batch and healthy resources. Memory pressure or increasing retry counts reduce the active lane allowance, without killing captures or releasing jobs early. The ceiling is configurable up to fifty for a separately measured capable host; it is not the default or a rate guarantee. Status includes active allowance, ceiling, memory fraction and one-minute CPU load.

Any actual HTTP 403/429 or challenge is signalled to every lane. New route requests and page starts stop globally. `Retry-After` (seconds or HTTP date) is retained as a minimum cooldown, never shortened by another worker, with a fifteen-minute floor. A persisted halt still requires inspection before resuming; expiry alone is not a reason to retry a CAPTCHA. No proxy rotation, challenge solving, IP switching, or TLS verification bypass was added.

The shared budget limits page starts, not every HTTP resource request. Pages issue multiple internal requests, so actual response status and transport errors remain important. Existing DOM snapshots, raw detail payloads, per-locale observations and uncertain-coverage flags remain unchanged. Parallelism does not establish universal coverage or make a missing notice evidence of zero deletions.

CPU load is reported separately; a high load average alone is not treated as a failed request. Scaling uses hysteresis: a healthy initial batch, at least ninety seconds between increases, and a minimum adjustment interval. Transient detail transport failures retain queue backoff and do not automatically halt all healthy lanes. Identity mismatches, conflicting locks and actual access blocks still pause the campaign. Nineteen Python tests and five Node tests cover the current controls.

## Inclusion filters

The user narrowed the detail scope to businesses with at least **25 reviews**, excluding **permanently closed** businesses. Discovery now extracts explicit count labels and permanent-closure text from individual search cards. These observations are retained in `place_filters` and in source checkpoints. Confirmed exclusions mark pending/retry detail jobs `skipped`; their place identity and search provenance remain preserved. Exactly 25 reviews is eligible. Missing labels remain unknown and do not cause exclusion. Temporary closure is not permanent closure.

When the search card lacks this information, the detail worker checks the first captured entry. A confirmed exclusion skips the second locale visit and stores the capture with `detail_exclusion_reason`; it is not repeatedly fetched. Successful previously cached results are retained. Newer evidence of 25+ reviews can requeue a job skipped for a low count; older evidence cannot override newer observations. Missing observations do not erase previously known filter values. Existing legacy search snapshots without count/status labels cannot be retrospectively classified from their place URLs alone; new overlapping searches gradually fill those fields.

The live rollout initially excluded 327 low-review-count candidates before any new detail requests for them. These filters reduce **detail traffic**, not the searches necessary to discover an area's businesses. Scope completeness now refers to the requested review-count/closure policy as well as geographic/category coverage. Twenty-one Python tests and eight Node tests cover the controls and exclusion boundaries.
