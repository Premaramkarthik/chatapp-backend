"""Keycloak helper tests."""

from v1.utils.keyclock_adapter import _extract_roles


def test_extract_roles_from_realm_and_clients() -> None:
    claims = {
        "realm_access": {"roles": ["admin", "user"]},
        "resource_access": {
            "chatapp-web": {"roles": ["traveler"]},
            "account": {"roles": ["user"]},
        },
    }

    assert _extract_roles(claims) == ["admin", "traveler", "user"]
