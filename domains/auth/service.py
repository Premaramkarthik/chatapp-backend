"""Auth application services for BFF signin, sessions, and account security."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from starlette.requests import Request

from core.config.settings import settings
from core.logging.domain_events import (
    AUTH_SIGNUP_FAILED,
    AUTH_SIGNUP_STARTED,
    AUTH_SIGNUP_SUCCESS,
    PASSWORD_RESET_TRIGGERED,
    log_domain_event,
)
from core.logging.logger import get_logger
from core.observability.instrumentation import observe_service
from core.observability.prometheus_metrics import (
    AUTH_LOGOUT_TOTAL,
    AUTH_SESSION_CREATED_TOTAL,
    LOGIN_FAILURE_TOTAL,
    LOGIN_SUCCESS_TOTAL,
    SIGNUP_SUCCESS_TOTAL,
)
from domains.auth.keycloak_client import KeycloakAuthClient, keycloak_auth_client
from domains.auth.models import (
    AuthSecurityEventType,
    AuthSession,
    AuthSessionStatus,
    SessionView,
    SigninState,
    SignupCompleteResult,
    SignupResult,
    SignupStartResult,
    TokenSet,
)
from domains.auth.password_policy import validate_signup_password
from domains.auth.security import (
    TokenCipher,
    create_pkce_challenge,
    create_pkce_verifier,
    expires_in,
    generate_token,
    hash_optional,
    hash_secret,
    now_utc,
    validate_post_signin_redirect,
)
from domains.auth.session_cache import cache_session_snapshot, mark_session_revoked
from domains.auth.signup_security import (
    decide_account_linking,
    email_domain,
    enforce_resend_rate_limit,
    enforce_signup_rate_limits,
    is_disposable_email,
    normalize_email,
    request_hash,
    validate_captcha,
)
from domains.users.user import BootstrapUserCommand, User
from domains.utils.signup_start import (
    SignupStartContext,
    build_signup_start_context,
    build_signup_start_idempotency_body,
    is_duplicate_signup_user,
    signup_start_result_from_mapping,
)
from domains.utils.signup_start_provision import SignupStartProvisioner
from infrastructure.database.repositories.auth import PostgresAuthRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from infrastructure.keycloak.adapter import keycloak_verifier
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import AppError, AuthenticationError, AuthorizationError, SigninCallbackError
from v1.utils.request_context import request_id_from

logger = get_logger(__name__)


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


class AuthService:
    """Coordinates auth use cases while keeping adapters replaceable."""

    def __init__(
        self,
        *,
        auth_repository: PostgresAuthRepository | None = None,
        user_repository: PostgresUserRepository | None = None,
        keycloak: KeycloakAuthClient | None = None,
        cipher: TokenCipher | None = None,
        signup_start_provisioner: SignupStartProvisioner | None = None,
    ) -> None:
        self._auth_repository = auth_repository or PostgresAuthRepository()
        self._user_repository = user_repository or PostgresUserRepository()
        self._keycloak = keycloak or keycloak_auth_client
        self._cipher = cipher or TokenCipher()
        self._signup_start_provisioner = signup_start_provisioner or SignupStartProvisioner(
            user_repository=self._user_repository,
            auth_repository=self._auth_repository,
            keycloak=self._keycloak,
        )

    @observe_service("auth")
    async def start_signin(
        self,
        *,
        post_signin_redirect_uri: str | None,
        identity_provider: str | None = None,
        account_mode: str | None = None,
        device_fingerprint: str | None = None,
        captcha_token: str | None = None,
        request: Request,
    ) -> SigninStartResult:
        """Create one-time PKCE signin state and return a Keycloak auth URL."""
        request_id = request_id_from(request)
        logger.info(
            "signin_start_received request_id={} identity_provider={}",
            request_id,
            identity_provider,
        )
        flow_type = "signup" if identity_provider else "signin"
        if identity_provider:
            fingerprint = device_fingerprint or "web-client"
            await self._guard_signup_abuse(
                email=None,
                device_fingerprint=fingerprint,
                captcha_token=captcha_token,
                request=request,
                social=True,
            )
        verifier = create_pkce_verifier()
        challenge = create_pkce_challenge(verifier)
        state = generate_token()
        nonce = generate_token()
        expires_at = expires_in(settings.auth.signin_state_ttl_sec)
        safe_redirect = validate_post_signin_redirect(post_signin_redirect_uri)

        await self._auth_repository.create_signin_state(
            state_hash=hash_secret(state),
            nonce_hash=hash_secret(nonce),
            code_verifier_encrypted=str(self._cipher.encrypt(verifier)),
            client_id=settings.keycloak.web_client_id,
            redirect_uri=settings.auth.callback_url,
            post_signin_redirect_uri=safe_redirect,
            expires_at=expires_at,
            flow_type=flow_type,
            account_mode=account_mode,
            identity_provider=identity_provider,
        )
        await self._record_event(
            AuthSecurityEventType.SIGNIN_STARTED,
            request=request,
            metadata={
                "client_id": settings.keycloak.web_client_id,
                "identity_provider": identity_provider,
            },
        )
        logger.info("signin_state_created request_id={} expires_at={}", request_id, expires_at)
        return SigninStartResult(
            authorization_url=self._keycloak.authorization_url(
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                redirect_uri=settings.auth.callback_url,
                identity_provider=identity_provider,
            ),
            state=state,
            expires_at=expires_at,
        )

    @observe_service("auth")
    async def signin_password(
        self,
        *,
        email: str,
        password: str,
        request: Request,
    ) -> SigninCallbackResult:
        """Sign in with email/password using server-side Keycloak token exchange."""
        request_id = request_id_from(request)
        normalized_email = normalize_email(email)
        email_hash = hash_secret(normalized_email)
        logger.info(
            "signin_password_received request_id={} email_hash={}", request_id, email_hash[:16]
        )
        await self._guard_password_signin_abuse(request=request)
        try:
            token_set = await self._keycloak.password_grant(
                username=normalized_email,
                password=password,
            )
        except AuthenticationError as exc:
            if exc.code == "email_verification_required":
                LOGIN_FAILURE_TOTAL.labels(reason="email_not_verified").inc()
                await self._record_event(
                    AuthSecurityEventType.SIGNIN_FAILED,
                    request=request,
                    email_hash=email_hash,
                    metadata={"reason": "email_not_verified"},
                )
                raise
            LOGIN_FAILURE_TOTAL.labels(reason="invalid_credentials").inc()
            await self._record_event(
                AuthSecurityEventType.SIGNIN_FAILED,
                request=request,
                email_hash=email_hash,
                metadata={"reason": "invalid_credentials"},
            )
            raise AuthenticationError("Invalid email or password") from None
        principal = await keycloak_verifier.verify_token(token_set.access_token)
        signin_state = SigninState(
            id="password",
            state_hash="",
            nonce_hash="",
            code_verifier_encrypted="",
            redirect_uri=settings.auth.callback_url,
            post_signin_redirect_uri=settings.auth.default_post_signin_redirect_url,
            expires_at=now_utc(),
            flow_type="signin",
        )
        user = await self._activate_or_reject_signin(principal, signin_state, request)
        display_name = principal.display_name or principal.preferred_username
        if user is None:
            user = await self._user_repository.bootstrap(
                BootstrapUserCommand(
                    keycloak_sub=principal.sub,
                    email=principal.email,
                    display_name=display_name,
                )
            )
        session_token = generate_token()
        csrf_token = generate_token()
        session = await self._create_session(
            user=user,
            principal=principal,
            token_set=token_set,
            session_token=session_token,
            csrf_token=csrf_token,
            request=request,
        )
        await cache_session_snapshot(session, roles=principal.roles)
        await self._record_event(
            AuthSecurityEventType.SIGNIN_SUCCEEDED,
            request=request,
            user=user,
            keycloak_sub=principal.sub,
        )
        LOGIN_SUCCESS_TOTAL.inc()
        return SigninCallbackResult(
            session_token=session_token,
            csrf_token=csrf_token,
            session=session,
            post_signin_redirect_uri=settings.auth.default_post_signin_redirect_url,
            principal=principal,
            user=user,
        )

    async def complete_onboarding(
        self,
        *,
        keycloak_sub: str,
        display_name: str,
        account_mode: str,
        request: Request,
    ) -> User:
        """Complete onboarding for users in pending_profile_setup."""
        request_id = request_id_from(request)
        logger.info(
            "onboarding_complete_received request_id={} keycloak_sub={} account_mode={}",
            request_id,
            keycloak_sub,
            account_mode,
        )
        user = await self._user_repository.get_by_keycloak_sub(keycloak_sub)
        if user is None or user.status != "pending_profile_setup":
            raise AuthenticationError("Onboarding is not available for this account")
        completed = await self._user_repository.complete_onboarding(
            user_id=user.id,
            display_name=display_name,
            account_mode=account_mode,
        )
        if completed is None:
            raise AuthenticationError("Onboarding could not be completed")
        if user.keycloak_sub:
            await self._keycloak.update_user_profile(
                user_id=user.keycloak_sub,
                display_name=display_name,
            )
        await self._auth_repository.write_outbox_event(
            event_type="signup.onboarding_completed",
            aggregate_type="user",
            aggregate_id=completed.id,
            payload={"account_mode": account_mode},
        )
        await self._record_event(
            AuthSecurityEventType.SIGNUP_CREATED,
            request=request,
            user=completed,
            keycloak_sub=keycloak_sub,
        )
        return completed

    @observe_service("auth")
    async def signup_start(
        self,
        *,
        email: str,
        password: str,
        device_fingerprint: str,
        captcha_token: str | None,
        idempotency_key: str,
        request: Request,
    ) -> SignupStartResult:
        """Create pending account with password set in Keycloak; return signup session token."""
        request_id = request_id_from(request)
        log_domain_event(AUTH_SIGNUP_STARTED, request_id=request_id)
        logger.info(
            "signup_start_received request_id={} idempotency_key_hash={} email_hash={}",
            request_id,
            hash_secret(idempotency_key)[:16],
            hash_secret(normalize_email(email))[:16],
        )
        ctx = build_signup_start_context(
            email=email,
            password=password,
            device_fingerprint=device_fingerprint,
            idempotency_key=idempotency_key,
        )
        validate_signup_password(password=password, email=ctx.normalized_email)
        logger.info(
            "signup_validation_ok request_id={} email_hash={}", request_id, ctx.email_hash[:16]
        )

        existing_result = await self._auth_repository.get_idempotency_result(
            idempotency_key_hash=ctx.idempotency_hash,
            request_hash=ctx.payload_hash,
        )
        if existing_result:
            if existing_result.get("error") == "idempotency_key_reused":
                raise AppError("Idempotency-Key was already used", code="idempotency_key_reused")
            return signup_start_result_from_mapping(existing_result)

        if is_disposable_email(ctx.normalized_email):
            return await self._generic_signup_start_response(
                ctx,
                request=request,
                event_type=AuthSecurityEventType.SIGNUP_DISPOSABLE_EMAIL_BLOCKED,
                metadata={"domain": email_domain(ctx.normalized_email)},
            )

        await self._guard_signup_abuse(
            email=ctx.normalized_email,
            device_fingerprint=device_fingerprint,
            captcha_token=captcha_token,
            request=request,
        )
        await self._record_event(
            AuthSecurityEventType.SIGNUP_REQUESTED,
            request=request,
            email_hash=ctx.email_hash,
            metadata={"domain": email_domain(ctx.normalized_email)},
        )

        user = await self._user_repository.get_by_email(ctx.normalized_email)
        if is_duplicate_signup_user(user):
            return await self._generic_signup_start_response(
                ctx,
                request=request,
                event_type=AuthSecurityEventType.SIGNUP_DUPLICATE,
                user=user,
            )

        user = await self._signup_start_provisioner.get_or_create_pending_user(
            email=ctx.normalized_email,
            existing=user,
        )
        if user.keycloak_sub is None:
            logger.info(
                "signup_user_created request_id={} user_id={} email_hash={}",
                request_id,
                user.id,
                ctx.email_hash[:16],
            )
        try:
            user, result, keycloak_sub = await self._signup_start_provisioner.provision(
                user=user,
                email=ctx.normalized_email,
                password=password,
                request_id=request_id,
            )
            await self._record_event(
                AuthSecurityEventType.SIGNUP_EMAIL_SENT,
                request=request,
                user=user,
                keycloak_sub=keycloak_sub,
                email_hash=ctx.email_hash,
            )
            SIGNUP_SUCCESS_TOTAL.inc()
            log_domain_event(
                AUTH_SIGNUP_SUCCESS,
                request_id=request_id,
                user_id=user.id,
                keycloak_sub=keycloak_sub,
            )
        except Exception:
            log_domain_event(AUTH_SIGNUP_FAILED, request_id=request_id)
            await self._signup_start_provisioner.mark_provision_failure(user=user)
            raise

        await self._store_signup_start_idempotency(
            ctx.idempotency_hash,
            ctx.payload_hash,
            result,
            ctx.email_hash,
        )
        logger.info(
            "signup_start_committed request_id={} user_id={} keycloak_sub={}",
            request_id,
            user.id,
            keycloak_sub,
        )
        return result

    async def signup_complete(
        self,
        *,
        signup_token: str,
        display_name: str,
        account_mode: str,
        request: Request,
    ) -> SignupCompleteResult:
        """Complete signup profile for a pending verification user."""
        request_id = request_id_from(request)
        logger.info("signup_complete_received request_id={}", request_id)
        session = await self._auth_repository.resolve_signup_session(
            token_hash=hash_secret(signup_token),
        )
        if session is None or session.step_completed != 1:
            raise AuthenticationError("Invalid or expired signup token")
        logger.info(
            "signup_session_resolved request_id={} user_id={} signup_session_id={}",
            request_id,
            session.user_id,
            session.id,
        )

        user = await self._user_repository.complete_signup_profile(
            user_id=session.user_id,
            display_name=display_name,
            account_mode=account_mode,
        )
        if user is None or user.keycloak_sub is None:
            raise AuthenticationError("Signup profile cannot be completed")

        await self._keycloak.update_user_profile(
            user_id=user.keycloak_sub,
            display_name=display_name,
        )
        logger.info(
            "profile_updated request_id={} user_id={} keycloak_sub={} account_mode={}",
            request_id,
            user.id,
            user.keycloak_sub,
            account_mode,
        )
        await self._auth_repository.complete_signup_session(session_id=session.id)
        await self._auth_repository.write_outbox_event(
            event_type="signup.profile_completed",
            aggregate_type="user",
            aggregate_id=user.id,
            payload={"account_mode": account_mode},
        )
        await self._record_event(
            AuthSecurityEventType.SIGNUP_CREATED,
            request=request,
            user=user,
            keycloak_sub=user.keycloak_sub,
        )
        return SignupCompleteResult()

    async def signup(
        self,
        *,
        email: str,
        display_name: str,
        account_mode: str,
        device_fingerprint: str,
        captcha_token: str | None,
        idempotency_key: str,
        request: Request,
    ) -> SignupResult:
        """Create a local pending account, then create/link a Keycloak user."""
        request_id = request_id_from(request)
        normalized_email = normalize_email(email)
        email_hash = hash_secret(normalized_email)
        logger.info(
            "signup_received request_id={} email_hash={} idempotency_key_hash={}",
            request_id,
            email_hash[:16],
            hash_secret(idempotency_key)[:16],
        )
        payload_hash = request_hash(
            {
                "email": normalized_email,
                "display_name": display_name,
                "account_mode": account_mode,
                "device_fingerprint": device_fingerprint,
            }
        )
        idempotency_hash = hash_secret(idempotency_key)
        existing_result = await self._auth_repository.get_idempotency_result(
            idempotency_key_hash=idempotency_hash,
            request_hash=payload_hash,
        )
        if existing_result:
            if existing_result.get("error") == "idempotency_key_reused":
                raise AppError("Idempotency-Key was already used", code="idempotency_key_reused")
            return SignupResult(**existing_result)

        generic = SignupResult()
        if is_disposable_email(normalized_email):
            await self._record_event(
                AuthSecurityEventType.SIGNUP_DISPOSABLE_EMAIL_BLOCKED,
                request=request,
                email_hash=email_hash,
                metadata={"domain": email_domain(normalized_email)},
            )
            await self._store_signup_idempotency(
                idempotency_hash,
                payload_hash,
                generic,
                email_hash,
            )
            return generic

        await self._guard_signup_abuse(
            email=normalized_email,
            device_fingerprint=device_fingerprint,
            captcha_token=captcha_token,
            request=request,
        )
        await self._record_event(
            AuthSecurityEventType.SIGNUP_REQUESTED,
            request=request,
            email_hash=email_hash,
            metadata={"domain": email_domain(normalized_email)},
        )

        user = await self._user_repository.get_by_email(normalized_email)
        if user and user.status in {"active", "pending_profile_setup"}:
            await self._record_event(
                AuthSecurityEventType.SIGNUP_DUPLICATE,
                request=request,
                user=user,
                email_hash=email_hash,
            )
            await self._store_signup_idempotency(
                idempotency_hash,
                payload_hash,
                generic,
                email_hash,
            )
            return generic

        if user is None:
            user = await self._user_repository.create_pending_signup(
                email=normalized_email,
                display_name=display_name,
                account_mode=account_mode,
                created_via="email",
            )

        try:
            keycloak_sub = user.keycloak_sub or await self._keycloak.create_user(
                email=normalized_email,
                display_name=display_name,
                required_actions=[],
            )
            if user.keycloak_sub is None:
                user = await self._user_repository.link_keycloak_subject(
                    user_id=user.id,
                    keycloak_sub=keycloak_sub,
                )
            await self._keycloak.clear_required_actions(user_id=keycloak_sub)
            await self._auth_repository.write_outbox_event(
                event_type="signup.created",
                aggregate_type="user",
                aggregate_id=user.id,
                payload={"created_via": "email", "account_mode": account_mode},
            )
            await self._keycloak.send_verification_email(user_id=keycloak_sub)
            await self._user_repository.mark_verification_sent(user_id=user.id)
            await self._auth_repository.write_outbox_event(
                event_type="signup.verification_email_sent",
                aggregate_type="user",
                aggregate_id=user.id,
                payload={},
            )
            await self._record_event(
                AuthSecurityEventType.SIGNUP_EMAIL_SENT,
                request=request,
                user=user,
                keycloak_sub=keycloak_sub,
                email_hash=email_hash,
            )
            SIGNUP_SUCCESS_TOTAL.inc()
        except Exception:
            await self._user_repository.mark_restricted(user_id=user.id)
            await self._auth_repository.write_outbox_event(
                event_type="account.restricted",
                aggregate_type="user",
                aggregate_id=user.id,
                payload={"reason": "signup_orchestration_failure"},
            )
            raise

        await self._store_signup_idempotency(idempotency_hash, payload_hash, generic, email_hash)
        logger.info("signup_committed request_id={} email_hash={}", request_id, email_hash[:16])
        return generic

    async def resend_signup_email(
        self,
        *,
        email: str,
        request: Request,
    ) -> SignupResult:
        """Resend verification/setup email with cooldown and generic response."""
        request_id = request_id_from(request)
        normalized_email = normalize_email(email)
        email_hash = hash_secret(normalized_email)
        logger.info(
            "signup_resend_received request_id={} email_hash={}",
            request_id,
            email_hash[:16],
        )
        rate = await enforce_resend_rate_limit(email=normalized_email)
        if not rate.allowed:
            logger.warning(
                "signup_resend_skipped request_id={} email_hash={} reason={}",
                request_id,
                email_hash[:16],
                rate.reason,
            )
            await self._record_event(
                AuthSecurityEventType.SUSPICIOUS_ACTIVITY,
                request=request,
                email_hash=email_hash,
                metadata={"reason": rate.reason},
            )
            return SignupResult()

        await self._record_event(
            AuthSecurityEventType.SIGNUP_RESEND_REQUESTED,
            request=request,
            email_hash=email_hash,
        )
        user = await self._user_repository.get_by_email(normalized_email)
        if (
            user is None
            or user.keycloak_sub is None
            or user.status
            not in {
                "pending_verification",
                "restricted",
            }
        ):
            logger.info(
                "signup_resend_skipped request_id={} email_hash={} reason={}",
                request_id,
                email_hash[:16],
                "user_not_eligible",
            )
            return SignupResult()
        if _verification_cooldown_active(user.last_verification_sent_at):
            logger.info(
                "signup_resend_skipped request_id={} email_hash={} reason={}",
                request_id,
                email_hash[:16],
                "cooldown_active",
            )
            return SignupResult()
        if user.verification_send_count >= settings.auth.signup_max_verification_sends:
            logger.info(
                "signup_resend_skipped request_id={} email_hash={} reason={}",
                request_id,
                email_hash[:16],
                "max_sends_reached",
            )
            return SignupResult()

        await self._keycloak.clear_required_actions(user_id=user.keycloak_sub)
        await self._keycloak.send_verification_email(user_id=user.keycloak_sub)
        await self._user_repository.mark_verification_sent(user_id=user.id)
        await self._auth_repository.write_outbox_event(
            event_type="signup.verification_email_sent",
            aggregate_type="user",
            aggregate_id=user.id,
            payload={"resend": True},
        )
        logger.info(
            "signup_resend_sent request_id={} user_id={} email_hash={}",
            request_id,
            user.id,
            email_hash[:16],
        )
        return SignupResult()

    async def start_social_signup(
        self,
        *,
        identity_provider: str,
        account_mode: str | None,
        device_fingerprint: str,
        captcha_token: str | None,
        post_signin_redirect_uri: str | None,
        request: Request,
    ) -> SigninStartResult:
        """Begin social signup and store signup intent in OAuth state."""
        request_id = request_id_from(request)
        logger.info(
            "social_signup_start_received request_id={} identity_provider={} account_mode={}",
            request_id,
            identity_provider,
            account_mode,
        )
        await self._guard_signup_abuse(
            email=None,
            device_fingerprint=device_fingerprint,
            captcha_token=captcha_token,
            request=request,
            social=True,
        )
        verifier = create_pkce_verifier()
        challenge = create_pkce_challenge(verifier)
        state = generate_token()
        nonce = generate_token()
        expires_at = expires_in(settings.auth.signin_state_ttl_sec)
        safe_redirect = validate_post_signin_redirect(post_signin_redirect_uri)
        await self._auth_repository.create_signin_state(
            state_hash=hash_secret(state),
            nonce_hash=hash_secret(nonce),
            code_verifier_encrypted=str(self._cipher.encrypt(verifier)),
            client_id=settings.keycloak.web_client_id,
            redirect_uri=settings.auth.callback_url,
            post_signin_redirect_uri=safe_redirect,
            expires_at=expires_at,
            flow_type="signup",
            account_mode=account_mode,
            identity_provider=identity_provider,
        )
        logger.info(
            "social_signup_state_created request_id={} identity_provider={} expires_at={}",
            request_id,
            identity_provider,
            expires_at,
        )
        return SigninStartResult(
            authorization_url=self._keycloak.authorization_url(
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                redirect_uri=settings.auth.callback_url,
                identity_provider=identity_provider,
            ),
            state=state,
            expires_at=expires_at,
        )

    @observe_service("auth")
    async def handle_callback(
        self,
        *,
        code: str,
        state: str,
        request: Request,
    ) -> SigninCallbackResult:
        """Exchange auth code and create a server-side app session."""
        request_id = request_id_from(request)
        logger.info("signin_callback_received request_id={}", request_id)
        signin_state = await self._consume_signin_state(state)
        redirect_uri = signin_state.post_signin_redirect_uri
        try:
            return await self._complete_signin_callback(
                code=code,
                signin_state=signin_state,
                request=request,
                request_id=request_id,
            )
        except AuthenticationError as exc:
            if isinstance(exc, SigninCallbackError):
                raise
            raise SigninCallbackError(
                exc.message,
                code=exc.code,
                post_signin_redirect_uri=redirect_uri,
            ) from exc

    async def _complete_signin_callback(
        self,
        *,
        code: str,
        signin_state: SigninState,
        request: Request,
        request_id: str,
    ) -> SigninCallbackResult:
        """Run token exchange, activation, and session creation for OAuth callback."""
        verifier = self._cipher.decrypt(signin_state.code_verifier_encrypted)
        if verifier is None:
            raise AuthenticationError("Invalid signin state")

        token_set = await self._keycloak.exchange_code(
            code=code,
            redirect_uri=signin_state.redirect_uri,
            code_verifier=verifier,
        )
        logger.info("token_exchanged request_id={}", request_id)
        principal = await keycloak_verifier.verify_token(token_set.access_token)
        logger.info(
            "principal_parsed request_id={} keycloak_sub={} email_verified={}",
            request_id,
            principal.sub,
            principal.email_verified,
        )
        user = await self._activate_or_reject_signin(principal, signin_state, request)
        display_name = principal.display_name or principal.preferred_username
        if user is None:
            user = await self._user_repository.bootstrap(
                BootstrapUserCommand(
                    keycloak_sub=principal.sub,
                    email=principal.email,
                    display_name=display_name,
                )
            )

        session_token = generate_token()
        csrf_token = generate_token()
        session = await self._create_session(
            user=user,
            principal=principal,
            token_set=token_set,
            session_token=session_token,
            csrf_token=csrf_token,
            request=request,
        )
        await cache_session_snapshot(session, roles=principal.roles)
        await self._record_event(
            AuthSecurityEventType.SIGNIN_SUCCEEDED,
            request=request,
            user=user,
            keycloak_sub=principal.sub,
        )
        LOGIN_SUCCESS_TOTAL.inc()
        return SigninCallbackResult(
            session_token=session_token,
            csrf_token=csrf_token,
            session=session,
            post_signin_redirect_uri=signin_state.post_signin_redirect_uri,
            principal=principal,
            user=user,
        )

    @observe_service("auth")
    async def logout(
        self,
        *,
        session: AuthSession,
        request: Request,
    ) -> str:
        """Revoke one local BFF session and return a Keycloak logout URL."""
        request_id = request_id_from(request)
        logger.info(
            "logout_received request_id={} session_id={} user_id={}",
            request_id,
            session.id,
            session.user_id,
        )
        await self._auth_repository.revoke_session(
            session_id=session.id,
            user_id=session.user_id,
        )
        await mark_session_revoked(session.session_hash)
        await self._record_event(
            AuthSecurityEventType.LOGOUT_SUCCEEDED,
            request=request,
            user_id=session.user_id,
            keycloak_sub=session.keycloak_sub,
        )
        AUTH_LOGOUT_TOTAL.inc()
        logger.info(
            "logout_session_revoked request_id={} session_id={} user_id={}",
            request_id,
            session.id,
            session.user_id,
        )
        id_token = self._cipher.decrypt(session.id_token_encrypted)
        return self._keycloak.logout_url(
            id_token_hint=id_token,
            post_logout_redirect_uri=settings.auth.post_logout_redirect_url,
        )

    async def forgot_password(self, *, email: str, request: Request) -> None:
        """Trigger Keycloak reset email with a generic external response."""
        request_id = request_id_from(request)
        email_hash = hash_secret(email.lower().strip())
        logger.info(
            "forgot_password_received request_id={} email_hash={}",
            request_id,
            email_hash[:16],
        )
        await self._record_event(
            AuthSecurityEventType.FORGOT_PASSWORD_REQUESTED,
            request=request,
            email_hash=email_hash,
        )
        sent = await self._keycloak.send_password_reset_email(email=email)
        if sent:
            log_domain_event(PASSWORD_RESET_TRIGGERED, request_id=request_id)
            await self._record_event(
                AuthSecurityEventType.FORGOT_PASSWORD_EMAIL_SENT,
                request=request,
                email_hash=email_hash,
            )
            logger.info(
                "forgot_password_email_sent request_id={} email_hash={}",
                request_id,
                email_hash[:16],
            )

    @observe_service("auth")
    async def delete_account(
        self,
        *,
        principal_sub: str,
        request: Request,
    ) -> None:
        """Delete Keycloak account and local user records."""
        request_id = request_id_from(request)
        await self._keycloak.delete_user(user_id=principal_sub)
        deleted = await self._user_repository.delete_by_keycloak_sub(principal_sub)
        await self._record_event(
            AuthSecurityEventType.ACCOUNT_DELETED,
            request=request,
            user_id=deleted.id if deleted else None,
            keycloak_sub=principal_sub,
        )
        logger.info(
            "account_deleted request_id={} keycloak_sub={}",
            request_id,
            principal_sub,
        )

    async def _activate_or_reject_signin(
        self,
        principal: KeycloakPrincipal,
        signin_state: SigninState,
        request: Request,
    ) -> User | None:
        if not principal.email:
            return None
        existing = await self._user_repository.get_by_email(normalize_email(principal.email))
        if existing is None:
            if signin_state.flow_type != "signup":
                return None
            existing = await self._user_repository.create_pending_signup(
                email=normalize_email(principal.email),
                display_name=(
                    principal.display_name or principal.preferred_username or principal.email
                ),
                account_mode=signin_state.account_mode,
                created_via=signin_state.identity_provider or "email",
            )
        decision = decide_account_linking(
            existing_status=existing.status,
            existing_keycloak_sub=existing.keycloak_sub,
            incoming_keycloak_sub=principal.sub,
            expected_identity_provider=signin_state.identity_provider,
            incoming_identity_provider=(
                principal.identity_provider or signin_state.identity_provider
            ),
        )
        if decision.value != "allow_pending_match":
            await self._record_event(
                AuthSecurityEventType.ACCOUNT_LINKING_REQUIRED,
                request=request,
                user=existing,
                keycloak_sub=principal.sub,
            )
            raise AuthenticationError("Account linking confirmation is required")
        if existing.keycloak_sub != principal.sub and existing.status == "pending_verification":
            existing = await self._user_repository.link_keycloak_subject(
                user_id=existing.id,
                keycloak_sub=principal.sub,
            )
        elif existing.keycloak_sub is None:
            existing = await self._user_repository.link_keycloak_subject(
                user_id=existing.id,
                keycloak_sub=principal.sub,
            )
        if existing.status == "pending_verification":
            request_id = request_id_from(request)
            logger.info(
                "activation_attempted request_id={} user_id={} keycloak_sub={} "
                "email_verified={} status={}",
                request_id,
                existing.id,
                principal.sub,
                principal.email_verified,
                existing.status,
            )
            if not principal.email_verified:
                logger.warning(
                    "activation_failed request_id={} user_id={} keycloak_sub={} reason={}",
                    request_id,
                    existing.id,
                    principal.sub,
                    "email_not_verified_in_token",
                )
                raise AuthenticationError(
                    "Email verification is required before signin",
                    code="email_verification_required",
                )
            failure_reason = _activation_failure_reason(existing, principal)
            activated = await self._user_repository.activate_after_verified_signin(
                keycloak_sub=principal.sub,
                email=normalize_email(principal.email),
                email_verified=principal.email_verified,
            )
            if activated is None:
                logger.warning(
                    "activation_failed request_id={} user_id={} keycloak_sub={} reason={}",
                    request_id,
                    existing.id,
                    principal.sub,
                    failure_reason or "activation_lookup_failed",
                )
                if principal.email_verified:
                    raise AuthenticationError(
                        (
                            "We couldn't finish setting up your account. "
                            "Please try again or contact support."
                        ),
                        code="account_activation_failed",
                    )
                raise AuthenticationError(
                    "Email verification is required before signin",
                    code="email_verification_required",
                )
            logger.info(
                "activation_succeeded request_id={} user_id={} keycloak_sub={} status={}",
                request_id,
                activated.id,
                principal.sub,
                activated.status,
            )
            await self._auth_repository.write_outbox_event(
                event_type="signup.verified",
                aggregate_type="user",
                aggregate_id=activated.id,
                payload={},
            )
            await self._record_event(
                AuthSecurityEventType.SIGNUP_ACTIVATED,
                request=request,
                user=activated,
                keycloak_sub=principal.sub,
            )
            return activated
        return existing

    async def list_sessions(self, *, user_id: str) -> list[SessionView]:
        """List active/recent sessions for a user."""
        return await self._auth_repository.list_sessions(user_id=user_id)

    async def revoke_session(
        self,
        *,
        session_id: str,
        user_id: str,
        request: Request,
    ) -> None:
        """Revoke one session owned by the current user."""
        request_id = request_id_from(request)
        logger.info(
            "session_revoke_received request_id={} session_id={} user_id={}",
            request_id,
            session_id,
            user_id,
        )
        session = await self._auth_repository.revoke_session(session_id=session_id, user_id=user_id)
        if session is None:
            raise AuthorizationError("Session not found")
        await mark_session_revoked(session.session_hash)
        await self._record_event(
            AuthSecurityEventType.SESSION_REVOKED,
            request=request,
            user_id=user_id,
            keycloak_sub=session.keycloak_sub,
        )
        logger.info(
            "session_revoked request_id={} session_id={} user_id={}",
            request_id,
            session_id,
            user_id,
        )

    async def revoke_all_sessions(
        self,
        *,
        user_id: str,
        keep_session_id: str | None,
        request: Request,
    ) -> int:
        """Revoke all sessions for a user, optionally preserving the current one."""
        request_id = request_id_from(request)
        logger.info(
            "session_revoke_all_received request_id={} user_id={} keep_session_id={}",
            request_id,
            user_id,
            keep_session_id,
        )
        sessions = await self._auth_repository.revoke_all_sessions(
            user_id=user_id,
            keep_session_id=keep_session_id,
        )
        for session in sessions:
            await mark_session_revoked(session.session_hash)
        await self._record_event(
            AuthSecurityEventType.SESSION_REVOKED,
            request=request,
            user_id=user_id,
            metadata={"count": len(sessions), "keep_current": keep_session_id is not None},
        )
        logger.info(
            "session_revoke_all_committed request_id={} user_id={} revoked_count={}",
            request_id,
            user_id,
            len(sessions),
        )
        return len(sessions)

    async def _consume_signin_state(self, state: str) -> SigninState:
        signin_state = await self._auth_repository.consume_signin_state(
            state_hash=hash_secret(state),
        )
        if signin_state is None:
            LOGIN_FAILURE_TOTAL.labels(reason="invalid_state").inc()
            raise AuthenticationError("Invalid or expired signin state")
        return signin_state

    async def _guard_password_signin_abuse(self, *, request: Request) -> None:
        ip_address = request.client.host if request.client else "unknown"
        rate = await enforce_signup_rate_limits(
            ip_address=ip_address,
            device_fingerprint=ip_address,
            email=None,
            social=False,
        )
        if not rate.allowed:
            await self._record_event(
                AuthSecurityEventType.SUSPICIOUS_ACTIVITY,
                request=request,
                metadata={"reason": rate.reason, "flow": "password_signin"},
            )
            raise AuthenticationError("Sign-in is temporarily unavailable")

    async def _guard_signup_abuse(
        self,
        *,
        email: str | None,
        device_fingerprint: str,
        captcha_token: str | None,
        request: Request,
        social: bool = False,
    ) -> None:
        validate_captcha(captcha_token)
        ip_address = request.client.host if request.client else "unknown"
        rate = await enforce_signup_rate_limits(
            ip_address=ip_address,
            device_fingerprint=device_fingerprint,
            email=email,
            social=social,
        )
        if not rate.allowed:
            await self._record_event(
                AuthSecurityEventType.SUSPICIOUS_ACTIVITY,
                request=request,
                email_hash=hash_secret(email) if email else None,
                metadata={"reason": rate.reason},
            )
            raise AuthenticationError("Signup is temporarily unavailable")

    async def _store_signup_idempotency(
        self,
        idempotency_key_hash: str,
        payload_hash: str,
        result: SignupResult,
        email_hash: str,
    ) -> None:
        await self._auth_repository.store_idempotency_result(
            idempotency_key_hash=idempotency_key_hash,
            request_hash=payload_hash,
            response_body={"status": result.status, "next_step": result.next_step},
            status_code=202,
            email_hash=email_hash,
            expires_at=expires_in(settings.auth.signup_idempotency_ttl_sec),
        )

    async def _generic_signup_start_response(
        self,
        ctx: SignupStartContext,
        *,
        request: Request,
        event_type: AuthSecurityEventType,
        user: User | None = None,
        metadata: dict | None = None,
    ) -> SignupStartResult:
        """Record a signup event and return the generic anti-enumeration response."""
        await self._record_event(
            event_type,
            request=request,
            user=user,
            email_hash=ctx.email_hash,
            metadata=metadata,
        )
        generic = SignupStartResult()
        await self._store_signup_start_idempotency(
            ctx.idempotency_hash,
            ctx.payload_hash,
            generic,
            ctx.email_hash,
        )
        return generic

    async def _store_signup_start_idempotency(
        self,
        idempotency_key_hash: str,
        payload_hash: str,
        result: SignupStartResult,
        email_hash: str,
    ) -> None:
        await self._auth_repository.store_idempotency_result(
            idempotency_key_hash=idempotency_key_hash,
            request_hash=payload_hash,
            response_body=build_signup_start_idempotency_body(result),
            status_code=202,
            email_hash=email_hash,
            expires_at=expires_in(settings.auth.signup_idempotency_ttl_sec),
        )

    async def _create_session(
        self,
        *,
        user: User,
        principal: KeycloakPrincipal,
        token_set: TokenSet,
        session_token: str,
        csrf_token: str,
        request: Request,
    ) -> AuthSession:
        now = now_utc()
        user_agent = request.headers.get("user-agent")
        ip_address = request.client.host if request.client else None
        device_label = _device_label(user_agent)
        session = await self._auth_repository.create_session(
            session_hash=hash_secret(session_token),
            user_id=user.id,
            keycloak_sub=principal.sub,
            access_token_encrypted=str(self._cipher.encrypt(token_set.access_token)),
            refresh_token_encrypted=self._cipher.encrypt(token_set.refresh_token),
            id_token_encrypted=self._cipher.encrypt(token_set.id_token),
            access_expires_at=token_set.expires_at,
            refresh_expires_at=token_set.refresh_expires_at,
            idle_expires_at=now + timedelta(seconds=settings.auth.session_idle_sec),
            max_expires_at=now + timedelta(seconds=settings.auth.session_max_sec),
            csrf_token_hash=hash_secret(csrf_token),
            device_label=device_label,
            ip_hash=hash_optional(ip_address),
            user_agent_hash=hash_optional(user_agent),
        )
        AUTH_SESSION_CREATED_TOTAL.inc()
        logger.info(
            "session_created request_id={} user_id={} session_id={}",
            request_id_from(request),
            user.id,
            session.id,
        )
        return session

    async def _record_event(
        self,
        event_type: AuthSecurityEventType,
        *,
        request: Request,
        user: User | None = None,
        user_id: str | None = None,
        keycloak_sub: str | None = None,
        email_hash: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        ip_address = request.client.host if request.client else None
        await self._auth_repository.record_event(
            event_type=event_type.value,
            user_id=user.id if user else user_id,
            keycloak_sub=keycloak_sub,
            email_hash=email_hash,
            ip_hash=hash_optional(ip_address),
            user_agent_hash=hash_optional(request.headers.get("user-agent")),
            request_id=getattr(request.state, "request_id", None),
            metadata=metadata,
        )


def _activation_failure_reason(existing: User, principal: KeycloakPrincipal) -> str | None:
    """Return a diagnostic reason when pending verification activation cannot proceed."""
    if not principal.email_verified:
        return "email_not_verified_in_token"
    if existing.keycloak_sub and existing.keycloak_sub != principal.sub:
        return "keycloak_sub_mismatch"
    if existing.status != "pending_verification":
        return "status_not_pending"
    return "activation_lookup_failed"


def roles_from_token_unverified(token: str) -> list[str]:
    """Extract role claims without verifying signature for cache metadata only."""
    claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    resource_access = claims.get("resource_access", {})
    client_roles: list[str] = []
    for access in resource_access.values():
        client_roles.extend(access.get("roles", []))
    return sorted({*realm_roles, *client_roles})


def _device_label(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    return user_agent[:120]


def _verification_cooldown_active(value: datetime | str | None) -> bool:
    if value is None:
        return False
    sent_at = datetime.fromisoformat(value) if isinstance(value, str) else value
    return sent_at + timedelta(seconds=settings.auth.signup_resend_cooldown_sec) > now_utc()


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
