# Systemarchitektur

Das System ist in einen asynchronen Schreibpfad und einen nutzerseitigen Lesepfad aufgeteilt. Beide verwenden dieselbe Embedding-Konfiguration und dieselben Qdrant-Vektornamen. Werden diese Werte nur auf einer Seite geändert, sind die indizierten Daten nicht mehr mit der Suche kompatibel.

## Komponenten

| Komponente      | Technologie          | Ausführungsform                   | Hauptabhängigkeit                           |
| --------------- | -------------------- | --------------------------------- | ------------------------------------------- |
| Suchoberfläche  | Vue 3 Custom Element | Statische Browserdateien          | Core-HTTP-API                               |
| Core-API        | FastAPI, LangChain   | Dauerhafter Dienst auf Port 8080  | Qdrant, OpenAI-kompatible API, Langfuse     |
| MCP-Server      | MCP Python SDK       | Dauerhafter Dienst auf Port 8080  | Core-Retrieval-API                           |
| Indexer         | Python, LangChain    | Bedarfs- oder zeitgesteuerter Job | Inhalts-APIs, Qdrant, OpenAI-kompatible API |
| Vektordatenbank | Qdrant               | Dauerhafter Dienst auf Port 6333  | Persistentes Volume                         |

Der Core-Container wird in mehreren Stufen erstellt. Zuerst baut Node das Frontend. Anschließend werden die statischen Dateien in das Python-Laufzeit-Image kopiert und von FastAPI unter `/` bereitgestellt. API-Routen liegen unter `/api`.

## Datenfluss

```text
Kommunale APIs ──► Indexer ──► dichte + dünnbesetzte Vektoren ──► Qdrant
                                                                       │
Browser ──► Vue Web Component ──► FastAPI ──► hybride Suche ───────────┘
                                      │
                                      ├──► OpenAI-kompatible Modelle
                                      └──► Langfuse-Traces und Feedback

MCP-Client ──► MCP-Server ──► FastAPI-Retrieval-API ──────────────────┘
```

Der MCP-Server ist ein schlanker Adapter für Agenten. Er bietet ein einzelnes schreibgeschütztes Retrieval-Tool an und delegiert die Suche an die Core-API; direkte Verbindungen zu Qdrant oder Modellanbietern bestehen nicht.

Die Collection `service` enthält strukturierte Dienstleistungsartikel. `info` enthält Magnolia-Informationsseiten. `VDB_COLLECTIONS` steuert, welche Builder der Indexer ausführt und welche Collections das Backend öffnet.

## Warum zwei Vektorarten?

Dichte Embeddings bilden semantische Ähnlichkeit ab: Unterschiedlich formulierte Fragen können im Vektorraum dennoch nahe beieinanderliegen. Sparse-BM25-Vektoren erhalten exakte Wortübereinstimmungen, was bei Verwaltungsbegriffen, Formularnamen und seltenen Kennungen wichtig ist. Qdrant führt beide Ergebnismengen zusammen, bevor optional ein Reranking erfolgt.

<img class="diagram light-only" src="../graphics/HowDoEmbeddingsWork.png" alt="Umwandlung von Text in Embeddings und Vergleich der Vektoren">
<img class="diagram dark-only" src="../graphics/HowDoEmbeddingsWork_dark.png" alt="Umwandlung von Text in Embeddings und Vergleich der Vektoren">

<img class="diagram light-only" src="../graphics/HybridSearch.png" alt="Kombination dichter und dünnbesetzter Suche zu einer hybriden Suche">
<img class="diagram dark-only" src="../graphics/HybridSearch_dark.png" alt="Kombination dichter und dünnbesetzter Suche zu einer hybriden Suche">

## Lebenszyklus des Core

Der Lifespan-Hook von FastAPI initialisiert die Anwendung in dieser Reihenfolge:

1. Langfuse verbinden und Prompt-Vorlagen laden.
2. Reranker erzeugen.
3. Chatmodell, dichtes Embedding-Modell und Sparse-BM25-Modell erzeugen.
4. Für jede konfigurierte Collection einen Qdrant Vector Store öffnen.
5. Query-Enhancement-, Retrieval-, Reranking-, Antwort- und Scrubber-Ketten zusammensetzen.
6. Optional die Aktualisierung der Popularitätsstatistik als Hintergrundtask starten.
7. Schlagwörter und Kategorien aus Qdrant-Metadaten oder Ersatzdateien laden.

Beim Herunterfahren wird der Popularitätstask beendet und Langfuse überträgt ausstehende Ereignisse.

## Vertrauens- und Datenschutzgrenzen

- Der Browser hält ausschließlich UI-Zustand und ein signiertes Session-Cookie.
- Optionales Scrubbing läuft vor dem Retrieval; nachfolgende Aufrufe sollten den bereinigten Text verwenden.
- Qdrant enthält normalisierte öffentliche Inhalte, Metadaten, Vektoren und optionale Besuchsstatistiken.
- Modell- und Observability-Aufrufe verlassen die Anwendung und müssen freigegebene Endpunkte verwenden.
- Secrets werden über Umgebungsvariablen injiziert und dürfen nicht eingecheckt werden.

## Technische Randbedingungen

Für Indizierung und Retrieval müssen dasselbe dichte Modell, dasselbe Sparse-Modell, dieselben Vektornamen und dieselben Dimensionen verwendet werden. Stabile UUIDv5-Dokument-IDs erlauben dem Indexer, geänderte Inhalte zu aktualisieren, anstatt Duplikate anzulegen. Der Core benötigt nur Lesezugriff auf Qdrant, während der Indexer Schreibrechte braucht.
