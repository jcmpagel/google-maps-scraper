# Munich discovery pilot — 12 October 2026

This is a bounded discovery experiment, not a complete Munich inventory. Searches collected links and IDs without intentionally opening place-detail pages, downloading reviews, or revisiting every overlapping result.

## First iteration

Ten German-language searches used fixed 1920×1080 browser viewports, one browser worker, four scrolls per search, four seconds between scrolls, and fifteen seconds between searches. Test centres were Munich centre, Sendling, and Aubing, with two additional centres approximately 500 metres east and north of the central point. Results were deduplicated by the stable Maps ID in the link; none required a URL fallback.

| Search | Zoom | Results | New across preceding searches | Furthest result from centre, approximately |
|---|---:|---:|---:|---:|
| Centre / Restaurant | 15 | 36 | 36 | 1.68 km |
| Centre / Café | 15 | 36 | 35 | 1.87 km |
| Sendling / Restaurant | 15 | 36 | 36 | 2.02 km |
| Sendling / Café | 15 | 36 | 35 | 2.16 km |
| Aubing / Restaurant | 15 | 36 | 36 | 3.72 km |
| Aubing / Café | 15 | 36 | 30 | 8.22 km |
| Centre / Restaurant | 16 | 36 | 9 | 0.88 km |
| Centre / Café | 16 | 36 | 14 | 0.87 km |
| Centre east / Restaurant | 16 | 36 | 2 | 1.29 km |
| Centre north / Restaurant | 16 | 36 | 8 | 1.27 km |

There were **360 appearances and 241 distinct Maps IDs**. A detail queue keyed by those IDs would avoid 119 repeated detail jobs in this sample, approximately 33% of appearances. The experiment itself made zero intentional place-detail requests. These counts do not represent HTTP request counts: each Maps search loads multiple resources and requests.

Pairwise comparison at the same central point: Restaurant zoom 16 added nine IDs absent from the zoom-15 sample; Café zoom 16 added fifteen. The Café row above has fourteen new IDs across *all* preceding searches, explaining the difference. The eastern neighbouring restaurant sample shared 31/36 IDs with the central zoom-16 restaurant sample, but added only two IDs across the accumulated inventory.

Every first-iteration search reached its scroll budget before the end-of-list marker. Therefore, differences can reflect ranking and truncation as well as geography. Low new-ID yield is not evidence that an area is fully covered. Keyword choice still matters: the central zoom-15 Restaurant and Café samples shared just one ID.

Distances were estimated from coordinates embedded in Maps links. They demonstrate that specifying a search centre and zoom does not enforce a fixed radius or municipal boundary. Filter confirmed coordinates against the Munich municipal polygon before calling a result a Munich establishment; preserve out-of-bound discoveries separately if useful.

## Operational findings

- The existing CLI grid has a shared in-memory URL deduper; it does not provide durable discovery/detail scheduling across restarts or worker processes. This pilot's persisted ID inventory does not replace that production component.
- The pilot checkpoints each completed search atomically and preserves failed attempts separately. Restarting a completed first-iteration run was verified to schedule no additional searches. `completed` means the bounded experiment finished, not that geographic coverage is complete.
- Initial diagnostics stopped on proxy-denied optional Google advertising/telemetry endpoints. The pilot now skips those specific endpoints. Other 403/429 responses, challenges, and transport failures stop the run rather than count it as successful. TLS verification remains enabled through Playwright request transport and the existing proxy.
- The grid generator previously omitted partial edge cells, sometimes producing no cells for a small valid box. It now includes centres of clipped edge cells. Regression tests cover small and fractional-width boxes around Munich, coordinate containment, and agreement with the estimated cell count.

## Second iteration: longer scrolling

Two follow-up searches used up to twenty scrolls at zoom 16. Both reached the UI end-of-list marker after roughly seventy seconds and returned 120 distinct IDs each:

| Search | Results | Furthest result, approximately | Comparison with first iteration |
|---|---:|---:|---|
| Centre / Restaurant / zoom 16 | 120 | 0.88 km | Contains all original 36 zoom-16 IDs plus 84 others |
| Aubing / Café / zoom 16 | 120 | 9.66 km | Contains all original 36 zoom-15 IDs plus 84 others; both zoom and scroll budget changed |

Across both iterations, **600 appearances correspond to 401 distinct Maps IDs**. The second iteration added 160 IDs absent from the entire first inventory. All IDs used stable Maps identifiers rather than URL fallback. Detail collection remained disabled.

The centre comparison isolates the effect of the larger scroll budget. Aubing does not isolate zoom from scrolling. Even at zoom 16 its results extend almost ten kilometres, so finer zoom alone is insufficient for geographic inclusion.

Exactly 120 results with an end marker is consistent with a capped search list. The end marker establishes that this particular list ended, not that all businesses in the area were found. Treat this as a candidate for subdivision and additional category searches. Compare the resulting unions before claiming better coverage.

Aggregate evidence is versioned in [munich-discovery-pilot-results.json](munich-discovery-pilot-results.json); raw checkpoints and links remain in the ignored output directories.

## Running the experiment in the prepared cloud environment

```bash
cd /workspace/google-maps-scraper
source /workspace/.setup/google-maps-scraper/activate.sh
NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
  node scripts/munich_discovery_pilot.cjs gmaps-output/munich-pilot
```

Use a separate output directory with `--deep` for two follow-up searches with a maximum of twenty scrolls: centre / Restaurant and Aubing / Café, both zoom 16. The script rejects reusing a directory with a different plan or budget. `--summarize` recomputes results from saved checkpoints without visiting Maps; add `--deep` when summarizing that plan.

Output contains `discovery.json` (checkpoints and source links), `places.json` (deduplicated inventory and search provenance), and `summary.json` (counts, pairwise overlaps, and distance estimates). Output stays in ignored `gmaps-output`; the report and experiment code are versioned. This helper uses the prepared pinned Playwright driver via `PLAYWRIGHT_DRIVER_PATH`, not an additional npm dependency installed into the repository.

## Next production iteration

The follow-up `--refine` experiment adds four central Restaurant searches at zoom 17, plus Döner and Imbiss at the original centre at zoom 16. It uses the twenty-scroll budget and must have its own output directory. Persistent inventory/detail scheduling is now available through the [discovery store](discovery-store.md); the Go CLI and automatic detail worker remain separate follow-up work.

Add `--store gmaps-output/munich.sqlite` to import checkpoints after every completed search, and `--boundary PATH.geojson` to classify discoveries using a supplied polygon. Previously completed checkpoints are reconciled on startup, including when imports were interrupted. `--summarize` can also reconcile saved captures into the store without visiting Maps.

Start with zoom 16 as a candidate for dense central areas, retaining multiple category queries. Validate longer scrolling before selecting a cell spacing. Use the municipal polygon for result inclusion. Extend the durable store with detail freshness, search-job reservations, and a global pacing budget. Failed detail jobs must remain retryable instead of being permanently marked seen.

Add Döner/Kebab, Imbiss, bar and other desired categories in a subsequent category experiment. The two tested terms do not cover all hospitality businesses. Evaluate adaptive subdivision using both truncated searches and incremental discoveries; duplicate percentage alone must not determine coverage. Review-removal notices and their language-dependent availability still need their separate detail collection stage.

The pilot does not establish a Germany-wide completion time or an acceptable sustained request rate. Base those estimates on longer runs including detail collection, failures, and backoff.

## Third iteration: subdivision, categories, and durable inventory

Four Restaurant searches at zoom 17 were centred approximately 250 metres north/south and east/west of the original central point. Each returned 120 IDs and reached its end marker; their union contained 276 IDs. Compared with the 120-ID parent search, 167 IDs were additional and eleven parent IDs were absent. Keep the parent discovery inventory when subdividing, since smaller searches do not necessarily include every previously ranked result.

To distinguish refinement from merely searching outside the original area, both result sets were clipped to the same approximately 1-km square around the original centre (latitude ±0.00449°, longitude ±0.00672°). The parent had 90 IDs inside that square; the children had 223, including every one of those 90. Thus **133 additional IDs were discovered within the same test area**. This is a controlled test rectangle, not the Munich municipal boundary. All four child lists also ended at 120, so their completeness remains unproven.

| Follow-up search | Results | New to the accumulated inventory |
|---|---:|---:|
| Southwest child / Restaurant / zoom 17 | 120 | 58 |
| Southeast child / Restaurant / zoom 17 | 120 | 27 |
| Northwest child / Restaurant / zoom 17 | 120 | 51 |
| Northeast child / Restaurant / zoom 17 | 120 | 25 |
| Centre / Döner / zoom 16 | 120 | 83 |
| Centre / Imbiss / zoom 16 | 120 | 61 |

The accumulated inventory now contains **706 distinct Maps IDs from 1,320 appearances in 18 successful searches**. Keywords are discovery signals; the actual business category still needs verification from detail data. The initial Imbiss attempt suffered an aborted Maps transport request and was excluded, then succeeded on one retry. No intentional detail or review requests were made.

The SQLite helper was exercised on these real captures and wired into the pilot's `--store` option. Reconciliation and restart preserved exactly 706 places, 18 search identities, and 1,320 unique search/place sightings. There is one pending detail job per canonical place identity. Nine tests cover restart/idempotence, concurrent reservations, stale worker rejection, backoff, exhausted crash recovery, coordinate ordering, transaction rollback, and polygon holes/edges.

An exploratory geographic classification used the archived deutschlandGeoJSON medium-resolution `Munich Städte` feature, derived from GIS-DATA. It classified 676 candidates inside and 30 outside, with no missing coordinates. This geometry is **preliminary**, not a verified current authoritative municipal boundary. It is not redistributed here. Replace it with a current appropriately sourced city polygon before production inclusion decisions, especially near the border. Source and boundary hash are recorded in [munich-refinement-results.json](munich-refinement-results.json).

The [bounded detail worker](munich-detail-pilot.md) now consumes the durable queue and has been tested on ten places, including two positive removal notices. Add current boundary provenance, refresh scheduling, and durable search-job reservations before launching the full-city campaign. The CLI's existing in-memory URL deduper remains unchanged; the new store serves the experiment and its detail worker.
