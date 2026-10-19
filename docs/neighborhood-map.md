# Small-area restaurant maps

## Current map: expanded 3 km radius and 550-place target

The user expanded the request on 19 October 2026: at least 500 venues, a real street map, mobile-first interaction and scores inspired by the live Munich site. The current run is **`gmaps-output/berlin-tempelhof-3km`**, with a 3,000-metre radius and a target of **550 verified food venues with known counts of at least 25**. Its geographic inputs are versioned under `data/neighborhoods/berlin-tempelhof-3km`. The earlier 2 km database is preserved.

The original searches had already discovered 946 candidates within 3 km, including 757 eligible before category/detail checks. Rather than repeat those Google searches, a SQLite backup reuses all IDs, card evidence, completed details, search provenance and access-halt state, then reclassifies the wider circle. The source inventory must be inactive. This is an expansion over existing discoveries, not a claim of systematic or complete 3 km discovery coverage. The target manager drains small, globally paced batches and stops after the verified published count reaches the target. Remaining candidates may stay pending; `target_reached` means the requested count was met, not that all inventory jobs finished.

```bash
source /workspace/.setup/google-maps-scraper/activate.sh
export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
# Only create a NEW destination; never overwrite the existing completed run.
python3 scripts/expand_neighborhood_inventory.py SOURCE_DIRECTORY NEW_DIRECTORY --radius-m 3000 --target-places 550
python3 -u scripts/run_neighborhood_map.py NEW_DIRECTORY --workers 12 --target-places 550
```

Twelve lanes retain the shared two-second page-start budget and fifteen-second per-lane pacing. No traffic is needed to view the frozen `web/neighborhood-map` site. Rebuild the current output with `python3 scripts/build_neighborhood_map.py gmaps-output/berlin-tempelhof-3km/inventory.sqlite gmaps-output/berlin-tempelhof-3km/region.json gmaps-output/berlin-tempelhof-3km/map`.

### Real streets and mobile UI

The package ships a local street network, so blocked tile access no longer leaves an empty marker canvas. This is an independently published OpenStreetMap-derived dataset from **EqualStreetNames Berlin**, not a proxy for blocked tile requests. The pinned upstream commit, full source URL, SHA-256 and transformation details are in `web/neighborhood-map/basemap.source.json`; the source update is 2 October 2026. Selected real streets intersect a local bounding box with a one-kilometre margin. Coordinates are rounded to five decimals, street labels are derived from actual line midpoints, and unrelated person/etymology data is omitted. The derived machine-readable street database is supplied as `basemap.geojson` under ODbL 1.0, with attribution and license links. Restaurant observations remain a separate dataset.

Reproduce the street selection from the pinned, TLS-verified source download and its recorded hash with `python3 scripts/prepare_local_basemap.py SOURCE_GEOJSON SOURCE_PROVENANCE_JSON REGION_JSON OUTPUT_DIRECTORY`. The downloaded 83 MB source is not committed. The compact local geometry and labels are. Online OpenStreetMap tiles replace the local layer when available; cloud browser tests deliberately block online tiles and require the real local streets and labels to render.

Local Leaflet 1.9.4 and markercluster 1.5.3 provide zoom, clusters, selection and popups without a JS CDN. On phones, the map is visible in the first screen, with bottom navigation, native filter/detail dialogs, touch-sized controls and a card list. Desktop uses a sidebar and score table. Base-score is an explicit alias of the Bayesian rating, with 100 prior reviews and the local review-weighted mean, matching the Munich site's prior weight. Its separate `cleanPower`/`isClean` assumptions and midpoint removal rates are not copied: missing removal notices do not prove zero removals. Scores, star mix, raw Google ratings and removal ranges stay distinct. CSV/JSON and a verified-only KML for Google Earth/My Maps are included.

The browser smoke test covers desktop, 320/390-pixel phones and an 820-pixel tablet, filters, dialog closing/Escape, map/list selection, clusters and actual offline street labels:

```bash
node scripts/smoke_neighborhood_map.cjs MAP_DIRECTORY SCREENSHOT_DIRECTORY --require-streets
```

Supermarkets, wholesalers, manufacturers, restaurant-supply businesses, fuel stations and hotels are excluded by their primary category even when a secondary tag mentions a bakery or café. Their overall business ratings do not establish a restaurant score. Genuine hybrid café/bar venues remain eligible when the parsed categories support food service. Missing metrics remain unknown in the source inventory.

The public Berlin Cloudflare deployment still requires actual hosting access; no new URL is claimed merely from generating a static package. A single-file version avoids extraction and relative asset dependencies:

```bash
python3 scripts/bundle_neighborhood_map.py MAP_DIRECTORY OUTPUT.html
node scripts/smoke_neighborhood_map.cjs OUTPUT.html SCREENSHOT_DIRECTORY --require-streets
```

This embeds scripts, CSS, street geometry, licenses and functional CSV/JSON/KML downloads. The ODbL street export is downloadable separately from the same file. It does not need a server to open locally. The compact frozen source folder remains the canonical versioned site; the single HTML file is reproducible from it.

## Original 2 km pass (preserved)

The birthday-map request targets **Gottlieb-Dunkel-Straße, Berlin**, confirmed by the user, with a **2,000-metre radius**. The named-street Google Maps result supplied a map camera centre at latitude 52.4581966, longitude 13.4139015. We use that as an approximate street midpoint, not a private house address or a district boundary.

The Berlin campaign uses a separate database and a spherical radius polygon. Its `neighborhood` profile seeds a bounded one-kilometre grid and six food queries: Restaurant, Café, Imbiss, Döner, Pizzeria and Bäckerei. The initial pass contains 144 query/cell jobs. Unlike the whole-city profile it does not automatically grow an exponential subdivision tree. Capped lists remain flagged as uncertain; further refinement can be designed from the measured union. This bounded pass does not establish that every local restaurant was found.

## Data collection and map build

The prepared workspace stores this run under `gmaps-output/berlin-tempelhof`. `location.json` records the resolved street and map camera; `region.json` describes the requested scope; `boundary.geojson` defines the radius. The default Munich plan and its existing database are unchanged.

The reproducible area inputs are checked in under `data/neighborhoods/berlin-tempelhof`. For a fresh collection, copy those JSON files into a **new** output directory, initialize its campaign with the command below, then run the neighborhood manager. Preserve existing databases, locks and checkpoints when resuming.

```bash
source /workspace/.setup/google-maps-scraper/activate.sh
export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
python3 scripts/munich_campaign.py \
  gmaps-output/berlin-tempelhof/inventory.sqlite \
  gmaps-output/berlin-tempelhof/campaign \
  gmaps-output/berlin-tempelhof/boundary.geojson --profile neighborhood
```

That initializes or inspects the saved plan without browsing. `scripts/run_neighborhood_map.py gmaps-output/berlin-tempelhof --workers 8` first fills a small detail sample, then coordinates the remaining search/detail queue and rebuilds the local site periodically. Numbered lane locks, transactional place leases, a shared page budget and global access-block handling are reused. Run one neighborhood manager/coordinator at a time. As with the city campaign, background processes depend on this environment remaining alive; queues and captures are resumable when the same workspace is available.

Search coordinates classify candidate inclusion; the builder checks parsed detail coordinates again using great-circle distance. Confirmed counts under 25 and permanent closures are excluded. Missing review metrics remain unknown. The builder excludes obvious non-food categories and never treats an absent removal notice as proof of zero removals. It retains recognized ranges, unsupported notices, locale conflicts and the languages actually fetched.

```bash
python3 scripts/build_neighborhood_map.py \
  gmaps-output/berlin-tempelhof/inventory.sqlite \
  gmaps-output/berlin-tempelhof/region.json \
  gmaps-output/berlin-tempelhof/map
```

The static template in `web/neighborhood-map` follows the existing Munich map's green/cream layout. It includes filters, distance sorting, ratings, a conservative Bayesian rating, star histograms, source links and removal notices. Scores use valid rating/count data only, shrink towards the local review-weighted mean with a prior weight of 100, and do not penalize removal notices. Unknown metrics never become a zero score. Local Leaflet assets are pinned to 1.9.4 with the upstream license; only map tiles require an external connection. The original public Munich site is not overwritten or redeployed.

Outputs are `index.html`, local UI/vendor assets, `data.js`, `data.json`, `restaurants.csv`, `coverage.json`, and opening/upload instructions. The wrapper creates `tempelhof-restaurant-karte.zip` after the collection pass. Opening the extracted index locally requires no build step; a normal static host can serve the same folder. No Cloudflare deployment credentials are required to produce this portable package.

In the compact map exports, absent/unsupported/conflicting removal counts are `null` (blank in CSV). For a recognized open-ended range such as “over 250”, the lower bound is 251 and the upper bound is `null`. Interpret bounds together with `removal_status` and `notice_conflict`. The original scraper entries keep their existing zero sentinel for compatibility.

## Saved map snapshot

The published `web/neighborhood-map` folder includes the frozen Berlin `data.js`, `data.json`, `restaurants.csv` and `coverage.json` alongside its UI assets. Download the repository and open that folder's `index.html`, or upload the entire folder to a new static site. No live scraper, database, build or JavaScript CDN is needed to use the saved map. Read `coverage.json` for its exact capture time, finished/pending jobs and availability counts. Raw detail responses and the resumable SQLite queue remain in the workspace's separate campaign directory; they are not part of the compact public snapshot.

## Validation

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
node --test scripts/test_detail_worker.cjs scripts/test_place_filters.cjs
node --check web/neighborhood-map/app.js
source /workspace/.setup/google-maps-scraper/activate.sh
node --test scripts/test_maps_consent.cjs
node scripts/smoke_neighborhood_map.cjs gmaps-output/berlin-tempelhof/map
```

Tests cover scope clipping, the 24/25 threshold, missing counts, irrelevant categories, untrusted names in generated JavaScript, capped-neighborhood coverage, and inherited queue/filter behavior. Browser validation checks real-data marker/list selection, search, minimum-count filters, colour mode, resetting, fit-to-radius, desktop rendering and mobile overflow.

The full Go race suite was also run. Its scraper/parser tests pass; the existing VPS `TestCheckConnectivity_Success` fails because `/home/agent/.gmapssaas` is read-only in this cloud environment. No VPS provisioning is needed for this map. The test was neither disabled nor reported as passing.

The cloud proxy denies the public OSM tile host. The current package therefore includes and tests the real local street geometry described above; its screenshots no longer depend on loading online tiles. Connected browsers additionally request normal OpenStreetMap tiles. Loaded online tiles have not been verified in this cloud environment. Historical screenshots of the original 2 km pass had only the empty-background fallback and do not represent the current street map.
