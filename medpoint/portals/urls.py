from django.urls import path
from . import views

app_name = 'portals'

urlpatterns = [
    # Authentication
    path('login/', views.portal_login, name='login'),
    path('logout/', views.portal_logout, name='logout'),

    # Dashboard (routes to admin or staff dashboard based on role)
    path('dashboard/', views.dashboard, name='dashboard'),

    # ── Booking management ────────────────────────────
    path('bookings/', views.booking_list, name='booking_list'),
    path('bookings/walk-in/', views.booking_create_walkin, name='booking_walkin'),
    path('bookings/<int:pk>/update-status/', views.booking_update_status, name='booking_update_status'),
    path('bookings/<int:pk>/delete/', views.booking_delete, name='booking_delete'),
    path('bookings/calendar/', views.booking_calendar, name='booking_calendar'),
    path('bookings/calendar/toggle-holiday/', views.toggle_holiday, name='toggle_holiday'),

    # ── Service management ────────────────────────────
    path('services/', views.service_list, name='service_list'),
    path('services/create/', views.service_create, name='service_create'),
    path('services/<int:pk>/edit/', views.service_edit, name='service_edit'),
    path('services/<int:pk>/delete/', views.service_delete, name='service_delete'),

    # ── Staff / Therapist management (admin only) ─────
    path('therapists/', views.therapist_list, name='therapist_list'),
    path('therapists/register/', views.therapist_create, name='therapist_create'),
    path('therapists/<int:pk>/edit/', views.therapist_edit, name='therapist_edit'),
    path('therapists/<int:pk>/delete/', views.therapist_delete, name='therapist_delete'),

    # ── Administrator management (admin only) ─────────
    path('admins/', views.admin_management_list, name='admin_management_list'),
    path('admins/register/', views.admin_management_create, name='admin_management_create'),
    path('admins/<int:pk>/edit/', views.admin_management_edit, name='admin_management_edit'),
    path('admins/<int:pk>/delete/', views.admin_management_delete, name='admin_management_delete'),

    # ── Schedule management ───────────────────────────
    path('schedules/', views.schedule_list, name='schedule_list'),
    path('schedules/assign/', views.schedule_create, name='schedule_create'),
    path('schedules/<str:pk>/edit/', views.schedule_edit, name='schedule_edit'),
    path('schedules/<str:pk>/delete/', views.schedule_delete, name='schedule_delete'),
    path('schedules/<str:pk>/toggle/', views.schedule_toggle_availability, name='schedule_toggle'),
    path('schedules/leave/assign/', views.staff_assign_leave, name='staff_assign_leave'),
    path('schedules/leave/<str:pk>/toggle-active/', views.staff_leave_toggle_active, name='staff_leave_toggle_active'),

    # ── Admin Leave Management ────────────────────────
    path('schedules/leave/', views.admin_leave_list, name='admin_leave_list'),
    path('schedules/leave/<int:pk>/review/', views.admin_leave_review, name='admin_leave_review'),

    # ── Staff Leave Application ───────────────────────
    path('my-schedule/leave/apply/', views.staff_apply_leave, name='staff_apply_leave'),
    path('my-schedule/leave/<int:pk>/delete/', views.staff_delete_leave, name='staff_delete_leave'),


    # ── Admin Reports ─────────────────────────────────
    path('reports/', views.admin_reports, name='admin_reports'),
    path('admin-settings/', views.admin_settings, name='admin_settings'),

    # ── Staff views (therapist limited access) ────────
    path('my-bookings/', views.staff_my_bookings, name='staff_my_bookings'),
    path('my-schedule/', views.staff_my_schedule, name='staff_my_schedule'),
    path('my-reports/', views.staff_my_reports, name='staff_my_reports'),
    path('staff-settings/', views.staff_settings, name='staff_settings'),

    # ── Messages ──────────────────────────────────────
    path('messages/', views.message_list, name='message_list'),
    path('messages/<int:pk>/toggle-read/', views.message_toggle_read, name='message_toggle_read'),
    path('messages/<int:pk>/reply/', views.message_reply, name='message_reply'),

    # ── Testimonials (admin only) ─────────────────────
    path('testimonials/', views.testimonial_list, name='testimonial_list'),
    path('testimonials/<int:pk>/toggle-featured/', views.testimonial_toggle_featured, name='testimonial_toggle_featured'),
    path('testimonials/<int:pk>/toggle-approved/', views.testimonial_toggle_approved, name='testimonial_toggle_approved'),

    # ── Gallery (admin only) ──────────────────────────
    path('gallery/', views.gallery_list, name='gallery_list'),

    # ── Notifications ─────────────────────────────────────
    path('notifications/', views.notification_list, name='notification_list'),
    path('notifications/<int:pk>/mark-read/', views.notification_mark_read, name='notification_mark_read'),
    path('api/live-counts/', views.live_counts, name='live_counts'),
    path('api/revenue-chart/', views.revenue_chart_data, name='revenue_chart_data'),
]
