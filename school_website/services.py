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
    ("Academics", "academics", WebsitePage.PageType.STANDARD),
    ("Student Life", "student-life", WebsitePage.PageType.STANDARD),
    ("Admissions", "admissions", WebsitePage.PageType.ADMISSIONS),
    ("Contact", "contact", WebsitePage.PageType.CONTACT),
)

DEFAULT_HERO_IMAGE = "/website-defaults/campus-hero.webp"
DEFAULT_ACADEMICS_IMAGE = "/website-defaults/science-class.webp"
DEFAULT_STUDENT_LIFE_IMAGE = "/website-defaults/student-life.webp"


def rich_text_document(*paragraphs):
    return {
        "type": "doc",
        "content": [
            {
                "type": "element",
                "tag": "p",
                "children": [{"type": "text", "text": paragraph}],
            }
            for paragraph in paragraphs
            if paragraph
        ],
    }


def reordered_items(items, item, target_index):
    ordered = list(items)
    current_index = ordered.index(item)
    bounded_index = max(0, min(target_index, len(ordered) - 1))
    if current_index == bounded_index:
        return ordered
    ordered.pop(current_index)
    ordered.insert(bounded_index, item)
    return ordered


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
    school_description = defaults["design_tokens"]["description"] or (
        f"{school_name} is committed to helping every learner grow in knowledge, "
        "character, confidence, and service."
    )
    contact = defaults["contact"]
    contact_summary = " · ".join(
        value
        for value in (contact["address"], contact["phone"], contact["email"])
        if value
    )
    WebsiteSection.objects.bulk_create(
        [
            WebsiteSection(
                page=pages["home"],
                block_type="hero",
                position=0,
                content={
                    "eyebrow": school_name,
                    "title": defaults["design_tokens"]["slogan"]
                    or "Learning today. Leading tomorrow.",
                    "rich_text": rich_text_document(school_description),
                    "image_url": DEFAULT_HERO_IMAGE,
                    "image_alt": f"Students arriving at {school_name}",
                    "primary_label": "Apply for admission",
                    "primary_url": "/admissions/apply",
                    "secondary_label": "Discover our school",
                    "secondary_url": "/about",
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["home"],
                block_type="programs",
                position=1,
                content={
                    "title": "An education built for the whole student",
                    "rich_text": rich_text_document(
                        "Strong academics, meaningful relationships, and opportunities to "
                        "lead help students prepare for school, work, and life."
                    ),
                    "items": [
                        {
                            "title": "Academic excellence",
                            "description": "Purposeful teaching builds strong foundations, curiosity, and independent thinking.",
                            "image_url": DEFAULT_ACADEMICS_IMAGE,
                        },
                        {
                            "title": "Character and leadership",
                            "description": "Students learn responsibility, teamwork, integrity, and service to their community.",
                            "image_url": DEFAULT_STUDENT_LIFE_IMAGE,
                        },
                        {
                            "title": "A supportive community",
                            "description": "Families, educators, and students work together so every learner is known and encouraged.",
                            "image_url": DEFAULT_HERO_IMAGE,
                        },
                    ],
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["home"],
                block_type="admissions",
                position=2,
                content={
                    "title": f"Your journey at {school_name} starts here",
                    "rich_text": rich_text_document(
                        "Explore our school, learn what families can expect, and begin an online application when you are ready."
                    ),
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["about"],
                block_type="hero",
                position=0,
                content={
                    "eyebrow": "About our school",
                    "title": f"About {school_name}",
                    "rich_text": rich_text_document(school_description),
                    "image_url": DEFAULT_HERO_IMAGE,
                    "image_alt": f"The {school_name} campus community",
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["about"],
                block_type="mission_vision_values",
                position=1,
                content={
                    "title": "What guides us",
                    "rich_text": rich_text_document(
                        "Our shared commitments shape how students learn, how educators teach, and how our community grows together."
                    ),
                    "items": [
                        {
                            "title": "Mission",
                            "description": f"To help every {school_name} student learn deeply, act with integrity, and contribute with purpose.",
                        },
                        {
                            "title": "Vision",
                            "description": "A confident community of lifelong learners prepared to lead positive change.",
                        },
                        {
                            "title": "Values",
                            "description": "Excellence, respect, responsibility, compassion, and service.",
                        },
                    ],
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["academics"],
                block_type="hero",
                position=0,
                content={
                    "eyebrow": "Academics",
                    "title": "Learning with purpose",
                    "rich_text": rich_text_document(
                        "Students build essential knowledge and practical skills through thoughtful instruction, collaboration, and discovery."
                    ),
                    "image_url": DEFAULT_ACADEMICS_IMAGE,
                    "image_alt": "Students learning together in a science classroom",
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["academics"],
                block_type="programs",
                position=1,
                content={
                    "title": "A balanced learning experience",
                    "items": [
                        {
                            "title": "Core academics",
                            "description": "Clear learning goals and strong foundations in language, mathematics, science, and social studies.",
                        },
                        {
                            "title": "Creative development",
                            "description": "Opportunities for expression, communication, problem-solving, and original thinking.",
                        },
                        {
                            "title": "Life and leadership skills",
                            "description": "Experiences that strengthen collaboration, confidence, responsibility, and service.",
                        },
                    ],
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["student-life"],
                block_type="hero",
                position=0,
                content={
                    "eyebrow": "Student life",
                    "title": "A place to belong and grow",
                    "rich_text": rich_text_document(
                        "Learning continues beyond the classroom through friendships, activities, teamwork, and service."
                    ),
                    "image_url": DEFAULT_STUDENT_LIFE_IMAGE,
                    "image_alt": "Students enjoying an outdoor school activity",
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["student-life"],
                block_type="gallery",
                position=1,
                content={
                    "title": "Life in our community",
                    "items": [
                        {
                            "url": DEFAULT_HERO_IMAGE,
                            "alt": "Students walking together on campus",
                            "caption": "A welcoming school community",
                        },
                        {
                            "url": DEFAULT_ACADEMICS_IMAGE,
                            "alt": "Students conducting a classroom experiment",
                            "caption": "Curiosity in action",
                        },
                        {
                            "url": DEFAULT_STUDENT_LIFE_IMAGE,
                            "alt": "Students playing football outdoors",
                            "caption": "Teamwork beyond the classroom",
                        },
                    ],
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["admissions"],
                block_type="hero",
                position=0,
                content={
                    "eyebrow": "Admissions",
                    "title": f"Join the {school_name} community",
                    "rich_text": rich_text_document(
                        "We want the application process to be clear and welcoming. Start online, track your request, and communicate with the school in one place."
                    ),
                    "image_url": DEFAULT_HERO_IMAGE,
                    "image_alt": f"Students at {school_name}",
                    "primary_label": "Start your application",
                    "primary_url": "/admissions/apply",
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["admissions"],
                block_type="admissions",
                position=1,
                content={
                    "title": "A simple application process",
                    "rich_text": rich_text_document(
                        "Choose the appropriate admission cycle, complete the student and guardian information, upload any requested documents, and submit your application.",
                        "You will receive a request ID so you can securely follow progress and respond if the school needs more information.",
                    ),
                },
                created_by=user,
                updated_by=user,
            ),
            WebsiteSection(
                page=pages["admissions"],
                block_type="faq",
                position=2,
                content={
                    "title": "Admissions questions",
                    "items": [
                        {
                            "question": "How do I begin?",
                            "answer": "Select Start your application and follow the guided online steps.",
                        },
                        {
                            "question": "Can returning students register online?",
                            "answer": "Yes. Sign in to the school portal and choose the returning-student registration option.",
                        },
                        {
                            "question": "How will I receive updates?",
                            "answer": "Use your request workspace to view status changes, messages, and information requests from the school.",
                        },
                    ],
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
                    "rich_text": rich_text_document(
                        f"We would be glad to hear from you. {contact_summary}"
                        if contact_summary
                        else "We would be glad to hear from you. Contact the school office for assistance."
                    ),
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
