# Small-area restaurant maps

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

The cloud proxy denies the public OSM tile host in this environment, so browser tests also verify the explicit no-basemap fallback. The downloaded package still requests normal OpenStreetMap tiles in a connected browser and preserves attribution. Do not claim that a blocked test screenshot shows a loaded street basemap. The complete site and exports remain usable without tile responses.
