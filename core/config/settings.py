"""Application settings loaded from environment variables and .env files."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

ENV_FILES = (REPO_ROOT / ".env",)


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
        "/health/live,/health/ready,/metrics,/docs,/redoc,/openapi.json,/v1/system/version,"
        "/v1/auth/signin/start,/v1/auth/signin/callback,/v1/auth/forgot-password,"
        "/v1/auth/signup,/v1/auth/signup/resend,/v1/auth/signup/social/start",
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
    csrf_enabled: bool = Field(True, alias="MIDDLEWARE_CSRF_ENABLED")
    security_headers_enabled: bool = Field(True, alias="MIDDLEWARE_SECURITY_HEADERS_ENABLED")
    csrf_excluded_paths_raw: str = Field(
        "/health/live,/health/ready,/metrics,/docs,/redoc,/openapi.json,/v1/system/version,"
        "/v1/auth/signin/start,/v1/auth/signin/callback,/v1/auth/forgot-password,"
        "/v1/auth/signup,/v1/auth/signup/resend,/v1/auth/signup/social/start,"
        "/internal/tinode/auth",
        alias="MIDDLEWARE_CSRF_EXCLUDED_PATHS",
    )
    content_security_policy: str = Field(
        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'",
        alias="MIDDLEWARE_CONTENT_SECURITY_POLICY",
    )
    docs_content_security_policy: str = Field(
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "font-src 'self' data: https://cdn.jsdelivr.net; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'",
        alias="MIDDLEWARE_DOCS_CONTENT_SECURITY_POLICY",
    )
    docs_csp_paths_raw: str = Field("/docs,/redoc", alias="MIDDLEWARE_DOCS_CSP_PATHS")

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

    @property
    def csrf_excluded_paths(self) -> set[str]:
        return set(parse_csv(self.csrf_excluded_paths_raw))

    @property
    def docs_csp_paths(self) -> set[str]:
        return set(parse_csv(self.docs_csp_paths_raw))


class DatabaseSettings(EnvSettings):
    """PostgreSQL and asyncpg pool settings."""

    host: str = Field("localhost", alias="DB_HOST")
    port: int = Field(5432, alias="DB_PORT")
    user: str = Field("postgres", alias="DB_USER")
    password: SecretStr = Field(SecretStr("postgres"), alias="DB_PASSWORD")
    name: str = Field("chatapp", alias="DB_NAME")
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
    public_base_url: str = Field("", alias="KEYCLOAK_PUBLIC_BASE_URL")
    internal_base_url: str = Field("", alias="KEYCLOAK_INTERNAL_BASE_URL")
    issuer_url: str = Field("", alias="KEYCLOAK_ISSUER_URL")
    realm: str = Field("chatapp", alias="KEYCLOAK_REALM")
    audience: str = Field("chatapp-api", alias="KEYCLOAK_AUDIENCE")
    algorithms_raw: str = Field("RS256", alias="KEYCLOAK_ALGORITHMS")
    jwks_cache_ttl_sec: int = Field(300, alias="KEYCLOAK_JWKS_CACHE_TTL_SEC")
    jwks_refresh_interval_sec: int = Field(240, alias="KEYCLOAK_JWKS_REFRESH_INTERVAL_SEC")
    stale_jwks_ttl_sec: int = Field(900, alias="KEYCLOAK_STALE_JWKS_TTL_SEC")
    web_client_id: str = Field("chatapp-web", alias="KEYCLOAK_WEB_CLIENT_ID")
    web_client_secret: SecretStr = Field(SecretStr("change-me"), alias="KEYCLOAK_WEB_CLIENT_SECRET")
    admin_client_id: str = Field(
        "chatapp-backend-admin",
        alias="KEYCLOAK_ADMIN_CLIENT_ID",
    )
    admin_client_secret: SecretStr = Field(
        SecretStr("change-me"),
        alias="KEYCLOAK_ADMIN_CLIENT_SECRET",
    )

    @property
    def algorithms(self) -> list[str]:
        """Return accepted JWT algorithms from comma-separated env text."""
        return [item.strip() for item in self.algorithms_raw.split(",") if item.strip()]

    @property
    def issuer(self) -> str:
        """Expected token issuer."""
        if self.issuer_url:
            return self.issuer_url.rstrip("/")
        return f"{self.public_base.rstrip('/')}/realms/{self.realm}"

    @property
    def well_known_url(self) -> str:
        """OIDC discovery document URL."""
        return f"{self.internal_realm_url}/.well-known/openid-configuration"

    @property
    def jwks_url(self) -> str:
        """JWKS URL for token verification."""
        return f"{self.internal_realm_url}/protocol/openid-connect/certs"

    @property
    def public_base(self) -> str:
        """Browser-visible Keycloak base URL."""
        return (self.public_base_url or self.base_url).rstrip("/")

    @property
    def internal_base(self) -> str:
        """Service-to-service Keycloak base URL."""
        return (self.internal_base_url or self.base_url).rstrip("/")

    @property
    def public_realm_url(self) -> str:
        """Browser-visible realm URL."""
        return f"{self.public_base}/realms/{self.realm}"

    @property
    def internal_realm_url(self) -> str:
        """Service-to-service realm URL."""
        return f"{self.internal_base}/realms/{self.realm}"

    @property
    def authorization_endpoint(self) -> str:
        """Browser authorization endpoint."""
        return f"{self.public_realm_url}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        """Service-to-service token endpoint."""
        return f"{self.internal_realm_url}/protocol/openid-connect/token"

    @property
    def logout_endpoint(self) -> str:
        """Browser logout endpoint."""
        return f"{self.public_realm_url}/protocol/openid-connect/logout"

    @property
    def admin_realm_url(self) -> str:
        """Keycloak Admin REST realm URL."""
        return f"{self.internal_base}/admin/realms/{self.realm}"

    @property
    def web_client_secret_value(self) -> str:
        """Return plain BFF client secret."""
        return self.web_client_secret.get_secret_value()

    @property
    def admin_client_secret_value(self) -> str:
        """Return plain admin client secret."""
        return self.admin_client_secret.get_secret_value()


class AuthSettings(EnvSettings):
    """BFF authentication and session settings."""

    callback_url: str = Field(
        "http://localhost:8000/v1/auth/signin/callback",
        alias="AUTH_CALLBACK_URL",
    )
    default_post_signin_redirect_url: str = Field(
        "http://localhost:3000",
        alias="AUTH_DEFAULT_POST_SIGNIN_REDIRECT_URL",
    )
    post_logout_redirect_url: str = Field(
        "http://localhost:3000",
        alias="AUTH_POST_LOGOUT_REDIRECT_URL",
    )
    allowed_redirect_origins_raw: str = Field(
        "http://localhost:3000",
        alias="AUTH_ALLOWED_REDIRECT_ORIGINS",
    )
    cookie_name: str = Field("pp_session", alias="AUTH_COOKIE_NAME")
    csrf_cookie_name: str = Field("pp_csrf", alias="AUTH_CSRF_COOKIE_NAME")
    csrf_header_name: str = Field("X-CSRF-Token", alias="AUTH_CSRF_HEADER_NAME")
    cookie_domain: str = Field("", alias="AUTH_COOKIE_DOMAIN")
    cookie_secure: bool = Field(True, alias="AUTH_COOKIE_SECURE")
    cookie_samesite: str = Field("lax", alias="AUTH_COOKIE_SAMESITE")
    token_encryption_key: SecretStr = Field(
        SecretStr("dev-auth-token-encryption-key-change-me"),
        alias="AUTH_TOKEN_ENCRYPTION_KEY",
    )
    signin_state_ttl_sec: int = Field(600, alias="AUTH_SIGNIN_STATE_TTL_SEC")
    session_idle_sec: int = Field(1800, alias="AUTH_SESSION_IDLE_SEC")
    session_max_sec: int = Field(43200, alias="AUTH_SESSION_MAX_SEC")
    refresh_leeway_sec: int = Field(60, alias="AUTH_REFRESH_LEEWAY_SEC")
    session_cache_ttl_sec: int = Field(300, alias="AUTH_SESSION_CACHE_TTL_SEC")
    revoke_cache_ttl_sec: int = Field(43200, alias="AUTH_REVOKE_CACHE_TTL_SEC")
    reset_email_lifespan_sec: int = Field(900, alias="AUTH_RESET_EMAIL_LIFESPAN_SEC")
    captcha_required: bool = Field(False, alias="AUTH_CAPTCHA_REQUIRED")
    signup_idempotency_ttl_sec: int = Field(86400, alias="AUTH_SIGNUP_IDEMPOTENCY_TTL_SEC")
    signup_ip_limit: int = Field(5, alias="AUTH_SIGNUP_IP_LIMIT")
    signup_ip_window_sec: int = Field(60, alias="AUTH_SIGNUP_IP_WINDOW_SEC")
    signup_device_limit: int = Field(5, alias="AUTH_SIGNUP_DEVICE_LIMIT")
    signup_device_window_sec: int = Field(60, alias="AUTH_SIGNUP_DEVICE_WINDOW_SEC")
    signup_domain_limit: int = Field(20, alias="AUTH_SIGNUP_DOMAIN_LIMIT")
    signup_domain_window_sec: int = Field(3600, alias="AUTH_SIGNUP_DOMAIN_WINDOW_SEC")
    signup_resend_email_limit: int = Field(3, alias="AUTH_SIGNUP_RESEND_EMAIL_LIMIT")
    signup_resend_email_window_sec: int = Field(
        900,
        alias="AUTH_SIGNUP_RESEND_EMAIL_WINDOW_SEC",
    )
    signup_social_ip_limit: int = Field(10, alias="AUTH_SIGNUP_SOCIAL_IP_LIMIT")
    signup_social_ip_window_sec: int = Field(60, alias="AUTH_SIGNUP_SOCIAL_IP_WINDOW_SEC")
    signup_resend_cooldown_sec: int = Field(300, alias="AUTH_SIGNUP_RESEND_COOLDOWN_SEC")
    signup_max_verification_sends: int = Field(5, alias="AUTH_SIGNUP_MAX_VERIFICATION_SENDS")
    blocked_email_domains_raw: str = Field(
        "tempmail.com,guerrillamail.com,10minutemail.com",
        alias="AUTH_BLOCKED_EMAIL_DOMAINS",
    )
    default_signup_roles_raw: str = Field(
        "profile:update,session:manage,message:send,message:create-room,"
        "trip:create,trip:update,trip:join",
        alias="AUTH_DEFAULT_SIGNUP_ROLES",
    )

    @property
    def allowed_redirect_origins(self) -> tuple[str, ...]:
        return tuple(parse_csv(self.allowed_redirect_origins_raw))

    @property
    def token_encryption_key_value(self) -> str:
        """Return plain token encryption material."""
        return self.token_encryption_key.get_secret_value()

    @property
    def cookie_domain_value(self) -> str | None:
        """Return cookie domain or None for host-only cookies."""
        return self.cookie_domain or None

    @property
    def blocked_email_domains(self) -> set[str]:
        """Return normalized disposable/blocked email domains."""
        return {domain.lower() for domain in parse_csv(self.blocked_email_domains_raw)}

    @property
    def default_signup_roles(self) -> list[str]:
        """Return client capability roles assigned to public signup users."""
        return parse_csv(self.default_signup_roles_raw)


class RedisSettings(EnvSettings):
    """Redis cache and coordination settings."""

    enabled: bool = Field(True, alias="REDIS_ENABLED")
    url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    socket_timeout_sec: float = Field(1.0, alias="REDIS_SOCKET_TIMEOUT_SEC")
    connect_timeout_sec: float = Field(1.0, alias="REDIS_CONNECT_TIMEOUT_SEC")


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
    grpc_required: bool = Field(False, alias="TINODE_GRPC_REQUIRED")
    auto_provision_on_accept: bool = Field(
        False,
        alias="TINODE_AUTO_PROVISION_ON_ACCEPT",
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
        self.auth = AuthSettings()
        self.redis = RedisSettings()
        self.tinode = TinodeSettings()
        self.meilisearch = MeilisearchSettings()


settings = Settings()
