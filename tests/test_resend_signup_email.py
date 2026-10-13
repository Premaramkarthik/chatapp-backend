"""Email verification belongs to Keycloak's hosted flow."""

import json
from pathlib import Path


def test_hosted_realm_requires_verification_and_explicit_broker_linking():
    realm = json.loads(Path("deployment/keycloak/realm-chatapp.json.example").read_text())
    assert realm["verifyEmail"] and realm["registrationAllowed"]
    assert realm["resetPasswordAllowed"]
    assert realm["eventsListeners"] == ["jboss-logging"]
    from infrastructure.keycloak.google_idp_config import GOOGLE_BROKER_FLOW_ALIAS

    assert GOOGLE_BROKER_FLOW_ALIAS == "first broker login"
