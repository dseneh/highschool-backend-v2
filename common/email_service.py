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


def _build_branding_context(user, school=None) -> dict[str, object]:
    from datetime import datetime

    timeout_seconds = getattr(settings, "PASSWORD_RESET_TIMEOUT", 3600)
    timeout_hours = max(1, timeout_seconds // 3600)

    school_name = "EzySchool"
    school_address = ""
    if school:
        school_name = getattr(school, "name", school_name)
        school_address = getattr(school, "address", school_address)

    user_display_name = getattr(user, "first_name", "") or getattr(user, "username", "there")

    context: dict[str, object] = {
        "user": user,
        "user_name": user_display_name,
        "school_name": school_name,
        "school_address": school_address,
        "timeout_hours": timeout_hours,
        "current_year": datetime.now().year,
        "product_name": "EzySchool System",
        "dev_name": "DewX IT Solutions",
        "dev_website": "https://www.dewx.tech",
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@ezyschool.app"),
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
        parsed_logo = urlparse(str(context["logo_url"]))
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
        context["school_website"] = "https://www.ezyschool.app"

    return context


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
        self.resend_api_key: str = getattr(settings, "RESEND_API_KEY", "").strip()
        self.from_email: str = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@ezyschool.app")
        self.from_name: str = getattr(settings, "EMAIL_FROM_NAME", "EzySchool")
        self.email_backend: str = getattr(settings, "EMAIL_BACKEND", "")
        self.email_host: str = getattr(settings, "EMAIL_HOST", "")
        self.email_host_user: str = getattr(settings, "EMAIL_HOST_USER", "").strip()
        self.email_host_password: str = getattr(settings, "EMAIL_HOST_PASSWORD", "").strip()

    @property
    def _from_address(self) -> str:
        return f"{self.from_name} <{self.from_email}>"

    @property
    def _smtp_is_configured(self) -> bool:
        return bool(self.email_host_user and self.email_host_password)

    def _prefer_local_smtp(self) -> bool:
        """In DEBUG, send through Django SMTP (e.g. Gmail) when credentials are set."""
        return bool(getattr(settings, "DEBUG", False) and self._smtp_is_configured)

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
        if self._prefer_local_smtp():
            logger.debug(
                "Using local SMTP (%s) for email to %s",
                self.email_host or "django backend",
                to,
            )
            return self._send_via_django(to, subject, html_body, text_body, reply_to=reply_to)

        if self.resend_api_key:
            return self._send_via_resend(
                to=to,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                reply_to=reply_to,
            )

        if "smtp" in self.email_backend and not self._smtp_is_configured:
            logger.error(
                "Email is not configured for production sending. RESEND_API_KEY is missing, and SMTP backend %s has no EMAIL_HOST_USER/EMAIL_HOST_PASSWORD. Set RESEND_API_KEY or valid SMTP credentials.",
                self.email_backend,
            )
            return False

        return self._send_via_django(to, subject, html_body, text_body, reply_to=reply_to)

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
        reply_to: Optional[str] = None,
    ) -> bool:
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body or "Please view this email in an HTML-capable client.",
                from_email=self._from_address,
                to=to,
            )
            if reply_to:
                msg.reply_to = [reply_to]
            if html_body:
                msg.attach_alternative(html_body, "text/html")
            msg.send()
            logger.info("SMTP (%s): sent to %s", self.email_backend, to)
            return True
        except Exception as exc:
            logger.error("SMTP (%s): failed to send to %s - %s", self.email_backend, to, exc)
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
    if not user.email:
        logger.warning("send_password_reset_email: user %s has no email address", user.username)
        return False

    context = _build_branding_context(user, school)
    context["reset_url"] = reset_url

    try:
        html_body = render_to_string("emails/password_reset.html", context)
        text_body = render_to_string("emails/password_reset.txt", context)
    except Exception as exc:
        logger.error("send_password_reset_email: template render error - %s", exc)
        return False

    service = ResendEmailService()
    return service.send(
        to=[user.email],
        subject=f"Password Reset Request - {context['school_name']}",
        html_body=html_body,
        text_body=text_body,
    )


def send_password_reset_success_email(user, login_url: str = "", school=None) -> bool:
    """Send a confirmation email after a password has been reset successfully."""
    if not user.email:
        logger.warning("send_password_reset_success_email: user %s has no email address", user.username)
        return False

    context = _build_branding_context(user, school)
    context["login_url"] = login_url

    try:
        html_body = render_to_string("emails/password_reset_success.html", context)
        text_body = render_to_string("emails/password_reset_success.txt", context)
    except Exception as exc:
        logger.error("send_password_reset_success_email: template render error - %s", exc)
        return False

    service = ResendEmailService()
    return service.send(
        to=[user.email],
        subject=f"Password Changed Successfully - {context['school_name']}",
        html_body=html_body,
        text_body=text_body,
    )


def _build_signup_request_email_context(signup_request) -> dict[str, object]:
    from datetime import datetime

    context: dict[str, object] = {
        "user_name": signup_request.first_name,
        "school_name": signup_request.school_name,
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@ezyschool.app"),
        "current_year": datetime.now().year,
        "product_name": "EzySchool",
        "dev_name": "DewX IT Solutions",
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

    return context


def _format_signup_request_admin_text(signup_request) -> str:
    frontend = getattr(settings, "FRONTEND_DOMAIN", "").rstrip("/")
    review_path = f"/admin/signup-requests/{signup_request.pk}"
    review_url = f"{frontend}{review_path}" if frontend else review_path

    return (
        f"A new school signup request has been submitted on EzySchool.\n\n"
        f"{'─' * 40}\n"
        f"CONTACT\n"
        f"  Name:     {signup_request.first_name} {signup_request.last_name}\n"
        f"  Email:    {signup_request.email}\n"
        f"  Phone:    {signup_request.phone or '—'}\n"
        f"\nSCHOOL\n"
        f"  School:   {signup_request.school_name}\n"
        f"  Role:     {signup_request.role_title}\n"
        f"  Country:  {signup_request.country}\n"
        f"  Students: {signup_request.students_count}\n"
        f"\nPREFERENCES\n"
        f"  Workspace: {signup_request.workspace_slug or '—'}\n"
        f"  Plan:      {signup_request.plan or '—'}\n"
        f"  Notes:     {signup_request.notes or '—'}\n"
        f"{'─' * 40}\n"
        f"Submitted at: {signup_request.submitted_at.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"Review in admin portal:\n{review_url}\n"
    )


def send_signup_request_confirmation_email(signup_request) -> bool:
    """Send a receipt email to the person who submitted the marketing signup form."""
    if not signup_request.email:
        logger.warning("send_signup_request_confirmation_email: missing submitter email")
        return False

    context = _build_signup_request_email_context(signup_request)

    try:
        html_body = render_to_string("emails/signup_request_confirmation.html", context)
        text_body = render_to_string("emails/signup_request_confirmation.txt", context)
    except Exception as exc:
        logger.error("send_signup_request_confirmation_email: template render error - %s", exc)
        return False

    service = ResendEmailService()
    return service.send(
        to=[signup_request.email],
        subject="We received your EzySchool signup request",
        html_body=html_body,
        text_body=text_body,
    )


def send_contact_inquiry_emails(*, name: str, email: str, school_name: str, topic: str, message: str) -> bool:
    """Notify admin and send receipt for a marketing contact form submission."""
    admin_email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "admin@dewx.tech")
    support_email = getattr(settings, "SUPPORT_EMAIL", "support@ezyschool.app")
    topic_labels = {
        "general": "General question",
        "sales": "Sales & pricing",
        "support": "Existing customer support",
        "migration": "Data migration",
    }
    topic_label = topic_labels.get(topic, topic)
    school_line = school_name.strip() or "—"

    admin_text = (
        f"New EzySchool contact form message\n\n"
        f"Name:   {name}\n"
        f"Email:  {email}\n"
        f"School: {school_line}\n"
        f"Topic:  {topic_label}\n\n"
        f"Message:\n{message}\n"
    )
    receipt_text = (
        f"Hi {name},\n\n"
        f"Thanks for contacting EzySchool. We received your message about "
        f"{topic_label.lower()} and will reply within one business day.\n\n"
        f"Your message:\n{message}\n\n"
        f"If you need urgent help, email {support_email}.\n"
    )

    service = ResendEmailService()
    admin_ok = service.send(
        to=[admin_email],
        subject=f"[EzySchool] Contact — {topic_label}",
        text_body=admin_text,
        reply_to=email,
    )
    receipt_ok = service.send(
        to=[email],
        subject="We received your message — EzySchool",
        text_body=receipt_text,
    )
    return admin_ok and receipt_ok


def send_signup_request_admin_notification_email(signup_request) -> bool:
    """Notify the platform admin team about a new marketing signup request."""
    admin_email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "admin@dewx.tech")
    if not admin_email:
        logger.warning("send_signup_request_admin_notification_email: ADMIN_NOTIFICATION_EMAIL is not set")
        return False

    text_body = _format_signup_request_admin_text(signup_request)
    service = ResendEmailService()
    return service.send(
        to=[admin_email],
        subject=f"[EzySchool] New Signup Request — {signup_request.school_name}",
        text_body=text_body,
        reply_to=signup_request.email,
    )


def send_billing_reminder_email(
    *,
    to: list[str],
    subject: str,
    tenant,
    context: dict,
) -> bool:
    """Email tenant admins about subscription billing milestones."""
    if not to:
        return False

    reminder_type = context.get("reminder_type", "")
    school_name = context.get("school_name") or getattr(tenant, "name", "your school")
    billing_url = context.get("billing_url", "")

    if reminder_type == "complimentary_ending":
        days = context.get("days_remaining", "")
        end_date = context.get("end_date", "")
        headline = f"Complimentary access ends in {days} days"
        body_text = (
            f"Complimentary EzySchool access for {school_name} ends on {end_date} "
            f"({days} days from now). Set up billing now to avoid interruption."
        )
    elif reminder_type == "subscription_renewal":
        days = context.get("days_remaining", "")
        end_date = context.get("end_date", "")
        headline = f"Subscription renews in {days} days"
        body_text = (
            f"Your EzySchool subscription for {school_name} renews on {end_date}. "
            "Review your plan and payment method before renewal."
        )
    elif reminder_type == "past_due":
        days = context.get("days_overdue", 0)
        if context.get("in_grace"):
            headline = "Payment overdue — workspace is read-only"
            body_text = (
                f"Payment for {school_name} is {days} day(s) overdue. "
                "Non-admin users currently have read-only access until billing is resolved."
            )
        else:
            headline = "Payment failed — action required"
            body_text = (
                f"We could not process the latest payment for {school_name}. "
                "Update your billing details to avoid service interruption."
            )
    else:
        headline = "Billing reminder"
        body_text = f"Your EzySchool billing for {school_name} needs attention."

    email_context = {
        "headline": headline,
        "body_text": body_text,
        "billing_url": billing_url,
        "school_name": school_name,
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@ezyschool.app"),
        "logo_url": getattr(settings, "EMAIL_LOGO_URL", ""),
    }

    try:
        html_body = render_to_string("emails/billing_reminder.html", email_context)
        text_body = render_to_string("emails/billing_reminder.txt", email_context)
    except Exception as exc:
        logger.error("send_billing_reminder_email: template render error - %s", exc)
        return False

    service = ResendEmailService()
    return service.send(to=to, subject=subject, html_body=html_body, text_body=text_body)


def send_notification_email(
    user,
    subject: str,
    body: str,
    category: str = "announcement",
    school=None,
    action_url: str = "",
) -> bool:
    """Send a school notification/announcement email to a user."""
    if not user.email or str(user.email).endswith("@local.user"):
        logger.info(
            "send_notification_email: skipping user %s due to missing/placeholder email",
            getattr(user, "username", user.pk),
        )
        return False

    context = _build_branding_context(user, school)
    context["subject"] = subject
    context["body"] = body
    context["category"] = category
    context["action_url"] = action_url or context.get("school_website", "")

    try:
        html_body = render_to_string("emails/notifications/announcement.html", context)
        text_body = render_to_string("emails/notifications/announcement.txt", context)
    except Exception as exc:
        logger.error("send_notification_email: template render error - %s", exc)
        text_body = f"{subject}\n\n{body}\n"
        html_body = None

    service = ResendEmailService()
    return service.send(
        to=[user.email],
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )


def send_tenant_onboarding_email(
    user,
    tenant,
    temporary_password: str = "",
    login_url: str = "",
    workspace_url: str = "",
    *,
    existing_account: bool = False,
) -> bool:
    """Send onboarding email to the tenant admin after workspace provisioning completes."""
    if not user.email or str(user.email).endswith("@local.user"):
        logger.info(
            "send_tenant_onboarding_email: skipping user %s due to missing/placeholder email",
            user.username,
        )
        return False

    context = _build_branding_context(user, tenant)
    context["username"] = user.username
    context["temporary_password"] = temporary_password
    context["existing_account"] = existing_account
    context["login_url"] = login_url or context.get("school_website", "")
    context["workspace_name"] = getattr(tenant, "schema_name", "")
    context["workspace_url"] = workspace_url or context["login_url"]

    try:
        html_body = render_to_string("emails/tenant_onboarding.html", context)
        text_body = render_to_string("emails/tenant_onboarding.txt", context)
    except Exception as exc:
        logger.error("send_tenant_onboarding_email: template render error - %s", exc)
        return False

    service = ResendEmailService()
    return service.send(
        to=[user.email],
        subject=f"Welcome to {context['school_name']} - Your Workspace Is Ready",
        html_body=html_body,
        text_body=text_body,
    )


def send_account_created_email(
    user,
    temporary_password: str,
    login_url: str = "",
    school=None,
) -> bool:
    """Send a welcome email with initial login instructions for a newly created account."""
    if not user.email or user.email.endswith("@local.user"):
        logger.info(
            "send_account_created_email: skipping user %s due to missing/placeholder email",
            user.username,
        )
        return False

    context = _build_branding_context(user, school)
    context["username"] = user.username
    context["temporary_password"] = temporary_password
    context["login_url"] = login_url or context.get("school_website", "")

    try:
        html_body = render_to_string("emails/account_created.html", context)
        text_body = render_to_string("emails/account_created.txt", context)
    except Exception as exc:
        logger.error("send_account_created_email: template render error - %s", exc)
        return False

    service = ResendEmailService()
    return service.send(
        to=[user.email],
        subject=f"Welcome to {context['school_name']} - Your Account Is Ready",
        html_body=html_body,
        text_body=text_body,
    )