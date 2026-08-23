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

    period = request.GET.get('period', 'week')  # day, week, month, year
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
        elif period in ('week', 'month'):
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
            therapist=therapist, status='pending'
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

    bookings = Booking.objects.filter(Q(booking_type='walk_in') | Q(is_verified=True)).select_related('therapist').prefetch_related('services').order_by('-created_at')

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
        old_status = booking.status
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

            messages.success(request, f'Walk-in booking #{booking_obj.pk:04d} created successfully.')
            return redirect('portals:booking_list')
        else:
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
    else:
        form = WalkInBookingForm(initial={
            'date': timezone.now().date(),
            'status': 'confirmed',
        })
    return render(request, 'portals/booking_walkin.html', {
        'form': form,
        'services_list': Service.objects.filter(is_active=True),
    })


@login_required(login_url='portals:login')
def booking_delete(request, pk):
    return JsonResponse({'error': 'Method not allowed'}, status=405)


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
    if request.method == 'POST':
        form = ServiceForm(request.POST, request.FILES, instance=service)
        if form.is_valid():
            form.save()
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
            ).exclude(status__in=['cancelled']).order_by('date')

            if conflicting_bookings.exists():
                conflict_dates = ', '.join(
                    set(b.date.strftime('%b %d, %Y') for b in conflicting_bookings)
                )
                messages.error(
                    request,
                    f'You have active bookings during this period ({conflict_dates}). '
                    f'Please resolve those bookings before applying for leave on those days.'
                )
            else:
                leave.save()
                messages.success(request, 'Your leave request has been submitted and is awaiting admin approval.')
                return redirect('portals:staff_my_schedule')
        else:
            first_error = list(form.errors.values())[0][0] if form.errors else 'Please correct the errors below.'
            messages.error(request, first_error)
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

    context = {
        'leaves': leaves,
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
        if action == 'approve':
            leave.status = StaffLeave.STATUS_APPROVED
            leave.is_active = True
            leave.save()
            messages.success(request, f'Leave for {leave.therapist.name} has been approved.')
        elif action == 'reject':
            leave.status = StaffLeave.STATUS_REJECTED
            leave.is_active = False
            leave.save()
            messages.success(request, f'Leave for {leave.therapist.name} has been rejected.')
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
    total_bookings_period = Booking.objects.filter(
        Q(booking_type='walk_in') | Q(is_verified=True),
        date__gte=start_date, date__lte=end_date,
    ).count()

    # Per-staff performance
    staff_data = []
    therapists = Therapist.objects.filter(is_active=True)
    for t in therapists:
        t_bookings = completed.filter(therapist=t)
        t_count = t_bookings.count()
        t_revenue = Decimal('0')
        for b in t_bookings:
            for svc in b.services.all():
                t_revenue += svc.discounted_price
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
    bookings = Booking.objects.select_related('therapist').prefetch_related('services').none()

    if therapist:
        bookings = Booking.objects.select_related('therapist').prefetch_related('services').filter(
            Q(booking_type='walk_in') | Q(is_verified=True),
            therapist=therapist,
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

    if therapist:
        completed = Booking.objects.filter(
            Q(booking_type='walk_in') | Q(is_verified=True),
            therapist=therapist,
            status='completed',
            date__gte=start_date,
            date__lte=end_date,
        ).prefetch_related('services').order_by('-date', '-time')

        services_rendered = completed.count()
        for b in completed:
            price = b.total_discounted_price
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
def message_reply(request, pk):
    if not request.user.is_staff or not _is_admin(request):
        messages.error(request, 'Unauthorized access.')
        return redirect('portals:dashboard')

    msg = get_object_or_404(ContactMessage, pk=pk)

    if request.method == 'POST':
        reply_text = request.POST.get('reply_text', '').strip()
        if reply_text:
            msg.reply_text = reply_text
            msg.replied_at = timezone.now()
            msg.is_read = True
            msg.save()

            # Send Email
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
            }

            try:
                html_content = render_to_string('website/emails/message_reply.html', context)
                text_content = strip_tags(html_content)

                email = EmailMultiAlternatives(
                    subject=f"Re: {msg.subject} - Medpoint Massage & Spa",
                    body=text_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[msg.email]
                )
                email.attach_alternative(html_content, "text/html")
                email.send(fail_silently=False)

                messages.success(request, f'Reply sent successfully to {msg.email}.')
            except Exception as e:
                logging.getLogger(__name__).warning(f'Failed to send reply email: {e}')
                messages.warning(request, f'Reply saved, but email failed to send: {e}')
        else:
            messages.error(request, 'Reply text cannot be empty.')
            
    return redirect('portals:message_list')

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
    pending_count = Booking.objects.filter(status='pending').count()
    messages_count = ContactMessage.objects.filter(is_read=False).count() if role == 'admin' else 0

    return JsonResponse({
        'unread_notifications': notif_count,
        'pending_bookings': pending_count,
        'unread_messages': messages_count,
        'latest_notifications': latest_notifs,
    })

