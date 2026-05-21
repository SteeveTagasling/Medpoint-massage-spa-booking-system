from django.urls import path
from . import views

app_name = 'portals'

urlpatterns = [
    # Authentication
    path('login/', views.portal_login, name='login'),
    path('logout/', views.portal_logout, name='logout'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Booking management
    path('bookings/', views.booking_list, name='booking_list'),
    path('bookings/<int:pk>/update-status/', views.booking_update_status, name='booking_update_status'),

    # Service management (admin only)
    path('services/', views.service_list, name='service_list'),

    # Messages
    path('messages/', views.message_list, name='message_list'),
    path('messages/<int:pk>/toggle-read/', views.message_toggle_read, name='message_toggle_read'),

    # Staff / Therapist management (admin only)
    path('therapists/', views.therapist_list, name='therapist_list'),

    # Testimonials (admin only)
    path('testimonials/', views.testimonial_list, name='testimonial_list'),

    # Gallery (admin only)
    path('gallery/', views.gallery_list, name='gallery_list'),
]
