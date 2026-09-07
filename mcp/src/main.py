from src.config.settings import McpSettings
from src.server import create_server


def main() -> None:
    settings = McpSettings()
    server = create_server(settings)
    if settings.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(
            transport="streamable-http",
            host=settings.host,
            port=settings.port,
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
            transport_security=settings.transport_security,
        )


if __name__ == "__main__":
    main()
