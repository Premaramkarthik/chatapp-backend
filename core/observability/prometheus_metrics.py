"""Prometheus metric definitions for chatapp-backend."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# --- Auth / signup counters ---

SIGNUP_REQUESTS_TOTAL = Counter(
    "signup_requests_total",
    "Signup start requests",
    ["outcome"],
)

SIGNUP_SUCCESS_TOTAL = Counter(
    "signup_success_total",
    "Successful signup provisions",
)

SIGNUP_FAILURE_TOTAL = Counter(
    "signup_failure_total",
    "Failed signup attempts",
    ["reason"],
)

VERIFICATION_SENT_TOTAL = Counter(
    "verification_sent_total",
    "Verification emails sent successfully",
)

VERIFICATION_FAILURE_TOTAL = Counter(
    "verification_failure_total",
    "Verification email or reconcile failures",
    ["reason"],
)

VERIFICATION_SUCCESS_TOTAL = Counter(
    "verification_success_total",
    "Users activated after email verification",
    ["source"],
)

LOGIN_SUCCESS_TOTAL = Counter(
    "login_success_total",
    "Successful OAuth sign-in callbacks",
)

LOGIN_FAILURE_TOTAL = Counter(
    "login_failure_total",
    "Failed sign-in attempts",
    ["reason"],
)

AUTH_SESSION_CREATED_TOTAL = Counter(
    "auth_session_created_total",
    "Auth sessions created",
)

AUTH_LOGOUT_TOTAL = Counter(
    "auth_logout_total",
    "User logout events",
)

AUTH_JWKS_REFRESH_FAILURE_TOTAL = Counter(
    "auth_jwks_refresh_failure_total",
    "JWKS refresh failures",
)

AUTH_REFRESH_FAILURE_TOTAL = Counter(
    "auth_refresh_failure_total",
    "Token refresh failures",
    ["reason"],
)

AUTH_REDIS_FALLBACK_TOTAL = Counter(
    "auth_redis_fallback_total",
    "Redis cache fallback events",
    ["reason"],
)

# --- Keycloak ---

KEYCLOAK_REQUESTS_TOTAL = Counter(
    "keycloak_requests_total",
    "Keycloak Admin/OAuth HTTP requests",
    ["operation", "status"],
)

KEYCLOAK_FAILURES_TOTAL = Counter(
    "keycloak_failures_total",
    "Keycloak request failures",
    ["operation"],
)

KEYCLOAK_REQUEST_DURATION_SECONDS = Histogram(
    "keycloak_request_duration_seconds",
    "Keycloak request duration in seconds",
    ["operation"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# --- Database ---

DATABASE_QUERY_DURATION_SECONDS = Histogram(
    "database_query_duration_seconds",
    "Database query duration in seconds",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

DATABASE_QUERY_FAILURES_TOTAL = Counter(
    "database_query_failures_total",
    "Failed database queries",
    ["operation"],
)

DATABASE_POOL_ACQUIRE_WAIT_SECONDS = Histogram(
    "database_pool_acquire_wait_seconds",
    "Time waiting to acquire a connection from the pool",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

DATABASE_CONNECTIONS_ACTIVE = Gauge(
    "database_connections_active",
    "Active connections in the asyncpg pool",
)

DATABASE_CONNECTIONS_IDLE = Gauge(
    "database_connections_idle",
    "Idle connections in the asyncpg pool",
)

# --- Service layer ---

SERVICE_EXECUTION_DURATION_SECONDS = Histogram(
    "service_execution_duration_seconds",
    "Service method execution duration in seconds",
    ["service", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# --- HTTP / middleware ---

RATE_LIMIT_EXCEEDED_TOTAL = Counter(
    "rate_limit_exceeded_total",
    "Rate limit rejections",
    ["path"],
)

# --- Background workers ---

BACKGROUND_JOB_RUNS_TOTAL = Counter(
    "background_job_runs_total",
    "Background worker batch iterations",
    ["job"],
)

BACKGROUND_JOB_FAILURES_TOTAL = Counter(
    "background_job_failures_total",
    "Background worker batch failures",
    ["job"],
)

# --- Gauges (updated periodically) ---

ACTIVE_SESSIONS = Gauge(
    "active_sessions",
    "Count of active auth sessions",
)

PENDING_VERIFICATIONS = Gauge(
    "pending_verifications",
    "Users awaiting email verification",
)

ACTIVE_USERS = Gauge(
    "active_users",
    "Approximate count of active users",
)

# --- Matrix ---

MATRIX_PROVISION_TOTAL = Counter(
    "matrix_provision_total",
    "Matrix user provisioning outcomes",
    ["outcome"],
)

MATRIX_ROOM_PROVISION_TOTAL = Counter(
    "matrix_room_provision_total",
    "Matrix room provisioning outcomes",
    ["outcome"],
)

MATRIX_SESSION_TOTAL = Counter(
    "matrix_session_total",
    "Matrix session issuance outcomes",
    ["outcome"],
)

MATRIX_ADMIN_REQUESTS_TOTAL = Counter(
    "matrix_admin_requests_total",
    "Synapse admin API requests",
    ["operation", "status"],
)

MATRIX_ADMIN_DURATION_SECONDS = Histogram(
    "matrix_admin_duration_seconds",
    "Synapse admin API request duration in seconds",
    ["operation"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

MATRIX_CLIENT_REQUESTS_TOTAL = Counter(
    "matrix_client_requests_total",
    "Matrix client API operations",
    ["operation", "status"],
)

MATRIX_CLIENT_DURATION_SECONDS = Histogram(
    "matrix_client_duration_seconds",
    "Matrix client operation duration in seconds",
    ["operation"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# --- Matrix chat ---

MATRIX_ROOM_CREATE_TOTAL = Counter(
    "matrix_room_create_total",
    "Matrix DM rooms created",
    ["outcome"],
)

MATRIX_ROOM_ARCHIVE_TOTAL = Counter(
    "matrix_room_archive_total",
    "Matrix rooms archived",
)

MATRIX_MESSAGES_SENT_TOTAL = Counter(
    "matrix_messages_sent_total",
    "Matrix messages sent via BFF business events",
    ["event_type"],
)

MATRIX_MESSAGES_FAILED_TOTAL = Counter(
    "matrix_messages_failed_total",
    "Matrix message/event publish failures",
    ["reason"],
)

MATRIX_MEDIA_UPLOAD_TOTAL = Counter(
    "matrix_media_upload_total",
    "Matrix attachment metadata recorded",
)

MATRIX_MEDIA_FAILED_TOTAL = Counter(
    "matrix_media_failed_total",
    "Matrix media metadata failures",
)

MATRIX_SYNC_FAILURES_TOTAL = Counter(
    "matrix_sync_failures_total",
    "Matrix session/sync failures",
    ["reason"],
)

MATRIX_SESSION_ISSUED_TOTAL = Counter(
    "matrix_session_issued_total",
    "Matrix client sessions issued",
)

MATRIX_PROVISION_ERRORS_TOTAL = Counter(
    "matrix_provision_errors_total",
    "Matrix user/room provisioning errors",
    ["kind"],
)

MATRIX_PRESENCE_UPDATES_TOTAL = Counter(
    "matrix_presence_updates_total",
    "Matrix presence updates recorded",
)

# --- Search / Typesense ---

SEARCH_REQUESTS_TOTAL = Counter(
    "search_requests_total",
    "Search API requests",
    ["endpoint", "outcome"],
)

SEARCH_CACHE_HITS_TOTAL = Counter(
    "search_cache_hits_total",
    "Search cache hits",
    ["endpoint"],
)

SEARCH_CACHE_MISSES_TOTAL = Counter(
    "search_cache_misses_total",
    "Search cache misses",
    ["endpoint"],
)

SEARCH_TYPESENSE_LATENCY_SECONDS = Histogram(
    "search_typesense_latency_seconds",
    "Typesense query latency in seconds",
    ["endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

SEARCH_INDEX_JOBS_TOTAL = Counter(
    "search_index_jobs_total",
    "Search indexing background jobs",
    ["collection", "action", "outcome"],
)

SEARCH_REINDEX_DURATION_SECONDS = Histogram(
    "search_reindex_duration_seconds",
    "Bulk reindex CLI duration in seconds",
    ["collection"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

SEARCH_EVENTS_RECORDED_TOTAL = Counter(
    "search_events_recorded_total",
    "Search analytics events recorded",
    ["type"],
)

SEARCH_ANALYTICS_JOB_DURATION_SECONDS = Histogram(
    "search_analytics_job_duration_seconds",
    "Search analytics aggregation job duration",
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0),
)
