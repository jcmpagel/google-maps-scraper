TEMPELHOFER RESTAURANT SIGNAL
3 km rund um die Gottlieb-Dunkel-Straße · Tempelhof / Neukölln

Die ZIP-Datei vollständig entpacken und index.html im Browser öffnen.
Kein Build und kein JavaScript-CDN erforderlich. Alle Dateien zusammenlassen.
Falls du die separat bereitgestellte Einzeldatei tempelhof-restaurant-karte.html
hast, genügt es, nur diese Datei zu öffnen; Entpacken ist dann nicht nötig.

Die Karte enthält einen lokalen, echten Berliner Straßenplan samt Straßennamen
und Marker-Clustern. Mit Internet werden zusätzlich normale OpenStreetMap-
Kacheln geladen. Ohne erreichbare Kacheln bleibt der lokale Straßenplan nutzbar.
Mobil: Karte direkt im ersten Bildschirm; unten zwischen Karte, Orten und
Filtern wechseln. Ein Ort öffnet seine Details in einer schließbaren Ansicht.

Base-Score = Bayes-Score, wie im Münchner Vorbild mit 100 Vergleichsbewertungen.
Formel: (Sterne * Bewertungszahl + lokaler Durchschnitt * 100) /
(Bewertungszahl + 100). Der Score bleibt zwischen 1 und 5.
Der lokale Durchschnitt kann sich vom Münchner Datensatz unterscheiden.
Löschhinweise sind separate Beobachtungen und keine Strafpunkte im Score.

restaurants.csv: Tabellenexport (UTF-8 mit BOM).
data.json: Kartendaten mit Verfügbarkeit und Erfassungszeitpunkten.
coverage.json: Radius, Zielzahl und tatsächlicher Erfassungsumfang.
restaurants.kml: direkt in Google Earth öffnen oder in Google My Maps
als neue Ebene importieren; enthält nur geprüfte Orte ab 25 Bewertungen.

Zum öffentlichen Teilen den gesamten Ordner als NEUES Cloudflare-Pages-Projekt
per Direct Upload hochladen. Das ZIP ist dafür vorbereitet. Die Münchner Seite
wird nicht ersetzt. Dieses Paket allein erzeugt noch keine öffentliche URL.

Der größere Umkreis verwendet bereits gefundene Google-Orts-IDs und fertige
Details weiter. Nicht erneut abgefragte Kandidaten sind ausdrücklich markiert;
die Standardansicht zeigt geprüfte Orte mit mindestens 25 bekannten Bewertungen.
Dauerhaft geschlossene Orte und bestätigt kleinere Bewertungszahlen werden
übersprungen. Unbekannte Werte werden nicht als gemessene Null interpretiert.
Alle Entfernungen sind Luftlinie ab einem ungefähren Straßenmittelpunkt.
Die Ergebnislisten sind begrenzt: keine garantierte vollständige Bezirksliste.

Löschhinweise sind Googles Spannweiten für im vergangenen Jahr entfernte
Rezensionen nach Beschwerden wegen Diffamierung unter deutschem Recht.
Kein Nachweis, wer eine Entfernung veranlasst hat; keine Gesamtzahl aller
jemals gelöschten oder gelöschten Ein-Stern-Bewertungen. Ohne erkannten
Hinweis bleibt die Zahl unbekannt. Widersprüche werden gesondert markiert.

Lokaler Straßenplan: © OpenStreetMap contributors / EqualStreetNames Berlin,
ODbL 1.0. Die abgeleitete Straßendatenbank liegt separat als basemap.geojson vor.
Quelle, SHA-256, Version und Änderungen: basemap.source.json.
Lizenz und Quellenangaben: BASEMAP-LICENSE.txt.
Leaflet 1.9.4 und Leaflet.markercluster 1.5.3: Lizenzen unter vendor/.

Code und Datensnapshot:
https://github.com/jcmpagel/google-maps-scraper/tree/main/web/neighborhood-map
