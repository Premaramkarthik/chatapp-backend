"""Hosted OIDC authentication and durable local-first revocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request

from core.config.settings import settings
from domains.auth.keycloak_client import keycloak_auth_client
from domains.auth.models import AuthSession, AuthSessionStatus
from domains.auth.remote_operations import result_for, unavailable_local
from domains.auth.security import (
    TokenCipher,
    constant_time_equal,
    create_pkce_challenge,
    create_pkce_verifier,
    expires_in,
    generate_token,
    hash_optional,
    hash_secret,
    now_utc,
    validate_post_signin_redirect,
)
from domains.auth.session_cache import mark_session_revoked
from domains.auth.signup_security import normalize_email
from domains.users.user import User
from infrastructure.database.repositories.auth import PostgresAuthRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from infrastructure.keycloak.adapter import keycloak_verifier
from infrastructure.keycloak.session_control import session_control
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import AuthenticationError, SigninCallbackError


@dataclass(frozen=True, slots=True)
class SigninStartResult:
    """Result returned to a browser client to begin signin."""

    authorization_url: str
    state: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SigninCallbackResult:
    """Result after Keycloak callback succeeds."""

    session_token: str
    csrf_token: str
    session: AuthSession
    post_signin_redirect_uri: str
    principal: KeycloakPrincipal
    user: User
    cookie_max_age_sec: int | None = None


class AuthService:
    def __init__(self, *, auth_repository=None, user_repository=None, keycloak=None, cipher=None):
        self._auth_repository = auth_repository or PostgresAuthRepository()
        self._user_repository = user_repository or PostgresUserRepository()
        self._keycloak = keycloak or keycloak_auth_client
        self._cipher = cipher or TokenCipher()

    async def start_signin(
        self,
        *,
        post_signin_redirect_uri=None,
        identity_provider=None,
        intent="signin",
        request: Request,
        **unused,
    ) -> SigninStartResult:
        if intent not in {"signin", "signup"}:
            raise AuthenticationError("Invalid authentication intent")
        verifier, state, nonce = create_pkce_verifier(), generate_token(), generate_token()
        expires_at = expires_in(settings.auth.signin_state_ttl_sec)
        redirect = validate_post_signin_redirect(post_signin_redirect_uri)
        await self._auth_repository.create_signin_state(
            state_hash=hash_secret(state),
            nonce_hash=hash_secret(nonce),
            code_verifier_encrypted=self._cipher.encrypt(verifier),
            client_id=settings.keycloak.web_client_id,
            redirect_uri=settings.auth.callback_url,
            post_signin_redirect_uri=redirect,
            expires_at=expires_at,
            flow_type=intent,
            identity_provider=identity_provider,
        )
        return SigninStartResult(
            self._keycloak.authorization_url(
                state=state,
                nonce=nonce,
                code_challenge=create_pkce_challenge(verifier),
                redirect_uri=settings.auth.callback_url,
                identity_provider=identity_provider,
                intent=intent,
            ),
            state,
            expires_at,
        )

    async def handle_callback(
        self, *, code: str, state: str, request: Request
    ) -> SigninCallbackResult:
        saved = await self._auth_repository.consume_signin_state(state_hash=hash_secret(state))
        if saved is None:
            raise AuthenticationError("Invalid or expired signin state")
        try:
            verifier = self._cipher.decrypt(saved.code_verifier_encrypted)
            if not verifier:
                raise AuthenticationError("Invalid signin state")
            tokens = await self._keycloak.exchange_code(
                code=code, redirect_uri=saved.redirect_uri, code_verifier=verifier
            )
            claims = await keycloak_verifier.verify_id_token(tokens.id_token)
            if not constant_time_equal(hash_secret(str(claims.get("nonce", ""))), saved.nonce_hash):
                raise AuthenticationError("Invalid authentication nonce")
            principal = await keycloak_verifier.verify_token(tokens.access_token)
            if claims["sub"] != principal.sub:
                raise AuthenticationError("Token subject mismatch")
            await session_control.check(principal)
            user = await self._activate_or_reject_signin(principal, saved, request)
            session_token, csrf_token = generate_token(), generate_token()
            now = now_utc()
            session = await self._auth_repository.create_session(
                session_hash=hash_secret(session_token),
                user_id=user.id,
                keycloak_sub=principal.sub,
                keycloak_session_id=principal.sid,
                authenticated_at=datetime.fromtimestamp(
                    principal.auth_time or int(now.timestamp()), UTC
                ),
                access_token_encrypted=self._cipher.encrypt(tokens.access_token),
                refresh_token_encrypted=self._cipher.encrypt(tokens.refresh_token),
                id_token_encrypted=self._cipher.encrypt(tokens.id_token),
                access_expires_at=tokens.expires_at,
                refresh_expires_at=tokens.refresh_expires_at,
                idle_expires_at=now + timedelta(seconds=settings.auth.session_idle_sec),
                max_expires_at=now + timedelta(seconds=settings.auth.session_max_sec),
                csrf_token_hash=hash_secret(csrf_token),
                device_label=request.headers.get("user-agent", "browser")[:120],
                ip_hash=hash_optional(request.client.host if request.client else None),
                user_agent_hash=hash_optional(request.headers.get("user-agent")),
            )
            # Never accept a session stamped from a lookup instead of its authenticated token.
            await session_control.check(principal)
            return SigninCallbackResult(
                session_token,
                csrf_token,
                session,
                saved.post_signin_redirect_uri,
                principal,
                user,
                settings.auth.session_max_sec,
            )
        except AuthenticationError as exc:
            raise SigninCallbackError(
                exc.message, code=exc.code, post_signin_redirect_uri=saved.post_signin_redirect_uri
            ) from exc

    async def _activate_or_reject_signin(self, principal, signin_state, request) -> User:
        if not principal.email or not principal.email_verified:
            raise AuthenticationError("Verified email required", code="email_verification_required")
        # Atomic repository linking serializes email/subject claims and rejects reassignment.
        return await self._user_repository.resolve_verified_identity(
            subject=principal.sub,
            email=normalize_email(principal.email),
            display_name=principal.display_name or principal.preferred_username,
            created_via=principal.identity_provider or "email",
        )

    async def _revoke(
        self, *, user_id, subject, session_id=None, keep_session_id=None, delete_account=False
    ):
        try:
            operation, sessions = await self._auth_repository.revoke_with_operation(
                user_id=user_id,
                subject=subject,
                session_id=session_id,
                keep_session_id=keep_session_id,
                delete_account=delete_account,
            )
        except Exception as exc:
            raise unavailable_local(exc) from exc
        for session in sessions:
            try:
                await mark_session_revoked(session.session_hash)
            except Exception:
                pass  # PostgreSQL remains authoritative.
        return await result_for(operation, count=len(sessions))

    async def logout(self, *, session, request):
        return await self._revoke(
            user_id=session.user_id, subject=session.keycloak_sub, session_id=session.id
        )

    async def revoke_all_sessions(self, *, user_id, keycloak_sub, keep_session_id=None, request):
        return await self._revoke(
            user_id=user_id, subject=keycloak_sub, keep_session_id=keep_session_id
        )

    async def revoke_session(self, *, session_id, user_id, request):
        user = await self._user_repository.get_by_id(user_id)
        if user is None:
            raise AuthenticationError("Account not found")
        return await self._revoke(user_id=user_id, subject=user.keycloak_sub, session_id=session_id)

    async def list_sessions(self, *, user_id, request):
        return await self._auth_repository.list_sessions(user_id=user_id)

    async def delete_account(self, *, principal_sub, request):
        user = await self._user_repository.get_by_keycloak_sub(principal_sub)
        if user is None:
            raise AuthenticationError("Account not found")
        return await self._revoke(user_id=user.id, subject=principal_sub, delete_account=True)

    async def sync_display_name(self, *, keycloak_sub, display_name):
        await self._keycloak.update_user_profile(user_id=keycloak_sub, display_name=display_name)

    async def complete_onboarding(self, *, keycloak_sub, display_name, account_mode, request):
        user = await self._user_repository.get_by_keycloak_sub(keycloak_sub)
        if user is None or user.status != "pending_profile_setup":
            raise AuthenticationError("Onboarding is not available")
        result = await self._user_repository.complete_onboarding(
            user_id=user.id, display_name=display_name, account_mode=account_mode
        )
        if result is None:
            raise AuthenticationError("Onboarding could not be completed")
        return result


def transition_session_status(
    current: AuthSessionStatus,
    requested: AuthSessionStatus,
) -> AuthSessionStatus:
    """Validate important session state transitions."""
    allowed = {
        AuthSessionStatus.ACTIVE: {
            AuthSessionStatus.REFRESHING,
            AuthSessionStatus.REVOKED,
            AuthSessionStatus.EXPIRED,
            AuthSessionStatus.COMPROMISED,
            AuthSessionStatus.LOCKED,
        },
        AuthSessionStatus.REFRESHING: {
            AuthSessionStatus.ACTIVE,
            AuthSessionStatus.REVOKED,
            AuthSessionStatus.COMPROMISED,
        },
        AuthSessionStatus.LOCKED: {
            AuthSessionStatus.ACTIVE,
            AuthSessionStatus.REVOKED,
            AuthSessionStatus.COMPROMISED,
        },
    }
    if requested in allowed.get(current, set()):
        return requested
    if current == requested:
        return current
    raise AuthenticationError(f"Invalid auth session transition: {current} -> {requested}")


auth_service = AuthService()
