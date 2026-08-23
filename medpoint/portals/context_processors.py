from website.models import Booking, ContactMessage, StaffLeave
from .models import StaffNotification


def portal_counts(request):
    """Provide sidebar badge counts for the portal navigation."""
    if request.user.is_authenticated and request.user.is_staff:
        # Notification count based on role
        role = request.session.get('portal_role', 'staff')
        if role == 'admin':
            notif_count = StaffNotification.objects.filter(
                is_read=False, target_role__in=['admin', 'all']
            ).count()
        else:
            from django.db.models import Q
            notif_qs = StaffNotification.objects.filter(
                is_read=False, target_role__in=['staff', 'all']
            )
            # Scope to this therapist if they have a profile
            if hasattr(request.user, 'therapist_profile') and request.user.therapist_profile:
                notif_qs = notif_qs.filter(
                    Q(target_therapist=request.user.therapist_profile) |
                    Q(target_therapist__isnull=True)
                )
            else:
                notif_qs = notif_qs.filter(target_therapist__isnull=True)
            notif_count = notif_qs.count()

        return {
            'pending_bookings_count': Booking.objects.filter(status='pending').count(),
            'unread_messages_count': ContactMessage.objects.filter(is_read=False).count(),
            'unread_notifications_count': notif_count,
            'pending_leaves_count': StaffLeave.objects.filter(status='pending').count() if role == 'admin' else 0,
        }
    return {}

