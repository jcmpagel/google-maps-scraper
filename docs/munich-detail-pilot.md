# Bounded Munich detail worker

The pilot now connects the persistent discovery queue to live place-detail capture and the normal Go parser. It uses one browser worker, at most twenty places per invocation (five by default), and fifteen seconds between locale page visits. It does not scroll or download full review histories. This is a small validation worker, not a full-city launch.

```bash
source /workspace/.setup/google-maps-scraper/activate.sh
go build -p 4 -o bin/parse-place ./cmd/parse-place
NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
  node scripts/munich_detail_worker.cjs \
    gmaps-output/munich-inventory.sqlite \
    gmaps-output/munich-details \
    /workspace/google-maps-scraper/bin/parse-place --limit 5
```

The default claim rectangle is `48.13,11.56,48.145,11.59`, around central Munich. `--bbox minLat,minLon,maxLat,maxLon` narrows it. Jobs must also have `scope=inside` in the store; the rectangle cannot override an unknown or outside classification. The current experimental city polygon remains preliminary. Use a current authoritative boundary before expanding the campaign.

Each job is reserved with an expiring lease. A captured place's DataID/CID is checked against that job before storing anything as successful; 64-bit CID comparison uses integer arithmetic without JavaScript precision loss. `cmd/parse-place` reads captured JSON from stdin and exports the repository's Entry schema. Missing identity or title is an error.

The worker captures German first. The default `--fallback missing-data` tries English when current review metrics are missing or the removal notice is unrecognized. A missing notice with complete metrics remains `not_present`, without an extra English visit. `--fallback notice-or-metrics` also tests English for absent notices; that broader policy was used in the first small comparison. A fallback counts as a separate page visit. The worker keeps both observations with language, time, and raw-payload path. Available metrics may fill absent metrics; a missing notice never establishes zero removals. Different parsed ranges across languages set `detail_removal_conflict=true` and leave the merged numeric range unrecognized (0/0), retaining both original ranges for inspection. No exact lifetime or one-star removal count is inferred. Missing-data mode can miss notices available only in an unrequested locale; its results are language-specific observations, not proof of absence.

Raw payloads, parsed results, and per-run reports stay under ignored `gmaps-output`. UUID report filenames retain run history; `run.json` points to the latest report. Completed jobs remain done across worker restarts and imports. Failed fetches are recorded with queue backoff and stop that invocation. Lease completion rejects stale workers. The worker uses TLS-verifying Playwright request transport through the existing HTTPS proxy, skips image/media/font loads and the previously identified optional ad/log endpoints, and stops on transport failures, access blocks, or challenges.

A database-adjacent `.detail-worker.lock` permits one detail worker for that local database at a time. Normal shutdown removes it. After a hard crash, inspect the PID and running processes before removing a stale lock; do not remove an active worker's lock. Expired job leases can then be recovered. `.detail-pacing.json` persists the most recent locale visit, enforcing the minimum fifteen-second gap across subsequent invocations as well as within a run. This lock is a local single-worker safeguard, not a cross-host distributed scheduler or a sustained rate guarantee.

```bash
node --test scripts/test_detail_worker.cjs
python3 -m unittest discover -s scripts -p 'test_discovery_store.py'
go test -race ./gmaps ./cmd/parse-place
```

Refresh scheduling, authoritative boundary sourcing, broader category validation, and a shared pacing budget across search/detail processes remain necessary before a full-city campaign. Stop discovery while this small worker is running so the pilot has one active source of Maps traffic.

## Live iteration — 12 October 2026

Ten distinct places were fetched successfully in eighteen locale page visits, with no failed jobs. The first five central places used German and English; neither locale yielded a removal notice, while review counts and histograms were available. La Casa de Kebab, selected as a known positive case, returned the German range **2–5** with missing current review metrics. Its English capture supplied those metrics and the same range, without a conflict. The merged result retained both original observations.

Three more central places tested the cheaper fallback policy: Wolf’s Brotzeitladen required English to complete missing metrics, while The Rooftop Restaurant and SEBASTIANS needed only German. Thus this small comparison used four instead of six locale visits. It does not establish a representative fallback rate for Munich.

A second invocation restricted to the already-completed La Casa job made zero locale visits and completed zero jobs; its first result and per-run history were preserved. Aggregate evidence is in [munich-detail-results.json](munich-detail-results.json). Sendling’s Spezial Kebap House Marienplatz also returned a matching German/English range of **101–150**, with English filling missing metrics. All ten stored records have available review counts and five-star histograms after merging; in these captures each histogram sums to the corresponding review count. Eight remain `not_present`; that does not mean zero deletions.
