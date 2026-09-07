# Lokale Entwicklung

Eine vollständige Umgebung lässt sich am schnellsten mit Docker Compose starten. Die direkte Ausführung eignet sich für Änderungen, die nur Backend oder Frontend betreffen.

## Voraussetzungen

- Docker mit Compose-Unterstützung
- Python 3.13 und `uv` für direkte Python-Entwicklung
- Node.js 24 und npm für Frontend und Dokumentation
- Zugangsdaten für die konfigurierten OpenAI-kompatiblen und Langfuse-Endpunkte

## Anwendungen konfigurieren

Zunächst ignorierte Umgebungsdateien aus den eingecheckten Vorlagen erstellen:

```bash
cp core/backend/.env.example core/backend/.env
cp indexer/.env.example indexer/.env
```

Die Vorlagen sind bewusst minimal. Der Backend-Code prüft beim Start zusätzlich folgende Werte:

| Variable                                                      | Zweck                                                                           |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `DLF_SESSION_SECRET`                                          | Signiert Browser-Session-Cookies                                                |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Prompt-Laden, Tracing und Feedback                                              |
| `OPENAI_API_KEY`, `OPENAI_API_BASE`                           | Zugriff auf Chat-, Embedding- und Reranking-API                                 |
| `OPENAI_CHAT_MODEL`, `OPENAI_EMBEDDING_MODEL`                 | Auswahl der Laufzeitmodelle                                                     |
| `QDRANT_URL`                                                  | Endpunkt der Vektordatenbank; Compose überschreibt ihn mit `http://qdrant:6333` |

Wenn die Plattform einen reinen Lesezugang bereitstellt, sollte der Core `QDRANT_READONLY_API_KEY` verwenden. Der Indexer benötigt `QDRANT_API_KEY` mit Schreibrechten für Collections und Points.

::: warning Übereinstimmende Konfiguration
`OPENAI_EMBEDDING_MODEL`, `EMB_SPARSE_MODEL`, `VDB_DENSE_VECTOR_NAME` und `VDB_SPARSE_VECTOR_NAME` müssen in Core und Indexer übereinstimmen.
:::

## Vollständigen Stack starten

```bash
docker compose up --build core
```

Compose startet Qdrant und Core. Danach sind erreichbar:

- Oberfläche: `http://localhost:8080/`
- Health Check: `http://localhost:8080/api/healthz`
- OpenAPI-Oberfläche: `http://localhost:8080/docs`, wenn `DLF_ENABLE_DOCS=true`
- Qdrant: `http://localhost:6333`

Der Indexer liegt hinter einem expliziten Profil, weil er externe Systeme aufruft und Qdrant-Daten verändert:

```bash
docker compose --profile indexer run --rm indexer
```

## Komponenten direkt ausführen

Vor dem Start von FastAPI muss das Frontend in das Static-Verzeichnis des Backends gebaut werden:

```bash
cd core/frontend
npm ci
npm run buildlocal

cd ../backend
uv sync
uv run python app.py
```

Ohne vorherigen Frontend-Build liefert `core/backend/app.py` nur die Platzhalterseite des Quellbaums aus. Für Hot Reload im Frontend:

```bash
cd core/frontend
npm ci
npm run dev
```

Die Anwendung läuft unter `http://localhost:8082/`. Das Entwicklungsfrontend erwartet die in `src/util/constants.ts` konfigurierte API-Basis-URL.

## Qualitätsprüfungen ausführen

```bash
cd core/backend
uv sync
uv run ruff check .
uv run pytest

cd ../frontend
npm ci
npm run lint
npm run build

cd ../../indexer
uv sync
uv run ruff check .
uv run pytest
```

## Dokumentation bearbeiten

```bash
cd docs
npm install
npm run docs:dev
```

Die Entwicklungs-URL lautet normalerweise `http://localhost:5173`. Der Produktions-Build wird mit `npm run docs:build` geprüft und mit `npm run docs:preview` betrachtet.

## Häufige Fehler

| Symptom                                      | Wahrscheinliche Ursache                                                                  |
| -------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Backend beendet sich beim Import             | Eine erforderliche Session- oder Langfuse-Variable fehlt                                 |
| Backend startet, aber Retrieval schlägt fehl | Collections sind leer, Zugangsdaten falsch oder Vektorkonfigurationen unterscheiden sich |
| Nur eine Platzhalterseite erscheint          | Das Frontend wurde nicht mit `npm run buildlocal` gebaut                                 |
| Indexer endet mit Status 2                   | `QDRANT_URL` oder `QDRANT_API_KEY` fehlt                                                 |
| Indexer stoppt nach dem Sammeln              | Weniger als `DLF_INDEXER_MIN_ARTICLES` Dienstleistungsartikel wurden geliefert           |
| Browser blockiert Aufrufe                    | Der Origin fehlt in der kommaseparierten Variable `DLF_ALLOWED_ORIGINS`                  |
