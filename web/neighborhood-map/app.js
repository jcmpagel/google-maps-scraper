(() => {
  'use strict';
  const dataset = window.RESTAURANT_DATA;
  if (!dataset?.meta || !Array.isArray(dataset.rows)) return;
  const { meta, rows } = dataset;
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const number = value => value === null || value === undefined ? '–' : new Intl.NumberFormat('de-DE').format(value);
  const decimal = value => value === null || value === undefined ? '–' : value.toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const safeLink = value => { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? escape(url.href) : '#'; } catch { return '#'; } };
  const removal = row => {
    if (row.notice_conflict) return 'Widersprüchliche Hinweise';
    if (row.removal_status === 'parsed' && row.removed_min > 0) return row.removed_max > 0 ? (row.removed_min === row.removed_max ? number(row.removed_min) : `${number(row.removed_min)}–${number(row.removed_max)}`) : `Mindestens ${number(row.removed_min)}`;
    if (row.removal_status === 'unrecognized') return 'Text nicht erkannt';
    if (row.removal_status === 'not_present') return 'Kein Hinweis erfasst';
    return 'Noch nicht abgefragt';
  };
  const badge = row => `<span class="badge ${row.removal_status === 'parsed' && !row.notice_conflict ? 'notice' : !row.detail_checked ? 'pending' : ''}">${escape(removal(row))}</span>`;
  const categories = [...new Set(rows.map(r => r.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'de'));
  $('category').innerHTML += categories.map(c => `<option value="${escape(c)}">${escape(c)}</option>`).join('');
  document.title = meta.title;
  $('title').textContent = meta.title;
  $('detailCount').textContent = number(meta.checked_details);
  $('noticeCount').textContent = number(rows.filter(r => r.removal_status === 'parsed' && !r.notice_conflict).length);
  const finished = meta.campaign_jobs.done || 0;
  const unfinished = Object.entries(meta.campaign_jobs).filter(([state]) => state !== 'done').reduce((total, [, count]) => total + count, 0);
  $('searchCount').textContent = `${finished} / ${finished + unfinished}`;
  const date = new Date(meta.generated_at).toLocaleString('de-DE', { timeZone: 'Europe/Berlin', dateStyle: 'medium', timeStyle: 'short' });
  $('captureDate').textContent = `Stand: ${date} Uhr (Berlin)`;
  $('coverage').textContent = `${meta.shown_candidates} passende Kartenkandidaten im 2-km-Umkreis, ${meta.checked_details} mit abgefragten Details. ${finished} Suchläufe abgeschlossen${unfinished ? `, ${unfinished} noch offen oder nicht erfolgreich` : ''}. ${meta.searches_without_confirmed_end ? `Bei ${meta.searches_without_confirmed_end} Suchlisten wurde das Listenende nicht bestätigt. ` : ''}${meta.data_paused ? 'Die Erfassung ist wegen einer Zugriffsbegrenzung pausiert. ' : ''}Stand: ${date} Uhr. Die Suche kann weitere Betriebe übersehen; dies ist keine vollständige Bezirksliste.`;
  let map, radiusLayer, markers = [], selected = null, tileErrors = 0;
  if (window.L) {
    map = L.map('map', { preferCanvas: true, scrollWheelZoom: false }).setView(meta.center, 14);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>', detectRetina: false }).on('tileerror', () => { if (++tileErrors > 2) $('mapFallback').hidden = false; }).addTo(map);
    radiusLayer = L.circle(meta.center, { radius: meta.radius_m, color: '#446c5b', weight: 1.5, dashArray: '5 7', fillColor: '#cae3cc', fillOpacity: 0.07 }).addTo(map);
    L.marker(meta.center, { icon: L.divIcon({ className: '', html: '<div class="street-centre"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }) }).addTo(map).bindTooltip('Gottlieb-Dunkel-Straße · Straßenmittelpunkt');
    map.fitBounds(radiusLayer.getBounds(), { padding: [15, 15] });
  } else { $('mapFallback').hidden = false; $('map').style.display = 'none'; }
  function colour(row) {
    if ($('colour').value === 'notices') return row.notice_conflict || row.removal_status === 'unrecognized' ? '#945bb0' : row.removal_status === 'parsed' ? '#b96e00' : row.removal_status === 'not_present' ? '#087d8d' : '#94a09a';
    return row.rating === null ? '#94a09a' : row.rating >= 4.5 ? '#0f8f68' : row.rating >= 4 ? '#087d8d' : '#b96e00';
  }
  function select(row, pan = true) {
    selected = row.id;
    if (pan && map) map.setView([row.lat, row.lon], Math.max(map.getZoom(), 15));
    const histogram = row.histogram ? [5, 4, 3, 2, 1].map(star => {
      const count = row.histogram[String(star)] ?? 0;
      const total = Object.values(row.histogram).reduce((sum, n) => sum + n, 0);
      return `<div class="stars-row"><span>${star} ★</span><span class="bar"><b style="width:${total ? 100 * count / total : 0}%"></b></span><span>${number(count)}</span></div>`;
    }).join('') : '<p class="muted">Keine vollständige Sterne-Verteilung in der Antwort.</p>';
    $('detail').innerHTML = `<p class="eyebrow">Dein nächster Stopp</p><h2>${escape(row.title)}</h2><p class="muted">${escape(row.category || 'Kategorie noch nicht abgefragt')}<br>${escape(row.address)}<br>${number(row.distance_m)} m Luftlinie</p><div class="metrics"><div><span>Google-Bewertung</span><strong>${decimal(row.rating)}${row.rating !== null ? ' ★' : ''}</strong></div><div><span>Bewertungen${row.review_count !== null && !row.review_count_available ? ' · Suchkarte' : ''}</span><strong>${number(row.review_count)}</strong></div></div>${histogram}<p class="field-label">Löschhinweis · vergangenes Jahr</p>${badge(row)}${row.notice ? `<blockquote>${escape(row.notice)}</blockquote>` : '<p class="muted">Ohne erkannten Hinweis bleibt die Zahl der Entfernungen unbekannt.</p>'}<p class="muted">${row.languages.length ? `Abgefragte Sprachen: ${escape(row.languages.join(', ').toUpperCase())}.` : 'Noch keine Detailabfrage.'}${row.bayesian !== null ? ` Gewichtete Bewertung: ${decimal(row.bayesian)}.` : ''}</p><a class="detail-link" href="${safeLink(row.link)}" target="_blank" rel="noopener noreferrer">In Google Maps öffnen ↗</a>${row.website ? `<br><a class="detail-link" href="${safeLink(row.website)}" target="_blank" rel="noopener noreferrer">Website des Orts ↗</a>` : ''}`;
    document.querySelectorAll('tr[data-id]').forEach(tr => tr.classList.toggle('is-selected', tr.dataset.id === selected));
  }
  function render() {
    const query = $('search').value.trim().toLocaleLowerCase('de');
    const category = $('category').value;
    const minimum = Number($('minimum').value);
    const visible = rows.filter(r => (!query || `${r.title} ${r.address} ${r.category} ${r.categories.join(' ')}`.toLocaleLowerCase('de').includes(query)) && (!category || r.category === category) && r.review_count !== null && r.review_count >= minimum && (!$('checked').checked || r.detail_checked) && (!$('notices').checked || r.removal_status === 'parsed' && !r.notice_conflict));
    const criterion = $('sort').value;
    visible.sort((a, b) => criterion === 'distance' ? a.distance_m - b.distance_m : criterion === 'reviews' ? b.review_count - a.review_count : criterion === 'rating' ? (b.rating ?? -1) - (a.rating ?? -1) || b.review_count - a.review_count : (b.bayesian ?? -1) - (a.bayesian ?? -1) || b.review_count - a.review_count);
    $('visibleCount').textContent = number(visible.length);
    $('resultLabel').textContent = `${number(visible.length)} Orte`;
    $('empty').hidden = visible.length > 0;
    $('rows').innerHTML = visible.map(r => `<tr data-id="${escape(r.id)}"><td><button class="venue-button" type="button">${escape(r.title)}</button><span class="venue-meta">${escape(r.category || 'Details ausstehend')}</span></td><td class="rating">${decimal(r.rating)}${r.rating !== null ? ' ★' : ''}</td><td>${number(r.review_count)}</td><td>${number(r.distance_m)} m</td><td>${badge(r)}</td></tr>`).join('');
    $('rows').querySelectorAll('tr').forEach(tr => tr.querySelector('button').addEventListener('click', () => select(visible.find(r => r.id === tr.dataset.id))));
    if (map) {
      markers.forEach(m => m.remove()); markers = [];
      for (const row of visible) {
        const marker = L.circleMarker([row.lat, row.lon], { radius: Math.max(5, Math.min(10, 3 + Math.log10((row.review_count || 0) + 1) * 2)), color: 'white', weight: 1.5, fillColor: colour(row), fillOpacity: .88 }).addTo(map);
        marker.bindPopup(`<strong>${escape(row.title)}</strong><br>${decimal(row.rating)} ★ · ${number(row.review_count)} Bewertungen<br>${escape(removal(row))}`);
        marker.on('click', () => select(row, false)); markers.push(marker);
      }
    }
    $('legend').innerHTML = $('colour').value === 'notices' ? '<span><i style="background:#b96e00"></i>Hinweis erkannt</span><span><i style="background:#087d8d"></i>Kein Hinweis erfasst · Zahl unbekannt</span><span><i style="background:#945bb0"></i>Unklarer Hinweis</span><span><i style="background:#94a09a"></i>Nicht abgefragt</span>' : '<span><i style="background:#0f8f68"></i>Ab 4,5 Sternen</span><span><i style="background:#087d8d"></i>4,0–4,4 Sterne</span><span><i style="background:#b96e00"></i>Unter 4,0 Sternen</span><span><i style="background:#94a09a"></i>Bewertung unbekannt</span>';
  }
  for (const id of ['search', 'category', 'minimum', 'sort', 'colour', 'checked', 'notices']) $(id).addEventListener(id === 'search' ? 'input' : 'change', render);
  $('fit').addEventListener('click', () => { if (map) map.fitBounds(radiusLayer.getBounds(), { padding: [15, 15] }); });
  $('reset').addEventListener('click', () => { $('search').value = ''; $('category').value = ''; $('minimum').value = '25'; $('sort').value = 'bayesian'; $('colour').value = 'rating'; $('checked').checked = true; $('notices').checked = false; render(); });
  render();
  window.mapReady = true;
})();
