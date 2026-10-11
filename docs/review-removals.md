# Review-removal notices

Review-removal extraction is part of the scraper on `main`; no separate feature branch is needed. It works in the normal place-detail parser and the search-results parser used by fast mode.

Google Maps sometimes includes a notice that reviews were removed **in the past year due to defamation complaints under German law**. The scraper exports the bounds from that notice. This is not a lifetime deletion total, a count of deleted one-star reviews, or evidence that a restaurant requested the removals.

## Output fields

| Field | Meaning |
|---|---|
| `removed_reviews_min` | Inclusive lower bound of the parsed notice |
| `removed_reviews_max` | Inclusive upper bound; `0` means open-ended when the minimum is positive |
| `removed_reviews_status` | `parsed`, `not_present`, or `unrecognized` |
| `removed_reviews_notice` | Original notice text used to parse the bounds, or an unrecognized notice for diagnosis |
| `review_count_available` | Whether Google supplied a valid current review count |
| `reviews_per_rating_available` | Whether Google supplied all five valid star counts |

These fields are present in JSON and CSV. CSV also includes the flattened `reviews_1_star` through `reviews_5_star` columns.

Examples:

- “Two to five” or “zwei bis fünf” → minimum `2`, maximum `5`, status `parsed`.
- “201 to 250” or “201 bis 250” → minimum `201`, maximum `250`, status `parsed`.
- “Over 250” or “über 250” → minimum `251`, maximum `0`, status `parsed`.
- No removal notice → minimum `0`, maximum `0`, status `not_present`.
- A removal notice with unsupported wording → minimum `0`, maximum `0`, status `unrecognized`, with the notice text retained.

**Neither `not_present` nor `unrecognized` proves that no reviews were removed.** A dashboard must not classify a restaurant as having zero deletions solely because the numeric fields are zero. The notice is not guaranteed to appear in every response or locale.

For compatibility, existing numeric review-count fields still default to zero when Google omits them. Check their availability flags before treating them as measured values or using them in scores. A real, supplied zero count has `review_count_available=true`. A missing count has `review_count_available=false`. Partial or missing histograms have `reviews_per_rating_available=false`.

## Parsing and tests

The scraper reads type-3 notices from the Maps payload, tries their full and shortened text, and returns the first recognized range. It does not add together duplicate notices. Posting restrictions and hidden-post notices are separate notice types and are not numeric removal totals.

Supported formats include English and German small-number words, numeric ranges with `to`, `bis`, or dash separators, thousands separators, singular notices, and open-ended ranges. Unsupported formats remain distinguishable through their status and original text. Positive bounds are required, and reversed ranges are rejected.

Run the regression tests with:

```bash
go test -race ./gmaps
```

The tests exercise both parsers, JSON/CSV output, missing versus supplied zero metrics, notice selection, and a reduced real German payload from La Casa de Kebab. That payload previously produced `0/0` for “zwei bis fünf”; it now produces `2/5`.

## Munich dashboard files

The core review-removal feature is versioned here. The custom Munich grid scripts, dashboard generator, and generated `gmaps-output/restaurant-dashboard` site identified in the local workflow were not present in the published branch histories when this feature was consolidated onto `main`.

Recover and version those original scripts before claiming the complete dashboard pipeline is reproducible from this repository. Generated outputs should remain in the ignored output directory. Any dashboard consuming these fields also needs to honor the notice status and metric availability flags.
