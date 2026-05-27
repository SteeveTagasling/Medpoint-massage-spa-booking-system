from django.urls import path
from . import views

app_name = 'website'

urlpatterns = [
    path('', views.home, name='home'),
    path('services/', views.services, name='services'),
    path('services/<slug:slug>/', views.service_detail, name='service_detail'),
    path('about/', views.about, name='about'),
    path('booking/', views.booking, name='booking'),
    path('booking/success/', views.booking_success, name='booking_success'),
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('booking/<int:pk>/cancel/', views.cancel_booking, name='cancel_booking'),
    path('contact/', views.contact, name='contact'),
    path('submit-testimonial/', views.submit_testimonial, name='submit_testimonial'),
    # API endpoints
    path('api/therapists/', views.get_therapists_by_preference, name='api_therapists'),
    path('api/notification/<int:pk>/read/', views.mark_notification_read, name='mark_notification_read'),
]
