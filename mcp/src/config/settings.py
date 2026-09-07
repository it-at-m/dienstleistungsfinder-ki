from typing import Literal

from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", env_file=".env", extra="ignore", populate_by_name=True)

    dlf_retrieval_url: HttpUrl = Field(
        default="http://localhost:8080/api/retrieval",
        validation_alias="DLF_RETRIEVAL_URL",
    )
    dlf_timeout: float = Field(default=60, gt=0, validation_alias="DLF_TIMEOUT")
    transport: Literal["stdio", "streamable-http"] = "streamable-http"
    host: str = "0.0.0.0"
    port: int = Field(default=8081, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    collections: Literal["all"] | list[Literal["service", "info"]] = Field(default="all", min_length=1)
    enhance_query: bool = True
    rerank: bool = False
    n_results: int | None = Field(default=None, ge=1, le=20)

    allowed_hosts: list[str] | None = None
    allowed_origins: list[str] = Field(default_factory=list)

    @property
    def transport_security(self) -> TransportSecuritySettings | None:
        if self.allowed_hosts is None:
            return None  # Keep the SDK defaults unless an allowlist is configured.
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
        )
