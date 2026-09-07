# Frontend und Bereitstellung

Das Vue-Frontend wird als Standard-Custom-Element `<dlf-search-webcomponent>` ausgeliefert. Das produktive Core-Image stellt sowohl den Loader als auch die API bereit. Dadurch lässt sich die Komponente ohne eigenen Frontend-Dienst einbetten.

## Aufbau des Frontends

`src/dlf-search-webcomponent.ce.vue` steuert den Suchablauf und kombiniert spezialisierte UI-Komponenten für Einführung, Suchfeld, Fortschritt, Ergebnisdokumente, Filterauswahl, Beispiele und Feedback. API-Zugriffe liegen getrennt in den Services unter `src/api/`; TypeScript-Interfaces bilden die Request- und Response-Modelle des Backends ab.

Beim Mounten lädt die Komponente:

- Laufzeitkonfiguration für Feedback, Beispiele und Scrubber von `/api/config`;
- verfügbare Filterwerte von `/api/keywords` und `/api/categories`.

Eine Suche kann durch Text, Schlagwortfilter, Kategoriefilter oder eine Kombination ausgelöst werden. `AbortController` beendet eine laufende Anfrage, sobald eine neuere Suche startet. Nach dem Retrieval werden Antwortanfragen pro Kandidat ausgeführt und Ergebnisse fortlaufend angezeigt.

## Komponente einbetten

Der Build erzeugt einen Loader, der das gehashte Komponenten-Bundle importiert:

```html
<script src="https://your-core.example/loader.js" type="module"></script>

<dlf-search-webcomponent></dlf-search-webcomponent>
```

Hostseiten können kommaseparierte Metadatenfilter vorbelegen:

```html
<dlf-search-webcomponent
  categories="Wohnen, Mobilität"
  keywords="Anmeldung, Termin"
></dlf-search-webcomponent>
```

Die Komponente verwendet Shadow DOM über den Custom-Element-Build von Vue. Sie importiert das Stylesheet des Münchner Designsystems und bündelt Icon-Sprites sowie Komponentenstile.

## Build-Modi

| Befehl in `core/frontend` | Ergebnis                                                |
| ------------------------- | ------------------------------------------------------- |
| `npm run dev`             | Vite-Entwicklungsserver auf Port 8082                   |
| `npm run build`           | Produktives Web-Component-Bundle in `dist/`             |
| `npm run buildlocal`      | Build und Kopie der Dateien nach `core/backend/static/` |
| `npm run lint`            | ESLint- und Prettier-Prüfungen                          |

Der Post-Build-Prozess erzeugt `loader.js` mit dem tatsächlichen gehashten JavaScript-Dateinamen. Einbettende Seiten müssen den Vite-Asset-Hash daher nicht kennen.

## Core-Container

`core/Dockerfile` hat zwei Stufen:

1. Ein Node-24-UBI-Image installiert Frontend-Abhängigkeiten, lädt das fest versionierte Designsystem-CSS und führt den Produktions-Build aus.
2. Ein minimales UBI-Image installiert das Python-Backend mit `uv`, kopiert Backend und gebautes Frontend, läuft als UID 1001, öffnet Port 8080 und startet `python app.py`.

Der Indexer verwendet ein eigenes minimales UBI-Image und läuft ebenfalls als UID 1001. `/app/artifacts` ist gruppenbeschreibbar, um die Ausführung unter beliebigen OpenShift-UIDs zu unterstützen.

## Lokale Orchestrierung

`compose.yaml` definiert drei Services:

| Service   | Port   | Persistenz                 | Startverhalten              |
| --------- | ------ | -------------------------- | --------------------------- |
| `qdrant`  | 6333   | Named Volume `qdrant-data` | Normal                      |
| `core`    | 8080   | Zustandslos                | Normal; abhängig von Qdrant |
| `indexer` | keiner | Schreibt nach Qdrant       | Nur mit Profil `indexer`    |

Proxy-Variablen werden als Build-Argumente akzeptiert. Zur Laufzeit enthält `NO_PROXY` Qdrant und localhost.

## CI und Releases

Core-CI prüft das Python-Backend, lintet und baut das Frontend und baut den kombinierten Container. Indexer-CI führt Ruff, pytest und einen Image-Build aus. Beide Anwendungen werden unabhängig über semantische Versions-Tags veröffentlicht:

| Git-Tag          | Veröffentlichtes Image                                   |
| ---------------- | -------------------------------------------------------- |
| `core-vX.Y.Z`    | `ghcr.io/it-at-m/dienstleistungsfinder-ki-core:X.Y.Z`    |
| `indexer-vX.Y.Z` | `ghcr.io/it-at-m/dienstleistungsfinder-ki-indexer:X.Y.Z` |

Release-Workflows veröffentlichen außerdem `sha-<commit>`-Tags, Software Bills of Materials und Provenance-Attestierungen. Deployments sollten eine geprüfte semantische Version und einen unveränderlichen Digest statt `latest` festschreiben.

## Checkliste für Produktion

1. Getrennte Qdrant-Zugangsdaten mit minimalen Rechten für Core und Indexer verwenden.
2. Modell- und Vektoreinstellungen in beiden Images identisch halten.
3. Ein starkes `DLF_SESSION_SECRET` und explizite `DLF_ALLOWED_ORIGINS` setzen.
4. `/docs` mit `DLF_ENABLE_DOCS=false` abschalten, wenn die interaktive API-Dokumentation nicht öffentlich sein soll.
5. Health Probes auf `/api/healthz` konfigurieren.
6. Indexer ausführen und prüfen, bevor Nutzerverkehr auf eine neue Collection geleitet wird.
7. Image-Digests festschreiben und Qdrant-Snapshots für Rollbacks aufbewahren.

Umgebungsspezifische OpenShift-Ressourcen, Zeitpläne, Secrets und Promotion-Regeln liegen bewusst außerhalb dieses öffentlichen Repositorys.
