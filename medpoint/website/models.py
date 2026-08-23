from django.db import models
from django.utils import timezone


class Service(models.Model):
    """Spa service/treatment model."""
    CATEGORY_CHOICES = [
        ('massage', 'Massage'),
        ('facial', 'Facial'),
        ('body', 'Body Treatment'),
        ('aromatherapy', 'Aromatherapy'),
        ('package', 'Package'),
    ]

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    category = models.CharField(max_length=200, default='massage', help_text="Comma-separated categories")
    description = models.TextField()
    short_description = models.CharField(max_length=300, blank=True)
    duration_minutes = models.PositiveIntegerField(help_text="Duration in minutes")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Discount percentage (0-100). Set > 0 when running a promo."
    )
    image = models.ImageField(upload_to='services/', blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @property
    def discounted_price(self):
        """Return price after discount."""
        if self.discount_percentage and self.discount_percentage > 0:
            discount = self.price * (self.discount_percentage / 100)
            return self.price - discount
        return self.price

    @property
    def has_discount(self):
        return self.discount_percentage and self.discount_percentage > 0

    @property
    def get_category_display(self):
        if not self.category:
            return ""
        codes = self.category.split(',')
        displays = dict(self.CATEGORY_CHOICES)
        return ', '.join(str(displays.get(c.strip(), c.strip())) for c in codes if c.strip())


from django.conf import settings

class Therapist(models.Model):
    """Spa therapist/staff model."""
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='therapist_profile')
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=100, help_text="e.g. Senior Massage Therapist")
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='female')
    bio = models.TextField()
    photo = models.ImageField(upload_to='therapists/', blank=True, null=True)
    specialties = models.ManyToManyField(Service, blank=True, related_name='therapists')
    years_experience = models.PositiveIntegerField(default=0)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    commission_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=30,
        help_text="Commission percentage per service (for salary calculation)"
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class StaffSchedule(models.Model):
    """Schedule assignment for therapists/staff."""
    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    therapist = models.ForeignKey(Therapist, on_delete=models.CASCADE, related_name='schedules')
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_available = models.BooleanField(default=True, help_text="Toggle availability for this slot")
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['therapist', 'day_of_week', 'start_time']
        unique_together = ['therapist', 'day_of_week', 'start_time']

    def __str__(self):
        return f"{self.therapist.name} — {self.get_day_of_week_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class StaffLeave(models.Model):
    """Leave assignments for therapists/staff."""
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    therapist = models.ForeignKey(Therapist, on_delete=models.CASCADE, related_name='leaves')
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    is_active = models.BooleanField(default=True, help_text="If false, this leave has been cancelled or ended")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.therapist.name} on leave {self.start_date} to {self.end_date}"



class Testimonial(models.Model):
    """Customer testimonial/review."""
    client_name = models.CharField(max_length=200)
    client_photo = models.ImageField(upload_to='testimonials/', blank=True, null=True)
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True)
    rating = models.PositiveIntegerField(choices=[(i, i) for i in range(1, 6)], default=5)
    content = models.TextField()
    is_featured = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.client_name} - {self.rating}★"


class GalleryImage(models.Model):
    """Spa gallery image."""
    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to='gallery/')
    caption = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-created_at']

    def __str__(self):
        return self.title


class Booking(models.Model):
    """Appointment booking model."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    BOOKING_TYPE_CHOICES = [
        ('online', 'Online'),
        ('walk_in', 'Walk-in'),
    ]

    TIME_CHOICES = [
        ('10:00', '10:00 AM'),
        ('11:00', '11:00 AM'),
        ('12:00', '12:00 PM'),
        ('13:00', '1:00 PM'),
        ('14:00', '2:00 PM'),
        ('15:00', '3:00 PM'),
        ('16:00', '4:00 PM'),
        ('17:00', '5:00 PM'),
        ('18:00', '6:00 PM'),
        ('19:00', '7:00 PM'),
        ('20:00', '8:00 PM'),
        ('21:00', '9:00 PM'),
        ('22:00', '10:00 PM'),
        ('23:00', '11:00 PM'),
        ('00:00', '12:00 MN'),
    ]

    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
    ]

    THERAPIST_PREF_CHOICES = [
        ('male', 'Male Therapist'),
        ('female', 'Female Therapist'),
        ('random', 'Any / Random'),
    ]

    booking_type = models.CharField(max_length=10, choices=BOOKING_TYPE_CHOICES, default='online')
    client_name = models.CharField(max_length=200)
    client_email = models.EmailField()
    client_phone = models.CharField(max_length=20)
    client_gender = models.CharField(
        max_length=10, choices=GENDER_CHOICES, default='male',
        help_text="Customer gender (affects therapist preference options)"
    )
    therapist_preference = models.CharField(
        max_length=10, choices=THERAPIST_PREF_CHOICES, default='random',
        help_text="Preferred therapist gender. Female clients can only select Female."
    )
    services = models.ManyToManyField(Service, related_name='bookings', help_text="Select one or more services")
    therapist = models.ForeignKey(Therapist, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    time = models.CharField(max_length=5, choices=TIME_CHOICES)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_verified = models.BooleanField(default=False, help_text="True if client verified their email OTP")
    verification_otp = models.CharField(max_length=6, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-time']

    def __str__(self):
        services_names = ", ".join([s.name for s in self.services.all()]) if self.pk else "New Booking"
        return f"{self.client_name} - {services_names} on {self.date}"

    @property
    def service_names(self):
        return ", ".join(s.name for s in self.services.all())
        
    @property
    def total_discounted_price(self):
        return sum(s.discounted_price for s in self.services.all())
        
    @property
    def total_duration_minutes(self):
        return sum(s.duration_minutes for s in self.services.all())


class BookingNotification(models.Model):
    """Notifications for booking status changes."""
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=[
        ('confirmed', 'Booking Confirmed'),
        ('cancelled', 'Booking Cancelled'),
        ('completed', 'Service Completed'),
        ('reminder', 'Reminder'),
    ], default='confirmed')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification for {self.booking.client_name} — {self.notification_type}"


class ContactMessage(models.Model):
    """Contact form submissions."""
    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=300)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    reply_text = models.TextField(blank=True, null=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.subject}"


class ClosedDay(models.Model):
    """Specific dates where the spa is closed (e.g., holidays)."""
    date = models.DateField(unique=True)
    reason = models.CharField(max_length=200, default="Holiday")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"{self.date} - {self.reason}"
