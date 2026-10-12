# Durable discovery and detail-job store

`scripts/discovery_store.py` provides a SQLite inventory and transactional detail-job queue for the Munich experiment. It makes no network requests. The pilot can import completed searches automatically with `--store DATABASE` and optionally classify coordinates with `--boundary GEOJSON` after each search. The existing Go CLI does not yet use this store; no automatic detail worker has been connected.

The store normalizes hexadecimal Maps feature IDs and decimal CID links to the same decimal CID identity. Other place identifiers retain their case. It records query parameters and search provenance, earliest/latest observation dates, coordinates, boundary classification, and detail-job state. Importing a checkpoint twice does not create another place, sighting, or detail job. Failed searches are excluded; an invalid checkpoint import rolls back. Older observations do not replace newer coordinates. A changed coordinate resets its geographic classification until classification is rerun.

```bash
python3 scripts/discovery_store.py gmaps-output/munich.sqlite import \
  gmaps-output/munich-pilot/discovery.json
python3 scripts/discovery_store.py gmaps-output/munich.sqlite classify PATH_TO_CITY_BOUNDARY.geojson
python3 scripts/discovery_store.py gmaps-output/munich.sqlite stats
```

Supply a GeoJSON Polygon or MultiPolygon, optionally inside a Feature, in WGS84 longitude/latitude order. Holes are excluded; points on an exterior edge are included. Missing coordinates remain `unknown`. Boundary bytes are hashed and the hash is stored with each classification, so the polygon used is identifiable. Polygon provenance and accuracy must be established separately; geometry hashing does not establish that a polygon is authoritative or current.

Only places classified `inside` can receive a detail-job lease. Unknown and outside places remain in the inventory for provenance and reclassification but are excluded from claims. `eligible_details` distinguishes the scoped queue from all pending discoveries.

```bash
# Reserves one eligible job for five minutes; prints JSON or null.
python3 scripts/discovery_store.py gmaps-output/munich.sqlite claim

# After a separate worker fetches the corresponding place:
python3 scripts/discovery_store.py gmaps-output/munich.sqlite finish LEASE_TOKEN RESULT.json

# A failed fetch remains retryable with backoff:
python3 scripts/discovery_store.py gmaps-output/munich.sqlite fail LEASE_TOKEN 'temporary transport error'
```

Reservations use `BEGIN IMMEDIATE` and are exclusive across SQLite connections. Completion requires the active, unexpired lease token. A worker whose lease expired cannot overwrite a reclaimed job. Failed jobs receive increasing backoff and stop after three attempts; expired reservations can be recovered, with the same attempt ceiling. Successful jobs remain done when overlapping discoveries are reimported. Store the actual scraper JSON in `RESULT.json`, retaining removal-notice status and metric availability; discovery alone is not evidence about removals.

Tests use temporary databases, multiple concurrent connections, controlled lease times, and synthetic polygons:

```bash
python3 -m unittest discover -s scripts -p 'test_discovery_store.py' -v
```

SQLite files and captures belong in ignored `gmaps-output`. Before scaling, connect a paced detail worker, define refresh scheduling for completed details, use a current authoritative municipal boundary, and add durable reservations for search jobs themselves. Search execution remains a single-worker checkpointed experiment; the detail queue's transaction guarantees do not turn it into a distributed search scheduler. Normalized-URL fallback identities are weaker than Maps identifiers and may require reconciliation when a stronger identifier becomes available. The imported search format currently assumes the prepared pilot's German locale and viewport.
