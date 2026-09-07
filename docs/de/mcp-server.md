# MCP-Server

Der MCP-Server stellt die Suche des Dienstleistungsfinders für MCP-kompatible Agenten bereit. Er ist ein schlanker, zustandsloser Adapter: Clients rufen ein MCP-Tool auf, der Server sendet die Anfrage an die Retrieval-API des Core und gibt das vollständige Suchergebnis zurück.

```text
MCP-Client ──► Streamable HTTP /mcp ──► MCP-Server ──► POST /api/retrieval ──► Core
```

Direkte Verbindungen zu Qdrant, Embedding-Modellen, Rerankern oder Langfuse bestehen nicht. Diese Aufgaben verbleiben im Core.

## Tool

Der Server bietet genau ein schreibgeschütztes Tool an:

| Tool                                | Eingabe                                 | Ergebnis                                                                               |
| ----------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------- |
| `retrieve_munich_service_documents` | Eine nicht leere, eigenständige `query` | Vollständige Dokumente, Quellmetadaten, Run-ID und erweiterte Suchanfrage aus dem Core |

Agenten sollen Antworten aus den gelieferten Dokumenttexten erzeugen und URLs aus den Metadaten zitieren. Das Tool durchsucht vorhandene Informationen; es stellt keine Anträge und bucht keine Termine.

## Lokal ausführen

Der Server benötigt Python 3.13 und [uv](https://docs.astral.sh/uv/). Die Befehle müssen im Verzeichnis `mcp` ausgeführt werden, damit Pydantic die Datei `mcp/.env` lädt:

```shell
cd mcp
cp .env.example .env
uv sync --locked
uv run dlf-search-mcp
```

Der Streamable-HTTP-Endpunkt ist standardmäßig unter `http://localhost:8081/mcp` erreichbar; `GET /healthz` dient als Health-Endpunkt. Für einen lokalen stdio-Client kann `MCP_TRANSPORT=stdio` gesetzt werden.

## Konfiguration

Umgebungsvariablen überschreiben Werte aus `.env` im aktuellen Arbeitsverzeichnis.

| Variable              | Standardwert                          | Zweck                                               |
| --------------------- | ------------------------------------- | --------------------------------------------------- |
| `DLF_RETRIEVAL_URL`   | `http://localhost:8080/api/retrieval` | Vollständige Core-Retrieval-URL                     |
| `DLF_TIMEOUT`         | `60`                                  | Zeitlimit für Core-Anfragen in Sekunden             |
| `MCP_TRANSPORT`       | `streamable-http`                     | `streamable-http` oder `stdio`                      |
| `MCP_HOST`            | `0.0.0.0`                             | HTTP-Bind-Adresse                                   |
| `MCP_PORT`            | `8081`; Image: `8080`                 | HTTP-Port                                           |
| `MCP_LOG_LEVEL`       | `INFO`                                | Log-Level für Python und MCP SDK                    |
| `MCP_COLLECTIONS`     | `all`                                 | `all` oder JSON-Liste mit `service` und/oder `info` |
| `MCP_ENHANCE_QUERY`   | `true`                                | Query Enhancement beim Core anfordern               |
| `MCP_RERANK`          | `false`                               | Reranking beim Core anfordern                       |
| `MCP_N_RESULTS`       | nicht gesetzt                         | Optionale Ergebnisanzahl von 1 bis 20               |
| `MCP_ALLOWED_HOSTS`   | Standardwerte des MCP SDK             | JSON-Liste erlaubter HTTP-`Host`-Header             |
| `MCP_ALLOWED_ORIGINS` | `[]`                                  | JSON-Liste erlaubter HTTP-`Origin`-Header           |

Beim Start wird die effektive, nicht geheime Konfiguration auf Info-Level protokolliert. Dazu gehören Bind-Adresse, Transport, MCP-Pfad, Backend-URL ohne Zugangsdaten oder Query-Parameter, Retrieval-Optionen sowie die geparsten Host- und Origin-Listen. Wenn ein Deployment einen erwarteten Umgebungswert nicht verwendet, sollten zuerst diese Meldungen geprüft werden.

## Transportsicherheit

Mit `MCP_ALLOWED_HOSTS` wird über den DNS-Rebinding-Schutz des MCP SDK eine explizite Positivliste aktiviert. Host-Einträge enthalten kein Schema und werden einschließlich Port exakt verglichen. Die einzige unterstützte Wildcard-Form ist `hostname:*`; sie erlaubt jeden Port für genau diesen Host, aber keine Subdomains.

```dotenv
MCP_ALLOWED_HOSTS=["localhost:*","127.0.0.1:*","dlf-mcp.namespace.svc:*","mcp.example.org","mcp.example.org:*"]
MCP_ALLOWED_ORIGINS=["https://client.example.org"]
```

Anfragen ohne `Origin`-Header werden akzeptiert, wenn ihr Host gültig ist. Sendet ein Browser oder Proxy einen `Origin`-Header, muss dessen exakter Wert in `MCP_ALLOWED_ORIGINS` stehen. Origins enthalten das Schema und bei nicht standardmäßigen Ports auch den Port.

| Antwort                     | Bedeutung                                                                   |
| --------------------------- | --------------------------------------------------------------------------- |
| `421 Invalid Host header`   | Der empfangene `Host`-Wert fehlt in `MCP_ALLOWED_HOSTS`                     |
| `403 Invalid Origin header` | Die Anfrage enthält einen `Origin`-Wert, der in `MCP_ALLOWED_ORIGINS` fehlt |

Das SDK protokolliert den abgelehnten Wert. Dieser kann mit den beim Start ausgegebenen Positivlisten verglichen werden.

## OpenShift

Der Container lauscht auf Port 8080. Die Core-Service-URL und alle Hostnamen, über die Clients oder Router den MCP-Server ansprechen, müssen konfiguriert werden:

```yaml
env:
  - name: DLF_RETRIEVAL_URL
    value: http://dlf-core:8080/api/retrieval
  - name: MCP_ALLOWED_HOSTS
    value: '["localhost:*","127.0.0.1:*","dlf-mcp","dlf-mcp:*","dlf-mcp.namespace.svc:*","mcp.example.org","mcp.example.org:*"]'
```

HTTP-Probes von OpenShift und Kubernetes senden normalerweise Pod-IP und Port als `Host`-Header. Pod-IPs sind dynamisch und sollten nicht in die Positivliste aufgenommen werden. Stattdessen wird in beiden Probes ein bereits erlaubter Host explizit gesendet:

```yaml
readinessProbe:
  httpGet:
    path: /healthz
    port: http
    httpHeaders:
      - name: Host
        value: localhost:8080
livenessProbe:
  httpGet:
    path: /healthz
    port: http
    httpHeaders:
      - name: Host
        value: localhost:8080
```

Nach Änderungen an Umgebungswerten muss ein neuer Pod ausgerollt werden, da die Einstellungen nur beim Prozessstart gelesen werden. Der effektive Wert kann im laufenden Deployment geprüft werden:

```shell
oc exec deployment/dlf-mcp -n namespace -- printenv MCP_ALLOWED_HOSTS
oc logs deployment/dlf-mcp -n namespace | grep -E "Transport security|Invalid Host|Invalid Origin"
```

Der Server besitzt keine eigene Client-Authentifizierung. Externe Routes müssen über die Authentifizierungs- und Autorisierungsfunktionen der Plattform geschützt werden. Das Proxy-Zeitlimit sollte größer als `DLF_TIMEOUT` sein.

## Image und Releases

`mcp/Dockerfile` erstellt das OpenShift-kompatible Image. Tags nach dem Muster `mcp-vX.Y.Z` veröffentlichen `ghcr.io/it-at-m/dienstleistungsfinder-ki-mcp:X.Y.Z` und `latest`; der Release-Workflow erstellt außerdem ein unveränderliches Tag `sha-<commit>`. Deployments sollten eine geprüfte Version und einen Digest fest vorgeben.
