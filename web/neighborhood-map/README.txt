TEMPELHOFER RESTAURANT SIGNAL
Rund um die Gottlieb-Dunkel-Straße · 2 km Umkreis

Die ZIP-Datei vollständig entpacken und index.html im Browser öffnen.
Für den OpenStreetMap-Kartenhintergrund ist Internet erforderlich.
Die Leaflet-Bibliothek liegt lokal bei. Bei blockierten Kartenkacheln bleiben
Marker, Filter, Liste und Google-Maps-Links nutzbar.

Zum Teilen im Internet den gesamten entpackten Ordner auf einen statischen
Webhost hochladen, z. B. als neues Cloudflare-Pages-Projekt per Direct Upload.
index.html, app.js, data.js, styles.css und vendor müssen zusammenbleiben.
Die bestehende Münchner Website wird dadurch nicht verändert.

restaurants.csv: kompakter Export für Tabellenprogramme, UTF-8 mit BOM.
data.json: dieselben Kartenzeilen mit Datenverfügbarkeit und Zeitpunkten.
coverage.json: Suchumfang und Erfassungsfortschritt dieses Exports.

Orte: mindestens 25 zuletzt bekannte Bewertungen; keine bestätigte dauerhafte
Schließung. Fehlende Zahlen werden nicht als Null interpretiert.
Der Mittelpunkt entspricht dem Straßenmittelpunkt, nicht einer Hausnummer.
Alle Entfernungen sind Luftlinie.

Löschhinweise sind Googles Spannweiten für Entfernungen im vergangenen Jahr,
nicht die Gesamtzahl jemals gelöschter oder gelöschter Ein-Stern-Bewertungen.
Ohne erkannten Hinweis bleibt die Zahl unbekannt. Ein Hinweis beweist nicht,
wer eine Entfernung veranlasst hat. Widersprüchliche Sprachfassungen werden
gesondert markiert. Originale Detailantworten bleiben im Scraper-Datensatz.

Die Ergebnislisten von Google Maps sind begrenzt. coverage_complete=false
ist beabsichtigt: Es wird keine garantierte vollständige Erfassung behauptet.

Erstellt mit dem Scraper unter:
https://github.com/jcmpagel/google-maps-scraper
Leaflet 1.9.4: siehe vendor/LEAFLET-LICENSE.txt
Kartenmaterial: https://www.openstreetmap.org/copyright
