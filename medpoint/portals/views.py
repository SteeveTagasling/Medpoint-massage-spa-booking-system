import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Sum, Q, F
from django.utils import timezone

from website.models import (
    Service, Therapist, Testimonial, GalleryImage,
    Booking, ContactMessage, StaffSchedule,
)
from .forms import ServiceForm, TherapistForm, WalkInBookingForm, StaffScheduleForm


# ─── Auth ─────────────────────────────────────────────────────────────────────

def portal_login(request):
    """Login page for admin/staff portal with role selection."""
    if request.user.is_authenticated:
        return redirect('portals:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        role = request.POST.get('role', 'staff')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            if role == 'admin' and not user.is_superuser:
                messages.error(request, 'This account does not have admin privileges.')
            elif not user.is_staff:
                messages.error(request, 'You do not have permission to access the portal.')
            else:
                login(request, user)
                request.session['portal_role'] = role
                next_url = request.GET.get('next', 'portals:dashboard')
                return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'portals/login.html')


@login_required(login_url='portals:login')
def portal_logout(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('portals:login')


def _is_admin(request):
    return request.user.is_superuser and request.session.get('portal_role') == 'admin'


def _is_staff_only(request):
    return request.session.get('portal_role') == 'staff'


def _require_admin(request):
    if _is_staff_only(request):
        messages.error(request, 'Admin access required for this action.')
        return redirect('portals:dashboard')
    return None


def _get_staff_therapist(request):
    """Try to find the Therapist record linked to the current user by name or email."""
    user = request.user
    therapist = Therapist.objects.filter(
        Q(email=user.email, email__gt='') |
        Q(name__iexact=user.get_full_name()) |
        Q(name__iexact=user.username)
    ).first()
    return therapist


def _get_date_range(period):
    """Return (start_date, end_date, label) for a given period."""
    today = timezone.now().date()
    if period == 'weekly':
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        label = f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
    elif period == 'monthly':
        start = today.replace(day=1)
        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        label = today.strftime('%B %Y')
    else:  # today
        start = today
        end = today
        label = today.strftime('%B %d, %Y')
    return start, end, label


# ═══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def dashboard(request):
    if not request.user.is_staff:
        return redirect('portals:login')

    # Staff role → staff dashboard
    if _is_staff_only(request):
        return _staff_dashboard(request)

    today = timezone.now().date()
    total_bookings = Booking.objects.count()
    pending_bookings = Booking.objects.filter(status='pending').count()
    confirmed_bookings = Booking.objects.filter(status='confirmed').count()
    today_bookings = Booking.objects.filter(date=today).count()
    total_services = Service.objects.filter(is_active=True).count()
    total_therapists = Therapist.objects.filter(is_active=True).count()
    unread_messages = ContactMessage.objects.filter(is_read=False).count()
    online_bookings = Booking.objects.filter(booking_type='online').count()
    walkin_bookings = Booking.objects.filter(booking_type='walk_in').count()
    recent_bookings = Booking.objects.select_related('service', 'therapist').order_by('-created_at')[:8]

    context = {
        'total_bookings': total_bookings,
        'pending_bookings': pending_bookings,
        'confirmed_bookings': confirmed_bookings,
        'today_bookings': today_bookings,
        'total_services': total_services,
        'total_therapists': total_therapists,
        'unread_messages': unread_messages,
        'online_bookings': online_bookings,
        'walkin_bookings': walkin_bookings,
        'recent_bookings': recent_bookings,
        'is_admin_role': _is_admin(request),
    }
    return render(request, 'portals/dashboard.html', context)


def _staff_dashboard(request):
    """Dashboard for staff/therapist role."""
    therapist = _get_staff_therapist(request)
    today = timezone.now().date()

    if therapist:
        my_bookings_today = Booking.objects.filter(
            therapist=therapist, date=today
        ).exclude(status='cancelled').select_related('service').order_by('time')
        my_total_completed = Booking.objects.filter(
            therapist=therapist, status='completed'
        ).count()
        my_pending = Booking.objects.filter(
            therapist=therapist, status='pending'
        ).count()
    else:
        my_bookings_today = Booking.objects.none()
        my_total_completed = 0
        my_pending = 0

    context = {
        'therapist': therapist,
        'my_bookings_today': my_bookings_today,
        'my_total_completed': my_total_completed,
        'my_pending': my_pending,
        'today': today,
        'is_admin_role': False,
    }
    return render(request, 'portals/staff_dashboard.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
#  BOOKING MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def booking_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')

    status_filter = request.GET.get('status', '')
    type_filter = request.GET.get('type', '')
    search = request.GET.get('search', '')

    bookings = Booking.objects.select_related('service', 'therapist').all()

    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if type_filter:
        bookings = bookings.filter(booking_type=type_filter)
    if search:
        bookings = bookings.filter(
            Q(client_name__icontains=search) |
            Q(client_email__icontains=search) |
            Q(client_phone__icontains=search)
        )

    context = {
        'bookings': bookings,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'search': search,
        'status_choices': Booking.STATUS_CHOICES,
        'type_choices': Booking.BOOKING_TYPE_CHOICES,
    }
    return render(request, 'portals/booking_list.html', context)


@login_required(login_url='portals:login')
def booking_update_status(request, pk):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method == 'POST':
        booking = get_object_or_404(Booking, pk=pk)
        new_status = request.POST.get('status')
        if new_status in dict(Booking.STATUS_CHOICES):
            booking.status = new_status
            booking.save()
            return JsonResponse({'success': True, 'status': new_status})
        return JsonResponse({'error': 'Invalid status'}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required(login_url='portals:login')
def booking_create_walkin(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    if request.method == 'POST':
        form = WalkInBookingForm(request.POST)
        if form.is_valid():
            booking = form.save()
            messages.success(request, f'Walk-in booking #{booking.pk:04d} created successfully.')
            return redirect('portals:booking_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = WalkInBookingForm(initial={
            'date': timezone.now().date(),
            'status': 'confirmed',
        })
    return render(request, 'portals/booking_walkin.html', {'form': form})


@login_required(login_url='portals:login')
def booking_delete(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    booking = get_object_or_404(Booking, pk=pk)
    if request.method == 'POST':
        booking.delete()
        messages.success(request, 'Booking deleted successfully.')
    return redirect('portals:booking_list')


# ═══════════════════════════════════════════════════════════════════════════════
#  SERVICE MANAGEMENT (CRUD)
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def service_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    # Both admin and staff can manage services
    category_filter = request.GET.get('category', '')
    services = Service.objects.all()
    if category_filter:
        services = services.filter(category=category_filter)
    context = {
        'services': services,
        'categories': Service.CATEGORY_CHOICES,
        'category_filter': category_filter,
    }
    return render(request, 'portals/service_list.html', context)


@login_required(login_url='portals:login')
def service_create(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    if request.method == 'POST':
        form = ServiceForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Service created successfully.')
            return redirect('portals:service_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ServiceForm()
    return render(request, 'portals/service_form.html', {'form': form, 'action': 'Create'})


@login_required(login_url='portals:login')
def service_edit(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    service = get_object_or_404(Service, pk=pk)
    if request.method == 'POST':
        form = ServiceForm(request.POST, request.FILES, instance=service)
        if form.is_valid():
            form.save()
            messages.success(request, f'"{service.name}" updated successfully.')
            return redirect('portals:service_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ServiceForm(instance=service)
    return render(request, 'portals/service_form.html', {'form': form, 'action': 'Edit', 'service': service})


@login_required(login_url='portals:login')
def service_delete(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    service = get_object_or_404(Service, pk=pk)
    if request.method == 'POST':
        name = service.name
        service.delete()
        messages.success(request, f'"{name}" deleted successfully.')
    return redirect('portals:service_list')


# ═══════════════════════════════════════════════════════════════════════════════
#  THERAPIST / STAFF MANAGEMENT (CRUD)
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def therapist_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    therapists = Therapist.objects.all()
    return render(request, 'portals/therapist_list.html', {'therapists': therapists})


@login_required(login_url='portals:login')
def therapist_create(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    if request.method == 'POST':
        form = TherapistForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Therapist registered successfully.')
            return redirect('portals:therapist_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = TherapistForm()
    return render(request, 'portals/therapist_form.html', {'form': form, 'action': 'Register'})


@login_required(login_url='portals:login')
def therapist_edit(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    therapist = get_object_or_404(Therapist, pk=pk)
    if request.method == 'POST':
        form = TherapistForm(request.POST, request.FILES, instance=therapist)
        if form.is_valid():
            form.save()
            messages.success(request, f'"{therapist.name}" updated successfully.')
            return redirect('portals:therapist_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = TherapistForm(instance=therapist)
    return render(request, 'portals/therapist_form.html', {'form': form, 'action': 'Edit', 'therapist': therapist})


@login_required(login_url='portals:login')
def therapist_delete(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    therapist = get_object_or_404(Therapist, pk=pk)
    if request.method == 'POST':
        name = therapist.name
        therapist.delete()
        messages.success(request, f'"{name}" removed successfully.')
    return redirect('portals:therapist_list')


# ═══════════════════════════════════════════════════════════════════════════════
#  SCHEDULE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def schedule_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    therapist_filter = request.GET.get('therapist', '')
    schedules = StaffSchedule.objects.select_related('therapist').all()
    if therapist_filter:
        schedules = schedules.filter(therapist_id=therapist_filter)
    therapists = Therapist.objects.filter(is_active=True)
    context = {
        'schedules': schedules,
        'therapists': therapists,
        'therapist_filter': therapist_filter,
    }
    return render(request, 'portals/schedule_list.html', context)


@login_required(login_url='portals:login')
def schedule_create(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    if request.method == 'POST':
        form = StaffScheduleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Schedule assigned successfully.')
            return redirect('portals:schedule_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = StaffScheduleForm()
    return render(request, 'portals/schedule_form.html', {'form': form, 'action': 'Assign'})


@login_required(login_url='portals:login')
def schedule_edit(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    schedule = get_object_or_404(StaffSchedule, pk=pk)
    if request.method == 'POST':
        form = StaffScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            form.save()
            messages.success(request, 'Schedule updated successfully.')
            return redirect('portals:schedule_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = StaffScheduleForm(instance=schedule)
    return render(request, 'portals/schedule_form.html', {'form': form, 'action': 'Edit', 'schedule': schedule})


@login_required(login_url='portals:login')
def schedule_delete(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    schedule = get_object_or_404(StaffSchedule, pk=pk)
    if request.method == 'POST':
        schedule.delete()
        messages.success(request, 'Schedule entry removed.')
    return redirect('portals:schedule_list')


@login_required(login_url='portals:login')
def schedule_toggle_availability(request, pk):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method == 'POST':
        schedule = get_object_or_404(StaffSchedule, pk=pk)
        schedule.is_available = not schedule.is_available
        schedule.save()
        return JsonResponse({'success': True, 'is_available': schedule.is_available})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


# ═══════════════════════════════════════════════════════════════════════════════
#  CALENDAR VIEW
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def booking_calendar(request):
    if not request.user.is_staff:
        return redirect('portals:login')

    today = timezone.now().date()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    view_mode = request.GET.get('view', 'calendar')

    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    month_start = date(year, month, 1)
    month_end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)

    # For staff role, only show their bookings
    bookings_qs = Booking.objects.select_related('service', 'therapist').filter(
        date__gte=month_start, date__lte=month_end
    )
    if _is_staff_only(request):
        therapist = _get_staff_therapist(request)
        if therapist:
            bookings_qs = bookings_qs.filter(therapist=therapist)
        else:
            bookings_qs = bookings_qs.none()

    bookings = bookings_qs.order_by('date', 'time')

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(year, month)

    bookings_by_date = {}
    for b in bookings:
        bookings_by_date.setdefault(b.date.day, []).append(b)

    prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)

    context = {
        'month_days': month_days,
        'month_name': calendar.month_name[month],
        'year': year, 'month': month,
        'today': today,
        'bookings_by_date': bookings_by_date,
        'prev_month': prev_month, 'prev_year': prev_year,
        'next_month': next_month, 'next_year': next_year,
        'view_mode': view_mode,
        'list_bookings': bookings if view_mode == 'list' else None,
        'weekday_names': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    }
    return render(request, 'portals/booking_calendar.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN REPORTS
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def admin_reports(request):
    """Admin business performance reports — viewable & printable, not downloadable."""
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check

    period = request.GET.get('period', 'today')
    start_date, end_date, period_label = _get_date_range(period)

    # All completed bookings in period
    completed = Booking.objects.filter(
        status='completed',
        date__gte=start_date,
        date__lte=end_date,
    ).select_related('service', 'therapist')

    # Revenue
    total_revenue = Decimal('0')
    for b in completed:
        total_revenue += b.service.discounted_price

    total_completed = completed.count()
    total_bookings_period = Booking.objects.filter(
        date__gte=start_date, date__lte=end_date
    ).count()

    # Per-staff performance
    staff_data = []
    therapists = Therapist.objects.filter(is_active=True)
    for t in therapists:
        t_bookings = completed.filter(therapist=t)
        t_count = t_bookings.count()
        t_revenue = Decimal('0')
        for b in t_bookings:
            t_revenue += b.service.discounted_price
        t_commission = t_revenue * (t.commission_percentage / Decimal('100'))
        staff_data.append({
            'therapist': t,
            'services_rendered': t_count,
            'total_revenue': t_revenue,
            'commission_rate': t.commission_percentage,
            'commission_earned': t_commission,
        })

    # Sort by services rendered (desc)
    staff_data.sort(key=lambda x: x['services_rendered'], reverse=True)

    # Booking type breakdown
    online_count = completed.filter(booking_type='online').count()
    walkin_count = completed.filter(booking_type='walk_in').count()

    # Service breakdown
    service_breakdown = []
    for svc in Service.objects.filter(is_active=True):
        svc_bookings = completed.filter(service=svc)
        svc_count = svc_bookings.count()
        if svc_count > 0:
            svc_revenue = Decimal('0')
            for b in svc_bookings:
                svc_revenue += svc.discounted_price
            service_breakdown.append({
                'service': svc,
                'count': svc_count,
                'revenue': svc_revenue,
            })
    service_breakdown.sort(key=lambda x: x['count'], reverse=True)

    context = {
        'period': period,
        'period_label': period_label,
        'start_date': start_date,
        'end_date': end_date,
        'total_revenue': total_revenue,
        'total_completed': total_completed,
        'total_bookings_period': total_bookings_period,
        'staff_data': staff_data,
        'service_breakdown': service_breakdown,
        'online_count': online_count,
        'walkin_count': walkin_count,
    }
    return render(request, 'portals/admin_reports.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
#  STAFF VIEWS (Therapist limited access)
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def staff_my_bookings(request):
    """Staff: view assigned bookings."""
    if not request.user.is_staff:
        return redirect('portals:login')

    therapist = _get_staff_therapist(request)
    status_filter = request.GET.get('status', '')
    bookings = Booking.objects.select_related('service', 'therapist').none()

    if therapist:
        bookings = Booking.objects.select_related('service', 'therapist').filter(
            therapist=therapist
        )
        if status_filter:
            bookings = bookings.filter(status=status_filter)

    context = {
        'bookings': bookings,
        'therapist': therapist,
        'status_filter': status_filter,
        'status_choices': Booking.STATUS_CHOICES,
    }
    return render(request, 'portals/staff_my_bookings.html', context)


@login_required(login_url='portals:login')
def staff_my_schedule(request):
    """Staff: calendar view with auto-availability detection.
    Times that have bookings are detected as unavailable.
    """
    if not request.user.is_staff:
        return redirect('portals:login')

    therapist = _get_staff_therapist(request)
    today = timezone.now().date()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))

    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    month_start = date(year, month, 1)
    month_end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)

    my_bookings = Booking.objects.none()
    my_schedules = StaffSchedule.objects.none()

    if therapist:
        my_bookings = Booking.objects.filter(
            therapist=therapist,
            date__gte=month_start,
            date__lte=month_end,
        ).exclude(status='cancelled').select_related('service').order_by('date', 'time')

        my_schedules = StaffSchedule.objects.filter(therapist=therapist).order_by('day_of_week', 'start_time')

    # Build booked slots: date -> list of times
    booked_slots = {}
    for b in my_bookings:
        booked_slots.setdefault(b.date.day, []).append({
            'time': b.get_time_display(),
            'time_raw': b.time,
            'service': b.service.name,
            'client': b.client_name,
            'status': b.status,
        })

    cal_obj = calendar.Calendar(firstweekday=0)
    month_days = cal_obj.monthdayscalendar(year, month)

    prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)

    # Build schedule map: day_of_week -> list of schedule entries
    schedule_map = {}
    for s in my_schedules:
        schedule_map.setdefault(s.day_of_week, []).append(s)

    context = {
        'therapist': therapist,
        'month_days': month_days,
        'month_name': calendar.month_name[month],
        'year': year, 'month': month,
        'today': today,
        'booked_slots': booked_slots,
        'prev_month': prev_month, 'prev_year': prev_year,
        'next_month': next_month, 'next_year': next_year,
        'weekday_names': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'my_schedules': my_schedules,
        'schedule_map': schedule_map,
    }
    return render(request, 'portals/staff_my_schedule.html', context)


@login_required(login_url='portals:login')
def staff_my_reports(request):
    """Staff: view personal work and activity reports."""
    if not request.user.is_staff:
        return redirect('portals:login')

    therapist = _get_staff_therapist(request)
    period = request.GET.get('period', 'today')
    start_date, end_date, period_label = _get_date_range(period)

    services_rendered = 0
    total_revenue = Decimal('0')
    commission_earned = Decimal('0')
    booking_details = []

    if therapist:
        completed = Booking.objects.filter(
            therapist=therapist,
            status='completed',
            date__gte=start_date,
            date__lte=end_date,
        ).select_related('service').order_by('-date', '-time')

        services_rendered = completed.count()
        for b in completed:
            price = b.service.discounted_price
            total_revenue += price
            booking_details.append({
                'booking': b,
                'price': price,
            })
        commission_earned = total_revenue * (therapist.commission_percentage / Decimal('100'))

    context = {
        'therapist': therapist,
        'period': period,
        'period_label': period_label,
        'services_rendered': services_rendered,
        'total_revenue': total_revenue,
        'commission_earned': commission_earned,
        'booking_details': booking_details,
    }
    return render(request, 'portals/staff_my_reports.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
#  MESSAGES / TESTIMONIALS / GALLERY (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def message_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    read_filter = request.GET.get('read', '')
    contact_messages = ContactMessage.objects.all()
    if read_filter == 'unread':
        contact_messages = contact_messages.filter(is_read=False)
    elif read_filter == 'read':
        contact_messages = contact_messages.filter(is_read=True)
    unread_count = ContactMessage.objects.filter(is_read=False).count()
    context = {
        'contact_messages': contact_messages,
        'read_filter': read_filter,
        'unread_count': unread_count,
    }
    return render(request, 'portals/message_list.html', context)


@login_required(login_url='portals:login')
def message_toggle_read(request, pk):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method == 'POST':
        msg = get_object_or_404(ContactMessage, pk=pk)
        msg.is_read = not msg.is_read
        msg.save()
        return JsonResponse({'success': True, 'is_read': msg.is_read})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required(login_url='portals:login')
def testimonial_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    testimonials = Testimonial.objects.all()
    return render(request, 'portals/testimonial_list.html', {'testimonials': testimonials})


@login_required(login_url='portals:login')
def gallery_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    images = GalleryImage.objects.all()
    return render(request, 'portals/gallery_list.html', {'images': images})
