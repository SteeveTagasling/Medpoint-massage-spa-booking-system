from django.db import models
from django.conf import settings

class AdminProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_profile')
    photo = models.ImageField(upload_to='admin_photos/', blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - Admin Profile"


class StaffNotification(models.Model):
    """Notifications for admin and staff portal users."""
    TYPE_CHOICES = [
        ('new_booking', 'New Booking'),
        ('booking_cancelled', 'Booking Cancelled'),
        ('booking_status', 'Booking Status Changed'),
        ('new_message', 'New Contact Message'),
        ('schedule_update', 'Schedule Updated'),
        ('system', 'System Notification'),
    ]

    TARGET_CHOICES = [
        ('admin', 'Admin Only'),
        ('staff', 'Staff Only'),
        ('all', 'Everyone'),
    ]

    ICON_MAP = {
        'new_booking': 'fa-calendar-plus',
        'booking_cancelled': 'fa-calendar-times',
        'booking_status': 'fa-calendar-check',
        'new_message': 'fa-envelope-open',
        'schedule_update': 'fa-clock',
        'system': 'fa-bell',
    }

    COLOR_MAP = {
        'new_booking': 'purple',
        'booking_cancelled': 'red',
        'booking_status': 'blue',
        'new_message': 'green',
        'schedule_update': 'amber',
        'system': 'purple',
    }

    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system')
    title = models.CharField(max_length=200)
    message = models.TextField()
    target_role = models.CharField(max_length=10, choices=TARGET_CHOICES, default='all')
    # Optional: link a notification to a specific therapist (for staff-specific notifications)
    target_therapist = models.ForeignKey(
        'website.Therapist', on_delete=models.CASCADE,
        null=True, blank=True, related_name='portal_notifications'
    )
    link = models.CharField(max_length=300, blank=True, help_text="Optional URL to link to when clicked")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_notification_type_display()}] {self.title}"

    @property
    def icon_class(self):
        return self.ICON_MAP.get(self.notification_type, 'fa-bell')

    @property
    def color(self):
        return self.COLOR_MAP.get(self.notification_type, 'purple')

    @property
    def time_ago(self):
        """Return a human-readable time-ago string."""
        from django.utils import timezone
        now = timezone.now()
        diff = now - self.created_at
        seconds = diff.total_seconds()
        if seconds < 60:
            return 'Just now'
        elif seconds < 3600:
            mins = int(seconds // 60)
            return f'{mins}m ago'
        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f'{hours}h ago'
        elif seconds < 604800:
            days = int(seconds // 86400)
            return f'{days}d ago'
        else:
            return self.created_at.strftime('%b %d, %Y')
