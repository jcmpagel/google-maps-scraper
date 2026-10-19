const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { entryIdentity, mergeObservations, needsEnglish, pace } = require('./munich_detail_worker.cjs');
const entry = (overrides = {}) => ({ data_id: '0x123:0xffffffffffffffff', removed_reviews_status: 'not_present', removed_reviews_min: 0, removed_reviews_max: 0, removed_reviews_notice: '', review_count: 0, review_count_available: false, reviews_per_rating: {}, reviews_per_rating_available: false, ...overrides });
const id = 'cid:18446744073709551615';

test('identity keeps 64-bit CID precision and rejects wrong venue', () => {
  assert.equal(entryIdentity(entry()), id);
  assert.throws(() => mergeObservations([{ language: 'de', entry: entry() }], 'cid:123'), /identity/);
});
test('English fallback adds notice and metrics without turning absence into zero evidence', () => {
  const result = mergeObservations([
    { language: 'de', entry: entry() },
    { language: 'en', entry: entry({ removed_reviews_status: 'parsed', removed_reviews_min: 2, removed_reviews_max: 5, removed_reviews_notice: 'Two to five reviews', review_count: 123, review_rating: 4.5, review_count_available: true }) },
  ], id);
  assert.equal(result.removed_reviews_min, 2);
  assert.equal(result.review_count, 123);
  assert.equal(result.review_rating, 4.5);
  assert.equal(result.reviews_per_rating_available, false);
  assert.equal(result.detail_observations.length, 2);
  assert.equal(mergeObservations([{ language: 'de', entry: entry() }], id).removed_reviews_status, 'not_present');
});
test('default fallback avoids another locale for complete metrics and absent notice', () => {
  const complete = entry({ review_count_available: true, reviews_per_rating_available: true });
  assert.equal(needsEnglish(complete, 'missing-data'), false);
  assert.equal(needsEnglish(complete, 'notice-or-metrics'), true);
  assert.equal(needsEnglish({ ...complete, reviews_per_rating_available: false }, 'missing-data'), true);
  assert.equal(needsEnglish({ ...complete, removed_reviews_status: 'unrecognized' }, 'missing-data'), true);
});
test('unrecognized fallback notice is retained rather than labelled absent', () => {
  const result = mergeObservations([{ language: 'de', entry: entry() },
    { language: 'en', entry: entry({ removed_reviews_status: 'unrecognized', removed_reviews_notice: 'Unsupported removal wording' }) }], id);
  assert.equal(result.removed_reviews_status, 'unrecognized');
  assert.equal(result.removed_reviews_notice, 'Unsupported removal wording');
});
test('conflicting locale ranges remain unrecognized and retain both observations', () => {
  const result = mergeObservations([
    { language: 'de', entry: entry({ removed_reviews_status: 'parsed', removed_reviews_min: 2, removed_reviews_max: 5 }) },
    { language: 'en', entry: entry({ removed_reviews_status: 'parsed', removed_reviews_min: 6, removed_reviews_max: 10 }) },
  ], id);
  assert.equal(result.detail_removal_conflict, true);
  assert.equal(result.removed_reviews_status, 'unrecognized');
  assert.equal(result.removed_reviews_min, 0);
  assert.equal(result.detail_observations[1].entry.removed_reviews_min, 6);
});
test('a new worker invocation respects the previous persisted visit time', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'detail-pace-'));
  try {
    const filename = path.join(directory, 'pace.json');
    let clock = 100000;
    const pauses = [];
    const wait = async milliseconds => { pauses.push(milliseconds); clock += milliseconds; };
    await pace(filename, () => clock, wait);
    clock += 1000;
    await pace(filename, () => clock, wait);
    assert.deepEqual(pauses, [14000]);
    assert.equal(JSON.parse(fs.readFileSync(filename)).lastVisit, 115000);
    fs.writeFileSync(filename, '{"lastVisit":"invalid"}');
    await assert.rejects(pace(filename, () => clock, wait), /Invalid/);
  } finally { fs.rmSync(directory, { recursive: true }); }
});
