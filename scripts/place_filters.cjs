function searchEvidence(countText, ariaText, cardText) {
  const parenthesized = /^\s*\(([\d.,\s]+)\)\s*$/.exec(countText || '');
  const labelled = /(?:^|\s)(\d[\d.,\s]*)\s+(?:Rezensionen|Bewertungen|reviews)\b/i.exec(ariaText || '');
  const token = parenthesized?.[1] || labelled?.[1];
  let count = token ? Number(token.replace(/[.,\s]/g, '')) : null;
  if (count !== null && (!Number.isSafeInteger(count) || count < 0)) count = null;
  if (count === null && /\b(?:Keine Rezensionen|Noch keine Rezensionen|No reviews)\b/i.test(cardText || '')) count = 0;
  const closed = /\b(?:Dauerhaft geschlossen|Permanently closed)\b/i.exec(cardText || '');
  return { review_count: count, permanently_closed: closed ? true : null,
    count_text: token || null, closure_text: closed?.[0] || null, source: 'search_card' };
}

function detailExclusion(entry) {
  if (/^(?:Dauerhaft geschlossen|Permanently closed|CLOSED_PERMANENTLY)$/i.test((entry.status || '').trim())) return 'permanently_closed';
  if (entry.review_count_available && Number.isSafeInteger(entry.review_count) && entry.review_count >= 0 && entry.review_count < 25) return 'under_25_reviews';
  return null;
}
module.exports = { searchEvidence, detailExclusion };
