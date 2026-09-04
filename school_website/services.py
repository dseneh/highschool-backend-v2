from django.db import transaction
from django.db.models import Max, Prefetch
from django.utils import timezone

from school_website.models import WebsiteNavigationItem, WebsitePage, WebsiteRevision, WebsiteSection, WebsiteSettings


def build_website_snapshot():
    settings = WebsiteSettings.get_solo()
    pages = WebsitePage.objects.filter(active=True).prefetch_related(
        Prefetch("sections", queryset=WebsiteSection.objects.filter(active=True))
    )
    return {
        "template": settings.template,
        "design_tokens": settings.design_tokens,
        "seo_defaults": settings.seo_defaults,
        "contact_overrides": settings.contact_overrides,
        "social_links": settings.social_links,
        "admissions_cta": settings.admissions_cta,
        "pages": [{
            "id": str(page.id), "title": page.title, "slug": page.slug,
            "page_type": page.page_type, "navigation_visible": page.navigation_visible,
            "navigation_order": page.navigation_order, "seo": page.seo,
            "sections": [{
                "id": str(section.id), "block_type": section.block_type,
                "position": section.position, "variant": section.variant,
                "content": section.content,
            } for section in page.sections.all()],
        } for page in pages],
        "navigation": [{
            "id": str(item.id), "label": item.label,
            "destination_type": item.destination_type,
            "page_id": str(item.page_id) if item.page_id else None,
            "url": item.url, "parent_id": str(item.parent_id) if item.parent_id else None,
            "position": item.position,
        } for item in WebsiteNavigationItem.objects.filter(active=True)],
    }


@transaction.atomic
def publish_website(*, user, note=""):
    settings, _created = WebsiteSettings.objects.get_or_create(
        key="default", defaults={"created_by": user, "updated_by": user}
    )
    settings = WebsiteSettings.objects.select_for_update().get(pk=settings.pk)
    next_number = (WebsiteRevision.objects.aggregate(value=Max("revision_number"))["value"] or 0) + 1
    revision = WebsiteRevision.objects.create(
        revision_number=next_number, snapshot=build_website_snapshot(), note=note,
        created_by=user, updated_by=user,
    )
    settings.published_revision = revision
    settings.published_at = timezone.now()
    settings.updated_by = user
    settings.save(update_fields=["published_revision", "published_at", "updated_by", "updated_at"])
    return revision
