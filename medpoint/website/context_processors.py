from django.db import OperationalError, ProgrammingError

from .models import ServiceCategory, SiteContent, WebsitePolicyItem
from .site_content import SITE_CONTENT_DEFAULTS


def site_content(request):
    """Make editable website content available to every template."""
    values = SITE_CONTENT_DEFAULTS.copy()
    footer_service_categories = []
    policy_items = {
        WebsitePolicyItem.SECTION_BOOKING: [],
        WebsitePolicyItem.SECTION_PRIVACY: [],
        WebsitePolicyItem.SECTION_TERMS: [],
    }
    try:
        values.update(dict(SiteContent.objects.values_list('key', 'value')))
        footer_service_categories = list(
            ServiceCategory.objects.filter(is_active=True).order_by('order', 'name')
        )
        for item in WebsitePolicyItem.objects.all():
            policy_items[item.section].append(item)
    except (OperationalError, ProgrammingError):
        # Allows deploys to render safely while the new migration is pending.
        pass
    return {
        'site_content': values,
        'footer_service_categories': footer_service_categories,
        'booking_policy_items': policy_items[WebsitePolicyItem.SECTION_BOOKING],
        'privacy_policy_items': policy_items[WebsitePolicyItem.SECTION_PRIVACY],
        'terms_condition_items': policy_items[WebsitePolicyItem.SECTION_TERMS],
    }
