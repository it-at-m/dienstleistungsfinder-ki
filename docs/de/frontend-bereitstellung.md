# Frontend und Bereitstellung

Das Vue-Frontend wird als Standard-Custom-Element `<dlf-search-webcomponent>` ausgeliefert. Das produktive Core-Image stellt sowohl den Loader als auch die API bereit. Dadurch lässt sich die Komponente ohne eigenen Frontend-Dienst einbetten.

## Aufbau des Frontends

`src/dlf-search-webcomponent.ce.vue` steuert den Suchablauf und kombiniert spezialisierte UI-Komponenten für Einführung, Suchfeld, Fortschritt, Ergebnisdokumente, Filterauswahl, Beispiele und Feedback. API-Zugriffe liegen getrennt in den Services unter `src/api/`; TypeScript-Interfaces bilden die Request- und Response-Modelle des Backends ab.

Beim Mounten lädt die Komponente:

- Laufzeitkonfiguration für Feedback und Beispiele von `/api/config`;
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

### Ein Release erstellen

Änderungen nach `main` mergen, die relevanten CI-Prüfungen abwarten und den lokalen Checkout mit `git switch main` und `git pull --ff-only` aktualisieren. Der Arbeitsbaum muss sauber sein und `HEAD` muss dem veröffentlichten `main`-Commit des gewählten Remotes entsprechen.

Den interaktiven Helfer im Repository-Stamm ausführen (Python und Git müssen installiert sein):

```bash
python scripts/release.py
```

Das Skript fragt zuerst, ob **both** (beide Images), **core** oder **indexer** veröffentlicht werden sollen, und anschließend nach **patch**, **minor** oder **major**:

- **Patch**: Fehlerkorrekturen, z. B. `1.2.3` → `1.2.4`.
- **Minor**: abwärtskompatible Funktionen, z. B. `1.2.3` → `1.3.0`.
- **Major**: inkompatible Änderungen, z. B. `1.2.3` → `2.0.0`.

Die nächste Version wird für jede Komponente unabhängig anhand ihres höchsten stabilen Release-Tags auf dem Remote berechnet. Prerelease- und fremde Tags werden ignoriert; ohne stabilen Tag ist die Ausgangsversion `0.0.0`. Das Skript zeigt Commit, Tags und Image-Namen und fragt nach einer Bestätigung, bevor es annotierte Tags erstellt und gemeinsam atomar pusht. Nur die ausgewählten Tags werden gepusht. Lokale Tag-Kollisionen brechen das Release ab.

Für eine Vorschau ohne Erstellen oder Pushen von Tags oder für einen anderen konfigurierten Remote:

```bash
python scripts/release.py --dry-run
python scripts/release.py --remote upstream
```

Die Workflows **Release core image** und/oder **Release indexer image** in [GitHub Actions](https://github.com/it-at-m/Dienstleistungsfinder-KI/actions) verfolgen. Die Images stehen nach erfolgreichem Workflow-Abschluss zur Verfügung. Diese Workflows veröffentlichen Container-Images; sie erstellen keine GitHub-Release-Seite und ändern keine Paketversionsdateien. Bei einem fehlgeschlagenen Push behält das Skript lokale Tags und zeigt Befehle zur Wiederherstellung an; vor einem erneuten Versuch den Remote prüfen.

Für ein manuelles Release den benötigten Tag erstellen und pushen, zum Beispiel:

```bash
git tag -a core-v1.0.1 -m "Release core-v1.0.1"
git push origin refs/tags/core-v1.0.1:refs/tags/core-v1.0.1
```

Die Beispielversion durch die nächste unbenutzte Version ersetzen. Für ein Indexer-Release `indexer-vX.Y.Z` verwenden.

## Checkliste für Produktion

1. Getrennte Qdrant-Zugangsdaten mit minimalen Rechten für Core und Indexer verwenden.
2. Modell- und Vektoreinstellungen in beiden Images identisch halten.
3. Ein starkes `DLF_SESSION_SECRET` und explizite `DLF_ALLOWED_ORIGINS` setzen.
4. `/docs` mit `DLF_ENABLE_DOCS=false` abschalten, wenn die interaktive API-Dokumentation nicht öffentlich sein soll.
5. Health Probes auf `/api/healthz` konfigurieren.
6. Indexer ausführen und prüfen, bevor Nutzerverkehr auf eine neue Collection geleitet wird.
7. Image-Digests festschreiben und Qdrant-Snapshots für Rollbacks aufbewahren.

Umgebungsspezifische OpenShift-Ressourcen, Zeitpläne, Secrets und Promotion-Regeln liegen bewusst außerhalb dieses öffentlichen Repositorys.
