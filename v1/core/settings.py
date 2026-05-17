"""Application settings loaded from environment variables and .env files."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_ROOT = REPO_ROOT / "v1"

ENV_FILES = (REPO_ROOT / ".env", V1_ROOT / ".env")


class EnvSettings(BaseSettings):
    """Base settings loader shared by all config sections."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )


def parse_csv(value: str) -> list[str]:
    """Parse a comma-separated env value into a clean string list."""
    return [item.strip() for item in value.split(",") if item.strip()]


class AppSettings(EnvSettings):
    """Application process settings."""

    name: str = Field("chatapp API", alias="APP_NAME")
    environment: str = Field("local", alias="APP_ENV")
    version: str = Field("0.1.0", alias="APP_VERSION")
    debug: bool = Field(True, alias="APP_DEBUG")
    skip_startup_integrations: bool = Field(False, alias="APP_SKIP_STARTUP_INTEGRATIONS")


class LoggingSettings(EnvSettings):
    """Logging settings."""

    level: str = Field("INFO", alias="LOG_LEVEL")
    file: str = Field("logs/backend.log", alias="LOG_FILE")
    json_logs: bool = Field(False, alias="LOG_JSON")


class MiddlewareSettings(EnvSettings):
    """Cross-cutting HTTP middleware settings."""

    cors_enabled: bool = Field(True, alias="MIDDLEWARE_CORS_ENABLED")
    cors_origins_raw: str = Field(
        "http://localhost:3000,http://localhost:8000",
        alias="MIDDLEWARE_CORS_ORIGINS",
    )
    cors_allow_credentials: bool = Field(True, alias="MIDDLEWARE_CORS_ALLOW_CREDENTIALS")
    cors_allow_methods_raw: str = Field("*", alias="MIDDLEWARE_CORS_ALLOW_METHODS")
    cors_allow_headers_raw: str = Field("*", alias="MIDDLEWARE_CORS_ALLOW_HEADERS")

    request_id_header: str = Field("X-Request-ID", alias="MIDDLEWARE_REQUEST_ID_HEADER")
    auth_enabled: bool = Field(True, alias="MIDDLEWARE_AUTH_ENABLED")
    auth_protected_prefixes_raw: str = Field("/v1", alias="MIDDLEWARE_AUTH_PROTECTED_PREFIXES")
    auth_public_paths_raw: str = Field(
        "/health/live,/health/ready,/metrics,/docs,/redoc,/openapi.json,/v1/system/version",
        alias="MIDDLEWARE_AUTH_PUBLIC_PATHS",
    )
    auth_public_prefixes_raw: str = Field("/internal", alias="MIDDLEWARE_AUTH_PUBLIC_PREFIXES")

    rate_limit_enabled: bool = Field(True, alias="MIDDLEWARE_RATE_LIMIT_ENABLED")
    rate_limit_requests: int = Field(120, alias="MIDDLEWARE_RATE_LIMIT_REQUESTS")
    rate_limit_window_sec: int = Field(60, alias="MIDDLEWARE_RATE_LIMIT_WINDOW_SEC")
    rate_limit_excluded_paths_raw: str = Field(
        "/health/live,/health/ready,/metrics",
        alias="MIDDLEWARE_RATE_LIMIT_EXCLUDED_PATHS",
    )

    db_session_enabled: bool = Field(True, alias="MIDDLEWARE_DB_SESSION_ENABLED")
    db_session_excluded_paths_raw: str = Field(
        "/health/live,/health/ready,/metrics,/docs,/redoc,/openapi.json,/v1/system/version,"
        "/internal/tinode/auth",
        alias="MIDDLEWARE_DB_SESSION_EXCLUDED_PATHS",
    )

    log_request_body: bool = Field(False, alias="MIDDLEWARE_LOG_REQUEST_BODY")

    @property
    def cors_origins(self) -> list[str]:
        return parse_csv(self.cors_origins_raw)

    @property
    def cors_allow_methods(self) -> list[str]:
        return parse_csv(self.cors_allow_methods_raw)

    @property
    def cors_allow_headers(self) -> list[str]:
        return parse_csv(self.cors_allow_headers_raw)

    @property
    def auth_protected_prefixes(self) -> tuple[str, ...]:
        return tuple(parse_csv(self.auth_protected_prefixes_raw))

    @property
    def auth_public_paths(self) -> set[str]:
        return set(parse_csv(self.auth_public_paths_raw))

    @property
    def auth_public_prefixes(self) -> tuple[str, ...]:
        return tuple(parse_csv(self.auth_public_prefixes_raw))

    @property
    def rate_limit_excluded_paths(self) -> set[str]:
        return set(parse_csv(self.rate_limit_excluded_paths_raw))

    @property
    def db_session_excluded_paths(self) -> set[str]:
        return set(parse_csv(self.db_session_excluded_paths_raw))


class DatabaseSettings(EnvSettings):
    """PostgreSQL and asyncpg pool settings."""

    host: str = Field("localhost", alias="DB_HOST")
    port: int = Field(5432, alias="DB_PORT")
    user: str = Field("postgres", alias="DB_USER")
    password: SecretStr = Field(SecretStr("postgres"), alias="DB_PASSWORD")
    name: str = Field("paripath", alias="DB_NAME")
    target_label: str = Field("", alias="DB_TARGET")
    pool_min: int = Field(1, alias="DB_POOL_MIN")
    pool_max: int | None = Field(None, alias="DB_POOL_MAX")
    pool_auto: bool = Field(True, alias="DB_POOL_AUTO")
    pool_auto_estimated_concurrency: int = Field(16, alias="DB_POOL_AUTO_CONCURRENT_REQUESTS")
    pool_auto_ceiling: int = Field(10, alias="DB_POOL_AUTO_CEILING")
    pool_acquire_warn_sec: float = Field(1.0, alias="DB_POOL_ACQUIRE_WARN_SEC")
    pool_close_warn_sec: float = Field(2.0, alias="DB_POOL_CLOSE_WARN_SEC")
    command_timeout_sec: float = Field(60.0, alias="DB_COMMAND_TIMEOUT_SEC")
    connect_timeout_sec: float = Field(10.0, alias="DB_CONNECT_TIMEOUT_SEC")

    @property
    def password_value(self) -> str:
        """Return the plain database password for asyncpg."""
        return self.password.get_secret_value()

    @property
    def dsn(self) -> str:
        """Return a libpq-style DSN safe for asyncpg.connect/create_pool."""
        return f"postgresql://{self.user}:{self.password_value}@{self.host}:{self.port}/{self.name}"


class KeycloakSettings(EnvSettings):
    """Keycloak OpenID Connect settings."""

    enabled: bool = Field(True, alias="KEYCLOAK_ENABLED")
    base_url: str = Field("http://localhost:8080", alias="KEYCLOAK_BASE_URL")
    realm: str = Field("paripath", alias="KEYCLOAK_REALM")
    audience: str = Field("paripath-web", alias="KEYCLOAK_AUDIENCE")
    algorithms_raw: str = Field("RS256", alias="KEYCLOAK_ALGORITHMS")
    jwks_cache_ttl_sec: int = Field(300, alias="KEYCLOAK_JWKS_CACHE_TTL_SEC")

    @property
    def algorithms(self) -> list[str]:
        """Return accepted JWT algorithms from comma-separated env text."""
        return [item.strip() for item in self.algorithms_raw.split(",") if item.strip()]

    @property
    def issuer(self) -> str:
        """Expected token issuer."""
        return f"{self.base_url.rstrip('/')}/realms/{self.realm}"

    @property
    def well_known_url(self) -> str:
        """OIDC discovery document URL."""
        return f"{self.issuer}/.well-known/openid-configuration"

    @property
    def jwks_url(self) -> str:
        """JWKS URL for token verification."""
        return f"{self.issuer}/protocol/openid-connect/certs"


class TinodeSettings(EnvSettings):
    """Tinode integration settings."""

    enabled: bool = Field(True, alias="TINODE_ENABLED")
    web_url: str = Field("http://localhost:6060", alias="TINODE_WEB_URL")
    grpc_host: str = Field("localhost:16060", alias="TINODE_GRPC_HOST")
    api_key: SecretStr = Field(SecretStr("change-me"), alias="TINODE_API_KEY")
    rest_auth_shared_secret: SecretStr = Field(
        SecretStr("dev-tinode-rest-auth-secret"),
        alias="TINODE_REST_AUTH_SHARED_SECRET",
    )
    auth_lifetime_sec: int = Field(86400, alias="TINODE_AUTH_LIFETIME_SEC")
    allow_plaintext_dev_secret: bool = Field(
        True,
        alias="TINODE_AUTH_ALLOW_PLAINTEXT_DEV_SECRET",
    )

    @property
    def api_key_value(self) -> str:
        """Return plain Tinode API key."""
        return self.api_key.get_secret_value()

    @property
    def rest_auth_secret_value(self) -> str:
        """Return shared secret used to protect Tinode REST auth calls."""
        return self.rest_auth_shared_secret.get_secret_value()


class MeilisearchSettings(EnvSettings):
    """Meilisearch settings."""

    enabled: bool = Field(True, alias="MEILI_ENABLED")
    url: str = Field("http://localhost:7700", alias="MEILI_URL")
    master_key: SecretStr = Field(SecretStr("dev-meili-master-key"), alias="MEILI_MASTER_KEY")
    traveler_index: str = Field("travelers", alias="MEILI_TRAVELER_INDEX")

    @property
    def master_key_value(self) -> str:
        """Return plain Meilisearch key."""
        return self.master_key.get_secret_value()


class Settings:
    """Application settings grouped by concern."""

    def __init__(self) -> None:
        self.app = AppSettings()
        self.logging = LoggingSettings()
        self.middleware = MiddlewareSettings()
        self.database = DatabaseSettings()
        self.keycloak = KeycloakSettings()
        self.tinode = TinodeSettings()
        self.meilisearch = MeilisearchSettings()


settings = Settings()
