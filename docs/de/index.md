---
layout: home

hero:
  name: "Dienstleistungsfinder KI"
  text: "Technische Dokumentation"
  tagline: Retrieval-Augmented Search für verlässliche Informationen zu kommunalen Dienstleistungen.
  actions:
    - theme: brand
      text: Architektur verstehen
      link: /de/architektur
    - theme: alt
      text: Lokal ausführen
      link: /de/lokale-entwicklung

features:
  - title: Hybride Suche
    details: Dichte OpenAI-Embeddings und Sparse-BM25-Vektoren durchsuchen gemeinsam die Qdrant-Collections.
  - title: Quellengebundene Antworten
    details: FastAPI-Retrieval- und Antwortketten verbinden Nutzende mit den ursprünglichen kommunalen Dokumenten.
  - title: Einbettbare Oberfläche
    details: Ein Vue Custom Element stellt die vollständige Suche zur Einbindung in andere Webseiten bereit.
---

## Aufgabe des Projekts

Dienstleistungsfinder KI ist eine Retrieval-Augmented-Generation-Anwendung (RAG) für Informationen zu öffentlichen Dienstleistungen. Sie sammelt offizielle Inhalte, wandelt sie in durchsuchbare Dokumente um, speichert dichte und dünnbesetzte Vektoren in Qdrant, ermittelt passende Dokumente zu einer natürlichsprachlichen Frage und kann eine Antwort erzeugen, die sich auf eine ausgewählte Quelle stützt.

Das Monorepository veröffentlicht drei unabhängig versionierte Anwendungen:

| Anwendung | Verzeichnis | Aufgabe                                                                                                  |
| --------- | ----------- | -------------------------------------------------------------------------------------------------------- |
| Core      | `core/`     | Vue Web Component, FastAPI-API, Retrieval- und Antwortketten sowie Auslieferung statischer Dateien       |
| Indexer   | `indexer/`  | Sammlung, Normalisierung, Embedding, Qdrant-Indizierung und optionale Anreicherung mit Popularitätsdaten |
| MCP-Server | `mcp/`     | MCP-Tool, das die Core-Suche über Streamable HTTP oder stdio für Agenten bereitstellt                    |

Qdrant bildet die gemeinsame Schnittstelle zwischen Indexer und Core: Der Indexer schreibt Collections, der Core liest sie. Der MCP-Server ruft den Core auf und greift nicht direkt auf Qdrant zu. Dadurch kann die Indizierung als geplanter Job laufen, ohne an den nutzerseitigen Anfrageverkehr gekoppelt zu sein.

## Anfrage von Anfang bis Ende

1. Eine Person stellt im Web Component eine Frage.
2. Das Frontend lässt personenbezogene Angaben optional durch das Backend entfernen.
3. Das Backend erweitert die Suchanfrage, führt eine hybride Suche aus und sortiert Kandidaten optional neu.
4. Das Frontend fordert für jedes gefundene Dokument eine quellengebundene Antwort an und zeigt Ergebnisse fortlaufend an.
5. Positive oder negative Rückmeldungen werden dem Trace in Langfuse zugeordnet.

<img class="diagram light-only" src="../graphics/dlf_rag.png" alt="Gesamtablauf von der Frage über die hybride Suche bis zur Antwortgenerierung">
<img class="diagram dark-only" src="../graphics/dlf_rag_dark.png" alt="Gesamtablauf von der Frage über die hybride Suche bis zur Antwortgenerierung">

## Inhalt der Dokumentation

- [Systemarchitektur](./architektur) erläutert Komponenten, Datenfluss und Suchkonzepte.
- [Lokale Entwicklung](./lokale-entwicklung) beschreibt Voraussetzungen, Konfiguration, Start und Prüfungen.
- [Indizierungspipeline](./indexing-pipeline) verfolgt Inhalte von den Quellsystemen bis Qdrant.
- [Suche und API](./suche-api) dokumentiert Laufzeitketten, Endpunkte, Anfragefluss und Fehler.
- [MCP-Server](./mcp-server) beschreibt Agentenanbindung, Konfiguration, Transportsicherheit und Bereitstellung.
- [Frontend und Bereitstellung](./frontend-bereitstellung) behandelt Web Component, Container-Build, CI und Releases.

::: tip Geltungsbereich
Deployment-Manifeste, Secrets, umgebungsspezifische Endpunkte und Promotion-Abläufe liegen in einem separaten privaten Infrastruktur-Repository. Diese Dokumentation bezieht sich auf das öffentliche Anwendungs-Repository.
:::
