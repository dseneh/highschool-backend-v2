"""Check or register the exact callback for the global Parent workspace."""
import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import URLValidator
from django.db import transaction
from django_tenants.utils import get_public_schema_name, schema_context


def parent_callback(origin):
    try:
        parsed = urlsplit(origin)
        URLValidator(schemes=["https", "http"])(origin)
        port = parsed.port
    except (ValueError, ValidationError):
        raise CommandError("Provide a valid parent origin, such as https://parent.example.com.")
    host = parsed.hostname or ""
    local = host == "parent.localhost" or host == "parent.lvh.me"
    if (not host.startswith("parent.") or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
            or (parsed.scheme != "https" and not local)
            or (port and port != 443 and not local)):
        raise CommandError("Use an HTTPS parent subdomain origin without a path, credentials, query, or fragment. HTTP/custom ports are allowed only for local development.")
    authority = host + (f":{port}" if port else "")
    return f"{parsed.scheme}://{authority}/auth/callback"


def school_callback(origin, slug):
    parent = urlsplit(parent_callback(origin))
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", slug) or slug in {"parent", "auth", "public", "admin", "api", "www"}:
        raise CommandError(f"School workspace {slug!r} is not a valid school subdomain.")
    root = parent.netloc.removeprefix("parent.")
    return f"{parent.scheme}://{slug}.{root}/auth/callback"


class Command(BaseCommand):
    help = "Check parent workspace prerequisites; --apply registers its exact OAuth callback."

    def add_arguments(self, parser):
        parser.add_argument("--origin", required=True)
        parser.add_argument("--client-id", default="ezyschool-web")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--include-schools", action="store_true", help="Also register exact callbacks for active school workspace subdomains under this same root.")

    @transaction.atomic
    def handle(self, *args, **options):
        from core.models import Tenant
        from users.models import OAuthClient, OAuthRedirectURI

        callback = parent_callback(options["origin"])
        with schema_context(get_public_schema_name()):
            if Tenant.objects.filter(schema_name="parent").exists():
                raise CommandError("A school already uses the reserved parent workspace name. Resolve this collision before rollout.")
            if not Tenant.objects.filter(schema_name=get_public_schema_name(), active=True, status="active").exists():
                raise CommandError("An active public tenant is required. Configure it before parent rollout.")
            client = OAuthClient.objects.filter(client_id=options["client_id"]).first()
            if client and (not client.is_active or not client.require_pkce):
                raise CommandError("The OAuth client must be active and require PKCE. Review its configuration explicitly.")
            callbacks = [callback]
            if options["include_schools"]:
                schools = Tenant.objects.filter(active=True, status="active").exclude(schema_name=get_public_schema_name())
                callbacks.extend(school_callback(options["origin"], slug) for slug in schools.order_by("schema_name").values_list("schema_name", flat=True))
            # Validate the entire set before writing anything. Never reactivate disabled callbacks.
            for uri in callbacks:
                if client and OAuthRedirectURI.objects.filter(client=client, redirect_uri=uri, is_active=False).exists():
                    raise CommandError(f"This callback was disabled: {uri}. Review that decision before re-enabling it.")
            if options["apply"] and not client:
                client = OAuthClient.objects.create(client_id=options["client_id"], name="EzySchool Web", require_pkce=True)
            for uri in callbacks:
                redirect = OAuthRedirectURI.objects.filter(client=client, redirect_uri=uri).first() if client else None
                if options["apply"]:
                    OAuthRedirectURI.objects.get_or_create(client=client, redirect_uri=uri)
                state = "Registered" if options["apply"] else "Ready" if redirect else "Would register"
                self.stdout.write(f"{state}: {uri} (client {options['client_id']})")
            self.stdout.write("DNS, TLS, frontend environment, and email delivery must be verified separately.")
