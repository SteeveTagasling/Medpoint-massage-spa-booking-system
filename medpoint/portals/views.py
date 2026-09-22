import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Sum, Q, F
from django.utils import timezone
from django.conf import settings

from website.models import (
    Service, Therapist, Testimonial, GalleryImage,
    Booking, ContactMessage, MessageReply, StaffSchedule, StaffLeave,
    ServicePriceHistory,
)
from .forms import ServiceForm, TherapistForm, WalkInBookingForm, StaffScheduleForm, AdminSettingsForm, AdminUserForm, StaffSettingsForm, BulkStaffScheduleForm, StaffLeaveForm, StaffLeaveRequestForm
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
    total_bookings = Booking.objects.filter(is_verified=True).count()
    pending_bookings = Booking.objects.filter(status='pending', is_verified=True).count()
    confirmed_bookings = Booking.objects.filter(status='confirmed', is_verified=True).count()
    today_bookings = Booking.objects.filter(date=today).count()
    total_services = Service.objects.filter(is_active=True).count()
    total_therapists = Therapist.objects.filter(is_active=True).count()
    unread_messages = ContactMessage.objects.filter(is_read=False).count()
    online_bookings = Booking.objects.filter(booking_type='online', is_verified=True).count()
    walkin_bookings = Booking.objects.filter(booking_type='walk_in').count()
    recent_bookings = Booking.objects.filter(Q(booking_type='walk_in') | Q(is_verified=True)).select_related('therapist').prefetch_related('services').order_by('-created_at')[:8]

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


def revenue_chart_data(request):
    """API endpoint returning revenue chart data for the admin dashboard."""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    period = request.GET.get('period', 'week')  # day, week, month, year, custom
    today = timezone.now().date()

    if period == 'day':
        # 10:00 AM to 12:00 MN
        hour_sequence = list(range(10, 24)) + [0]
        labels = [f"{h:02d}:00" for h in hour_sequence]
        label_strs = labels  # string labels for day period
        date_range = [today]
    elif period == 'week':
        labels = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
        date_range = labels
        label_strs = [d.strftime('%a %b %d') for d in labels]
    elif period == 'month':
        # Last 30 days grouped by day
        labels = [(today - timedelta(days=i)) for i in range(29, -1, -1)]
        date_range = labels
        label_strs = [d.strftime('%b %d') for d in labels]
    elif period == 'custom':
        import datetime as _dt
        date_from_str = request.GET.get('date_from', None)
        date_to_str = request.GET.get('date_to', None)
        try:
            date_from = _dt.date.fromisoformat(date_from_str)
            date_to = _dt.date.fromisoformat(date_to_str)
        except (TypeError, ValueError):
            date_from = today
            date_to = today
        # Clamp to avoid absurdly long ranges (max 366 days)
        delta = (date_to - date_from).days
        if delta < 0:
            date_from, date_to = date_to, date_from
            delta = -delta
        if delta > 365:
            date_from = date_to - timedelta(days=365)
        num_days = (date_to - date_from).days + 1
        labels = [date_from + timedelta(days=i) for i in range(num_days)]
        date_range = labels
        if num_days <= 31:
            label_strs = [d.strftime('%b %d') for d in labels]
        elif num_days <= 366:
            label_strs = [d.strftime('%b %d') for d in labels]
        else:
            label_strs = [d.strftime('%b %d') for d in labels]
    else:  # year
        # Last 12 months
        from datetime import date as dt_date
        labels = []
        for i in range(11, -1, -1):
            month = today.month - i
            year = today.year
            while month < 1:
                month += 12
                year -= 1
            labels.append((year, month))
        label_strs = [dt_date(y, m, 1).strftime('%b %Y') for y, m in labels]

    therapists = Therapist.objects.filter(is_active=True).order_by('name')

    # Build datasets per therapist
    datasets = []
    total_by_label = {}

    # Palette of nice colors for each therapist line
    palette = [
        ('rgba(168,85,247,1)', 'rgba(168,85,247,0.15)'),
        ('rgba(96,165,250,1)', 'rgba(96,165,250,0.15)'),
        ('rgba(52,211,153,1)', 'rgba(52,211,153,0.15)'),
        ('rgba(251,191,36,1)', 'rgba(251,191,36,0.15)'),
        ('rgba(248,113,113,1)', 'rgba(248,113,113,0.15)'),
        ('rgba(167,243,208,1)', 'rgba(167,243,208,0.15)'),
        ('rgba(196,181,253,1)', 'rgba(196,181,253,0.15)'),
        ('rgba(253,186,116,1)', 'rgba(253,186,116,0.15)'),
    ]

    for idx, therapist in enumerate(therapists):
        color, bg = palette[idx % len(palette)]

        # Get completed bookings for this therapist
        qs = Booking.objects.filter(
            therapist=therapist, status='completed'
        ).prefetch_related('services')

        if period == 'day':
            qs = qs.filter(date=today)
            # Group by hour string label (e.g. '10:00')
            revenue_map = {}
            for b in qs:
                hour = 0
                if b.time:
                    try:
                        hour = int(str(b.time).split(':')[0])
                    except (ValueError, TypeError, AttributeError):
                        hour = 0
                lbl_key = f"{hour:02d}:00"
                rev = sum(s.discounted_price for s in b.services.all())
                revenue_map[lbl_key] = revenue_map.get(lbl_key, Decimal('0')) + rev
            data = [float(revenue_map.get(lbl, 0)) for lbl in label_strs]
        elif period in ('week', 'month', 'custom'):
            qs = qs.filter(date__in=date_range)
            revenue_map = {}
            for b in qs:
                rev = sum(s.discounted_price for s in b.services.all())
                revenue_map[b.date] = revenue_map.get(b.date, Decimal('0')) + rev
            data = [float(revenue_map.get(d, 0)) for d in date_range]
        else:  # year
            revenue_map = {}
            for b in qs:
                key = (b.date.year, b.date.month)
                rev = sum(s.discounted_price for s in b.services.all())
                revenue_map[key] = revenue_map.get(key, Decimal('0')) + rev
            data = [float(revenue_map.get(lbl, 0)) for lbl in labels]

        # Add to totals using the string label
        for i, val in enumerate(data):
            lbl = label_strs[i]
            total_by_label[lbl] = total_by_label.get(lbl, 0) + val

        datasets.append({
            'label': therapist.name,
            'data': data,
            'borderColor': color,
            'backgroundColor': bg,
            'tension': 0.4,
            'pointRadius': 4,
            'pointHoverRadius': 7,
            'borderWidth': 2.5,
            'fill': False,
        })

    # Total revenue across all therapists per label
    final_labels = label_strs
    total_data = [total_by_label.get(lbl, 0) for lbl in label_strs]

    total_revenue = sum(total_data)

    return JsonResponse({
        'labels': final_labels,
        'datasets': datasets,
        'total_revenue': float(total_revenue),
        'period': period,
    })


def _staff_dashboard(request):
    """Dashboard for staff/therapist role."""
    from decimal import Decimal
    therapist = _get_staff_therapist(request)
    today = timezone.now().date()

    if therapist:
        my_bookings_today = Booking.objects.filter(
            therapist=therapist, date=today
        ).exclude(status='cancelled').prefetch_related('services').order_by('time')
        my_completed_bookings = Booking.objects.filter(
            therapist=therapist, status='completed'
        ).prefetch_related('services')
        
        my_total_completed = my_completed_bookings.count()
        my_pending = Booking.objects.filter(
            therapist=therapist, status='pending', is_verified=True
        ).count()
        
        # Calculate Unique Customers
        # Using a set of lowercased emails for simplicity or names if email is blank
        customers = set()
        total_income = Decimal('0')
        
        for b in my_completed_bookings:
            customers.add(b.client_email.lower().strip() or b.client_name.lower().strip())
            total_income += sum(svc.discounted_price for svc in b.services.all()) * (therapist.commission_percentage / Decimal('100'))
            
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
    show_filter = request.GET.get('show', '')  # '' = active, 'archived' = archived

    base_qs = Booking.objects.filter(Q(booking_type='walk_in') | Q(is_verified=True)).select_related('therapist').prefetch_related('services').order_by('-created_at')

    if show_filter == 'archived':
        bookings = base_qs.filter(is_archived=True)
    else:
        bookings = base_qs.filter(is_archived=False)

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
        bookings = bookings.filter(services__id=service_filter)

    services = Service.objects.all()
    active_count = base_qs.filter(is_archived=False).count()
    archived_count = base_qs.filter(is_archived=True).count()

    context = {
        'bookings': bookings,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'date_filter': date_filter,
        'service_filter': service_filter,
        'search': search,
        'show_filter': show_filter,
        'active_count': active_count,
        'archived_count': archived_count,
        'status_choices': [c for c in Booking.STATUS_CHOICES if c[0] != 'awaiting_verification'],
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
        old_status = booking.status
        new_status = request.POST.get('status')
        if new_status == 'cancelled' and not request.user.is_superuser:
            return JsonResponse({'error': 'Only admins can cancel bookings.'}, status=403)
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

            # Send confirmation email to client when status changes to 'confirmed'
            if new_status == 'confirmed' and old_status != 'confirmed' and booking.client_email:
                try:
                    from django.core.mail import send_mail
                    from django.conf import settings

                    therapist_name = booking.therapist.name if booking.therapist else 'To be assigned'
                    time_display = dict(booking.TIME_CHOICES).get(booking.time, booking.time)
                    date_display = booking.date.strftime('%B %d, %Y')

                    subject = f'Your Booking is Confirmed – Medpoint Massage & Spa'

                    plain_message = (
                        f"Hi {booking.client_name},\n\n"
                        f"Your booking at Medpoint Massage & Spa has been CONFIRMED!\n\n"
                        f"Booking Details:\n"
                        f"  Reference #: {booking.pk:04d}\n"
                        f"  Services: {booking.service_names}\n"
                        f"  Therapist: {therapist_name}\n"
                        f"  Date: {date_display}\n"
                        f"  Time: {time_display}\n\n"
                        f"Please arrive 15 minutes before your scheduled time.\n"
                        f"If you need to reschedule, please contact us as soon as possible.\n\n"
                        f"Thank you for choosing Medpoint Massage & Spa!\n"
                        f"– The Medpoint Team"
                    )

                    html_message = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;background-color:#0f0f15;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 16px;">

    <!-- Logo Header -->
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
           style="max-width:560px;margin:0 auto 0;background:linear-gradient(135deg,#4a1a7a 0%,#2d1060 50%,#1a0845 100%);
                  border-radius:16px 16px 0 0;overflow:hidden;">
      <tr>
        <td align="center" style="padding:32px 32px 28px;">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0">
            <tr>
              <td align="center">
                <span style="font-size:24px;font-weight:700;letter-spacing:4px;
                             color:#ffffff;font-family:Georgia,serif;">MEDPOINT</span>
                <br/>
                <span style="font-size:11px;letter-spacing:2px;color:#c084fc;
                             text-transform:uppercase;margin-top:4px;display:block;">
                  Massage &amp; Spa
                </span>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>

    <!-- Card -->
    <div style="background:#1a1a2e;border-radius:0 0 18px 18px;overflow:hidden;border:1px solid rgba(255,255,255,0.08);border-top:none;max-width:560px;margin:0 auto;">

      <!-- Green confirmed banner -->
      <div style="background:linear-gradient(135deg,#16a34a,#15803d);padding:28px 32px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">Booking Confirmed!</h1>
        <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">Your appointment has been approved.</p>
      </div>

      <!-- Body -->
      <div style="padding:28px 32px;">
        <p style="margin:0 0 20px;color:#c8c8d8;font-size:15px;">Hi <strong style="color:#fff;">{booking.client_name}</strong>,</p>
        <p style="margin:0 0 24px;color:#c8c8d8;font-size:14px;line-height:1.6;">
          Great news! Your booking at <strong style="color:#a78bfa;">Medpoint Massage &amp; Spa</strong> has been confirmed.
          We look forward to seeing you!
        </p>

        <!-- Details box -->
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:20px 24px;margin-bottom:24px;">
          <h3 style="margin:0 0 16px;color:#a78bfa;font-size:12px;text-transform:uppercase;letter-spacing:0.08em;">Booking Details</h3>

          <table style="width:100%;border-collapse:collapse;">
            <tr>
              <td style="padding:7px 0;color:#888;font-size:13px;width:40%;">Reference #</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">#{booking.pk:04d}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Service(s)</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;">{booking.service_names}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Therapist</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;">{therapist_name}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Date</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">{date_display}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Time</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">{time_display}</td>
            </tr>
          </table>
        </div>

        <!-- Reminder -->
        <div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);border-radius:10px;padding:14px 18px;margin-bottom:24px;">
          <p style="margin:0;color:#f87171;font-size:13px;line-height:1.55;">
            Please arrive <strong>15 minutes early</strong> to complete any paperwork and prepare for your session.
          </p>
        </div>

        <p style="margin:0;color:#666;font-size:13px;line-height:1.6;">
          Need to reschedule or have questions? Please contact us as soon as possible so we can assist you.
        </p>
      </div>

      <!-- Footer -->
      <div style="border-top:1px solid rgba(255,255,255,0.06);padding:18px 32px;text-align:center;">
        <p style="margin:0;color:#555;font-size:12px;">
          © Medpoint Massage &amp; Spa &nbsp;|&nbsp; Thank you for choosing us!
        </p>
      </div>
    </div>
  </div>
</body>
</html>
"""
                    send_mail(
                        subject=subject,
                        message=plain_message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[booking.client_email],
                        html_message=html_message,
                        fail_silently=True,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f'Failed to send booking confirmation email: {e}')

            # Send completion email to client when status changes to 'completed'
            if new_status == 'completed' and old_status != 'completed' and booking.client_email:
                try:
                    from django.core.mail import send_mail
                    from django.conf import settings

                    therapist_name = booking.therapist.name if booking.therapist else 'Our therapist'
                    time_display = dict(booking.TIME_CHOICES).get(booking.time, booking.time)
                    date_display = booking.date.strftime('%B %d, %Y')

                    subject = f'Your Session is Complete – Thank You! | Medpoint Massage & Spa'

                    plain_message = (
                        f"Hi {booking.client_name},\n\n"
                        f"Your appointment at Medpoint Massage & Spa has been marked as COMPLETED.\n\n"
                        f"Booking Details:\n"
                        f"  Reference #: {booking.pk:04d}\n"
                        f"  Services: {booking.service_names}\n"
                        f"  Therapist: {therapist_name}\n"
                        f"  Date: {date_display}\n"
                        f"  Time: {time_display}\n\n"
                        f"We hope you enjoyed your experience!\n"
                        f"We'd love to see you again. Book your next session with us anytime.\n\n"
                        f"Thank you for choosing Medpoint Massage & Spa!\n"
                        f"– The Medpoint Team"
                    )

                    html_message = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;background-color:#0f0f15;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 16px;">

    <!-- Logo Header -->
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
           style="max-width:560px;margin:0 auto;background:linear-gradient(135deg,#4a1a7a 0%,#2d1060 50%,#1a0845 100%);
                  border-radius:16px 16px 0 0;overflow:hidden;">
      <tr>
        <td align="center" style="padding:32px 32px 28px;">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0">
            <tr>
              <td align="center">
                <span style="font-size:24px;font-weight:700;letter-spacing:4px;
                             color:#ffffff;font-family:Georgia,serif;">MEDPOINT</span>
                <br/>
                <span style="font-size:11px;letter-spacing:2px;color:#c084fc;
                             text-transform:uppercase;margin-top:4px;display:block;">
                  Massage &amp; Spa
                </span>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>

    <!-- Card -->
    <div style="background:#1a1a2e;border-radius:0 0 18px 18px;overflow:hidden;border:1px solid rgba(255,255,255,0.08);border-top:none;max-width:560px;margin:0 auto;">

      <!-- Teal completed banner -->
      <div style="background:linear-gradient(135deg,#0e7490,#0891b2);padding:28px 32px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">Session Completed!</h1>
        <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">Thank you for visiting us.</p>
      </div>

      <!-- Body -->
      <div style="padding:28px 32px;">
        <p style="margin:0 0 20px;color:#c8c8d8;font-size:15px;">Hi <strong style="color:#fff;">{booking.client_name}</strong>,</p>
        <p style="margin:0 0 24px;color:#c8c8d8;font-size:14px;line-height:1.6;">
          Your session at <strong style="color:#a78bfa;">Medpoint Massage &amp; Spa</strong> has been completed.
          We hope it was a relaxing and enjoyable experience. We'd love to see you again!
        </p>

        <!-- Details box -->
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:20px 24px;margin-bottom:24px;">
          <h3 style="margin:0 0 16px;color:#a78bfa;font-size:12px;text-transform:uppercase;letter-spacing:0.08em;">Booking Summary</h3>
          <table style="width:100%;border-collapse:collapse;">
            <tr>
              <td style="padding:7px 0;color:#888;font-size:13px;width:40%;">Reference #</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">#{booking.pk:04d}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Service(s)</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;">{booking.service_names}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Therapist</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;">{therapist_name}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Date</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">{date_display}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Time</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">{time_display}</td>
            </tr>
          </table>
        </div>

        <p style="margin:0;color:#666;font-size:13px;line-height:1.6;">
          Book your next session anytime by visiting our website. We look forward to serving you again!
        </p>
      </div>

      <!-- Footer -->
      <div style="border-top:1px solid rgba(255,255,255,0.06);padding:18px 32px;text-align:center;">
        <p style="margin:0;color:#555;font-size:12px;">
          © Medpoint Massage &amp; Spa &nbsp;|&nbsp; Thank you for choosing us!
        </p>
      </div>
    </div>
  </div>
</body>
</html>
"""
                    send_mail(
                        subject=subject,
                        message=plain_message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[booking.client_email],
                        html_message=html_message,
                        fail_silently=True,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f'Failed to send booking completed email: {e}')

            # Send cancellation email to client when status changes to 'cancelled'
            if new_status == 'cancelled' and old_status != 'cancelled' and booking.client_email:
                try:
                    from django.core.mail import send_mail
                    from django.conf import settings

                    therapist_name = booking.therapist.name if booking.therapist else 'To be assigned'
                    time_display = dict(booking.TIME_CHOICES).get(booking.time, booking.time)
                    date_display = booking.date.strftime('%B %d, %Y')

                    subject = f'Your Booking Has Been Cancelled – Medpoint Massage & Spa'

                    plain_message = (
                        f"Hi {booking.client_name},\n\n"
                        f"We're sorry to inform you that your booking at Medpoint Massage & Spa has been CANCELLED.\n\n"
                        f"Booking Details:\n"
                        f"  Reference #: {booking.pk:04d}\n"
                        f"  Services: {booking.service_names}\n"
                        f"  Therapist: {therapist_name}\n"
                        f"  Date: {date_display}\n"
                        f"  Time: {time_display}\n\n"
                        f"If you have any questions, please contact us and we'll be happy to assist.\n"
                        f"You may book a new appointment at any time.\n\n"
                        f"We hope to see you soon!\n"
                        f"– The Medpoint Team"
                    )

                    html_message = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;background-color:#0f0f15;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 16px;">

    <!-- Logo Header -->
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
           style="max-width:560px;margin:0 auto;background:linear-gradient(135deg,#4a1a7a 0%,#2d1060 50%,#1a0845 100%);
                  border-radius:16px 16px 0 0;overflow:hidden;">
      <tr>
        <td align="center" style="padding:32px 32px 28px;">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0">
            <tr>
              <td align="center">
                <span style="font-size:24px;font-weight:700;letter-spacing:4px;
                             color:#ffffff;font-family:Georgia,serif;">MEDPOINT</span>
                <br/>
                <span style="font-size:11px;letter-spacing:2px;color:#c084fc;
                             text-transform:uppercase;margin-top:4px;display:block;">
                  Massage &amp; Spa
                </span>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>

    <!-- Card -->
    <div style="background:#1a1a2e;border-radius:0 0 18px 18px;overflow:hidden;border:1px solid rgba(255,255,255,0.08);border-top:none;max-width:560px;margin:0 auto;">

      <!-- Red cancelled banner -->
      <div style="background:linear-gradient(135deg,#b91c1c,#991b1b);padding:28px 32px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">Booking Cancelled</h1>
        <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">Your appointment has been cancelled.</p>
      </div>

      <!-- Body -->
      <div style="padding:28px 32px;">
        <p style="margin:0 0 20px;color:#c8c8d8;font-size:15px;">Hi <strong style="color:#fff;">{booking.client_name}</strong>,</p>
        <p style="margin:0 0 24px;color:#c8c8d8;font-size:14px;line-height:1.6;">
          We're sorry to inform you that your booking at <strong style="color:#a78bfa;">Medpoint Massage &amp; Spa</strong> has been cancelled.
          Please contact us if you'd like to reschedule or if you have any questions.
        </p>

        <!-- Details box -->
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:20px 24px;margin-bottom:24px;">
          <h3 style="margin:0 0 16px;color:#a78bfa;font-size:12px;text-transform:uppercase;letter-spacing:0.08em;">Cancelled Booking</h3>
          <table style="width:100%;border-collapse:collapse;">
            <tr>
              <td style="padding:7px 0;color:#888;font-size:13px;width:40%;">Reference #</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">#{booking.pk:04d}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Service(s)</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;">{booking.service_names}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Therapist</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;">{therapist_name}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Date</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">{date_display}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Time</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">{time_display}</td>
            </tr>
          </table>
        </div>

        <p style="margin:0;color:#666;font-size:13px;line-height:1.6;">
          We hope to see you again. You may book a new appointment at any time on our website.
        </p>
      </div>

      <!-- Footer -->
      <div style="border-top:1px solid rgba(255,255,255,0.06);padding:18px 32px;text-align:center;">
        <p style="margin:0;color:#555;font-size:12px;">
          © Medpoint Massage &amp; Spa &nbsp;|&nbsp; We hope to serve you again!
        </p>
      </div>
    </div>
  </div>
</body>
</html>
"""
                    send_mail(
                        subject=subject,
                        message=plain_message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[booking.client_email],
                        html_message=html_message,
                        fail_silently=True,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f'Failed to send booking cancellation email: {e}')

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

            # Snapshot service prices at time of booking
            snapshots = []
            total_lock = Decimal('0')
            for svc in booking_obj.services.all():
                snapshots.append({
                    'service_id': svc.id,
                    'name': svc.name,
                    'base_price': float(svc.price),
                    'discount_percentage': float(svc.discount_percentage),
                    'discounted_price': float(svc.discounted_price),
                })
                total_lock += svc.discounted_price
            booking_obj.locked_price = total_lock
            booking_obj.service_prices_snapshot = snapshots
            booking_obj.save(update_fields=['locked_price', 'service_prices_snapshot'])

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
                if _is_staff_only(request):
                    return redirect('portals:staff_my_bookings')
                return redirect('portals:booking_list')

            # Create notification for client
            BookingNotification.objects.create(
                booking=booking_obj,
                notification_type='confirmed',
                message=(
                    f"Your walk-in booking for {booking_obj.service_names} on "
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

            # Create portal notification for admin when created by staff
            if _is_staff_only(request):
                from django.urls import reverse
                StaffNotification.objects.create(
                    notification_type='new_booking',
                    title='New Walk-in Booking',
                    message=f"Staff {request.user.get_full_name() or request.user.username} created walk-in booking #{booking_obj.pk:04d}.",
                    target_role='admin',
                    link=reverse('portals:booking_list')
                )

            messages.success(request, f'Walk-in booking #{booking_obj.pk:04d} created successfully.')
            if _is_staff_only(request):
                return redirect('portals:staff_my_bookings')
            return redirect('portals:booking_list')
        else:
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
    else:
        form = WalkInBookingForm(initial={
            'date': timezone.localtime(timezone.now()).date(),
            'status': 'confirmed',
        })
    staff_therapist = _get_staff_therapist(request) if _is_staff_only(request) else None
    return render(request, 'portals/booking_walkin.html', {
        'form': form,
        'services_list': Service.objects.filter(is_active=True),
        'current_therapist_id': staff_therapist.id if staff_therapist else None,
    })


@login_required(login_url='portals:login')
def booking_delete(request, pk):
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required(login_url='portals:login')
def booking_archive(request, pk):
    """Admin: Archive a single booking."""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    booking = get_object_or_404(Booking, pk=pk)
    booking.is_archived = True
    booking.save(update_fields=['is_archived'])
    return JsonResponse({'success': True, 'is_archived': True})


@login_required(login_url='portals:login')
def booking_restore(request, pk):
    """Admin: Restore an archived booking back to the active list."""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    booking = get_object_or_404(Booking, pk=pk)
    booking.is_archived = False
    booking.save(update_fields=['is_archived'])
    return JsonResponse({'success': True, 'is_archived': False})


@login_required(login_url='portals:login')
def booking_bulk_archive(request):
    """Admin: Bulk-archive bookings."""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    import json as _json
    try:
        data = _json.loads(request.body)
        ids = [int(i) for i in data.get('ids', [])]
    except Exception:
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    Booking.objects.filter(pk__in=ids).update(is_archived=True)
    return JsonResponse({'success': True, 'count': len(ids)})


@login_required(login_url='portals:login')
def booking_bulk_restore(request):
    """Admin: Bulk-restore archived bookings."""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    import json as _json
    try:
        data = _json.loads(request.body)
        ids = [int(i) for i in data.get('ids', [])]
    except Exception:
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    Booking.objects.filter(pk__in=ids).update(is_archived=False)
    return JsonResponse({'success': True, 'count': len(ids)})


@login_required(login_url='portals:login')
def booking_delete(request, pk):
    """Admin: Permanently delete an archived booking (superuser only)."""
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    booking = get_object_or_404(Booking, pk=pk)
    booking.delete()
    return JsonResponse({'success': True})


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
            service = form.save()
            from website.models import ServicePriceHistory
            ServicePriceHistory.objects.create(
                service=service,
                base_price=service.price,
                discount_percentage=service.discount_percentage,
                effective_from=timezone.now().date(),
                notes="Initial Established Rate"
            )
            messages.success(request, 'Service created successfully.')
            return redirect('portals:service_list')
        else:
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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
    old_price = service.price
    old_discount = service.discount_percentage
    if request.method == 'POST':
        form = ServiceForm(request.POST, request.FILES, instance=service)
        if form.is_valid():
            service = form.save()
            if service.price != old_price or service.discount_percentage != old_discount:
                from website.models import ServicePriceHistory
                today = timezone.now().date()
                # Close previous active record
                ServicePriceHistory.objects.filter(service=service, effective_to__isnull=True).update(effective_to=today)
                note_parts = []
                if service.price != old_price:
                    note_parts.append(f"Price: ₱{old_price} ➔ ₱{service.price}")
                if service.discount_percentage != old_discount:
                    note_parts.append(f"Discount: {old_discount}% ➔ {service.discount_percentage}%")
                ServicePriceHistory.objects.create(
                    service=service,
                    base_price=service.price,
                    discount_percentage=service.discount_percentage,
                    effective_from=today,
                    notes=", ".join(note_parts) or "Price Adjusted"
                )
            messages.success(request, f'"{service.name}" updated successfully.')
            return redirect('portals:service_list')
        else:
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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
        # Deactivate instead of delete
        if therapist.is_active:
            therapist.is_active = False
            messages.success(request, f'"{name}" deactivated successfully.')
        else:
            therapist.is_active = True
            messages.success(request, f'"{name}" reactivated successfully.')
        therapist.save(update_fields=['is_active'])
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
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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
        # Prevent self-deactivation
        if admin_user == request.user:
            messages.error(request, 'You cannot deactivate your own admin account.')
        else:
            username = admin_user.username
            if admin_user.is_active:
                admin_user.is_active = False
                messages.success(request, f'Admin "{username}" deactivated successfully.')
            else:
                admin_user.is_active = True
                messages.success(request, f'Admin "{username}" reactivated successfully.')
            admin_user.save(update_fields=['is_active'])
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
    
    context = {
        'grouped_schedules': grouped_schedules,
        'therapists': therapists,
        'therapist_filter': therapist_filter,
        'status_filter': status_filter,
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
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
    else:
        form = BulkStaffScheduleForm()
    return render(request, 'portals/schedule_form.html', {'form': form, 'action': 'Assign'})


# ─── Staff Leave — Booking Cancellation Helpers ──────────────────────────────

def _send_leave_cancellation_email(booking, leave, rebook_url):
    """Send a premium HTML email to a client whose booking was cancelled due to staff leave."""
    import logging
    from django.core.mail import send_mail
    from django.conf import settings

    therapist_name = booking.therapist.name if booking.therapist else 'Your therapist'
    time_display = dict(booking.TIME_CHOICES).get(booking.time, booking.time)
    date_display = booking.date.strftime('%B %d, %Y')
    services_str = booking.service_names
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Medpoint Massage & Spa <noreply@medpoint.com>')

    subject = 'Important Update About Your Booking – Medpoint Massage & Spa'

    plain_message = (
        f"Hi {booking.client_name},\n\n"
        f"We regret to inform you that your booking at Medpoint Massage & Spa has been cancelled because "
        f"{therapist_name} is unexpectedly unavailable on {date_display}.\n\n"
        f"Cancelled Booking Details:\n"
        f"  Reference #: {booking.pk:04d}\n"
        f"  Services: {services_str}\n"
        f"  Date: {date_display}\n"
        f"  Time: {time_display}\n\n"
        f"We sincerely apologize for the inconvenience. You can rebook by visiting the link below:\n"
        f"{rebook_url}\n\n"
        f"From that page, you may:\n"
        f"  - Choose a different available therapist for the same date and time, or\n"
        f"  - Reschedule your appointment to a new date.\n\n"
        f"Thank you for your understanding.\n"
        f"– The Medpoint Team"
    )

    html_message = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Important Update – Medpoint Massage & Spa</title>
</head>
<body style="margin:0;padding:0;background-color:#0f0f15;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:580px;margin:0 auto;padding:32px 16px;">

    <!-- Logo Header -->
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
           style="max-width:580px;margin:0 auto;background:linear-gradient(135deg,#4a1a7a 0%,#2d1060 50%,#1a0845 100%);
                  border-radius:16px 16px 0 0;overflow:hidden;">
      <tr>
        <td align="center" style="padding:32px 32px 28px;">
          <span style="font-size:24px;font-weight:700;letter-spacing:4px;
                       color:#ffffff;font-family:Georgia,serif;">MEDPOINT</span><br/>
          <span style="font-size:11px;letter-spacing:2px;color:#c084fc;
                       text-transform:uppercase;margin-top:4px;display:block;">Massage &amp; Spa</span>
        </td>
      </tr>
    </table>

    <!-- Card -->
    <div style="background:#1a1a2e;border-radius:0 0 18px 18px;overflow:hidden;
                border:1px solid rgba(255,255,255,0.08);border-top:none;max-width:580px;margin:0 auto;">

      <!-- Amber alert banner -->
      <div style="background:linear-gradient(135deg,#b45309,#92400e);padding:28px 32px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:21px;font-weight:700;">Booking Cancelled – Action Required</h1>
        <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">Your therapist is unexpectedly unavailable.</p>
      </div>

      <!-- Body -->
      <div style="padding:28px 32px;">
        <p style="margin:0 0 18px;color:#c8c8d8;font-size:15px;">Hi <strong style="color:#fff;">{booking.client_name}</strong>,</p>
        <p style="margin:0 0 20px;color:#c8c8d8;font-size:14px;line-height:1.7;">
          We sincerely apologize, but we had to cancel your booking at
          <strong style="color:#a78bfa;">Medpoint Massage &amp; Spa</strong> because
          <strong style="color:#fbbf24;">{therapist_name}</strong> is unexpectedly unavailable on <strong style="color:#fbbf24;">{date_display}</strong>.
          We understand this is inconvenient and we are very sorry.
        </p>

        <!-- Details box -->
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
                    border-radius:12px;padding:20px 24px;margin-bottom:24px;">
          <h3 style="margin:0 0 14px;color:#a78bfa;font-size:12px;text-transform:uppercase;letter-spacing:0.08em;">Cancelled Booking</h3>
          <table style="width:100%;border-collapse:collapse;">
            <tr>
              <td style="padding:7px 0;color:#888;font-size:13px;width:38%;">Reference #</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;font-weight:600;">#{booking.pk:04d}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Service(s)</td>
              <td style="padding:7px 0;color:#fff;font-size:13px;">{services_str}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Date</td>
              <td style="padding:7px 0;color:#fbbf24;font-size:13px;font-weight:600;">{date_display}</td>
            </tr>
            <tr style="border-top:1px solid rgba(255,255,255,0.05);">
              <td style="padding:7px 0;color:#888;font-size:13px;">Time</td>
              <td style="padding:7px 0;color:#fbbf24;font-size:13px;font-weight:600;">{time_display}</td>
            </tr>
          </table>
        </div>

        <!-- What to do next -->
        <div style="background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.2);
                    border-radius:12px;padding:20px 24px;margin-bottom:24px;">
          <h3 style="margin:0 0 12px;color:#c4b5fd;font-size:13px;font-weight:600;">What would you like to do?</h3>
          <p style="margin:0 0 8px;color:#9ca3af;font-size:13px;line-height:1.6;">
            Click the button below to choose one of these options:
          </p>
          <ul style="margin:0 0 16px;padding-left:20px;color:#9ca3af;font-size:13px;line-height:2;">
            <li><strong style="color:#c4b5fd;">Choose a different therapist</strong> &mdash; keep the same date &amp; time</li>
            <li><strong style="color:#c4b5fd;">Reschedule to a new date</strong> &mdash; your services will be pre-filled</li>
          </ul>
          <a href="{rebook_url}"
             style="display:inline-block;padding:13px 28px;background:linear-gradient(135deg,#7c3aed,#6d28d9);
                    color:#fff;font-size:14px;font-weight:700;text-decoration:none;
                    border-radius:10px;margin-top:4px;">
            Rebook My Appointment
          </a>
        </div>

        <p style="margin:0;color:#555;font-size:12px;line-height:1.6;">
          This link is unique to your booking and can only be used once.
          If you need further assistance, please contact us at
          <a href="mailto:medpointmassage.spa@gmail.com" style="color:#a78bfa;">medpointmassage.spa@gmail.com</a>.
        </p>
      </div>

      <!-- Footer -->
      <div style="border-top:1px solid rgba(255,255,255,0.06);padding:18px 32px;text-align:center;">
        <p style="margin:0;color:#555;font-size:12px;">
          &copy; Medpoint Massage &amp; Spa &nbsp;|&nbsp; We look forward to serving you!
        </p>
      </div>
    </div>
  </div>
</body>
</html>"""

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=from_email,
            recipient_list=[booking.client_email],
            html_message=html_message,
            fail_silently=True,
        )
    except Exception as e:
        logging.getLogger(__name__).warning(f'Failed to send leave-cancellation email to {booking.client_email}: {e}')


def _cancel_bookings_for_leave(leave, request=None):
    """
    Auto-cancel all pending/confirmed bookings for a therapist during their leave.
    Sends a leave-cancellation email to each client with a secure rebooking link.
    Returns the number of bookings cancelled.
    """
    import uuid as uuid_module
    from django.urls import reverse
    from website.models import BookingNotification

    # Bookings that still need to be cancelled (active)
    pending_affected = Booking.objects.filter(
        therapist=leave.therapist,
        date__gte=leave.start_date,
        date__lte=leave.end_date,
        status__in=['pending', 'confirmed'],
        is_archived=False,
    ).select_related('therapist').prefetch_related('services')

    # Bookings already cancelled in this period but never sent a rebook token/email
    already_cancelled_no_token = Booking.objects.filter(
        therapist=leave.therapist,
        date__gte=leave.start_date,
        date__lte=leave.end_date,
        status='cancelled',
        rebooking_token__isnull=True,
        is_archived=False,
    ).select_related('therapist').prefetch_related('services')

    from django.db.models import QuerySet
    from itertools import chain
    affected = list(chain(pending_affected, already_cancelled_no_token))

    cancelled_count = 0
    for booking in affected:
        # Generate a fresh rebooking token
        booking.rebooking_token = uuid_module.uuid4()
        booking.status = 'cancelled'
        booking.save(update_fields=['status', 'rebooking_token'])
        cancelled_count += 1

        # Build the public absolute rebooking URL
        path = reverse('website:rebooking_options', args=[str(booking.rebooking_token)])
        base_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
        rebook_url = None

        if request:
            try:
                candidate = request.build_absolute_uri(path)
                if candidate and candidate.startswith(('http://', 'https://')) and not candidate.startswith(('http:///', 'https:///')):
                    rebook_url = candidate
            except Exception:
                pass

        if not rebook_url:
            clean_path = '/' + path.lstrip('/')
            rebook_url = f"{base_url}{clean_path}"

        # Send the leave-cancellation email
        _send_leave_cancellation_email(booking, leave, rebook_url)

        # Create a client-facing booking notification
        BookingNotification.objects.create(
            booking=booking,
            notification_type='cancelled',
            message=(
                f"Your booking #{booking.pk:04d} for {booking.service_names} on "
                f"{booking.date.strftime('%B %d, %Y')} was cancelled because "
                f"your therapist is on leave. Please check your email to rebook."
            ),
        )

        # Notify admin portal
        StaffNotification.objects.create(
            notification_type='booking_cancelled',
            title='Booking Auto-Cancelled (Staff Leave)',
            message=(
                f"Booking #{booking.pk:04d} ({booking.client_name}) was automatically "
                f"cancelled due to {leave.therapist.name}'s approved leave."
            ),
            target_role='admin',
        )

    return cancelled_count


@login_required(login_url='portals:login')
def staff_assign_leave(request):
    """Admin-only: directly assign leave (auto-approved)."""
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check

    if request.method == 'POST':
        form = StaffLeaveForm(request.POST)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.status = StaffLeave.STATUS_APPROVED
            leave.save()
            cancelled_count = _cancel_bookings_for_leave(leave, request)
            if cancelled_count:
                messages.warning(
                    request,
                    f'{cancelled_count} booking(s) during this leave period were automatically '
                    f'cancelled and clients have been notified by email.'
                )
            messages.success(request, 'Leave assigned and approved successfully.')
            return redirect('portals:admin_leave_list')
        else:
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
    else:
        form = StaffLeaveForm()

    return render(request, 'portals/staff_leave_form.html', {'form': form})


@login_required(login_url='portals:login')
def staff_apply_leave(request):
    """Staff-only: submit a leave request (status=pending)."""
    if not request.user.is_staff:
        return redirect('portals:login')
    try:
        therapist = request.user.therapist_profile
    except Exception:
        messages.error(request, 'Your account is not linked to a therapist profile. Contact your admin.')
        return redirect('portals:staff_my_schedule')

    if request.method == 'POST':
        form = StaffLeaveRequestForm(request.POST)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.therapist = therapist
            leave.status = StaffLeave.STATUS_PENDING

            # Check for booking conflicts during the requested leave dates
            start_date = form.cleaned_data['start_date']
            end_date = form.cleaned_data['end_date']
            conflicting_bookings = Booking.objects.filter(
                therapist=therapist,
                date__gte=start_date,
                date__lte=end_date,
                status__in=['pending', 'confirmed'],
                is_archived=False,
            )

            leave.save()
            conflict_count = conflicting_bookings.count()
            if conflict_count > 0:
                messages.warning(
                    request,
                    f'Your leave request has been submitted for admin approval. Note: You have {conflict_count} '
                    f'booking(s) during this period. If approved by admin, clients will be automatically notified with rebooking options.'
                )
            else:
                messages.success(request, 'Your leave request has been submitted and is awaiting admin approval.')
            return redirect('portals:staff_my_schedule')
        else:
            pass  # form errors are rendered via form.non_field_errors in the template
    else:
        form = StaffLeaveRequestForm()

    my_leaves = StaffLeave.objects.filter(therapist=therapist).order_by('-start_date')
    return render(request, 'portals/staff_leave_apply.html', {'form': form, 'my_leaves': my_leaves})


@login_required(login_url='portals:login')
def staff_delete_leave(request, pk):
    """Staff-only: delete their own pending leave request."""
    if not request.user.is_staff:
        return redirect('portals:login')
    try:
        therapist = request.user.therapist_profile
    except Exception:
        messages.error(request, 'Your account is not linked to a therapist profile.')
        return redirect('portals:staff_apply_leave')

    if request.method == 'POST':
        leave = get_object_or_404(StaffLeave, pk=pk, therapist=therapist)
        if leave.status == StaffLeave.STATUS_APPROVED:
            messages.error(request, 'You cannot delete an approved leave. Contact your admin to revoke it.')
        else:
            leave.delete()
            messages.success(request, 'Leave request has been deleted.')
    return redirect('portals:staff_apply_leave')

@login_required(login_url='portals:login')
def admin_leave_list(request):
    """Admin-only: view and manage all staff leave requests."""
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check

    status_filter = request.GET.get('status', '')
    therapist_filter = request.GET.get('therapist', '')

    leaves = StaffLeave.objects.select_related('therapist').all().order_by('-created_at')
    if status_filter:
        leaves = leaves.filter(status=status_filter)
    if therapist_filter:
        leaves = leaves.filter(therapist_id=therapist_filter)

    therapists = Therapist.objects.filter(is_active=True)
    pending_count = StaffLeave.objects.filter(status=StaffLeave.STATUS_PENDING).count()

    today = timezone.localdate()
    leaves_list = list(leaves)
    for l in leaves_list:
        l.is_past = l.end_date < today
        if l.status == StaffLeave.STATUS_APPROVED:
            l.cancelled_count = Booking.objects.filter(
                therapist=l.therapist,
                date__gte=l.start_date,
                date__lte=l.end_date,
                status='cancelled'
            ).count()
            l.affected_count = 0
            # Can only revoke if no bookings were affected and leave is not already completed/passed
            l.can_revoke = (l.cancelled_count == 0) and (not l.is_past)
        elif l.status == StaffLeave.STATUS_PENDING:
            l.cancelled_count = 0
            l.affected_count = Booking.objects.filter(
                therapist=l.therapist,
                date__gte=l.start_date,
                date__lte=l.end_date,
                status__in=['pending', 'confirmed'],
                is_archived=False,
            ).count()
            l.can_revoke = False
        else:
            l.cancelled_count = 0
            l.affected_count = 0
            l.can_revoke = False

    context = {
        'leaves': leaves_list,
        'therapists': therapists,
        'status_filter': status_filter,
        'therapist_filter': therapist_filter,
        'status_choices': StaffLeave.STATUS_CHOICES,
        'pending_count': pending_count,
    }
    return render(request, 'portals/admin_leave_list.html', context)


@login_required(login_url='portals:login')
def admin_leave_review(request, pk):
    """Admin-only: approve or reject a leave request."""
    if not request.user.is_staff:
        return redirect('portals:login')
    check = _require_admin(request)
    if check:
        return check

    if request.method == 'POST':
        leave = get_object_or_404(StaffLeave, pk=pk)
        action = request.POST.get('action')
        today = timezone.localdate()

        if action == 'approve':
            if leave.end_date < today:
                messages.error(request, 'Cannot approve a leave request that has already passed.')
                return redirect('portals:admin_leave_list')

            leave.status = StaffLeave.STATUS_APPROVED
            leave.is_active = True
            leave.save()
            cancelled_count = _cancel_bookings_for_leave(leave, request)
            if cancelled_count:
                messages.warning(
                    request,
                    f'{cancelled_count} booking(s) during this leave period were automatically '
                    f'cancelled and clients have been notified by email.'
                )
            messages.success(request, f'Leave for {leave.therapist.name} has been approved.')
        elif action == 'reject':
            was_approved = (leave.status == StaffLeave.STATUS_APPROVED)
            if was_approved:
                if leave.end_date < today:
                    messages.error(request, 'Cannot revoke a leave that has already passed.')
                    return redirect('portals:admin_leave_list')

                affected_count = Booking.objects.filter(
                    therapist=leave.therapist,
                    date__gte=leave.start_date,
                    date__lte=leave.end_date,
                    status='cancelled'
                ).count()
                if affected_count > 0:
                    messages.error(
                        request,
                        f'Cannot revoke this leave because {affected_count} booking(s) were affected/cancelled.'
                    )
                    return redirect('portals:admin_leave_list')

            leave.status = StaffLeave.STATUS_REJECTED
            leave.is_active = False
            leave.save()
            msg = f'Leave for {leave.therapist.name} has been revoked.' if was_approved else f'Leave for {leave.therapist.name} has been rejected.'
            messages.success(request, msg)
        elif action == 'toggle':
            leave.is_active = not leave.is_active
            leave.save()
            messages.success(request, f'Leave record updated.')
    return redirect('portals:admin_leave_list')


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
        return redirect('portals:admin_leave_list')
    return redirect('portals:admin_leave_list')


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
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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
    bookings_qs = Booking.objects.select_related('therapist').prefetch_related('services').filter(
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

    from website.models import StaffLeave
    leaves_qs = StaffLeave.objects.select_related('therapist').filter(
        status='approved',
        start_date__lte=month_end,
        end_date__gte=month_start
    )
    if _is_staff_only(request):
        therapist = _get_staff_therapist(request)
        if therapist:
            leaves_qs = leaves_qs.filter(therapist=therapist)
        else:
            leaves_qs = leaves_qs.none()
            
    leaves_by_date = {}
    for leave in leaves_qs:
        d_start = max(leave.start_date, month_start)
        d_end = min(leave.end_date, month_end)
        curr = d_start
        while curr <= d_end:
            leaves_by_date.setdefault(curr.day, []).append(leave)
            curr += timedelta(days=1)

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
        'leaves_by_date': leaves_by_date,
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

    report_type = request.GET.get('report_type', 'bookings')  # 'bookings' or 'sales'
    period = request.GET.get('period', 'today')
    if request.GET.get('start_date') and request.GET.get('end_date'):
        period = 'custom'
        messages.success(request, "Report filtered by custom date range.")
    start_date, end_date, period_label = _get_date_range(request)

    # All completed bookings in period (walk-in OR verified online only)
    completed = Booking.objects.filter(
        Q(booking_type='walk_in') | Q(is_verified=True),
        status='completed',
        date__gte=start_date,
        date__lte=end_date,
    ).select_related('therapist').prefetch_related('services')

    # Revenue — sum across all services per booking (M2M)
    total_revenue = Decimal('0')
    for b in completed:
        for svc in b.services.all():
            total_revenue += svc.discounted_price

    total_completed = completed.count()

    # ── Booking Report: all bookings in period ──
    all_bookings_in_period = Booking.objects.filter(
        Q(booking_type='walk_in') | Q(is_verified=True),
        date__gte=start_date,
        date__lte=end_date,
    ).select_related('therapist').prefetch_related('services').order_by('-date', '-created_at')

    total_bookings_period = all_bookings_in_period.count()

    # ── Sales Report data ──
    staff_data = []
    total_commission = Decimal('0')
    therapists = Therapist.objects.filter(is_active=True)
    for t in therapists:
        t_bookings = completed.filter(therapist=t)
        t_count = t_bookings.count()
        t_revenue = Decimal('0')
        for b in t_bookings:
            for svc in b.services.all():
                t_revenue += svc.discounted_price
        t_commission = t_revenue * (t.commission_percentage / Decimal('100'))
        total_commission += t_commission
        staff_data.append({
            'therapist': t,
            'services_rendered': t_count,
            'total_revenue': t_revenue,
            'commission_rate': t.commission_percentage,
            'commission_earned': t_commission,
        })
    staff_data.sort(key=lambda x: x['services_rendered'], reverse=True)

    online_count = all_bookings_in_period.filter(booking_type='online').count()
    walkin_count = all_bookings_in_period.filter(booking_type='walk_in').count()

    service_breakdown = []
    for svc in Service.objects.filter(is_active=True):
        svc_bookings = completed.filter(services=svc)
        svc_count = svc_bookings.count()
        if svc_count > 0:
            svc_revenue = svc.discounted_price * svc_count
            service_breakdown.append({
                'service': svc,
                'count': svc_count,
                'revenue': svc_revenue,
            })
    service_breakdown.sort(key=lambda x: x['count'], reverse=True)

    context = {
        'report_type': report_type,
        'period': period,
        'period_label': period_label,
        'start_date': start_date,
        'end_date': end_date,
        'total_revenue': total_revenue,
        'total_completed': total_completed,
        'total_commission': total_commission,
        'total_bookings_period': total_bookings_period,
        'all_bookings_in_period': all_bookings_in_period,
        'staff_data': staff_data,
        'service_breakdown': service_breakdown,
        'online_count': online_count,
        'walkin_count': walkin_count,
    }
    return render(request, 'portals/admin_reports.html', context)


@login_required(login_url='portals:login')
def price_checker(request):
    """
    Price Checker for administrators:
    View previous and current prices of services for a specific month or date range,
    and verify that bookings were charged based on the service price at the time of booking.
    """
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. Admin only.')
        return redirect('portals:dashboard')

    from website.models import Service, ServicePriceHistory, Booking
    import calendar
    from datetime import datetime, date

    # Ensure backfill for any service missing price history
    for svc in Service.objects.all():
        if not svc.price_history.exists():
            start_d = svc.created_at.date() if svc.created_at else date(2026, 1, 1)
            ServicePriceHistory.objects.create(
                service=svc,
                base_price=svc.price,
                discount_percentage=svc.discount_percentage,
                effective_from=start_d,
                effective_to=None,
                notes="Initial Established Rate"
            )
    today = timezone.now().date()
    Service.sync_all_for_today()

    selected_service_id = request.GET.get('service_id', '')
    month_param = request.GET.get('month', '')
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    active_tab = request.GET.get('tab', 'services')

    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            period_label = f"{start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}"
            selected_month = None
        except ValueError:
            start_date = date(today.year, today.month, 1)
            _, last_day = calendar.monthrange(today.year, today.month)
            end_date = date(today.year, today.month, last_day)
            period_label = start_date.strftime('%B %Y')
            selected_month = start_date.strftime('%Y-%m')
    elif month_param:
        try:
            year_val, month_val = map(int, month_param.split('-'))
            start_date = date(year_val, month_val, 1)
            _, last_day = calendar.monthrange(year_val, month_val)
            end_date = date(year_val, month_val, last_day)
            period_label = start_date.strftime('%B %Y')
            selected_month = month_param
        except Exception:
            start_date = date(today.year, today.month, 1)
            _, last_day = calendar.monthrange(today.year, today.month)
            end_date = date(today.year, today.month, last_day)
            period_label = start_date.strftime('%B %Y')
            selected_month = start_date.strftime('%Y-%m')
    else:
        start_date = date(today.year, today.month, 1)
        _, last_day = calendar.monthrange(today.year, today.month)
        end_date = date(today.year, today.month, last_day)
        period_label = start_date.strftime('%B %Y')
        selected_month = start_date.strftime('%Y-%m')

    # Available months for quick dropdown (past 8 months to next 4 months)
    available_months = []
    curr_y, curr_m = today.year, today.month
    for offset in range(-8, 5):
        m = curr_m + offset
        y = curr_y
        while m < 1:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        val = f"{y:04d}-{m:02d}"
        label = date(y, m, 1).strftime('%B %Y')
        available_months.append({'value': val, 'label': label})

    services_qs = Service.objects.all().order_by('category', 'name')
    if selected_service_id:
        try:
            services_qs = services_qs.filter(pk=int(selected_service_id))
        except (ValueError, TypeError):
            pass

    service_price_rows = []
    total_price_changes_in_period = 0

    for svc in services_qs:
        current_base = svc.price
        current_discount = svc.discount_percentage if svc.has_discount else Decimal('0')
        current_final = svc.discounted_price

        # Find price record effective during the selected period
        hist = svc.price_history.filter(
            effective_from__lte=end_date
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=start_date)
        ).order_by('-effective_from', '-created_at').first()

        if hist:
            hist_base = hist.base_price
            hist_discount = hist.discount_percentage
            hist_final = hist.discounted_price
            hist_effective_from = hist.effective_from
            hist_effective_to = hist.effective_to
            hist_notes = hist.notes
        else:
            # No history record exists for this period — show base price with no discount
            # (do NOT bleed today's live promo into a past period where it didn't apply)
            hist_base = current_base
            hist_discount = Decimal('0')
            hist_final = current_base
            hist_effective_from = svc.created_at.date() if svc.created_at else date(2026, 1, 1)
            hist_effective_to = None
            hist_notes = "No price record for this period"

        price_diff = current_final - hist_final
        if price_diff > 0:
            change_type = 'increased'
        elif price_diff < 0:
            change_type = 'decreased'
        else:
            change_type = 'unchanged'

        changes_in_range = svc.price_history.filter(
            effective_from__gte=start_date, effective_from__lte=end_date
        ).count()
        if changes_in_range > 0:
            total_price_changes_in_period += changes_in_range

        full_timeline = list(svc.price_history.all().order_by('-effective_from', '-created_at'))

        service_price_rows.append({
            'service': svc,
            'current_base': current_base,
            'current_discount': current_discount,
            'current_final': current_final,
            'hist_base': hist_base,
            'hist_discount': hist_discount,
            'hist_final': hist_final,
            'hist_effective_from': hist_effective_from,
            'hist_effective_to': hist_effective_to,
            'hist_notes': hist_notes,
            'price_diff': price_diff,
            'change_type': change_type,
            'changes_in_range': changes_in_range,
            'timeline': full_timeline,
        })

    # Bookings Verification
    bookings_qs = Booking.objects.filter(
        date__gte=start_date,
        date__lte=end_date,
    ).select_related('therapist').prefetch_related('services').order_by('-date', '-created_at')

    if selected_service_id:
        try:
            bookings_qs = bookings_qs.filter(services__id=int(selected_service_id)).distinct()
        except (ValueError, TypeError):
            pass

    booking_audit_rows = []
    total_charged_revenue = Decimal('0')
    total_current_value = Decimal('0')
    price_protected_bookings_count = 0

    for b in bookings_qs:
        charged_price = b.total_discounted_price
        total_charged_revenue += charged_price

        current_today_price = Decimal('0')
        for s in b.services.all():
            current_today_price += s.discounted_price
        total_current_value += current_today_price

        variance = charged_price - current_today_price
        is_variance = abs(variance) > Decimal('0.009')
        if is_variance:
            price_protected_bookings_count += 1

        booking_audit_rows.append({
            'booking': b,
            'charged_price': charged_price,
            'current_today_price': current_today_price,
            'variance': variance,
            'is_variance': is_variance,
            'snapshots': b.service_prices_snapshot or [],
        })

    # Quick Price Lookup Tool
    lookup_result = None
    lookup_service_id = request.GET.get('lookup_service')
    lookup_date_str = request.GET.get('lookup_date')
    if lookup_service_id and lookup_date_str:
        try:
            lookup_svc = Service.objects.get(pk=int(lookup_service_id))
            target_lookup_date = datetime.strptime(lookup_date_str, '%Y-%m-%d').date()
            hist = lookup_svc.price_history.filter(
                effective_from__lte=target_lookup_date
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gte=target_lookup_date)
            ).order_by('-effective_from', '-created_at').first()

            if hist:
                lookup_result = {
                    'service': lookup_svc,
                    'date': target_lookup_date,
                    'base_price': hist.base_price,
                    'discount_percentage': hist.discount_percentage,
                    'final_price': hist.discounted_price,
                    'effective_from': hist.effective_from,
                    'effective_to': hist.effective_to,
                    'notes': hist.notes,
                    'current_final': lookup_svc.discounted_price,
                    'is_different': hist.discounted_price != lookup_svc.discounted_price,
                }
            else:
                lookup_result = {
                    'service': lookup_svc,
                    'date': target_lookup_date,
                    'base_price': lookup_svc.price,
                    'discount_percentage': lookup_svc.discount_percentage,
                    'final_price': lookup_svc.discounted_price,
                    'effective_from': lookup_svc.created_at.date() if lookup_svc.created_at else date(2026, 1, 1),
                    'effective_to': None,
                    'notes': 'Base Established Rate',
                    'current_final': lookup_svc.discounted_price,
                    'is_different': False,
                }
        except Exception:
            lookup_result = None

    history_logs_qs = ServicePriceHistory.objects.select_related('service').order_by('-effective_from', '-created_at')
    # Filter history to records that overlap with the selected period
    history_logs_qs = history_logs_qs.filter(
        effective_from__lte=end_date
    ).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=start_date)
    )
    if selected_service_id:
        try:
            history_logs_qs = history_logs_qs.filter(service_id=int(selected_service_id))
        except (ValueError, TypeError):
            pass

    # Enrich history logs with status
    history_logs_list = list(history_logs_qs)
    for log in history_logs_list:
        if log.effective_to and log.effective_to < today:
            log.status_badge = 'archived'
            log.status_label = 'Archived'
        elif log.effective_from > today:
            log.status_badge = 'upcoming'
            log.status_label = 'Scheduled'
        else:
            log.status_badge = 'active'
            log.status_label = 'Active'

    # Build client-side JSON for instant interactive Price Inspector
    import json
    pricing_data_list = []
    for s in Service.objects.filter(is_active=True).prefetch_related('price_history').order_by('name'):
        histories = []
        for h in s.price_history.all().order_by('-effective_from', '-created_at'):
            h_status = 'active'
            if h.effective_to and h.effective_to < today:
                h_status = 'archived'
            elif h.effective_from > today:
                h_status = 'upcoming'
            histories.append({
                'base_price': float(h.base_price),
                'discount_percentage': float(h.discount_percentage),
                'discounted_price': float(h.discounted_price),
                'effective_from': h.effective_from.strftime('%Y-%m-%d') if h.effective_from else '',
                'effective_to': h.effective_to.strftime('%Y-%m-%d') if h.effective_to else None,
                'notes': h.notes or '',
                'status': h_status,
            })
        pricing_data_list.append({
            'id': s.id,
            'name': s.name,
            'category': str(s.get_category_display or s.category),
            'current_price': float(s.price),
            'current_discount': float(s.discount_percentage if s.has_discount else Decimal('0')),
            'current_final': float(s.discounted_price),
            'histories': histories,
        })
    service_pricing_json = json.dumps(pricing_data_list)

    # Format timeline for each service price row for in-page modal
    for row in service_price_rows:
        row_timeline = []
        for t in row['timeline']:
            t_status = 'active'
            if t.effective_to and t.effective_to < today:
                t_status = 'archived'
            elif t.effective_from > today:
                t_status = 'upcoming'
            row_timeline.append({
                'base_price': float(t.base_price),
                'discount': float(t.discount_percentage),
                'final_price': float(t.discounted_price),
                'from_str': t.effective_from.strftime('%b %d, %Y') if t.effective_from else 'Genesis',
                'to_str': t.effective_to.strftime('%b %d, %Y') if t.effective_to else 'Present',
                'notes': t.notes or 'Established Rate',
                'status': t_status,
            })
        row['timeline_json'] = json.dumps(row_timeline)

    rate_matched_bookings_count = max(0, bookings_qs.count() - price_protected_bookings_count)
    net_variance = total_charged_revenue - total_current_value

    context = {
        'period_label': period_label,
        'selected_month': selected_month,
        'start_date': start_date,
        'end_date': end_date,
        'available_months': available_months,
        'all_services': Service.objects.filter(is_active=True).order_by('name'),
        'selected_service_id': selected_service_id,
        'active_tab': active_tab,
        'service_price_rows': service_price_rows,
        'booking_audit_rows': booking_audit_rows,
        'total_bookings_count': bookings_qs.count(),
        'total_charged_revenue': total_charged_revenue,
        'total_current_value': total_current_value,
        'price_protected_bookings_count': price_protected_bookings_count,
        'rate_matched_bookings_count': rate_matched_bookings_count,
        'net_variance': net_variance,
        'total_price_changes_in_period': total_price_changes_in_period,
        'history_logs': history_logs_list,
        'lookup_result': lookup_result,
        'lookup_service_id': lookup_service_id,
        'lookup_date_str': lookup_date_str,
        'service_pricing_json': service_pricing_json,
        'today': today,
    }
    return render(request, 'portals/price_checker.html', context)


@login_required(login_url='portals:login')
def price_checker_add_record(request):
    """Admin manually adds or schedules a price change record."""
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. Admin only.')
        return redirect('portals:dashboard')

    if request.method == 'POST':
        from website.models import Service, ServicePriceHistory
        from datetime import datetime
        service_id = request.POST.get('service_id')
        base_price_str = request.POST.get('base_price')
        discount_percentage_str = request.POST.get('discount_percentage', '0')
        effective_from_str = request.POST.get('effective_from')
        effective_to_str = request.POST.get('effective_to')
        notes = request.POST.get('notes', '').strip()
        update_current_service = request.POST.get('update_current_service') == '1'

        try:
            service = Service.objects.get(pk=int(service_id))
            base_price = Decimal(base_price_str)
            discount_percentage = Decimal(discount_percentage_str or '0')
            effective_from = datetime.strptime(effective_from_str, '%Y-%m-%d').date()
            effective_to = datetime.strptime(effective_to_str, '%Y-%m-%d').date() if effective_to_str else None

            today = timezone.now().date()
            is_effective_today = (effective_from <= today) and (effective_to is None or effective_to >= today)

            ServicePriceHistory.objects.create(
                service=service,
                base_price=base_price,
                discount_percentage=discount_percentage,
                effective_from=effective_from,
                effective_to=effective_to,
                notes=notes or "Manual Price Adjustment"
            )

            if is_effective_today and update_current_service:
                service.price = base_price
                service.discount_percentage = discount_percentage
                service.save(update_fields=['price', 'discount_percentage'])
                ServicePriceHistory.objects.filter(
                    service=service, effective_to__isnull=True
                ).exclude(effective_from=effective_from).update(effective_to=effective_from)
            else:
                # Future or past schedule: do not overwrite current live rate today
                service.sync_rates_with_today()

            # Ensure all services' rates and statuses are kept in sync
            Service.sync_all_for_today()

            if effective_from > today:
                messages.success(request, f'Price schedule for "{service.name}" saved! It will automatically become effective on {effective_from.strftime("%b %d, %Y")}.')
            else:
                messages.success(request, f'Price record for "{service.name}" added successfully.')
        except Exception as e:
            messages.error(request, f'Failed to add price record: {e}')

    return redirect(f"{reverse('portals:price_checker')}?tab=history")


@login_required(login_url='portals:login')
def price_checker_delete_record(request, pk):
    """Delete a scheduled (upcoming) price history record and update all statuses."""
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. Admin only.')
        return redirect('portals:dashboard')

    if request.method == 'POST':
        try:
            record = ServicePriceHistory.objects.get(pk=pk)
            today = timezone.now().date()
            # Only allow deleting future / scheduled records
            if record.effective_from > today:
                service_name = record.service.name
                record.delete()
                # Re-sync all service rates and statuses after deletion
                Service.sync_all_for_today()
                messages.success(request, f'Scheduled price for "{service_name}" has been removed and all statuses updated.')
            else:
                messages.error(request, 'Only scheduled (future) price records can be removed.')
        except ServicePriceHistory.DoesNotExist:
            messages.error(request, 'Price record not found.')
        except Exception as e:
            messages.error(request, f'Failed to remove record: {e}')

    return redirect(f"{reverse('portals:price_checker')}?tab=history")


@login_required(login_url='portals:login')
def price_checker_update_record(request, pk):
    """Update a scheduled (upcoming) price history record and update all statuses."""
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. Admin only.')
        return redirect('portals:dashboard')

    if request.method == 'POST':
        from datetime import datetime as dt
        try:
            record = ServicePriceHistory.objects.get(pk=pk)
            today = timezone.now().date()
            if record.effective_from <= today:
                messages.error(request, 'Only scheduled (future) price records can be edited.')
                return redirect(f"{reverse('portals:price_checker')}?tab=history")

            base_price_str = request.POST.get('base_price')
            discount_str = request.POST.get('discount_percentage', '0')
            from_str = request.POST.get('effective_from')
            to_str = request.POST.get('effective_to', '')
            notes = request.POST.get('notes', '').strip()

            record.base_price = Decimal(base_price_str)
            record.discount_percentage = Decimal(discount_str or '0')
            record.effective_from = dt.strptime(from_str, '%Y-%m-%d').date()
            record.effective_to = dt.strptime(to_str, '%Y-%m-%d').date() if to_str else None
            record.notes = notes or 'Scheduled Price Adjustment'
            record.save()

            # Re-sync all services' live rates and statuses
            Service.sync_all_for_today()
            messages.success(request, f'Scheduled price for "{record.service.name}" updated successfully and all statuses refreshed.')
        except ServicePriceHistory.DoesNotExist:
            messages.error(request, 'Price record not found.')
        except Exception as e:
            messages.error(request, f'Failed to update record: {e}')

    return redirect(f"{reverse('portals:price_checker')}?tab=history")


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
    show_filter = request.GET.get('show', '')  # '' = active, 'archived' = archived
    base_qs = Booking.objects.select_related('therapist').prefetch_related('services').none()

    if therapist:
        base_qs = Booking.objects.select_related('therapist').prefetch_related('services').filter(
            Q(booking_type='walk_in') | Q(is_verified=True),
            therapist=therapist,
        )

    if show_filter == 'archived':
        bookings = base_qs.filter(is_archived=True)
    else:
        bookings = base_qs.filter(is_archived=False)

    if status_filter:
        bookings = bookings.filter(status=status_filter)

    active_count = base_qs.filter(is_archived=False).count()
    archived_count = base_qs.filter(is_archived=True).count()

    context = {
        'bookings': bookings,
        'therapist': therapist,
        'status_filter': status_filter,
        'show_filter': show_filter,
        'active_count': active_count,
        'archived_count': archived_count,
        'status_choices': [c for c in Booking.STATUS_CHOICES if c[0] != 'awaiting_verification'],
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
        ).exclude(status='cancelled').prefetch_related('services').order_by('date', 'time')

        my_schedules = StaffSchedule.objects.filter(therapist=therapist).order_by('day_of_week', 'start_time')

    # Build booked slots: date -> list of times
    booked_slots = {}
    for b in my_bookings:
        booked_slots.setdefault(b.date.day, []).append({
            'time': b.get_time_display(),
            'time_raw': b.time,
            'service': b.service_names,
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

    # Build approved leave days for this month
    leave_days = set()
    if therapist:
        approved_leaves = StaffLeave.objects.filter(
            therapist=therapist,
            status=StaffLeave.STATUS_APPROVED,
            start_date__lte=month_end,
            end_date__gte=month_start,
        )
        for leave in approved_leaves:
            d = leave.start_date
            while d <= leave.end_date:
                if d.year == year and d.month == month:
                    leave_days.add(d.day)
                d += timedelta(days=1)

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
        'leave_days': list(leave_days),
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
    all_bookings_in_period = []
    total_bookings_period = 0
    online_count = 0
    walkin_count = 0

    if therapist:
        # All bookings in period for this therapist (for the Bookings section)
        all_bookings_qs = Booking.objects.filter(
            Q(booking_type='walk_in') | Q(is_verified=True),
            therapist=therapist,
            date__gte=start_date,
            date__lte=end_date,
        ).prefetch_related('services').order_by('-date', '-created_at')

        all_bookings_in_period = all_bookings_qs
        total_bookings_period = all_bookings_qs.count()
        online_count = all_bookings_qs.filter(booking_type='online').count()
        walkin_count = all_bookings_qs.filter(booking_type='walk_in').count()

        # Completed bookings only (for the Sales section)
        completed = all_bookings_qs.filter(status='completed')

        services_rendered = completed.count()
        for b in completed:
            price = b.total_discounted_price
            total_revenue += price
            booking_details.append({
                'booking': b,
                'price': price,
            })
        if therapist.commission_percentage:
            commission_earned = total_revenue * (therapist.commission_percentage / Decimal('100'))

    context = {
        'therapist': therapist,
        'period': period,
        'period_label': period_label,
        'start_date': start_date,
        'end_date': end_date,
        'services_rendered': services_rendered,
        'total_revenue': total_revenue,
        'commission_earned': commission_earned,
        'booking_details': booking_details,
        'all_bookings_in_period': all_bookings_in_period,
        'total_bookings_period': total_bookings_period,
        'online_count': online_count,
        'walkin_count': walkin_count,
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

    search_query = request.GET.get('q', '').strip()
    read_filter = request.GET.get('read', '')
    contact_messages = ContactMessage.objects.prefetch_related('replies').all()

    if search_query:
        contact_messages = contact_messages.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(subject__icontains=search_query) |
            Q(message__icontains=search_query)
        )

    if read_filter == 'archived':
        contact_messages = contact_messages.filter(is_archived=True)
    else:
        contact_messages = contact_messages.filter(is_archived=False)
        if read_filter == 'unread':
            contact_messages = contact_messages.filter(is_read=False)
        elif read_filter == 'read':
            contact_messages = contact_messages.filter(is_read=True)

    total_count = ContactMessage.objects.filter(is_archived=False).count()
    unread_count = ContactMessage.objects.filter(is_archived=False, is_read=False).count()
    read_count = ContactMessage.objects.filter(is_archived=False, is_read=True).count()
    archived_count = ContactMessage.objects.filter(is_archived=True).count()

    context = {
        'contact_messages': contact_messages,
        'read_filter': read_filter,
        'search_query': search_query,
        'total_count': total_count,
        'unread_count': unread_count,
        'read_count': read_count,
        'archived_count': archived_count,
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
def message_reply(request, pk):
    if not request.user.is_staff or not _is_admin(request):
        messages.error(request, 'Unauthorized access.')
        return redirect('portals:dashboard')

    msg = get_object_or_404(ContactMessage, pk=pk)

    if request.method == 'POST':
        reply_text = request.POST.get('reply_text', '').strip()
        if reply_text:
            # 1. Create a threaded MessageReply
            staff_name = request.user.get_full_name() or request.user.username or "Medpoint Staff"
            reply = MessageReply.objects.create(
                message=msg,
                sender_type=MessageReply.SENDER_ADMIN,
                sender_name=staff_name,
                sender_email=request.user.email or settings.DEFAULT_FROM_EMAIL,
                body=reply_text,
            )

            # 2. Update parent message for backward compatibility and status
            msg.reply_text = reply_text
            msg.replied_at = timezone.now()
            msg.is_read = True
            msg.save(update_fields=['reply_text', 'replied_at', 'is_read'])

            # 3. Generate client web reply link
            thread_path = reverse('website:client_message_thread', kwargs={'token': msg.access_token})
            base_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
            web_reply_url = None
            try:
                candidate = request.build_absolute_uri(thread_path)
                if candidate and candidate.startswith(('http://', 'https://')) and not candidate.startswith(('http:///', 'https:///')):
                    web_reply_url = candidate
            except Exception:
                pass
            if not web_reply_url:
                clean_path = '/' + thread_path.lstrip('/')
                web_reply_url = f"{base_url}{clean_path}"

            # 4. Send Email to client with [Ticket #ID]
            from django.core.mail import EmailMultiAlternatives
            from django.template.loader import render_to_string
            from django.utils.html import strip_tags
            from django.conf import settings
            import logging

            context = {
                'client_name': msg.name,
                'original_subject': msg.subject,
                'original_message': msg.message,
                'reply_text': reply_text,
                'ticket_id': msg.pk,
                'web_reply_url': web_reply_url,
            }

            try:
                html_content = render_to_string('website/emails/message_reply.html', context)
                text_content = strip_tags(html_content)

                sender_domain = getattr(settings, 'EMAIL_HOST_USER', 'medpointmassage.spa@gmail.com')
                email = EmailMultiAlternatives(
                    subject=f"Re: [Ticket #{msg.pk}] {msg.subject} - Medpoint Massage & Spa",
                    body=text_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[msg.email],
                    headers={
                        'Message-ID': f"<ticket-{msg.pk}-{reply.pk}@{sender_domain}>",
                        'In-Reply-To': f"<ticket-{msg.pk}@{sender_domain}>",
                        'References': f"<ticket-{msg.pk}@{sender_domain}>",
                    }
                )
                email.attach_alternative(html_content, "text/html")
                email.send(fail_silently=False)

                messages.success(request, f'Reply sent successfully to {msg.email}.')
            except Exception as e:
                logging.getLogger(__name__).warning(f'Failed to send reply email: {e}')
                messages.warning(request, f'Reply saved to thread, but email failed to send: {e}')
        else:
            messages.error(request, 'Reply text cannot be empty.')
            
    return redirect('portals:message_list')


@login_required(login_url='portals:login')
def message_sync_replies(request):
    """Admin: Manually trigger IMAP sync to fetch client email replies from Gmail."""
    if not request.user.is_staff or not _is_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    from website.email_sync import sync_incoming_email_replies
    result = sync_incoming_email_replies()
    return JsonResponse(result)


@login_required(login_url='portals:login')
def message_bulk_delete(request):
    """Admin: Delete multiple contact messages in one request."""
    if not request.user.is_staff or not _is_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    import json as _json
    try:
        data = _json.loads(request.body)
        ids = [int(i) for i in data.get('ids', [])]
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    deleted, _ = ContactMessage.objects.filter(pk__in=ids).delete()
    return JsonResponse({'success': True, 'deleted': deleted})


@login_required(login_url='portals:login')
def message_bulk_mark_read(request):
    """Admin: Mark multiple contact messages as read."""
    if not request.user.is_staff or not _is_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    import json as _json
    try:
        data = _json.loads(request.body)
        ids = [int(i) for i in data.get('ids', [])]
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    ContactMessage.objects.filter(pk__in=ids).update(is_read=True)
    return JsonResponse({'success': True})


@login_required(login_url='portals:login')
def message_bulk_mark_unread(request):
    """Admin: Mark multiple contact messages as unread."""
    if not request.user.is_staff or not _is_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    import json as _json
    try:
        data = _json.loads(request.body)
        ids = [int(i) for i in data.get('ids', [])]
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    ContactMessage.objects.filter(pk__in=ids).update(is_read=False)
    return JsonResponse({'success': True})


@login_required(login_url='portals:login')
def message_archive(request, pk):
    """Admin: Archive a single contact message."""
    if not request.user.is_staff or not _is_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    msg = get_object_or_404(ContactMessage, pk=pk)
    msg.is_archived = True
    msg.save(update_fields=['is_archived'])
    return JsonResponse({'success': True, 'is_archived': True})


@login_required(login_url='portals:login')
def message_restore(request, pk):
    """Admin: Restore an archived contact message back to inbox."""
    if not request.user.is_staff or not _is_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    msg = get_object_or_404(ContactMessage, pk=pk)
    msg.is_archived = False
    msg.save(update_fields=['is_archived'])
    return JsonResponse({'success': True, 'is_archived': False})


@login_required(login_url='portals:login')
def message_delete(request, pk):
    """Admin: Permanently delete a single contact message."""
    if not request.user.is_staff or not _is_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    msg = get_object_or_404(ContactMessage, pk=pk)
    msg.delete()
    return JsonResponse({'success': True})


@login_required(login_url='portals:login')
def message_bulk_archive(request):
    """Admin: Archive multiple contact messages."""
    if not request.user.is_staff or not _is_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    import json as _json
    try:
        data = _json.loads(request.body)
        ids = [int(i) for i in data.get('ids', [])]
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    ContactMessage.objects.filter(pk__in=ids).update(is_archived=True)
    return JsonResponse({'success': True})


@login_required(login_url='portals:login')
def message_bulk_restore(request):
    """Admin: Restore multiple contact messages back to inbox."""
    if not request.user.is_staff or not _is_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    import json as _json
    try:
        data = _json.loads(request.body)
        ids = [int(i) for i in data.get('ids', [])]
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    ContactMessage.objects.filter(pk__in=ids).update(is_archived=False)
    return JsonResponse({'success': True})


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
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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
    pending_count = Booking.objects.filter(status='pending', is_verified=True).count()
    messages_count = ContactMessage.objects.filter(is_read=False).count() if role == 'admin' else 0

    return JsonResponse({
        'unread_notifications': notif_count,
        'pending_bookings': pending_count,
        'unread_messages': messages_count,
        'latest_notifications': latest_notifs,
    })
