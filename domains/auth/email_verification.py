"""App-owned email verification token issuing and delivery."""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from urllib.parse import urlencode, urlparse, urlunparse

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
from domains.auth.security import expires_in, generate_token, hash_secret
from domains.users.user import User
from infrastructure.database.repositories.auth import PostgresAuthRepository
from v1.utils.base import ConfigurationError, IntegrationError

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class VerificationEmail:
    """Email payload for app-owned verification links."""

    to_email: str
    verify_link: str


class SmtpVerificationEmailSender:
    """Send branded verification email through the configured realm SMTP server."""

    async def send(self, message: VerificationEmail) -> None:
        """Send the message without blocking the event loop."""
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: VerificationEmail) -> None:
        if not settings.keycloak.smtp_host or not settings.keycloak.smtp_from:
            log_warning(
                logger,
                "App verification email was not sent because SMTP is not configured",
                smtp_host_set=bool(settings.keycloak.smtp_host),
                smtp_from_set=bool(settings.keycloak.smtp_from),
            )
            raise ConfigurationError(
                "SMTP is not configured for app verification email",
                context={"smtp_host_configured": bool(settings.keycloak.smtp_host)},
            )

        email = EmailMessage()
        email["Subject"] = "Verify your Veliqone email"
        email["From"] = _from_header()
        email["To"] = message.to_email
        email.set_content(_text_body(message.verify_link))
        email.add_alternative(_html_body(message.verify_link), subtype="html")

        try:
            if settings.keycloak.smtp_ssl.lower() == "true":
                with smtplib.SMTP_SSL(
                    settings.keycloak.smtp_host,
                    int(settings.keycloak.smtp_port),
                    timeout=settings.http.timeout_seconds,
                ) as smtp:
                    _login_and_send(smtp, email)
                log_info(
                    logger,
                    "App verification email sent successfully",
                    smtp_host=settings.keycloak.smtp_host,
                    to_domain=message.to_email.rsplit("@", 1)[-1],
                )
                return

            with smtplib.SMTP(
                settings.keycloak.smtp_host,
                int(settings.keycloak.smtp_port),
                timeout=settings.http.timeout_seconds,
            ) as smtp:
                if settings.keycloak.smtp_starttls.lower() == "true":
                    smtp.starttls()
                _login_and_send(smtp, email)
            log_info(
                logger,
                "App verification email sent successfully",
                smtp_host=settings.keycloak.smtp_host,
                to_domain=message.to_email.rsplit("@", 1)[-1],
            )
        except (OSError, smtplib.SMTPException) as exc:
            log_warning(
                logger,
                "App verification email delivery failed",
                smtp_host=settings.keycloak.smtp_host or "(unset)",
                to_domain=message.to_email.rsplit("@", 1)[-1],
                error_type=type(exc).__name__,
            )
            raise IntegrationError("Verification email delivery failed") from exc


class AppEmailVerificationIssuer:
    """Issue one-time verification links and deliver them by email."""

    def __init__(
        self,
        *,
        auth_repository: PostgresAuthRepository | None = None,
        sender: SmtpVerificationEmailSender | None = None,
    ) -> None:
        self._auth_repository = auth_repository or PostgresAuthRepository()
        self._sender = sender or SmtpVerificationEmailSender()

    async def issue_and_send(self, *, user: User) -> None:
        """Create a single-use token for a pending user and send the link."""
        if not user.email:
            raise ConfigurationError("Cannot verify an account without an email")

        raw_token = generate_token()
        await self._auth_repository.create_email_verification_token(
            user_id=user.id,
            token_hash=hash_secret(raw_token),
            expires_at=expires_in(settings.auth.email_verification_token_ttl_sec),
        )
        await self._sender.send(
            VerificationEmail(
                to_email=user.email,
                verify_link=_verification_link(raw_token),
            ),
        )


def _verification_link(token: str) -> str:
    parsed = urlparse(settings.auth.email_verify_redirect_url)
    query = urlencode({"token": token})
    return urlunparse(parsed._replace(query=query))


def _from_header() -> str:
    display = settings.keycloak.smtp_from_display_name.strip()
    if not display:
        return settings.keycloak.smtp_from
    return f"{display} <{settings.keycloak.smtp_from}>"


def _login_and_send(smtp: smtplib.SMTP, email: EmailMessage) -> None:
    if settings.keycloak.smtp_user and settings.keycloak.smtp_password_value:
        smtp.login(settings.keycloak.smtp_user, settings.keycloak.smtp_password_value)
    smtp.send_message(email)


def _text_body(link: str) -> str:
    return (
        "Welcome to Veliqone.\n\n"
        "Verify your email address to protect your account and finish setup:\n\n"
        f"{link}\n\n"
        "If you did not create a Veliqone account, you can safely ignore this email.\n"
    )


def _html_body(link: str) -> str:
    safe_link = escape(link, quote=True)
    return f"""\
<div style="margin:0;padding:32px 16px;background:#f8fafc;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:24px;
      border:1px solid #e5e7eb;font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <div style="padding:32px 32px 16px;">
      <div style="font-size:24px;font-weight:700;letter-spacing:-0.02em;">Veliqone</div>
      <h1 style="margin:28px 0 12px;font-size:30px;line-height:1.15;font-weight:700;">
        Verify your email
      </h1>
      <p style="margin:0;color:#4b5563;font-size:15px;line-height:1.6;">
        Welcome to Veliqone. Confirm this email address so we can protect your account
        and finish your setup.
      </p>
    </div>
    <div style="padding:16px 32px 8px;">
      <a href="{safe_link}" style="display:block;border-radius:14px;background:#111827;
          color:#ffffff;text-decoration:none;text-align:center;padding:14px 20px;
          font-size:15px;font-weight:700;">
        Verify email
      </a>
    </div>
    <div style="padding:16px 32px 32px;">
      <p style="margin:0;color:#6b7280;font-size:13px;line-height:1.6;">
        This link expires soon. If you did not create a Veliqone account,
        you can safely ignore this email.
      </p>
      <p style="margin:18px 0 0;color:#9ca3af;font-size:12px;line-height:1.5;
          word-break:break-all;">
        {safe_link}
      </p>
    </div>
  </div>
</div>
"""
