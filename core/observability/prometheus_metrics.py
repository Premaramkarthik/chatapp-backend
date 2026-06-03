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

# --- Integration counters (legacy names preserved) ---

TINODE_PROVISION_TOTAL = Counter(
    "tinode_provision_total",
    "Tinode user provisioning outcomes",
    ["outcome"],
)

TINODE_REST_AUTH_TOTAL = Counter(
    "tinode_rest_auth_total",
    "Tinode REST auth calls",
    ["endpoint"],
)

TINODE_REST_AUTH_DURATION_SECONDS = Histogram(
    "tinode_rest_auth_duration_seconds",
    "Tinode REST auth call duration in seconds",
    ["endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
