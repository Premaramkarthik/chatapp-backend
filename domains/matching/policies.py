"""Locked product rules for traveler discovery and connections (v1)."""

from __future__ import annotations

# Mutual accept required before user_connections and Tinode topic provisioning.
CONNECTION_REQUIRES_MUTUAL_ACCEPT = True

# Primary search dimension is planned destination country; optional current_country filter.
SEARCH_PRIMARY_FIELD = "destination_country"
SEARCH_INCLUDE_CURRENT_COUNTRY = True

# Pending requests expire on read when expires_at < now() (no batch job in v1).
REQUEST_EXPIRY_CHECK_ON_READ = True

CONNECTION_REQUEST_TTL_DAYS = 14
