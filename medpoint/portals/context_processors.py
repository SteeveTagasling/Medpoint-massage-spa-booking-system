from website.models import Booking, ContactMessage


def portal_counts(request):
    """Provide sidebar badge counts for the portal navigation."""
    if request.user.is_authenticated and request.user.is_staff:
        return {
            'pending_bookings_count': Booking.objects.filter(status='pending').count(),
            'unread_messages_count': ContactMessage.objects.filter(is_read=False).count(),
        }
    return {}
