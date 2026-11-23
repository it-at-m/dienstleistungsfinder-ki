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

Die Release-Änderungen nach `main` mergen und die relevanten CI-Prüfungen abwarten. Das Skript taggt immer den veröffentlichten `main`-Commit des gewählten Remotes, unabhängig vom ausgecheckten Branch und lokalen Änderungen. Nach der Bestätigung lädt es diesen Commit herunter, ohne den Checkout zu verändern. Falls sich `main` auf dem Remote während der Abfragen geändert hat, das Skript erneut ausführen und den aktualisierten Commit prüfen.

Der lokale Helfer benötigt nur Python, Git und die bestehende Git-Anmeldung mit Berechtigung zum Pushen von Tags. Weder GitHub CLI noch Personal Access Token sind erforderlich. Vor dem ersten gebündelten Release `.github/workflows/release-project.yml` und das aktualisierte Skript nach `main` mergen. Das lokale Skript pusht Tags; GitHub Actions veröffentlicht anschließend das Release mit dem automatisch bereitgestellten `GITHUB_TOKEN` und den Berechtigungen `contents: write` und `actions: read`.

Den interaktiven Helfer im Repository-Stamm ausführen:

```bash
python scripts/release.py
```

Das Skript fragt zuerst, ob **both** (beide Images), **core** oder **indexer** neu gebaut werden sollen, und anschließend nach **patch**, **minor** oder **major** für das Projekt-Release und die ausgewählten Komponenten:

- **Patch**: Fehlerkorrekturen, z. B. `1.2.3` → `1.2.4`.
- **Minor**: abwärtskompatible Funktionen, z. B. `1.2.3` → `1.3.0`.
- **Major**: inkompatible Änderungen, z. B. `1.2.3` → `2.0.0`.

Die Komponentenversionen werden unabhängig anhand der höchsten stabilen Tags `core-vX.Y.Z` und `indexer-vX.Y.Z` auf dem Remote berechnet. Das Projekt erhält eine eigene Version `vX.Y.Z`, die anhand stabiler Projekt-Tags berechnet wird. Prerelease- und fremde Tags werden ignoriert; ohne stabilen Tag ist die Ausgangsversion `0.0.0`. Wird nur eine Komponente neu gebaut, wird die höchste stabile Image-Version der anderen Komponente wiederverwendet. Dafür muss bereits ein Release dieser Komponente existieren; andernfalls beide Images auswählen.

Das Skript zeigt Commit, Projektversion, Komponenten-Tags und Image-Namen und fragt nach einer Bestätigung. Es erstellt annotierte Tags für die ausgewählten Komponenten und das Projekt und pusht sie gemeinsam atomar. Fremde Tags werden nicht gepusht. Lokale Tag-Kollisionen brechen das Release ab. Die Annotation des Projekt-Tags speichert die Bundle-Metadaten zur Wiederaufnahme.

Für eine Vorschau ohne Erstellen oder Pushen von Tags oder für einen anderen konfigurierten Remote:

```bash
python scripts/release.py --dry-run
python scripts/release.py --remote upstream
```

Nach dem Pushen der Tags gibt das lokale Skript den Link zu [GitHub Actions](https://github.com/it-at-m/Dienstleistungsfinder-KI/actions) aus und beendet sich. Der Projekt-Tag startet **Release project**. Dieser Workflow wartet auf **Release core image** und **Release indexer image** und gleicht dabei den genauen Tag und Quell-Commit jedes Images ab. Auch der ursprüngliche Build eines wiederverwendeten Images wird geprüft. Sobald beide Builds erfolgreich sind, erstellt er ein GitHub Release namens **Dienstleistungsfinder KI vX.Y.Z**, listet beide Image-Versionen samt Build-Links auf und hängt `release.json` mit den Versionen und Quell-Commits des Bundles an. Die Pakete bleiben in GHCR getrennt; das Projekt-Release fasst sie zu einem dokumentierten Bundle zusammen. Paketversionsdateien werden nicht geändert.

Der Projekt-Workflow wartet bis zu eine Stunde auf Image-Builds. Schlägt ein Image-Workflow fehl, diesen über die GitHub-Actions-Weboberfläche erneut ausführen und den erfolgreichen Abschluss abwarten. Anschließend **Release project** für denselben Projekt-Tag erneut ausführen. Dessen Annotation bewahrt das genaue Bundle, sodass weder eine neue Versionserhöhung noch neue Tags nötig sind. Das GitHub Release wird zunächst als Entwurf erstellt, dann wird das Manifest hochgeladen und erst anschließend veröffentlicht. Ein erneuter Workflow-Lauf kann einen vorhandenen Entwurf fertigstellen und erkennt ein bereits veröffentlichtes Release. Bei einem fehlgeschlagenen lokalen Push bleiben Tags erhalten und Befehle zur Wiederherstellung werden ausgegeben; vor einem erneuten Versuch den Remote prüfen.

Um manuell nur ein Komponenten-Image zu veröffentlichen, dessen Tag erstellen und pushen, zum Beispiel:

```bash
git tag -a core-v1.0.1 -m "Release core-v1.0.1"
git push origin refs/tags/core-v1.0.1:refs/tags/core-v1.0.1
```

Die Beispielversion durch die nächste unbenutzte Version ersetzen. Für ein Indexer-Release `indexer-vX.Y.Z` verwenden. Manuelle Komponenten-Tags starten Image-Builds, erstellen aber kein gebündeltes GitHub Release.

## Checkliste für Produktion

1. Getrennte Qdrant-Zugangsdaten mit minimalen Rechten für Core und Indexer verwenden.
2. Modell- und Vektoreinstellungen in beiden Images identisch halten.
3. Ein starkes `DLF_SESSION_SECRET` und explizite `DLF_ALLOWED_ORIGINS` setzen.
4. `/docs` mit `DLF_ENABLE_DOCS=false` abschalten, wenn die interaktive API-Dokumentation nicht öffentlich sein soll.
5. Health Probes auf `/api/healthz` konfigurieren.
6. Indexer ausführen und prüfen, bevor Nutzerverkehr auf eine neue Collection geleitet wird.
7. Image-Digests festschreiben und Qdrant-Snapshots für Rollbacks aufbewahren.

Umgebungsspezifische OpenShift-Ressourcen, Zeitpläne, Secrets und Promotion-Regeln liegen bewusst außerhalb dieses öffentlichen Repositorys.
