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
    Booking, ContactMessage, StaffSchedule, StaffLeave,
)
from .forms import ServiceForm, TherapistForm, WalkInBookingForm, StaffScheduleForm, AdminSettingsForm, AdminUserForm, StaffSettingsForm, BulkStaffScheduleForm, StaffLeaveForm
from .models import AdminProfile, StaffNotification


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
                
                remember_me = request.POST.get('remember_me')
                if not remember_me:
                    request.session.set_expiry(0) # Expire on browser close
                else:
                    request.session.set_expiry(1209600) # Persist for 2 weeks
                
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
    """Try to find the Therapist record linked to the current user."""
    user = request.user
    if hasattr(user, 'therapist_profile'):
        return user.therapist_profile
    
    # Fallback for old ones without user attached
    therapist = Therapist.objects.filter(
        Q(email=user.email, email__gt='') |
        Q(name__iexact=user.get_full_name()) |
        Q(name__iexact=user.username)
    ).first()
    return therapist


def _get_date_range(request):
    """Return (start_date, end_date, label) for a given request."""
    today = timezone.now().date()
    
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    
    if start_str and end_str:
        try:
            from datetime import datetime
            start = datetime.strptime(start_str, '%Y-%m-%d').date()
            end = datetime.strptime(end_str, '%Y-%m-%d').date()
            if start == end:
                label = start.strftime('%B %d, %Y')
            else:
                label = f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"
            return start, end, label
        except ValueError:
            pass

    period = request.GET.get('period', 'today')
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
    from decimal import Decimal
    therapist = _get_staff_therapist(request)
    today = timezone.now().date()

    if therapist:
        my_bookings_today = Booking.objects.filter(
            therapist=therapist, date=today
        ).exclude(status='cancelled').select_related('service').order_by('time')
        my_completed_bookings = Booking.objects.filter(
            therapist=therapist, status='completed'
        ).select_related('service')
        
        my_total_completed = my_completed_bookings.count()
        my_pending = Booking.objects.filter(
            therapist=therapist, status='pending'
        ).count()
        
        # Calculate Unique Customers
        # Using a set of lowercased emails for simplicity or names if email is blank
        customers = set()
        total_income = Decimal('0')
        
        for b in my_completed_bookings:
            customers.add(b.client_email.lower().strip() or b.client_name.lower().strip())
            total_income += b.service.discounted_price * (therapist.commission_percentage / Decimal('100'))
            
        my_unique_customers = len(customers)
        my_services_income = total_income
        
    else:
        my_bookings_today = Booking.objects.none()
        my_total_completed = 0
        my_pending = 0
        my_unique_customers = 0
        my_services_income = Decimal('0')

    context = {
        'therapist': therapist,
        'my_bookings_today': my_bookings_today,
        'my_total_completed': my_total_completed,
        'my_pending': my_pending,
        'my_unique_customers': my_unique_customers,
        'my_services_income': my_services_income,
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
    date_filter = request.GET.get('date', '')
    service_filter = request.GET.get('service', '')

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
    if date_filter:
        bookings = bookings.filter(date=date_filter)
    if service_filter:
        bookings = bookings.filter(service_id=service_filter)
        
    services = Service.objects.all()

    context = {
        'bookings': bookings,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'date_filter': date_filter,
        'service_filter': service_filter,
        'search': search,
        'status_choices': Booking.STATUS_CHOICES,
        'type_choices': Booking.BOOKING_TYPE_CHOICES,
        'services': services,
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
            
            if booking.therapist:
                from django.urls import reverse
                StaffNotification.objects.create(
                    notification_type='booking_status',
                    title='Booking Status Updated',
                    message=f"Booking #{booking.pk:04d} status has been changed to {new_status}.",
                    target_role='staff',
                    target_therapist=booking.therapist,
                    link=reverse('portals:staff_my_bookings')
                )
                
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
            booking_obj = form.save()

            # Auto-assign therapist if preference is set but no specific therapist chosen
            if not booking_obj.therapist and booking_obj.therapist_preference != 'random':
                matching = Therapist.objects.filter(
                    is_active=True, gender=booking_obj.therapist_preference
                )
                if matching.exists():
                    import random as rand_module
                    available = list(matching)
                    rand_module.shuffle(available)
                    booking_obj.therapist = available[0]
                    booking_obj.save()
            elif not booking_obj.therapist and booking_obj.therapist_preference == 'random':
                # For female clients, only assign female therapists even on random
                if booking_obj.client_gender == 'female':
                    matching = Therapist.objects.filter(is_active=True, gender='female')
                else:
                    matching = Therapist.objects.filter(is_active=True)
                if matching.exists():
                    import random as rand_module
                    available = list(matching)
                    rand_module.shuffle(available)
                    booking_obj.therapist = available[0]
                    booking_obj.save()

            from website.models import ClosedDay, BookingNotification
            is_closed = ClosedDay.objects.filter(date=booking_obj.date).exists()
            if is_closed:
                booking_obj.delete()
                messages.error(request, 'The selected date is a Holiday. The spa is closed. Please select another date.')
                return redirect('portals:booking_list')

            # Create notification for client
            BookingNotification.objects.create(
                booking=booking_obj,
                notification_type='confirmed',
                message=(
                    f"Your walk-in booking for {booking_obj.service.name} on "
                    f"{booking_obj.date.strftime('%B %d, %Y')} at "
                    f"{booking_obj.get_time_display()} has been registered."
                ),
            )

            # Create portal notification for assigned therapist
            if booking_obj.therapist:
                from django.urls import reverse
                StaffNotification.objects.create(
                    notification_type='new_booking',
                    title='Walk-in Assigned',
                    message=f"Walk-in booking #{booking_obj.pk:04d} has been assigned to you.",
                    target_role='staff',
                    target_therapist=booking_obj.therapist,
                    link=reverse('portals:staff_my_bookings')
                )

            messages.success(request, f'Walk-in booking #{booking_obj.pk:04d} created successfully.')
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
        services = services.filter(category__icontains=category_filter)
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
    check = _require_admin(request)
    if check:
        return check
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
#  ADMINISTRATOR MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def admin_management_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    
    from django.contrib.auth.models import User
    # Get all superusers
    admins = User.objects.filter(is_superuser=True).order_by('username')
    return render(request, 'portals/admin_list.html', {'admins': admins})

@login_required(login_url='portals:login')
def admin_management_create(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check

    if request.method == 'POST':
        form = AdminUserForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'Admin account created successfully.')
            return redirect('portals:admin_management_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = AdminUserForm()
    return render(request, 'portals/admin_form.html', {'form': form, 'action': 'Register'})

@login_required(login_url='portals:login')
def admin_management_edit(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
        
    from django.contrib.auth.models import User
    admin_user = get_object_or_404(User, pk=pk, is_superuser=True)
    if request.method == 'POST':
        form = AdminUserForm(request.POST, instance=admin_user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Admin account "{admin_user.username}" updated successfully.')
            return redirect('portals:admin_management_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = AdminUserForm(instance=admin_user)
    return render(request, 'portals/admin_form.html', {'form': form, 'action': 'Edit', 'admin_user': admin_user})

@login_required(login_url='portals:login')
def admin_management_delete(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
        
    from django.contrib.auth.models import User
    admin_user = get_object_or_404(User, pk=pk, is_superuser=True)
    if request.method == 'POST':
        # Prevent self-deletion
        if admin_user == request.user:
            messages.error(request, 'You cannot delete your own admin account.')
        else:
            username = admin_user.username
            admin_user.delete()
            messages.success(request, f'Admin "{username}" removed successfully.')
    return redirect('portals:admin_management_list')


# ═══════════════════════════════════════════════════════════════════════════════
#  SCHEDULE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def schedule_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    therapist_filter = request.GET.get('therapist', '')
    status_filter = request.GET.get('status')
    if status_filter is None:
        status_filter = 'available'
    
    schedules = StaffSchedule.objects.select_related('therapist').order_by('therapist__name', 'start_time')
    
    if therapist_filter:
        schedules = schedules.filter(therapist_id=therapist_filter)
        
    if status_filter == 'available':
        schedules = schedules.filter(is_available=True)
    elif status_filter == 'off':
        schedules = schedules.filter(is_available=False)
        
    grouped_schedules = []
    group_map = {}
    day_map = dict(StaffSchedule.DAY_CHOICES)
    
    for s in schedules:
        key = (s.therapist_id, s.start_time, s.end_time, s.is_available, s.notes)
        if key not in group_map:
            group_data = {
                'ids': [str(s.pk)],
                'therapist': s.therapist,
                'days': [day_map[s.day_of_week]],
                'day_ints': [s.day_of_week],
                'start_time': s.start_time,
                'end_time': s.end_time,
                'is_available': s.is_available,
                'notes': s.notes,
                'primary_pk': s.pk,
            }
            grouped_schedules.append(group_data)
            group_map[key] = group_data
        else:
            group_map[key]['ids'].append(str(s.pk))
            group_map[key]['days'].append(day_map[s.day_of_week])
            group_map[key]['day_ints'].append(s.day_of_week)
            
    for g in grouped_schedules:
        g['ids_str'] = ",".join(g['ids'])
        day_ints = sorted(g['day_ints'])
        day_names = [day_map[d] for d in day_ints]
        g['display_days'] = ", ".join(day_names)
        
    therapists = Therapist.objects.filter(is_active=True)
    
    leaves = StaffLeave.objects.select_related('therapist').all().order_by('-start_date')
    if therapist_filter:
        leaves = leaves.filter(therapist_id=therapist_filter)

    context = {
        'grouped_schedules': grouped_schedules,
        'therapists': therapists,
        'therapist_filter': therapist_filter,
        'status_filter': status_filter,
        'leaves': leaves,
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
        form = BulkStaffScheduleForm(request.POST)
        if form.is_valid():
            therapist = form.cleaned_data['therapist']
            days_of_week = form.cleaned_data['day_of_week']
            is_available = form.cleaned_data.get('is_available', True)
            start_time = form.cleaned_data['start_time']
            end_time = form.cleaned_data['end_time']
            notes = form.cleaned_data.get('notes', '')

            for day_index in range(7):
                if str(day_index) in days_of_week:
                    StaffSchedule.objects.update_or_create(
                        therapist=therapist,
                        day_of_week=day_index,
                        defaults={
                            'start_time': start_time,
                            'end_time': end_time,
                            'is_available': is_available,
                            'notes': notes,
                        }
                    )
                else:
                    # Auto-assign unchecked days as day off only if they don't already have one
                    if not StaffSchedule.objects.filter(therapist=therapist, day_of_week=day_index).exists():
                        import datetime
                        StaffSchedule.objects.create(
                            therapist=therapist,
                            day_of_week=day_index,
                            start_time=datetime.time(0,0),
                            end_time=datetime.time(0,0),
                            is_available=False,
                            notes="Day off"
                        )

            messages.success(request, f'Schedule assigned for multiple days successfully.')
            return redirect('portals:schedule_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = BulkStaffScheduleForm()
    return render(request, 'portals/schedule_form.html', {'form': form, 'action': 'Assign'})


@login_required(login_url='portals:login')
def staff_assign_leave(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check

    if request.method == 'POST':
        form = StaffLeaveForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Leave assigned successfully.')
            return redirect('portals:schedule_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = StaffLeaveForm()

    return render(request, 'portals/staff_leave_form.html', {'form': form})


@login_required(login_url='portals:login')
def staff_leave_toggle_active(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check

    if request.method == 'POST':
        import website.models
        leave = get_object_or_404(website.models.StaffLeave, pk=pk)
        leave.is_active = not leave.is_active
        leave.save()
        status_text = 'reactivated' if leave.is_active else 'ended'
        messages.success(request, f'Leave record {status_text} successfully.')
        return redirect('portals:schedule_list')
    return redirect('portals:schedule_list')


@login_required(login_url='portals:login')
def schedule_edit(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    ids = str(pk).split(',')
    schedules = StaffSchedule.objects.filter(pk__in=ids)
    if not schedules.exists():
        messages.error(request, 'Schedule not found.')
        return redirect('portals:schedule_list')
        
    first_schedule = schedules.first()

    if request.method == 'POST':
        form = BulkStaffScheduleForm(request.POST)
        if form.is_valid():
            therapist = form.cleaned_data['therapist']
            days_of_week = form.cleaned_data['day_of_week']
            is_available = form.cleaned_data.get('is_available', True)
            start_time = form.cleaned_data['start_time']
            end_time = form.cleaned_data['end_time']
            notes = form.cleaned_data.get('notes', '')

            previous_days = [s.day_of_week for s in schedules]
            schedules.delete()

            for day_index in range(7):
                if str(day_index) in days_of_week:
                    StaffSchedule.objects.update_or_create(
                        therapist=therapist,
                        day_of_week=day_index,
                        defaults={
                            'start_time': start_time,
                            'end_time': end_time,
                            'is_available': is_available,
                            'notes': notes,
                        }
                    )
                elif day_index in previous_days:
                    # They unchecked this day during the edit. So it explicitly becomes a Day off!
                    import datetime
                    StaffSchedule.objects.update_or_create(
                        therapist=therapist,
                        day_of_week=day_index,
                        defaults={
                            'start_time': datetime.time(0, 0),
                            'end_time': datetime.time(0, 0),
                            'is_available': False,
                            'notes': "Day off",
                        }
                    )

            messages.success(request, 'Schedule updated successfully.')
            return redirect('portals:schedule_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        initial_days = [str(s.day_of_week) for s in schedules]
        form = BulkStaffScheduleForm(initial={
            'therapist': first_schedule.therapist,
            'day_of_week': initial_days,
            'start_time': first_schedule.start_time,
            'end_time': first_schedule.end_time,
            'is_available': first_schedule.is_available,
            'notes': first_schedule.notes,
        })
    return render(request, 'portals/schedule_form.html', {'form': form, 'action': 'Edit', 'schedule': first_schedule})


@login_required(login_url='portals:login')
def schedule_delete(request, pk):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    
    if request.method == 'POST':
        ids = str(pk).split(',')
        StaffSchedule.objects.filter(pk__in=ids).delete()
        messages.success(request, 'Schedule entry removed.')
    return redirect('portals:schedule_list')


@login_required(login_url='portals:login')
def schedule_toggle_availability(request, pk):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method == 'POST':
        ids = str(pk).split(',')
        schedules = StaffSchedule.objects.filter(pk__in=ids)
        if schedules.exists():
            new_status = not schedules.first().is_available
            schedules.update(is_available=new_status)
            return JsonResponse({'success': True, 'is_available': new_status})
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

    from website.models import ClosedDay
    closed_dates = ClosedDay.objects.filter(
        date__gte=month_start, date__lte=month_end
    ).values_list('date', flat=True)
    closed_days = [d.day for d in closed_dates]

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
        'closed_days': closed_days,
    }
    return render(request, 'portals/booking_calendar.html', context)

@login_required(login_url='portals:login')
def toggle_holiday(request):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            date_str = data.get('date')
            import datetime
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            from website.models import ClosedDay
            reason = data.get('reason') or 'Holiday / Closed Date'
            obj, created = ClosedDay.objects.get_or_create(date=target_date, defaults={'reason': reason})
            if not created:
                obj.delete()
            return JsonResponse({'success': True, 'is_holiday': created})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


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
    if request.GET.get('start_date') and request.GET.get('end_date'):
        period = 'custom'
        messages.success(request, "Report filtered by custom date range.")
    start_date, end_date, period_label = _get_date_range(request)

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
    if request.GET.get('start_date') and request.GET.get('end_date'):
        period = 'custom'
        messages.success(request, "Report filtered by custom date range.")
    start_date, end_date, period_label = _get_date_range(request)

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
    check = _require_admin(request)
    if check:
        return check
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
    if not request.user.is_staff or not _is_admin(request):
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
def testimonial_toggle_featured(request, pk):
    if request.method == 'POST':
        check = _require_admin(request)
        if check:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        t = get_object_or_404(Testimonial, pk=pk)
        t.is_featured = not t.is_featured
        t.save()
        return JsonResponse({'success': True, 'is_featured': t.is_featured})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required(login_url='portals:login')
def testimonial_toggle_approved(request, pk):
    if request.method == 'POST':
        check = _require_admin(request)
        if check:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        t = get_object_or_404(Testimonial, pk=pk)
        t.is_approved = not t.is_approved
        t.save()
        return JsonResponse({'success': True, 'is_approved': t.is_approved})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required(login_url='portals:login')
def gallery_list(request):
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check
    images = GalleryImage.objects.all()
    return render(request, 'portals/gallery_list.html', {'images': images})


# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def admin_settings(request):
    """Admin settings page for profile, username, and password."""
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check

    user = request.user
    profile, created = AdminProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        form = AdminSettingsForm(request.POST, request.FILES)
        if form.is_valid():
            # Update User fields
            username = form.cleaned_data.get('username')
            first_name = form.cleaned_data.get('first_name')
            last_name = form.cleaned_data.get('last_name')
            password = form.cleaned_data.get('password')

            if username:
                user.username = username
            user.first_name = first_name
            user.last_name = last_name
            if password:
                user.set_password(password)
            user.save()
            
            # If password changed, update session so user doesn't get logged out
            if password:
                from django.contrib.auth import update_session_auth_hash
                update_session_auth_hash(request, user)

            # Update Profile fields
            photo = form.cleaned_data.get('photo')
            if 'photo' in request.FILES:
                profile.photo = request.FILES['photo']
            # If the user cleared the photo
            elif request.POST.get('photo-clear'):
                profile.photo = None
            profile.save()

            messages.success(request, 'Admin settings updated successfully.')
            return redirect('portals:admin_settings')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        initial_data = {
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
        }
        form = AdminSettingsForm(initial=initial_data)

    context = {
        'form': form,
        'profile': profile,
    }
    return render(request, 'portals/admin_settings.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
#  STAFF SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def staff_settings(request):
    """Settings page for staff to update their profile and password."""
    if not request.user.is_staff or request.user.is_superuser:
        return redirect('portals:login')
        
    therapist = request.user.therapist_profile
    if not therapist:
        messages.error(request, 'No therapist profile associated with this account.')
        return redirect('portals:dashboard')

    if request.method == 'POST':
        form = StaffSettingsForm(request.POST, request.FILES, instance=therapist)
        if form.is_valid():
            # Update password if provided
            password = form.cleaned_data.get('password')
            if password:
                user = request.user
                user.set_password(password)
                user.save()
                from django.contrib.auth import update_session_auth_hash
                update_session_auth_hash(request, user)
                
            form.save()
            
            # Manually handle photo removal since we switched to FileInput
            if request.POST.get('photo-clear'):
                therapist.photo.delete(save=False)
                therapist.photo = None
                therapist.save()

            messages.success(request, 'Your profile settings have been updated successfully.')
            return redirect('portals:staff_settings')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = StaffSettingsForm(instance=therapist)

    context = {
        'form': form,
        'therapist': therapist,
    }
    return render(request, 'portals/staff_settings.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
#  NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='portals:login')
def notification_list(request):
    """View to list all notifications for the current user."""
    if not request.user.is_staff:
        return redirect('portals:login')

    role = request.session.get('portal_role', 'staff')
    
    if role == 'admin':
        notifications = StaffNotification.objects.filter(
            target_role__in=['admin', 'all']
        )
    else:
        from django.db.models import Q
        notifications = StaffNotification.objects.filter(
            target_role__in=['staff', 'all']
        )
        if hasattr(request.user, 'therapist_profile') and request.user.therapist_profile:
            notifications = notifications.filter(
                Q(target_therapist=request.user.therapist_profile) |
                Q(target_therapist__isnull=True)
            )
        else:
            notifications = notifications.filter(target_therapist__isnull=True)

    # Mark all unread notifications as read if button is pressed
    if request.method == 'POST' and request.POST.get('action') == 'mark_all_read':
        notifications.filter(is_read=False).update(is_read=True)
        return JsonResponse({'success': True})

    return render(request, 'portals/notification_list.html', {
        'notifications': notifications,
        'page_title': 'Notifications'
    })


@login_required(login_url='portals:login')
def notification_mark_read(request, pk):
    """AJAX endpoint to mark a single notification as read."""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    if request.method == 'POST':
        notification = get_object_or_404(StaffNotification, pk=pk)
        
        # Verify access
        role = request.session.get('portal_role', 'staff')
        if role == 'admin' and notification.target_role not in ['admin', 'all']:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        elif role == 'staff':
            if notification.target_role not in ['staff', 'all']:
                return JsonResponse({'error': 'Unauthorized'}, status=403)
            if notification.target_therapist and hasattr(request.user, 'therapist_profile'):
                if notification.target_therapist != request.user.therapist_profile:
                    return JsonResponse({'error': 'Unauthorized'}, status=403)
                    
        notification.is_read = True
        notification.save()
        return JsonResponse({'success': True})
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required(login_url='portals:login')
def live_counts(request):
    """AJAX endpoint that returns live notification/booking/message counts
    and the latest unread notifications for toast display."""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    role = request.session.get('portal_role', 'staff')

    # ── Notification count ──
    if role == 'admin':
        notif_qs = StaffNotification.objects.filter(
            is_read=False, target_role__in=['admin', 'all']
        )
    else:
        notif_qs = StaffNotification.objects.filter(
            is_read=False, target_role__in=['staff', 'all']
        )
        if hasattr(request.user, 'therapist_profile') and request.user.therapist_profile:
            notif_qs = notif_qs.filter(
                Q(target_therapist=request.user.therapist_profile) |
                Q(target_therapist__isnull=True)
            )
        else:
            notif_qs = notif_qs.filter(target_therapist__isnull=True)

    notif_count = notif_qs.count()

    # Get up to 5 latest unread notifications for toast display
    latest_notifs = list(notif_qs.order_by('-created_at')[:5].values(
        'id', 'title', 'message', 'notification_type', 'created_at'
    ))
    # Convert datetime to string for JSON serialization
    for n in latest_notifs:
        n['created_at'] = n['created_at'].isoformat()
        n['icon'] = StaffNotification.ICON_MAP.get(n['notification_type'], 'fa-bell')
        n['color'] = StaffNotification.COLOR_MAP.get(n['notification_type'], 'purple')

    # ── Other counts ──
    pending_count = Booking.objects.filter(status='pending').count()
    messages_count = ContactMessage.objects.filter(is_read=False).count() if role == 'admin' else 0

    return JsonResponse({
        'unread_notifications': notif_count,
        'pending_bookings': pending_count,
        'unread_messages': messages_count,
        'latest_notifications': latest_notifs,
    })

