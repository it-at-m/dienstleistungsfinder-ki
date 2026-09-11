# Suche und API

Der Core stellt eine FastAPI-Anwendung bereit und kombiniert LangChain-Runnables für Query Enhancement, hybride Suche, optionales Reranking und dokumentgebundene Antworten.

## Suchkette

<img class="diagram light-only" src="../graphics/AnswerChain.png" alt="Quellengebundene Antwortkette für ein gefundenes Dokument">
<img class="diagram dark-only" src="../graphics/AnswerChain_dark.png" alt="Quellengebundene Antwortkette für ein gefundenes Dokument">

1. **Erweitern:** Das Chatmodell formuliert eine natürlichsprachliche Frage bei `enhance_query=true` in suchgeeignete Verwaltungsbegriffe um.
2. **Filtern:** Exakte Schlagwörter und Kategorien werden zu Qdrant-Payload-Filtern. Unbekannte Werte werden abgewiesen.
3. **Suchen:** Jede gewählte Collection führt dichte und Sparse-Suche aus; Qdrant kombiniert Kandidaten mit `VDB_RETRIEVAL_FUSION` (Standard `DBSF`).
4. **Neu sortieren:** Wenn aktiviert, ordnet ein OpenAI-kompatibles Cohere-Rerank-Modell die Kandidaten neu. Optionale Besuchsstatistiken erzeugen einen begrenzten Popularitäts-Boost.
5. **Antworten:** Der Antwort-Endpunkt lädt ein ausgewähltes Qdrant-Dokument und fordert vom Modell eine ausschließlich auf diesem Inhalt basierende Antwort an.

## HTTP-Endpunkte

| Methode | Pfad                    | Funktion                                             | Zielgruppe            |
| ------- | ----------------------- | ---------------------------------------------------- | --------------------- |
| GET     | `/api/healthz`          | Prozessstatus und Anwendungsversion                  | Betrieb               |
| GET     | `/api/keywords`         | Gültige Schlagwortfilter                             | Frontend, MCP-Clients |
| GET     | `/api/categories`       | Gültige Kategoriefilter                              | Frontend, MCP-Clients |
| GET     | `/api/config`           | Beispiele und Feedback-Vorlagen                      | Frontend              |
| POST    | `/api/retrieval`        | Priorisierte Dienstleistungsdokumente abrufen        | Frontend, MCP-Clients |
| POST    | `/api/answer`           | Antwort aus einem ausgewählten Dokument erzeugen     | Frontend              |
| POST    | `/api/score`            | Binäres Feedback mit einem Langfuse-Trace verknüpfen | Frontend              |
| GET     | `/api/popularity-stats` | Aktuelle Statistik zur Popularitätsnormalisierung    | Betrieb               |

Interaktive Swagger- und ReDoc-Oberflächen sind unter `/docs` und `/redoc` verfügbar, sofern `DLF_ENABLE_DOCS` nicht auf `false` gesetzt ist.

## Typischer API-Ablauf

Zunächst werden Dokumente gesucht:

```bash
curl -X POST http://localhost:8080/api/retrieval \
  -H 'Content-Type: application/json' \
  -c cookies.txt -b cookies.txt \
  -d '{
    "query": "Welche Unterlagen brauche ich für die Wohnsitzanmeldung?",
    "enhance_query": true,
    "result": "full",
    "collections": ["service", "info"],
    "rerank": true
  }'
```

Die Antwort enthält `retrieval_documents`, eine `run_id` und eine `enhanced_query`. Für den anwendungsspezifischen Antworthelfer werden `id` und `collection` des gewählten Dokuments zusammen mit denselben Anfrage- und Laufkennungen übergeben:

```json
{
  "doc": { "id": "<dokument-id>", "collection": "service" },
  "enhanced_query": { "...": "aus der Retrieval-Antwort übernehmen" },
  "run_id": "<run-id>"
}
```

Allgemeine Assistenten können `result: "full"` anfordern und direkt auf Grundlage des zurückgegebenen `page_content` antworten. Sie benötigen `/api/answer` nicht.

## Retrieval-Steuerung

Das Modell `RetrievalInput` unterstützt Query Enhancement, exakte Schlagwort- und Kategoriefilter, Collection-Auswahl, minimale oder vollständige Ergebnisse, Reranking, Inhalte in Leichter Sprache, Kategorieabgleich, eine optionale Ergebnisanzahl und eine vorhandene `run_id`. Das generierte OpenAPI-Schema ist die verbindliche Beschreibung des im ausgecheckten Stand gültigen Request-Modells.

Mit `RERANK_OVERRIDE=true` können Betreibende den Wert des Frontends ignorieren und `RERANK` erzwingen. So lässt sich ein langsamer oder nicht verfügbarer Reranker im Störungsfall ohne Client-Neubau abschalten.

## Fehler und Observability

- `422` kennzeichnet ungültige Anfrageformen oder unbekannte Filterwerte.
- `404` bedeutet, dass das gewählte Dokument keine quellengebundene Antwort ermöglicht hat.
- Verstöße gegen Inhaltsrichtlinien eines Modells werden in einen eindeutigen API-Fehler übersetzt.

Das Session-Cookie gruppiert Browseraktivitäten; die `run_id` verbindet Retrieval-, Antwort- und Score-Aufrufe. Langfuse-Callbacks erfassen Kettenaktivität, Prompts, Laufzeiten und Nutzerfeedback. Rohdaten von Secrets und sensible Nutzereingaben dürfen nicht in eigene Log-Ausgaben aufgenommen werden.

## MCP-Freigabe

`MCP_ENDPOINTS` wird von `core/backend/settings.py` als Umgebungseinstellung eingelesen: eine JSON-Liste von Methoden-Pfad-Objekten, beispielsweise `[{"method":"POST","path":"/api/retrieval"}]`. In `.env` oder der Container-Umgebung setzen und Core neu starten. Eine leere Liste deaktiviert alle MCP-Tools. Zunächst ist nur `POST /api/retrieval` freigegeben. Eine abschließende Ausschlussregel verhindert, dass weitere Endpunkte automatisch als MCP-Tools oder Ressourcen erscheinen. Für Antworten auf Basis der Dokumenttexte explizit `result="full"` angeben.
