(() => {
  'use strict';
  const dataset = window.RESTAURANT_DATA;
  if (!dataset?.meta || !Array.isArray(dataset.rows)) return;
  const { meta, rows } = dataset;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const number = value => value == null ? '–' : new Intl.NumberFormat('de-DE').format(value);
  const decimal = (value, digits = 1) => value == null ? '–' : new Intl.NumberFormat('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  const score = row => row.base_score ?? row.bayesian ?? null;
  const positive = row => row.positive_share == null ? '–' : `${decimal(100 * row.positive_share)} %`;
  const safeLink = value => { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? esc(url.href) : '#'; } catch { return '#'; } };
  const removal = row => row.notice_conflict ? 'Widersprüchliche Hinweise' : row.removal_status === 'parsed' && row.removed_min > 0 ? (row.removed_max > 0 ? (row.removed_min === row.removed_max ? number(row.removed_min) : `${number(row.removed_min)}–${number(row.removed_max)}`) : `Mindestens ${number(row.removed_min)}`) : row.removal_status === 'unrecognized' ? 'Text nicht erkannt' : row.removal_status === 'not_present' ? 'Kein Hinweis erfasst' : 'Noch nicht abgefragt';
  const badge = row => `<span class="badge ${row.removal_status === 'parsed' && !row.notice_conflict ? 'notice' : !row.detail_checked ? 'pending' : ''}">${esc(removal(row))}</span>`;
  const verified = rows.filter(r => r.detail_checked && r.review_count != null && r.review_count >= meta.minimum_reviews);
  $('category').innerHTML += [...new Set(rows.map(r => r.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'de')).map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
  document.title = meta.title; $('title').textContent = meta.title;
  $('radiusLabel').textContent = `${decimal(meta.radius_m / 1000, 0)} km Umkreis · Tempelhof / Neukölln`;
  $('detailCount').textContent = number(verified.length);
  $('noticeCount').textContent = number(verified.filter(r => r.removal_status === 'parsed' && !r.notice_conflict).length);
  const finished = meta.campaign_jobs.done || 0;
  $('searchCount').textContent = number(finished);
  const date = new Date(meta.generated_at).toLocaleString('de-DE', { timeZone: 'Europe/Berlin', dateStyle: 'medium', timeStyle: 'short' });
  $('captureDate').textContent = `Stand: ${date} Uhr (Berlin)`;
  $('coverage').textContent = `${number(verified.length)} geprüfte Orte mit mindestens ${meta.minimum_reviews} bekannten Bewertungen im ${decimal(meta.radius_m / 1000, 0)}-km-Umkreis. ${meta.collection_mode === 'expand_existing_inventory' ? 'Bereits gefundene Orts-IDs und fertige Details wurden wiederverwendet; weitere Detailantworten ergänzen den größeren Umkreis. Die Quellsuchen konzentrierten sich auf das ursprüngliche Gebiet. ' : `${finished} Suchläufe abgeschlossen. `}${meta.target_places ? `Ziel: mindestens ${meta.target_places} passende Orte. ` : ''}${meta.searches_without_confirmed_end ? `Bei ${meta.searches_without_confirmed_end} Quelllisten wurde das Listenende nicht bestätigt. ` : ''}${meta.data_paused ? 'Die Erfassung ist wegen einer Zugriffsbegrenzung pausiert. ' : ''}Stand: ${date} Uhr. ${number(rows.filter(r => r.detail_checked && r.review_count == null).length)} weitere Detailantworten ohne bekannte Bewertungszahl bleiben außerhalb der Standardansicht.`;

  const mobile = matchMedia('(max-width: 760px)');
  function syncPanels() {
    for (const [panel, anchor, dialog] of [['filters', 'filterAnchor', 'filterDialog'], ['detail', 'detailAnchor', 'detailDialog']]) {
      if (mobile.matches) $(dialog).append($(panel));
      else { if ($(dialog).open) $(dialog).close(); $(anchor).after($(panel)); }
    }
    if (map) setTimeout(() => map.invalidateSize(), 100);
  }
  document.addEventListener('click', event => { const button = event.target.closest('[data-close]'); if (button) $(button.dataset.close).close(); });
  $('showFilters').addEventListener('click', () => $('filterDialog').showModal());
  $('applyFilters').addEventListener('click', () => $('filterDialog').close());
  $('showMap').addEventListener('click', () => $('mapSection').scrollIntoView({ block: 'start' }));
  $('showPlaces').addEventListener('click', () => $('placesSection').scrollIntoView({ block: 'start' }));
  for (const id of ['filterDialog', 'detailDialog']) $(id).addEventListener('click', event => { if (event.target === $(id)) { const box = $(id).getBoundingClientRect(); if (event.clientY < box.top || event.clientY > box.bottom || event.clientX < box.left || event.clientX > box.right) $(id).close(); } });

  let map, radiusLayer, markerLayer, selected, loadedTiles = 0, tileErrors = 0, visible = [], offlineLayer;
  const markerById = new Map();
  if (window.L) {
    map = L.map('map', { preferCanvas: true, scrollWheelZoom: false, zoomAnimation: false, fadeAnimation: false }).setView(meta.center, 13);
    if (window.OFFLINE_BASEMAP?.features?.length) {
      offlineLayer = L.layerGroup().addTo(map);
      L.geoJSON(window.OFFLINE_BASEMAP, { interactive: false, style: feature => ({ color: '#c7cebf', weight: feature.properties?.major ? 6 : 3.5, opacity: 1 }) }).addTo(offlineLayer);
      L.geoJSON(window.OFFLINE_BASEMAP, { interactive: false, style: feature => ({ color: feature.properties?.major ? '#faf3d8' : '#fffef8', weight: feature.properties?.major ? 4 : 2, opacity: 1 }) }).addTo(offlineLayer);
      map.createPane('streetLabels'); map.getPane('streetLabels').style.zIndex = 450; map.getPane('streetLabels').style.pointerEvents = 'none';
      const streetLabels = L.layerGroup().addTo(offlineLayer);
      const drawLabels = () => {
        streetLabels.clearLayers();
        if (!map.hasLayer(offlineLayer)) return;
        const occupied = [], zoom = map.getZoom();
        for (const label of window.OFFLINE_BASEMAP.labels || []) {
          if (zoom < 14 && !label.major && label.length_m < 400 || !map.getBounds().contains(label.point)) continue;
          const point = map.latLngToContainerPoint(label.point), width = Math.min(175, label.name.length * 5.5 + 12);
          const box = [point.x - width / 2 - 5, point.y - 13, point.x + width / 2 + 5, point.y + 13];
          if (occupied.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue;
          occupied.push(box);
          L.marker(label.point, { pane: 'streetLabels', interactive: false, keyboard: false, icon: L.divIcon({ className: `street-label${label.major ? ' major' : ''}`, html: esc(label.name), iconSize: [width, 18], iconAnchor: [width / 2, 9] }) }).addTo(streetLabels);
          if (occupied.length >= (zoom < 14 ? 35 : 90)) break;
        }
      };
      map.on('zoomend moveend', drawLabels); drawLabels();
      map.attributionControl.addAttribution(window.OFFLINE_BASEMAP.attribution || 'Lokaler Straßenplan');
    }
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>', detectRetina: false }).on('tileload', () => { loadedTiles++; if (offlineLayer && map.hasLayer(offlineLayer)) map.removeLayer(offlineLayer); $('basemapLabel').textContent = 'Straßenkarte · OpenStreetMap'; }).on('tileerror', () => {
      if (++tileErrors > 2 && !loadedTiles) {
        $('mapFallback').hidden = false;
        $('basemapLabel').textContent = offlineLayer ? 'Lokaler Straßenplan · offline verfügbar' : 'Straßenkarte derzeit offline';
        if (offlineLayer) $('mapFallback').textContent = 'Die Online-Kacheln sind nicht erreichbar. Der mitgelieferte Straßenplan bleibt mit allen Ortsmarkern nutzbar.';
      }
    }).addTo(map);
    radiusLayer = L.circle(meta.center, { radius: meta.radius_m, color: '#55764c', weight: 1.4, dashArray: '4 7', fillOpacity: 0 }).addTo(map);
    L.marker(meta.center, { icon: L.divIcon({ className: '', html: '<div class="street-centre"></div>', iconSize: [16, 16], iconAnchor: [8, 8] }) }).addTo(map).bindTooltip('Gottlieb-Dunkel-Straße · Straßenmittelpunkt');
    markerLayer = L.markerClusterGroup ? L.markerClusterGroup({ maxClusterRadius: 38, disableClusteringAtZoom: 16, showCoverageOnHover: false, spiderfyOnMaxZoom: true, animate: false }) : L.layerGroup();
    markerLayer.addTo(map);
    map.fitBounds(radiusLayer.getBounds(), { padding: [15, 15] });
  } else { $('mapFallback').hidden = false; $('map').style.display = 'none'; }
  function colour(row) {
    if ($('colour').value === 'notices') return row.notice_conflict || row.removal_status === 'unrecognized' ? '#945bb0' : row.removal_status === 'parsed' ? '#bd8532' : row.removal_status === 'not_present' ? '#348a86' : '#a3ae9d';
    const value = $('colour').value === 'rating' ? row.rating : score(row);
    return value == null ? '#a3ae9d' : value >= 4.75 ? '#16734e' : value >= 4.5 ? '#348a86' : '#bd8532';
  }
  function select(row, pan = true) {
    selected = row.id;
    const histogram = row.histogram ? [5, 4, 3, 2, 1].map(star => { const count = row.histogram[String(star)] ?? 0; const total = Object.values(row.histogram).reduce((sum, n) => sum + n, 0); return `<div class="stars-row"><span>${star} ★</span><span class="bar"><b style="width:${total ? 100 * count / total : 0}%"></b></span><span>${number(count)}</span></div>`; }).join('') : '<p class="muted">Keine vollständige Sterne-Verteilung in der Antwort.</p>';
    $('detail').innerHTML = `<div class="sheet-heading"><div><p class="eyebrow">Dein nächster Stopp</p><h2>${esc(row.title)}</h2></div><button class="close-sheet" type="button" data-close="detailDialog" aria-label="Ortsdetails schließen">×</button></div><p class="muted">${esc(row.category || 'Kategorie noch unbekannt')}<br>${esc(row.address)}<br>${number(row.distance_m)} m Luftlinie</p><div class="metrics"><div class="primary-metric"><span>Base-Score · Bayes</span><strong>${decimal(score(row), 2)}</strong></div><div><span>Google-Bewertung</span><strong>${decimal(row.rating)}${row.rating != null ? ' ★' : ''}</strong></div><div><span>Bewertungen${row.review_count != null && !row.review_count_available ? ' · Suchkarte' : ''}</span><strong>${number(row.review_count)}</strong></div><div><span>Anteil 4–5 Sterne</span><strong>${positive(row)}</strong></div></div>${histogram}<p class="field-label">Löschhinweis · vergangenes Jahr</p>${badge(row)}${row.notice ? `<blockquote>${esc(row.notice)}</blockquote>` : '<p class="muted">Ohne erkannten Hinweis bleibt die Zahl der Entfernungen unbekannt.</p>'}<p class="muted">${row.languages.length ? `Abgefragte Sprachen: ${esc(row.languages.join(', ').toUpperCase())}.` : 'Noch keine Detailabfrage.'}</p><a class="detail-link" href="${safeLink(row.link)}" target="_blank" rel="noopener noreferrer">In Google Maps öffnen ↗</a>${row.website ? `<br><a class="detail-link" href="${safeLink(row.website)}" target="_blank" rel="noopener noreferrer">Website des Orts ↗</a>` : ''}`;
    document.querySelectorAll('tr[data-id]').forEach(tr => tr.classList.toggle('is-selected', tr.dataset.id === selected));
    if (pan && map) { map.setView([row.lat, row.lon], 16, { animate: false }); markerById.get(row.id)?.openPopup(); }
    if (mobile.matches && !$('detailDialog').open) $('detailDialog').showModal();
  }
  function render() {
    const query = $('search').value.trim().toLocaleLowerCase('de');
    visible = rows.filter(r => (!query || `${r.title} ${r.address} ${r.category} ${r.categories.join(' ')}`.toLocaleLowerCase('de').includes(query)) && (!$('category').value || r.category === $('category').value) && r.review_count != null && r.review_count >= Number($('minimum').value) && (!$('checked').checked || r.detail_checked) && (!$('notices').checked || r.removal_status === 'parsed' && !r.notice_conflict));
    const criterion = $('sort').value;
    visible.sort((a, b) => criterion === 'distance' ? a.distance_m - b.distance_m : criterion === 'reviews' ? b.review_count - a.review_count : criterion === 'rating' ? (b.rating ?? -1) - (a.rating ?? -1) || b.review_count - a.review_count : criterion === 'positive' ? (b.positive_share ?? -1) - (a.positive_share ?? -1) || b.review_count - a.review_count : (score(b) ?? -1) - (score(a) ?? -1) || b.review_count - a.review_count);
    $('visibleCount').textContent = number(visible.length); $('mobileCount').textContent = number(visible.length); $('resultLabel').textContent = `${number(visible.length)} Orte`; $('empty').hidden = visible.length > 0;
    $('rows').innerHTML = visible.map(r => `<tr data-id="${esc(r.id)}"><td><button class="venue-button" type="button">${esc(r.title)}</button><span class="venue-meta">${esc(r.category || 'Details ausstehend')}</span></td><td><span class="score">${decimal(score(r), 2)}</span></td><td class="rating">${decimal(r.rating)}${r.rating != null ? ' ★' : ''}</td><td>${number(r.review_count)}</td><td>${number(r.distance_m)} m</td><td>${badge(r)}</td></tr>`).join('');
    $('cards').innerHTML = visible.map(r => `<button class="venue-card" type="button" data-id="${esc(r.id)}"><span class="card-heading"><strong>${esc(r.title)}</strong><span class="score">${decimal(score(r), 2)}</span></span><span class="card-meta">${esc(r.category || 'Details ausstehend')} · ${number(r.distance_m)} m entfernt</span><span class="card-stats"><span>${decimal(r.rating)} ★</span><span>${number(r.review_count)} Bewertungen</span>${badge(r)}</span></button>`).join('');
    for (const container of ['rows', 'cards']) $(container).querySelectorAll('[data-id]').forEach(el => (container === 'rows' ? el.querySelector('button') : el).addEventListener('click', () => select(visible.find(r => r.id === el.dataset.id))));
    if (map) {
      markerLayer.clearLayers(); markerById.clear();
      for (const row of visible) {
        const marker = L.marker([row.lat, row.lon], { title: row.title, icon: L.divIcon({ className: '', html: `<div class="pin-dot" style="background:${colour(row)}"></div>`, iconSize: [14, 14], iconAnchor: [7, 7] }) });
        marker.bindPopup(`<strong>${esc(row.title)}</strong><br>Base ${decimal(score(row), 2)} · ${decimal(row.rating)} ★<br>${number(row.review_count)} Bewertungen<br>${esc(removal(row))}`);
        marker.on('click', () => select(row, false)); markerLayer.addLayer(marker); markerById.set(row.id, marker);
      }
    }
    $('legend').innerHTML = $('colour').value === 'notices' ? '<span><i style="background:#bd8532"></i>Hinweis erkannt</span><span><i style="background:#348a86"></i>Kein Hinweis erfasst · Zahl unbekannt</span><span><i style="background:#945bb0"></i>Unklarer Hinweis</span>' : '<span><i style="background:#16734e"></i>4,75–5,00</span><span><i style="background:#348a86"></i>4,50–4,74</span><span><i style="background:#bd8532"></i>Unter 4,50</span><span><i style="background:#a3ae9d"></i>Unbekannt</span>';
  }
  for (const id of ['search', 'category', 'minimum', 'sort', 'colour', 'checked', 'notices']) $(id).addEventListener(id === 'search' ? 'input' : 'change', render);
  $('fit').addEventListener('click', () => { if (map) { map.closePopup(); map.fitBounds(radiusLayer.getBounds(), { padding: [15, 15] }); } });
  $('reset').addEventListener('click', () => { $('search').value = ''; $('category').value = ''; $('minimum').value = '25'; $('sort').value = 'bayesian'; $('colour').value = 'base'; $('checked').checked = true; $('notices').checked = false; render(); });
  mobile.addEventListener('change', syncPanels); syncPanels(); render();
  window.mapReady = true;
  window.mapDiagnostics = () => ({ visibleMarkers: markerById.size, loadedTiles, offlineFeatures: window.OFFLINE_BASEMAP?.features?.length || 0, offlineVisible: !!offlineLayer && map.hasLayer(offlineLayer), clustered: !!markerLayer?.getVisibleParent });
})();
