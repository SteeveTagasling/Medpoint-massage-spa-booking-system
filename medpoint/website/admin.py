from django.contrib import admin
# pyrefly: ignore [missing-import]
from .models import Service, Therapist, Testimonial, Booking, ContactMessage, StaffSchedule


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price', 'discount_percentage', 'duration_minutes', 'is_featured', 'is_active', 'order']
    list_filter = ['category', 'is_featured', 'is_active']
    list_editable = ['is_featured', 'is_active', 'order', 'discount_percentage']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Therapist)
class TherapistAdmin(admin.ModelAdmin):
    list_display = ['name', 'title', 'gender', 'years_experience', 'phone', 'email', 'commission_percentage', 'is_active', 'order']
    list_filter = ['is_active', 'gender']
    list_editable = ['is_active', 'order', 'commission_percentage']
    search_fields = ['name', 'title']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(StaffSchedule)
class StaffScheduleAdmin(admin.ModelAdmin):
    list_display = ['therapist', 'day_of_week', 'start_time', 'end_time', 'is_available', 'notes']
    list_filter = ['therapist', 'day_of_week', 'is_available']
    list_editable = ['is_available']
    search_fields = ['therapist__name', 'notes']


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ['client_name', 'rating', 'service', 'is_featured', 'is_approved', 'created_at']
    list_filter = ['rating', 'is_featured', 'is_approved']
    list_editable = ['is_featured', 'is_approved']
    search_fields = ['client_name', 'content']


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['client_name', 'service', 'therapist', 'booking_type', 'date', 'time', 'status', 'created_at']
    list_filter = ['status', 'booking_type', 'date', 'service']
    list_editable = ['status']
    search_fields = ['client_name', 'client_email', 'client_phone']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['name', 'subject', 'email', 'is_read', 'created_at']
    list_filter = ['is_read']
    list_editable = ['is_read']
    search_fields = ['name', 'email', 'subject', 'message']
    readonly_fields = ['created_at']
