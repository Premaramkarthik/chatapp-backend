"""Load config.yaml defaults and merge with environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

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
    ("geo", "cache_enabled"): "GEO_CACHE_ENABLED",
    ("geo", "cache_ttl_countries_sec"): "GEO_CACHE_TTL_COUNTRIES_SEC",
    ("geo", "cache_ttl_states_sec"): "GEO_CACHE_TTL_STATES_SEC",
    ("geo", "cache_ttl_cities_sec"): "GEO_CACHE_TTL_CITIES_SEC",
    ("geo", "cache_log_enabled"): "GEO_CACHE_LOG_ENABLED",
    ("geo", "search_default_limit"): "GEO_SEARCH_DEFAULT_LIMIT",
    ("geo", "search_max_limit"): "GEO_SEARCH_MAX_LIMIT",
    ("geo", "search_min_chars"): "GEO_SEARCH_MIN_CHARS",
    ("geo", "list_limit_countries"): "GEO_LIST_LIMIT_COUNTRIES",
    ("geo", "list_limit_states"): "GEO_LIST_LIMIT_STATES",
    ("geo", "list_limit_cities"): "GEO_LIST_LIMIT_CITIES",
    ("middleware", "cors_enabled"): "MIDDLEWARE_CORS_ENABLED",
    ("middleware", "cors_origins"): "MIDDLEWARE_CORS_ORIGINS",
    ("middleware", "cors_allow_credentials"): "MIDDLEWARE_CORS_ALLOW_CREDENTIALS",
    ("middleware", "cors_allow_methods"): "MIDDLEWARE_CORS_ALLOW_METHODS",
    ("middleware", "cors_allow_headers"): "MIDDLEWARE_CORS_ALLOW_HEADERS",
    ("middleware", "request_id_header"): "MIDDLEWARE_REQUEST_ID_HEADER",
    ("middleware", "auth_enabled"): "MIDDLEWARE_AUTH_ENABLED",
    ("middleware", "auth_protected_prefixes"): "MIDDLEWARE_AUTH_PROTECTED_PREFIXES",
    ("middleware", "auth_public_paths"): "MIDDLEWARE_AUTH_PUBLIC_PATHS",
    ("middleware", "auth_public_prefixes"): "MIDDLEWARE_AUTH_PUBLIC_PREFIXES",
    ("middleware", "rate_limit_excluded_paths"): "MIDDLEWARE_RATE_LIMIT_EXCLUDED_PATHS",
    ("middleware", "db_session_enabled"): "MIDDLEWARE_DB_SESSION_ENABLED",
    ("middleware", "db_session_excluded_paths"): "MIDDLEWARE_DB_SESSION_EXCLUDED_PATHS",
    ("middleware", "log_request_body"): "MIDDLEWARE_LOG_REQUEST_BODY",
    ("middleware", "csrf_enabled"): "MIDDLEWARE_CSRF_ENABLED",
    ("middleware", "security_headers_enabled"): "MIDDLEWARE_SECURITY_HEADERS_ENABLED",
    ("middleware", "csrf_excluded_paths"): "MIDDLEWARE_CSRF_EXCLUDED_PATHS",
    ("middleware", "content_security_policy"): "MIDDLEWARE_CONTENT_SECURITY_POLICY",
    ("middleware", "docs_content_security_policy"): "MIDDLEWARE_DOCS_CONTENT_SECURITY_POLICY",
    ("middleware", "docs_csp_paths"): "MIDDLEWARE_DOCS_CSP_PATHS",
    ("database", "target"): "DB_TARGET",
    ("database", "pool_auto"): "DB_POOL_AUTO",
    ("database", "pool_auto_concurrent_requests"): "DB_POOL_AUTO_CONCURRENT_REQUESTS",
    ("database", "pool_auto_ceiling"): "DB_POOL_AUTO_CEILING",
    ("auth", "cookie_name"): "AUTH_COOKIE_NAME",
    ("auth", "csrf_cookie_name"): "AUTH_CSRF_COOKIE_NAME",
    ("auth", "csrf_header_name"): "AUTH_CSRF_HEADER_NAME",
    ("auth", "cookie_domain"): "AUTH_COOKIE_DOMAIN",
    ("auth", "cookie_secure"): "AUTH_COOKIE_SECURE",
    ("auth", "cookie_samesite"): "AUTH_COOKIE_SAMESITE",
    ("auth", "signin_state_ttl_sec"): "AUTH_SIGNIN_STATE_TTL_SEC",
    ("auth", "refresh_leeway_sec"): "AUTH_REFRESH_LEEWAY_SEC",
    ("auth", "session_cache_ttl_sec"): "AUTH_SESSION_CACHE_TTL_SEC",
    ("auth", "revoke_cache_ttl_sec"): "AUTH_REVOKE_CACHE_TTL_SEC",
    ("auth", "captcha_required"): "AUTH_CAPTCHA_REQUIRED",
    ("auth", "signup_idempotency_ttl_sec"): "AUTH_SIGNUP_IDEMPOTENCY_TTL_SEC",
    ("auth", "signup_ip_limit"): "AUTH_SIGNUP_IP_LIMIT",
    ("auth", "signup_ip_window_sec"): "AUTH_SIGNUP_IP_WINDOW_SEC",
    ("auth", "signup_device_limit"): "AUTH_SIGNUP_DEVICE_LIMIT",
    ("auth", "signup_device_window_sec"): "AUTH_SIGNUP_DEVICE_WINDOW_SEC",
    ("auth", "signup_domain_limit"): "AUTH_SIGNUP_DOMAIN_LIMIT",
    ("auth", "signup_domain_window_sec"): "AUTH_SIGNUP_DOMAIN_WINDOW_SEC",
    ("auth", "signup_resend_email_limit"): "AUTH_SIGNUP_RESEND_EMAIL_LIMIT",
    ("auth", "signup_resend_email_window_sec"): "AUTH_SIGNUP_RESEND_EMAIL_WINDOW_SEC",
    ("auth", "signup_social_ip_limit"): "AUTH_SIGNUP_SOCIAL_IP_LIMIT",
    ("auth", "signup_social_ip_window_sec"): "AUTH_SIGNUP_SOCIAL_IP_WINDOW_SEC",
    ("auth", "signup_max_verification_sends"): "AUTH_SIGNUP_MAX_VERIFICATION_SENDS",
    ("auth", "signup_session_ttl_sec"): "AUTH_SIGNUP_SESSION_TTL_SEC",
    ("auth", "verification_reconcile_interval_sec"): "AUTH_VERIFICATION_RECONCILE_INTERVAL_SEC",
    ("auth", "verification_reconcile_batch_size"): "AUTH_VERIFICATION_RECONCILE_BATCH_SIZE",
    ("auth", "signup_max_password_length"): "AUTH_SIGNUP_MAX_PASSWORD_LENGTH",
    ("auth", "blocked_email_domains"): "AUTH_BLOCKED_EMAIL_DOMAINS",
    ("matrix", "access_token_ttl_sec"): "MATRIX_ACCESS_TOKEN_TTL_SEC",
    ("matrix", "session_cache_ttl_sec"): "MATRIX_SESSION_CACHE_TTL_SEC",
    ("matrix", "image_max_bytes"): "MATRIX_IMAGE_MAX_BYTES",
    ("matrix", "document_max_bytes"): "MATRIX_DOCUMENT_MAX_BYTES",
    ("matrix", "video_max_bytes"): "MATRIX_VIDEO_MAX_BYTES",
    ("matrix", "message_rate_limit"): "MATRIX_MESSAGE_RATE_LIMIT",
    ("matrix", "message_rate_window_sec"): "MATRIX_MESSAGE_RATE_WINDOW_SEC",
    ("matrix", "media_rate_limit"): "MATRIX_MEDIA_RATE_LIMIT",
    ("matrix", "media_rate_window_sec"): "MATRIX_MEDIA_RATE_WINDOW_SEC",
    ("typesense", "enabled"): "TYPESENSE_ENABLED",
    ("typesense", "users_collection"): "TYPESENSE_USERS_COLLECTION",
    ("typesense", "travelers_collection"): "TYPESENSE_TRAVELERS_COLLECTION",
    ("typesense", "cities_collection"): "TYPESENSE_CITIES_COLLECTION",
    ("typesense", "countries_collection"): "TYPESENSE_COUNTRIES_COLLECTION",
    ("typesense", "states_collection"): "TYPESENSE_STATES_COLLECTION",
    ("typesense", "user_recommendations_collection"): "TYPESENSE_USER_RECOMMENDATIONS_COLLECTION",
    ("typesense", "popular_searches_collection"): "TYPESENSE_POPULAR_SEARCHES_COLLECTION",
    ("search", "cache_ttl_city_sec"): "SEARCH_CACHE_TTL_CITY_SEC",
    ("search", "cache_ttl_country_sec"): "SEARCH_CACHE_TTL_COUNTRY_SEC",
    ("search", "cache_ttl_state_sec"): "SEARCH_CACHE_TTL_STATE_SEC",
    ("search", "cache_ttl_user_sec"): "SEARCH_CACHE_TTL_USER_SEC",
    ("search", "cache_ttl_traveler_sec"): "SEARCH_CACHE_TTL_TRAVELER_SEC",
    ("search", "cache_ttl_global_sec"): "SEARCH_CACHE_TTL_GLOBAL_SEC",
    ("search", "cache_ttl_recent_sec"): "SEARCH_CACHE_TTL_RECENT_SEC",
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
    # Load local overrides first, preserving any deployment environment values.
    load_dotenv(path.parent / ".env", override=False)
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

        required = [
            "DB_PASSWORD",
            "KEYCLOAK_WEB_CLIENT_SECRET",
            "KEYCLOAK_ADMIN_CLIENT_SECRET",
            "AUTH_TOKEN_ENCRYPTION_KEY",
        ]
        if os.getenv("MATRIX_ENABLED", "true").lower() == "true":
            required += ["MATRIX_SERVICE_ADMIN_PASSWORD", "MATRIX_REGISTRATION_SHARED_SECRET"]
        if os.getenv("TYPESENSE_ENABLED", "true").lower() == "true":
            required += ["TYPESENSE_API_KEY"]
        for key in required:
            value = os.getenv(key, "")
            if (
                len(value) < 24
                or value in {"postgres", "admin", "chatapp", "synapse", "change-me"}
                or value.startswith("dev-")
            ):
                raise ConfigurationError(f"{key} must be an explicit production secret")
        from urllib.parse import urlparse

        for key in (
            "AUTH_CALLBACK_URL",
            "AUTH_DEFAULT_POST_SIGNIN_REDIRECT_URL",
            "AUTH_POST_LOGOUT_REDIRECT_URL",
            "KEYCLOAK_PUBLIC_BASE_URL",
        ):
            parsed = urlparse(os.getenv(key, ""))
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.fragment
            ):
                raise ConfigurationError(f"{key} must be an HTTPS URL")
        if os.getenv("AUTH_COOKIE_SECURE", "true").lower() != "true":
            raise ConfigurationError("AUTH_COOKIE_SECURE must be true in production")
