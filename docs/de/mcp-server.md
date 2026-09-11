# MCP-Integration im Core

Der Core enthält einen FastMCP-Server im selben Prozess und Container wie das FastAPI-Backend. Der Streamable-HTTP-Endpunkt `/mcp` liegt auf Port 8080.

```text
MCP-Client ──► Core /mcp (FastMCP) ──► Core-Retrieval-Kette
```

## Start und Verbindung

Den Core gemäß [Lokale Entwicklung](./lokale-entwicklung) konfigurieren und vom Repository-Stammverzeichnis aus starten:

```shell
docker compose up --build core
```

Ein Client auf dem Host verbindet sich mit `http://localhost:8080/mcp`. Ein Client in einem anderen Docker-Container verwendet einen dort erreichbaren Hostnamen, etwa `http://host.docker.internal:8080/mcp` für den veröffentlichten Host-Port oder `http://core:8080/mcp` in einem gemeinsamen Docker-Netzwerk. `localhost` bezeichnet innerhalb eines Client-Containers diesen Container selbst.

MUCGPT-Konfiguration:

```yaml
MCP:
  SOURCES:
    DLF:
      url: "http://host.docker.internal:8080/mcp"
      transport: "streamable_http"
```

Unter Linux Docker Engine kann der Client-Container `extra_hosts: ["host.docker.internal:host-gateway"]` benötigen. Der reguläre Core-Start mit `python app.py` bindet an `0.0.0.0:8080`; `--development` bindet ausschließlich an localhost. Der Health-Endpunkt ist `/api/healthz`.

## Freigegebenes Tool

Zunächst wird nur `retrieve_munich_service_documents` bereitgestellt. Es sucht offizielle Informationen zu Münchner Dienstleistungen und stellt keine Anträge oder Terminbuchungen.

Eine eigenständig verständliche `query` übergeben und für Antworten anhand der Dokumenttexte explizit `result="full"` setzen. Der API-Standard `minimal` liefert kompakte Dokumentreferenzen und Metadaten. Für allgemeine Suchen `enhance_query=true` und `collections="all"` beibehalten. Schlagwort- und Kategoriefilter weglassen, solange deren exakte gültige Werte nicht bekannt sind. Antworten auf die gefundenen Texte stützen und deren Quell-URLs zitieren.

## Freigabe konfigurieren

`MCP_ENDPOINTS` in `core/backend/app.py` definiert die erlaubten HTTP-Methoden und Pfade:

```python
MCP_ENDPOINTS = (("POST", "/api/retrieval"),)
```

Jeder Eintrag wird als FastMCP-Tool bereitgestellt. Eine abschließende Ausschlussregel verhindert die automatische Freigabe anderer Endpunkte als MCP-Tools oder Ressourcen. Für weitere Endpunkte explizite Methoden-Pfad-Paare ergänzen, Core neu bauen oder starten und die zwischengespeicherte Tool-Liste des Clients aktualisieren.

## Bereitstellung

MCP wird mit `ghcr.io/it-at-m/dienstleistungsfinder-ki-core:<version>` über den Core-Release-Workflow ausgeliefert. `/mcp` an denselben Core-Service und Port wie die HTTP-API weiterleiten. MCP nutzt die Umgebungskonfiguration und den Startlebenszyklus des Core. Extern erreichbare Endpunkte über die Authentifizierungs- und Autorisierungskontrollen der Plattform schützen.
