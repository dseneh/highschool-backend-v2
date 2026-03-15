"""Email service for transactional emails.

Provider priority:
    1) Resend API (if RESEND_API_KEY is set)
    2) Django EMAIL_BACKEND fallback

Configuration (in .env):
    RESEND_API_KEY=re_xxxxxxxxxxxxxxxx
    DEFAULT_FROM_EMAIL=noreply@yourdomain.com
    EMAIL_FROM_NAME=EzySchool
"""

import logging
from urllib.parse import urlparse
from typing import Optional

import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


def _is_public_email_asset_host(hostname: str) -> bool:
    """Return True when a hostname is suitable for email-client image fetching."""
    if not hostname:
        return False
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0"}
    if hostname in blocked_hosts:
        return False
    if hostname.endswith(".local"):
        return False
    return True


class ResendEmailService:
    """
    Sends transactional emails via the Resend REST API.

    Falls back to Django's email backend when RESEND_API_KEY is absent
    (useful in development with the console backend).
    """

    def __init__(self):
        self.resend_api_key: str = getattr(settings, "RESEND_API_KEY", "")
        self.from_email: str = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@ezyschool.net")
        self.from_name: str = getattr(settings, "EMAIL_FROM_NAME", "EzySchool")

    @property
    def _from_address(self) -> str:
        return f"{self.from_name} <{self.from_email}>"

    def send(
        self,
        to: list[str],
        subject: str = "",
        html_body: str = "",
        text_body: str = "",
        reply_to: Optional[str] = None,
    ) -> bool:
        """
        Send an email.

        Returns True on success, False on failure (errors are logged, not raised).
        """
        if self.resend_api_key:
            return self._send_via_resend(
                to=to,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                reply_to=reply_to,
            )
        return self._send_via_django(to, subject, html_body, text_body)

    def _send_via_resend(
        self,
        to: list[str],
        subject: str,
        html_body: str,
        text_body: str,
        reply_to: Optional[str],
    ) -> bool:
        payload: dict[str, object] = {
            "from": self._from_address,
            "to": to,
            "subject": subject,
            "html": html_body,
        }
        if text_body:
            payload["text"] = text_body
        if reply_to:
            payload["reply_to"] = reply_to

        headers = {
            "Authorization": f"Bearer {self.resend_api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                RESEND_API_URL,
                json=payload,
                headers=headers,
                timeout=10,
            )
            if response.status_code in (200, 201, 202):
                logger.info("Resend: email sent to %s (status %s)", to, response.status_code)
                return True

            logger.error(
                "Resend: non-2xx response %s; raw=%s",
                response.status_code,
                response.text[:500],
            )
            return False

        except requests.exceptions.Timeout:
            logger.error("Resend: request timed out sending to %s", to)
            return False

        except requests.exceptions.RequestException as exc:
            logger.error("Resend: request error sending to %s - %s", to, exc)
            return False

    # ------------------------------------------------------------------
    # Django email-backend fallback (dev/test)
    # ------------------------------------------------------------------

    def _send_via_django(
        self,
        to: list[str],
        subject: str,
        html_body: str,
        text_body: str,
    ) -> bool:
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body or "Please view this email in an HTML-capable client.",
                from_email=self._from_address,
                to=to,
            )
            if html_body:
                msg.attach_alternative(html_body, "text/html")
            msg.send()
            logger.debug("Django email backend: sent to %s", to)
            return True
        except Exception as exc:
            logger.error("Django email backend: failed to send to %s - %s", to, exc)
            return False


# Module-level singleton (avoids re-reading settings on every call)
_service = ResendEmailService()


# ------------------------------------------------------------------
# High-level helpers
# ------------------------------------------------------------------

def send_password_reset_email(user, reset_url: str, school=None) -> bool:
    """
    Render the password-reset email template and dispatch it to *user*.

    Args:
        user:       Django User instance (needs .email, .first_name / .username)
        reset_url:  Full URL the user should click to reset their password
        school:     Optional Tenant/School instance for branding

    Returns:
        True if the email was dispatched without error, False otherwise.
    """
    from datetime import datetime

    if not user.email:
        logger.warning("send_password_reset_email: user %s has no email address", user.username)
        return False

    # Build branding context ------------------------------------------------
    timeout_seconds = getattr(settings, "PASSWORD_RESET_TIMEOUT", 3600)
    timeout_hours = max(1, timeout_seconds // 3600)

    school_name = "EzySchool"
    school_address = ""
    if school:
        school_name = getattr(school, "name", school_name)
        school_address = getattr(school, "address", school_address)

    user_display_name = getattr(user, "first_name", "") or getattr(user, "username", "there")

    context = {
        "user": user,
        "user_name": user_display_name,
        "reset_url": reset_url,
        "school_name": school_name,
        "school_address": school_address,
        "timeout_hours": timeout_hours,
        "current_year": datetime.now().year,
        "product_name": "EzySchool System",
        "dev_name": "DewX IT Solutions",
        "dev_website": "https://www.dewx.tech",
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@ezyschool.net"),
        "logo_url": getattr(settings, "EMAIL_LOGO_URL", ""),
    }

    if not context["logo_url"]:
        frontend_domain = getattr(settings, "FRONTEND_DOMAIN", "")
        if frontend_domain:
            parsed_frontend = urlparse(frontend_domain)
            if (
                parsed_frontend.scheme
                and parsed_frontend.netloc
                and _is_public_email_asset_host(parsed_frontend.hostname or "")
            ):
                context["logo_url"] = f"{parsed_frontend.scheme}://{parsed_frontend.netloc}/img/logo-dark-full.png"

    if context["logo_url"]:
        parsed_logo = urlparse(context["logo_url"])
        if not (parsed_logo.scheme and parsed_logo.netloc and _is_public_email_asset_host(parsed_logo.hostname or "")):
            logger.warning(
                "EMAIL_LOGO_URL is not publicly reachable for email clients: %s",
                context["logo_url"],
            )
            context["logo_url"] = ""

    frontend_domain = getattr(settings, "FRONTEND_DOMAIN", "")
    parsed_domain = urlparse(frontend_domain) if frontend_domain else None
    if parsed_domain and parsed_domain.netloc:
        context["school_website"] = f"{parsed_domain.scheme}://{parsed_domain.netloc}"
    else:
        context["school_website"] = "https://www.ezyschool.net"

    try:
        html_body = render_to_string("emails/password_reset.html", context)
        text_body = render_to_string("emails/password_reset.txt", context)
    except Exception as exc:
        logger.error("send_password_reset_email: template render error - %s", exc)
        return False

    service = ResendEmailService()
    return service.send(
        to=[user.email],
        subject=f"Password Reset Request - {school_name}",
        html_body=html_body,
        text_body=text_body,
    )