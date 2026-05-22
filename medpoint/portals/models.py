from django.db import models
from django.conf import settings

class AdminProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_profile')
    photo = models.ImageField(upload_to='admin_photos/', blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - Admin Profile"
