from django.db import transaction
from django.db.models import Max, Prefetch
from django.utils import timezone

from school_website.models import (
    WebsiteNavigationItem,
    WebsitePage,
    WebsiteRevision,
    WebsiteSection,
    WebsiteSettings,
)

DEFAULT_PAGES = (
    ("Home", "home", WebsitePage.PageType.HOME),
    ("About", "about", WebsitePage.PageType.STANDARD),
    ("Admissions", "admissions", WebsitePage.PageType.ADMISSIONS),
    ("Contact", "contact", WebsitePage.PageType.CONTACT),
)


def _nested_value(data, *paths):
    for path in paths:
        value = data
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def tenant_website_defaults(tenant):
    """Derive public identity from the tenant instead of duplicating it in website settings."""
    theme = tenant.theme_config or {}
    primary = tenant.theme_color or _nested_value(
        theme,
        ("primary_color",),
        ("primary",),
        ("colors", "primary"),
        ("palette", "primary"),
    )
    logo = tenant.logo.url if getattr(tenant, "logo", None) else ""
    address = ", ".join(
        str(value).strip()
        for value in (
            tenant.address,
            tenant.city,
            tenant.state,
            tenant.country,
            tenant.postal_code,
        )
        if value
    )
    name = tenant.name
    return {
        "design_tokens": {
            "school_name": name,
            "short_name": tenant.short_name or name,
            "slogan": tenant.slogan or "",
            "description": tenant.description or "",
            "logo_url": logo,
            "primary_color": primary or "#173f35",
        },
        "contact": {
            "email": tenant.email or "",
            "phone": tenant.phone or "",
            "address": address,
        },
        "seo": {
            "title": name,
            "description": tenant.description or tenant.slogan or f"Welcome to {name}.",
        },
    }


@transaction.atomic
def ensure_default_website(*, tenant, user=None):
    """Create a minimal starter website once, when an entitled tenant first opens the editor."""
    defaults = tenant_website_defaults(tenant)
    settings, _created = WebsiteSettings.objects.get_or_create(
        key="default",
        defaults={
            "seo_defaults": defaults["seo"],
            "admissions_cta": {"label": "Apply now"},
            "created_by": user,
            "updated_by": user,
        },
    )
    if WebsitePage.objects.exists():
        return settings

    pages = {}
    for position, (title, slug, page_type) in enumerate(DEFAULT_PAGES):
        pages[slug] = WebsitePage.objects.create(
            title=title,
            slug=slug,
            page_type=page_type,
            navigation_visible=True,
            navigation_order=position,
            created_by=user,
            updated_by=user,
        )

    school_name = defaults["design_tokens"]["school_name"]
    WebsiteSection.objects.bulk_create(
        [
            WebsiteSection(
                page=pages["home"],
                block_type="hero",
                position=0,
                content={
                    "eyebrow": "Welcome",
                    "title": defaults["design_tokens"]["slogan"]
                    or f"Welcome to {school_name}",
                    "body": defaults["design_tokens"]["description"]
                    or "A place to learn, belong, and thrive.",
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["about"],
                block_type="about",
                position=0,
                content={
                    "title": f"About {school_name}",
                    "body": defaults["design_tokens"]["description"]
                    or "Share your school's story, mission, and community.",
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["admissions"],
                block_type="admissions",
                position=0,
                content={
                    "title": "Admissions",
                    "body": "Learn how to join our school community.",
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["contact"],
                block_type="contact",
                position=0,
                content={
                    "title": "Contact us",
                    "body": "We would be glad to hear from you.",
                },
                created_by=user,
                updated_by=user,
            ),
        ]
    )
    WebsiteNavigationItem.objects.bulk_create(
        [
            WebsiteNavigationItem(
                label=title,
                destination_type=WebsiteNavigationItem.DestinationType.PAGE,
                page=pages[slug],
                position=position,
                created_by=user,
                updated_by=user,
            )
            for position, (title, slug, _page_type) in enumerate(DEFAULT_PAGES)
        ]
    )
    return settings


def build_website_snapshot(*, tenant):
    settings = WebsiteSettings.get_solo()
    tenant_defaults = tenant_website_defaults(tenant)
    pages = WebsitePage.objects.filter(active=True).prefetch_related(
        Prefetch("sections", queryset=WebsiteSection.objects.filter(active=True))
    )
    return {
        "enabled": True,
        "published": True,
        "template": settings.template,
        "design_tokens": {**settings.design_tokens, **tenant_defaults["design_tokens"]},
        "seo_defaults": {**settings.seo_defaults, **tenant_defaults["seo"]},
        "contact_overrides": {
            **settings.contact_overrides,
            **tenant_defaults["contact"],
        },
        "social_links": settings.social_links,
        "admissions_cta": settings.admissions_cta,
        "pages": [
            {
                "id": str(page.id),
                "title": page.title,
                "slug": page.slug,
                "page_type": page.page_type,
                "navigation_visible": page.navigation_visible,
                "navigation_order": page.navigation_order,
                "seo": page.seo,
                "sections": [
                    {
                        "id": str(section.id),
                        "block_type": section.block_type,
                        "position": section.position,
                        "variant": section.variant,
                        "content": section.content,
                    }
                    for section in page.sections.all()
                ],
            }
            for page in pages
        ],
        "navigation": [
            {
                "id": str(item.id),
                "label": item.label,
                "destination_type": item.destination_type,
                "page_id": str(item.page_id) if item.page_id else None,
                "url": item.url,
                "parent_id": str(item.parent_id) if item.parent_id else None,
                "position": item.position,
            }
            for item in WebsiteNavigationItem.objects.filter(active=True)
        ],
    }


def public_website_fallback(*, tenant, enabled):
    defaults = tenant_website_defaults(tenant)
    return {
        "enabled": enabled,
        "published": False,
        "template": WebsiteSettings.Template.MODERN,
        "design_tokens": defaults["design_tokens"],
        "seo_defaults": defaults["seo"],
        "contact_overrides": defaults["contact"],
        "social_links": [],
        "admissions_cta": {"label": "Apply now"},
        "pages": [],
        "navigation": [],
    }


def published_website_snapshot(*, tenant, snapshot):
    defaults = tenant_website_defaults(tenant)
    return {
        **snapshot,
        "enabled": True,
        "published": True,
        "design_tokens": {
            **snapshot.get("design_tokens", {}),
            **defaults["design_tokens"],
        },
        "seo_defaults": {**snapshot.get("seo_defaults", {}), **defaults["seo"]},
        "contact_overrides": {
            **snapshot.get("contact_overrides", {}),
            **defaults["contact"],
        },
    }


@transaction.atomic
def publish_website(*, user, tenant, note=""):
    settings = ensure_default_website(tenant=tenant, user=user)
    settings = WebsiteSettings.objects.select_for_update().get(pk=settings.pk)
    next_number = (
        WebsiteRevision.objects.aggregate(value=Max("revision_number"))["value"] or 0
    ) + 1
    revision = WebsiteRevision.objects.create(
        revision_number=next_number,
        snapshot=build_website_snapshot(tenant=tenant),
        note=note,
        created_by=user,
        updated_by=user,
    )
    settings.published_revision = revision
    settings.published_at = timezone.now()
    settings.updated_by = user
    settings.save(
        update_fields=["published_revision", "published_at", "updated_by", "updated_at"]
    )
    return revision
