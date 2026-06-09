"""Load config.yaml defaults and merge with environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from v1.utils.base import ConfigurationError

# Maps nested YAML paths to environment variable names used by pydantic settings.
YAML_ENV_MAP: dict[tuple[str, ...], str] = {
    ("app", "name"): "APP_NAME",
    ("app", "environment"): "APP_ENV",
    ("app", "version"): "APP_VERSION",
    ("app", "debug"): "APP_DEBUG",
    ("app", "skip_startup_integrations"): "APP_SKIP_STARTUP_INTEGRATIONS",
    ("logging", "level"): "LOG_LEVEL",
    ("logging", "file"): "LOG_FILE",
    ("observability", "enabled"): "OBSERVABILITY_ENABLED",
    ("observability", "service_name"): "OTEL_SERVICE_NAME",
    ("observability", "otlp_endpoint"): "OTEL_EXPORTER_OTLP_ENDPOINT",
    ("observability", "otlp_insecure"): "OTEL_EXPORTER_OTLP_INSECURE",
    ("observability", "traces_sample_rate"): "OTEL_TRACES_SAMPLER_ARG",
    ("observability", "metrics_enabled"): "OBSERVABILITY_METRICS_ENABLED",
    ("observability", "correlation_header"): "OBSERVABILITY_CORRELATION_HEADER",
    ("http", "timeout_seconds"): "HTTP_TIMEOUT_SECONDS",
    ("http", "retry_attempts"): "HTTP_RETRY_ATTEMPTS",
    ("jwt", "audience"): "KEYCLOAK_AUDIENCE",
    ("jwt", "algorithms"): "KEYCLOAK_ALGORITHMS",
    ("jwt", "jwks_cache_ttl"): "KEYCLOAK_JWKS_CACHE_TTL_SEC",
    ("jwt", "jwks_refresh_interval_sec"): "KEYCLOAK_JWKS_REFRESH_INTERVAL_SEC",
    ("jwt", "stale_jwks_ttl_sec"): "KEYCLOAK_STALE_JWKS_TTL_SEC",
    ("jwt", "clock_leeway_sec"): "JWT_CLOCK_LEEWAY_SEC",
    ("keycloak", "enabled"): "KEYCLOAK_ENABLED",
    ("keycloak", "base_url"): "KEYCLOAK_BASE_URL",
    ("keycloak", "public_base_url"): "KEYCLOAK_PUBLIC_BASE_URL",
    ("keycloak", "internal_base_url"): "KEYCLOAK_INTERNAL_BASE_URL",
    ("keycloak", "issuer_url"): "KEYCLOAK_ISSUER_URL",
    ("keycloak", "realm"): "KEYCLOAK_REALM",
    ("keycloak", "web_client_id"): "KEYCLOAK_WEB_CLIENT_ID",
    ("keycloak", "admin_client_id"): "KEYCLOAK_ADMIN_CLIENT_ID",
    ("keycloak", "google_idp_alias"): "KEYCLOAK_GOOGLE_IDP_ALIAS",
    ("keycloak", "google_idp_hide_on_login_page"): "KEYCLOAK_GOOGLE_IDP_HIDE_ON_LOGIN_PAGE",
    ("keycloak", "auto_bootstrap"): "KEYCLOAK_AUTO_BOOTSTRAP",
    ("redis", "enabled"): "REDIS_ENABLED",
    ("redis", "cache_ttl"): "REDIS_CACHE_TTL_SEC",
    ("redis", "socket_timeout_sec"): "REDIS_SOCKET_TIMEOUT_SEC",
    ("redis", "connect_timeout_sec"): "REDIS_CONNECT_TIMEOUT_SEC",
    ("database", "host"): "DB_HOST",
    ("database", "port"): "DB_PORT",
    ("database", "user"): "DB_USER",
    ("database", "name"): "DB_NAME",
    ("database", "pool_min"): "DB_POOL_MIN",
    ("database", "pool_max"): "DB_POOL_MAX",
    ("middleware", "rate_limit_enabled"): "MIDDLEWARE_RATE_LIMIT_ENABLED",
    ("middleware", "rate_limit_requests"): "MIDDLEWARE_RATE_LIMIT_REQUESTS",
    ("middleware", "rate_limit_window_sec"): "MIDDLEWARE_RATE_LIMIT_WINDOW_SEC",
    ("auth", "callback_url"): "AUTH_CALLBACK_URL",
    ("auth", "default_post_signin_redirect_url"): "AUTH_DEFAULT_POST_SIGNIN_REDIRECT_URL",
    ("auth", "post_logout_redirect_url"): "AUTH_POST_LOGOUT_REDIRECT_URL",
    ("auth", "allowed_redirect_origins"): "AUTH_ALLOWED_REDIRECT_ORIGINS",
    ("auth", "email_verify_redirect_url"): "AUTH_EMAIL_VERIFY_REDIRECT_URL",
    ("auth", "password_reset_redirect_url"): "AUTH_PASSWORD_RESET_REDIRECT_URL",
    ("auth", "reset_email_lifespan_sec"): "AUTH_RESET_EMAIL_LIFESPAN_SEC",
    ("auth", "email_verification_token_ttl_sec"): "AUTH_EMAIL_VERIFICATION_TOKEN_TTL_SEC",
    ("auth", "session_idle_sec"): "AUTH_SESSION_IDLE_SEC",
    ("auth", "session_max_sec"): "AUTH_SESSION_MAX_SEC",
    ("auth", "remember_me_session_max_sec"): "AUTH_REMEMBER_ME_SESSION_MAX_SEC",
    ("auth", "signup_min_password_length"): "AUTH_SIGNUP_MIN_PASSWORD_LENGTH",
    ("auth", "default_signup_roles"): "AUTH_DEFAULT_SIGNUP_ROLES",
    ("auth", "verification_reconcile_enabled"): "AUTH_VERIFICATION_RECONCILE_ENABLED",
    ("auth", "signup_resend_cooldown_sec"): "AUTH_SIGNUP_RESEND_COOLDOWN_SEC",
}


def _flatten_yaml(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> dict[str, Any]:
    """Flatten nested YAML mapping to env-style key/value pairs."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        path = (*prefix, str(key))
        if isinstance(value, dict):
            flat.update(_flatten_yaml(value, path))
        else:
            env_key = YAML_ENV_MAP.get(path)
            if env_key is not None:
                flat[env_key] = value
    return flat


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load and flatten a YAML config file. Returns empty dict if missing."""
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not raw or not isinstance(raw, dict):
        return {}
    return _flatten_yaml(raw)


def apply_yaml_defaults_to_env(path: Path) -> dict[str, Any]:
    """Apply YAML values to os.environ only when not already set."""
    flat = load_yaml_config(path)
    for env_key, value in flat.items():
        if env_key in os.environ:
            continue
        if isinstance(value, bool):
            os.environ[env_key] = "true" if value else "false"
        elif isinstance(value, list):
            os.environ[env_key] = ",".join(str(item) for item in value)
        else:
            os.environ[env_key] = str(value)
    return flat


def validate_production_settings(*, environment: str, debug: bool) -> None:
    """Reject unsafe configuration combinations in production."""
    if environment.lower() in {"production", "prod"} and debug:
        raise ConfigurationError(
            "APP_DEBUG must be false when APP_ENV is production",
            context={"environment": environment},
        )
    if environment.lower() in {"production", "prod"}:
        auto_bootstrap = os.getenv("KEYCLOAK_AUTO_BOOTSTRAP", "").lower()
        if auto_bootstrap in {"true", "1", "yes"}:
            raise ConfigurationError(
                "KEYCLOAK_AUTO_BOOTSTRAP must be false in production; "
                "provision the realm via IaC or manual setup",
                context={"environment": environment},
            )
