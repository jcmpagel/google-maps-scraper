const test = require('node:test');
const assert = require('node:assert/strict');
const { searchEvidence, detailExclusion } = require('./place_filters.cjs');
test('search cards distinguish absent counts, zero, thresholds and localized thousands', () => {
  assert.equal(searchEvidence(null, '', '').review_count, null);
  assert.equal(searchEvidence('(24)', '', '').review_count, 24);
  assert.equal(searchEvidence('(25)', '', '').review_count, 25);
  assert.equal(searchEvidence('(1.234)', '', '').review_count, 1234);
  assert.equal(searchEvidence(null, '4,6 Sterne 123 Rezensionen', '').review_count, 123);
  assert.equal(searchEvidence(null, '', 'Keine Rezensionen').review_count, 0);
  assert.equal(searchEvidence('(€€)', '', '').review_count, null);
});
test('temporary closure is not treated as permanent', () => {
  assert.equal(searchEvidence(null, '', 'Vorübergehend geschlossen').permanently_closed, null);
  assert.equal(searchEvidence(null, '', 'Dauerhaft geschlossen').permanently_closed, true);
  assert.equal(detailExclusion({ status: 'Temporarily closed' }), null);
  assert.equal(detailExclusion({ status: 'Permanently closed' }), 'permanently_closed');
});
test('detail threshold retains 25 and unknown counts', () => {
  assert.equal(detailExclusion({ review_count: 24, review_count_available: true }), 'under_25_reviews');
  assert.equal(detailExclusion({ review_count: 25, review_count_available: true }), null);
  assert.equal(detailExclusion({ review_count: 0, review_count_available: false }), null);
});
