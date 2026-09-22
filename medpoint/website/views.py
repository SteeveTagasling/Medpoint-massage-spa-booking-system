from decimal import Decimal
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone

from .models import (
    Service, Therapist, Testimonial, GalleryImage,
    Booking, BookingNotification, ContactMessage, MessageReply,
    StaffLeave, ClosedDay, StaffSchedule,
)
from .forms import BookingForm, ContactForm, FamilyMemberForm
from portals.models import StaffNotification


def _get_site_stats():
    """Calculate dynamic site statistics for homepage and about page."""
    current_year = timezone.now().year
    # Starting at 3 years in 2026, automatically increments each passing year
    years_experience = max(3, current_year - 2023)
    # Starting at 5,000, automatically adds every completed booking
    completed_bookings = Booking.objects.filter(status='completed').count()
    happy_clients_count = 5000 + completed_bookings
    happy_clients_display = f"{happy_clients_count:,}"
    active_therapists_count = Therapist.objects.filter(is_active=True).count()
    active_services_count = Service.objects.filter(is_active=True).count()

    return {
        'happy_clients_count': happy_clients_count,
        'happy_clients_display': happy_clients_display,
        'years_experience': years_experience,
        'active_therapists_count': active_therapists_count,
        'active_services_count': active_services_count,
    }


def home(request):
    """Homepage view with featured services, testimonials, and gallery."""
    Service.sync_all_for_today()
    featured_services = Service.objects.filter(is_featured=True, is_active=True)[:6]
    all_services = Service.objects.filter(is_active=True)[:8]
    testimonials = Testimonial.objects.filter(is_featured=True, is_approved=True)[:6]
    gallery_images = GalleryImage.objects.filter(is_active=True)[:8]
    therapists = Therapist.objects.filter(is_active=True)[:4]

    services_to_show = featured_services if featured_services.exists() else all_services

    context = {
        'services': services_to_show,
        'testimonials': testimonials,
        'gallery_images': gallery_images,
        'therapists': therapists,
        'booking_form': BookingForm(),
        **_get_site_stats(),
    }
    return render(request, 'website/home.html', context)


def services(request):
    """Services listing page."""
    Service.sync_all_for_today()
    category = request.GET.get('category', '')
    all_services = Service.objects.filter(is_active=True)

    if category:
        all_services = all_services.filter(category__icontains=category)

    categories = Service.CATEGORY_CHOICES

    context = {
        'services': all_services,
        'categories': categories,
        'active_category': category,
    }
    return render(request, 'website/services.html', context)


def service_detail(request, slug):
    """Individual service detail page."""
    Service.sync_all_for_today()
    service = get_object_or_404(Service, slug=slug, is_active=True)
    cats = service.category.split(',')
    first_cat = cats[0].strip() if cats else ''
    related_services = Service.objects.filter(
        category__icontains=first_cat, is_active=True
    ).exclude(pk=service.pk)[:3]

    context = {
        'service': service,
        'related_services': related_services,
        'booking_form': BookingForm(initial={'service': service}),
    }
    return render(request, 'website/service_detail.html', context)


def about(request):
    """About us page."""
    therapists = Therapist.objects.filter(is_active=True)
    testimonials = Testimonial.objects.filter(is_approved=True)[:6]

    context = {
        'therapists': therapists,
        'testimonials': testimonials,
        **_get_site_stats(),
    }
    return render(request, 'website/about.html', context)


def _auto_assign_therapist(booking_obj):
    """Auto-assign a therapist to a booking based on preference/gender rules,
    respecting leave, day-off schedules, and existing booking conflicts."""
    import random as rand_module
    import datetime as dt

    if booking_obj.therapist:
        return

    target_date = booking_obj.date
    target_weekday = target_date.weekday()
    total_duration = sum(s.duration_minutes for s in booking_obj.services.all()) or 60

    # Build base queryset respecting gender rules
    pref = booking_obj.therapist_preference
    if booking_obj.client_gender == 'female':
        qs = Therapist.objects.filter(is_active=True, gender='female')
    elif pref in ('male', 'female'):
        qs = Therapist.objects.filter(is_active=True, gender=pref)
    else:
        qs = Therapist.objects.filter(is_active=True)

    # Exclude therapists on approved leave
    on_leave_ids = set(
        StaffLeave.objects.filter(
            is_active=True,
            status=StaffLeave.STATUS_APPROVED,
            start_date__lte=target_date,
            end_date__gte=target_date,
        ).values_list('therapist_id', flat=True)
    )

    # Exclude therapists scheduled as day-off on this weekday
    day_off_ids = set(
        StaffSchedule.objects.filter(
            therapist__in=qs,
            day_of_week=target_weekday,
            is_available=False,
        ).values_list('therapist_id', flat=True)
    )

    # Determine requested time window
    req_start_time = None
    req_start_dt = None
    req_end_dt = None
    req_end_time = None
    if booking_obj.time:
        try:
            req_start_time = dt.datetime.strptime(booking_obj.time, '%H:%M').time()
            req_start_dt = dt.datetime.combine(target_date, req_start_time)
            req_end_dt = req_start_dt + dt.timedelta(minutes=total_duration)
            req_end_time = req_end_dt.time()
        except Exception:
            req_start_time = None

    available = []
    for t in qs:
        if t.pk in on_leave_ids:
            continue
        if t.pk in day_off_ids:
            continue

        # Check shift hours
        if req_start_time:
            sched = StaffSchedule.objects.filter(
                therapist=t, day_of_week=target_weekday, is_available=True
            ).first()
            if sched:
                is_past_end = False
                if sched.end_time != dt.time(0, 0):
                    if req_end_time > sched.end_time:
                        is_past_end = True
                if req_start_time < sched.start_time or is_past_end:
                    continue

            # Check booking conflicts
            has_conflict = False
            t_bookings = Booking.objects.filter(
                therapist=t,
                date=target_date
            ).exclude(status='cancelled').exclude(pk=booking_obj.pk).prefetch_related('services')
            for tb in t_bookings:
                try:
                    b_start = dt.datetime.combine(
                        target_date,
                        dt.datetime.strptime(tb.time, '%H:%M').time()
                    )
                    b_dur = sum(s.duration_minutes for s in tb.services.all())
                    b_end = b_start + dt.timedelta(minutes=b_dur)
                    if max(req_start_dt, b_start) < min(req_end_dt, b_end):
                        has_conflict = True
                        break
                except Exception:
                    pass
            if has_conflict:
                continue

        available.append(t)

    if available:
        rand_module.shuffle(available)
        booking_obj.therapist = available[0]
        booking_obj.save()


def _create_booking_notifications(booking_obj):
    """Create customer and staff notifications for a new booking."""
    from django.urls import reverse

    services_str = ", ".join(s.name for s in booking_obj.services.all())
    BookingNotification.objects.create(
        booking=booking_obj,
        notification_type='confirmed',
        message=(
            f"Your booking for {services_str} on "
            f"{booking_obj.date.strftime('%B %d, %Y')} at "
            f"{booking_obj.get_time_display()} has been received. "
            f"We will confirm your appointment shortly."
        ),
    )
    StaffNotification.objects.create(
        notification_type='new_booking',
        title='New Online Booking',
        message=f"New online booking #{booking_obj.pk:04d} from {booking_obj.client_name}",
        target_role='all',
        target_therapist=booking_obj.therapist,
        link=reverse('portals:booking_list')
    )


def booking(request):
    """Booking page with form — supports single and family/group bookings."""
    Service.sync_all_for_today()
    if request.method == 'POST':
        is_family_mode = request.POST.get('booking_mode') == 'family'

        if is_family_mode:
            return _handle_family_booking(request)
        else:
            return _handle_single_booking(request)
    else:
        initial = {}
        service_id = request.GET.get('service')
        if service_id:
            initial['services'] = [service_id]
        form = BookingForm(initial=initial)

    services_list = Service.objects.filter(is_active=True)
    context = {
        'form': form,
        'services': services_list,
    }
    return render(request, 'website/booking.html', context)


def _handle_single_booking(request):
    """Process a standard single-person booking (existing behaviour)."""
    form = BookingForm(request.POST)
    if form.is_valid():
        booking_obj = form.save()
        _auto_assign_therapist(booking_obj)

        from .models import ClosedDay
        if ClosedDay.objects.filter(date=booking_obj.date).exists():
            booking_obj.delete()
            messages.error(request, 'The selected date is a Holiday. The spa is closed. Please select another date.')
            return redirect('website:booking')

        _create_booking_notifications(booking_obj)

        if 'my_bookings' not in request.session:
            request.session['my_bookings'] = []
        request.session['my_bookings'].append(booking_obj.pk)
        request.session.modified = True
        request.session['last_booking_id'] = booking_obj.pk
        request.session['last_booking_ids'] = [booking_obj.pk]
        
        _send_booking_otp(request, [booking_obj], booking_obj.client_email)
        return redirect('website:verify_booking')
    else:
        messages.error(request, 'Please correct the errors below.')
        services_list = Service.objects.filter(is_active=True)
        return render(request, 'website/booking.html', {
            'form': form,
            'services': services_list,
        })


def _handle_family_booking(request):
    """Process a family/group booking — multiple members, one email/phone."""
    import datetime
    from .models import ClosedDay

    POST = request.POST
    errors = []

    # --- shared fields ---
    client_email = POST.get('client_email', '').strip()
    client_phone = POST.get('client_phone', '').strip()
    date_str = POST.get('date', '').strip()
    time_val = POST.get('time', '').strip()
    notes = POST.get('notes', '').strip()

    if not client_email:
        errors.append('Email address is required.')
    if not client_phone:
        errors.append('Phone number is required.')
    if not date_str:
        errors.append('Date is required.')
    if not time_val:
        errors.append('Time is required.')

    # Parse date
    booking_date = None
    if date_str:
        try:
            booking_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            errors.append('Invalid date format.')

    # Check closed day
    if booking_date and ClosedDay.objects.filter(date=booking_date).exists():
        errors.append('The selected date is a Holiday. The spa is closed. Please select another date.')

    # --- parse members ---
    try:
        member_count = int(POST.get('member_count', 0))
    except (ValueError, TypeError):
        member_count = 0

    if member_count < 1:
        errors.append('At least one family member is required.')
    if member_count > 5:
        errors.append('Maximum 5 family members per group booking.')

    member_forms = []
    for i in range(min(member_count, 5)):
        mf = FamilyMemberForm({
            'name': POST.get(f'member_{i}_name', ''),
            'gender': POST.get(f'member_{i}_gender', ''),
            'services': POST.getlist(f'member_{i}_services'),
            'therapist_preference': POST.get(f'member_{i}_therapist_preference', ''),
            'therapist': POST.get(f'member_{i}_therapist', '') or None,
        })
        if not mf.is_valid():
            for field, field_errors in mf.errors.items():
                for e in field_errors:
                    errors.append(f'Member {i+1} — {e}')
        member_forms.append(mf)

    # --- therapist time-overlap check across the group ---
    if not errors and booking_date and time_val:
        try:
            from .models import StaffSchedule
            req_start_time = datetime.datetime.strptime(time_val, '%H:%M').time()
            target_weekday = booking_date.weekday()
            # Build a map of therapist -> list of durations for this group
            group_therapist_services = {}  # therapist_id -> [(start, end), ...]
            for mf in member_forms:
                cd = mf.cleaned_data
                therapist = cd.get('therapist')
                services = cd.get('services')
                if therapist and services:
                    total_duration = sum(s.duration_minutes for s in services)
                    duration = datetime.timedelta(minutes=total_duration)
                    req_start_dt = datetime.datetime.combine(booking_date, req_start_time)
                    req_end_dt = req_start_dt + duration
                    if therapist.pk not in group_therapist_services:
                        group_therapist_services[therapist.pk] = []
                    group_therapist_services[therapist.pk].append((req_start_dt, req_end_dt, therapist.name))

            from .models import StaffLeave
            # Check if requested time falls within each therapist's schedule and leave
            for t_id, slots in group_therapist_services.items():
                leave = StaffLeave.objects.filter(
                    is_active=True,
                    therapist_id=t_id, 
                    start_date__lte=booking_date, 
                    end_date__gte=booking_date
                ).first()
                if leave:
                    errors.append(f'{slots[0][2]} is on leave on this date.')
                    continue

                sched = StaffSchedule.objects.filter(
                    therapist_id=t_id,
                    day_of_week=target_weekday,
                    is_available=True,
                ).first()
                if sched:
                    for req_s, req_e, t_name in slots:
                        if req_start_time < sched.start_time or req_e.time() > sched.end_time:
                            sched_start_label = sched.start_time.strftime('%I:%M %p')
                            sched_end_label = sched.end_time.strftime('%I:%M %p')
                            errors.append(
                                f'{t_name} is only available from '
                                f'{sched_start_label} to {sched_end_label} on this day. '
                                f'Please choose a time within their schedule.'
                            )

            # Check if any therapist in the group is double-booked
            if not errors:
                for t_id, slots in group_therapist_services.items():
                    if len(slots) > 1:
                        errors.append(
                            f'Therapist {slots[0][2]} is selected for multiple family members '
                            f'at the same time. Please choose different therapists.'
                        )
                        break

            # Check against existing DB bookings
            if not errors:
                existing_bookings = Booking.objects.filter(
                    Q(booking_type='walk_in') | Q(is_verified=True) | Q(status__in=['pending', 'confirmed']),
                    date=booking_date,
                    status__in=['pending', 'confirmed'],
                ).prefetch_related('services')

                for t_id, slots in group_therapist_services.items():
                    for req_s, req_e, t_name in slots:
                        for b in existing_bookings:
                            if b.therapist_id != t_id:
                                continue
                            b_start = datetime.datetime.combine(booking_date,
                                datetime.datetime.strptime(b.time, '%H:%M').time())
                            b_total_dur = sum(s.duration_minutes for s in b.services.all())
                            b_end = b_start + datetime.timedelta(minutes=b_total_dur)
                            if max(req_s, b_start) < min(req_e, b_end):
                                errors.append(
                                    f'Therapist {t_name} is already booked during this timeframe. '
                                    f'Please select a different time or therapist.'
                                )
                                break
        except ValueError:
            pass

    # --- If errors, re-render with error messages ---
    if errors:
        for e in errors:
            messages.error(request, e)
        form = BookingForm()  # fresh form for re-render
        services_list = Service.objects.filter(is_active=True)
        return render(request, 'website/booking.html', {
            'form': form,
            'services': services_list,
            'family_errors': errors,
            'family_post_data': POST,
        })

    # --- All valid — create bookings ---
    created_bookings = []
    for mf in member_forms:
        cd = mf.cleaned_data
        booking_obj = Booking.objects.create(
            booking_type='online',
            client_name=cd['name'],
            client_email=client_email,
            client_phone=client_phone,
            client_gender=cd['gender'],
            therapist_preference=cd['therapist_preference'],
            therapist=cd.get('therapist'),
            date=booking_date,
            time=time_val,
            notes=notes,
            status='awaiting_verification',
        )
        booking_obj.services.set(cd['services'])
        snapshots = []
        total_lock = Decimal('0')
        for svc in cd['services']:
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
        _auto_assign_therapist(booking_obj)
        _create_booking_notifications(booking_obj)
        created_bookings.append(booking_obj)

    # Store all booking IDs in session
    if 'my_bookings' not in request.session:
        request.session['my_bookings'] = []
    booking_ids = [b.pk for b in created_bookings]
    request.session['my_bookings'].extend(booking_ids)
    request.session.modified = True
    request.session['last_booking_id'] = created_bookings[0].pk
    request.session['last_booking_ids'] = booking_ids
    
    _send_booking_otp(request, created_bookings, client_email)
    return redirect('website:verify_booking')


def booking_success(request):
    """Booking success confirmation page — supports single and family bookings."""
    booking_ids = request.session.get('last_booking_ids', [])
    bookings = []
    if booking_ids:
        bookings = list(
            Booking.objects.filter(pk__in=booking_ids)
            .select_related('therapist')
            .prefetch_related('services')
            .order_by('pk')
        )

    # Fallback to single booking for backwards compatibility
    if not bookings:
        last_booking_id = request.session.get('last_booking_id')
        if last_booking_id:
            try:
                bookings = [Booking.objects.select_related('therapist').prefetch_related('services').get(pk=last_booking_id)]
            except Booking.DoesNotExist:
                pass

    booking_obj = bookings[0] if bookings else None
    is_family = len(bookings) > 1

    return render(request, 'website/booking_success.html', {
        'booking': booking_obj,
        'bookings': bookings,
        'is_family': is_family,
    })


def my_bookings(request):
    """Customer: View booking history based on email lookup."""
    bookings = Booking.objects.none()
    notifications = BookingNotification.objects.none()
    email = request.GET.get('email', '').strip()
    searched = False

    has_completed_booking = False
    completed_services = Service.objects.none()
    if email:
        searched = True
        bookings = Booking.objects.filter(
            client_email__iexact=email
        ).exclude(status='awaiting_verification').select_related('therapist').prefetch_related('services').order_by('-created_at')
        has_completed_booking = bookings.filter(status='completed').exists()
        if has_completed_booking:
            completed_services = Service.objects.filter(
                bookings__client_email__iexact=email,
                bookings__status='completed',
            ).distinct()

    context = {
        'bookings': bookings,
        'notifications': notifications,
        'email': email,
        'searched': searched,
        'services': completed_services,
        'has_completed_booking': has_completed_booking,
    }
    return render(request, 'website/my_bookings.html', context)



def cancel_booking(request, pk):
    """Customer: Initiate cancellation - sends OTP for authentication."""
    booking_obj = get_object_or_404(Booking, pk=pk)

    # System rule: can only cancel pending or confirmed bookings
    if booking_obj.status not in ('pending', 'confirmed'):
        messages.error(
            request,
            'This booking can no longer be cancelled. '
            'Only pending or confirmed bookings may be cancelled.'
        )
        return redirect('website:my_bookings')

    if request.method == 'POST':
        # Send OTP to the client's email for cancellation authentication
        otp_sent = _send_booking_otp(request, [booking_obj], booking_obj.client_email, is_creation=False)
        if otp_sent:
            request.session['cancel_booking_pk'] = booking_obj.pk
            messages.info(
                request,
                f'A verification code has been sent to {booking_obj.client_email}. '
                'Please enter it below to confirm your cancellation.'
            )
            return redirect('website:cancel_booking_verify')
        else:
            # _send_booking_otp already added a warning message
            return redirect('website:my_bookings')

    context = {'booking': booking_obj}
    return render(request, 'website/cancel_booking.html', context)


def cancel_booking_verify(request):
    """Customer: Verify OTP to complete booking cancellation."""
    pk = request.session.get('cancel_booking_pk')
    if not pk:
        return redirect('website:my_bookings')

    booking_obj = get_object_or_404(Booking, pk=pk)

    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '').strip()

        if booking_obj.verification_otp and booking_obj.verification_otp == entered_otp:
            # OTP is correct — perform the cancellation
            booking_obj.verification_otp = None
            booking_obj.status = 'cancelled'
            booking_obj.save()

            # Clear session
            del request.session['cancel_booking_pk']

            # Create client notification
            services_str = ", ".join(s.name for s in booking_obj.services.all())
            BookingNotification.objects.create(
                booking=booking_obj,
                notification_type='cancelled',
                message=(
                    f"Your booking #{booking_obj.pk:04d} for {services_str} on "
                    f"{booking_obj.date.strftime('%B %d, %Y')} has been cancelled."
                ),
            )

            # Notify admin/staff
            from portals.models import StaffNotification
            from django.urls import reverse
            StaffNotification.objects.create(
                notification_type='booking_cancelled',
                title='Booking Cancelled',
                message=f"Booking #{booking_obj.pk:04d} was cancelled by the customer.",
                target_role='all',
                target_therapist=booking_obj.therapist,
                link=reverse('portals:booking_list')
            )

            messages.success(
                request,
                f'Booking #{booking_obj.pk:04d} has been cancelled successfully.'
            )
            return redirect('website:my_bookings')
        else:
            messages.error(request, 'Invalid OTP. Please try again.')

    return render(request, 'website/cancel_booking_verify.html', {'booking': booking_obj})


def mark_notification_read(request, pk):
    """AJAX: Mark a notification as read."""
    if request.method == 'POST':
        notif = get_object_or_404(BookingNotification, pk=pk)
        notif.is_read = True
        notif.save()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


import random
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

def _send_booking_otp(request, bookings, email, is_creation=True):
    otp = str(random.randint(100000, 999999))

    for b in bookings:
        b.verification_otp = otp
        if is_creation:
            b.is_verified = False
            b.save(update_fields=['verification_otp', 'is_verified'])
        else:
            b.save(update_fields=['verification_otp'])

    subject = "Verify Your Medpoint Spa Booking"
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Medpoint Massage & Spa <noreply@medpoint.com>')

    # ── Plain-text fallback (for clients that don't support HTML) ──────────────
    plain_message = (
        f"Hello,\n\n"
        f"Your OTP verification code for your Medpoint Massage & Spa appointment is:\n\n"
        f"  {otp}\n\n"
        f"Enter this code on the verification page to confirm your booking.\n"
        f"This code is valid for your current session only.\n\n"
        f"Thank you,\n"
        f"Medpoint Massage & Spa\n"
        f"medpointmassage.spa@gmail.com\n\n"
        f"This is an automated message. Please do not reply directly to this email."
    )

    # ── HTML email ─────────────────────────────────────────────────────────────
    html_message = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Verify Your Medpoint Spa Booking</title>
</head>
<body style="margin:0;padding:0;background-color:#1a1025;font-family:'Inter',Arial,sans-serif;">

  <!-- Wrapper -->
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
         style="background-color:#1a1025;padding:40px 16px;">
    <tr>
      <td align="center">

        <!-- Card -->
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
               style="max-width:560px;background-color:#1f1330;border-radius:16px;
                      overflow:hidden;border:1px solid rgba(168,85,247,0.2);
                      box-shadow:0 20px 60px rgba(0,0,0,0.5);">

          <!-- Header -->
          <tr>
            <td align="center"
                style="background:linear-gradient(135deg,#4a1a7a 0%,#2d1060 50%,#1a0845 100%);
                       padding:40px 32px 32px;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center">
                    <span style="font-size:26px;font-weight:700;letter-spacing:4px;
                                 color:#ffffff;font-family:Georgia,serif;">MEDPOINT</span>
                    <br/>
                    <span style="font-size:12px;letter-spacing:2px;color:#c084fc;
                                 text-transform:uppercase;margin-top:4px;display:block;">
                      Massage &amp; Spa
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">

              <h1 style="margin:0 0 8px;font-size:20px;font-weight:600;
                         color:#f3e8ff;font-family:Georgia,serif;">
                Booking Verification
              </h1>
              <p style="margin:0 0 24px;font-size:14px;color:#a78bfa;line-height:1.5;">
                Your appointment request has been received. Use the code below to confirm your booking.
              </p>

              <!-- OTP Box -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center" style="padding:8px 0 32px;">
                    <div style="background:linear-gradient(135deg,rgba(139,92,246,0.15),rgba(168,85,247,0.1));
                                border:2px solid rgba(168,85,247,0.4);border-radius:12px;
                                padding:28px 40px;display:inline-block;">
                      <p style="margin:0 0 8px;font-size:11px;letter-spacing:3px;
                                color:#a78bfa;text-transform:uppercase;font-weight:600;">
                        One-Time Password
                      </p>
                      <p style="margin:0;font-size:42px;font-weight:700;letter-spacing:12px;
                                color:#d4a843;font-family:Georgia,'Courier New',monospace;">
                        {otp}
                      </p>
                    </div>
                  </td>
                </tr>
              </table>

              <!-- Instructions -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
                     style="background:rgba(139,92,246,0.08);border-radius:10px;
                            border-left:3px solid #8b5cf6;margin-bottom:28px;">
                <tr>
                  <td style="padding:16px 20px;">
                    <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:#c4b5fd;">
                      How to use this code:
                    </p>
                    <p style="margin:0;font-size:13px;color:#9ca3af;line-height:1.7;">
                      1. Return to the Medpoint booking page in your browser.<br/>
                      2. Enter the 6-digit code above in the verification field.<br/>
                      3. Your appointment will be confirmed immediately.
                    </p>
                  </td>
                </tr>
              </table>

              <!-- Warning -->
              <p style="margin:0 0 8px;font-size:12px;color:#6b7280;line-height:1.6;">
                ⚠️ This code is valid for your <strong style="color:#9ca3af;">current session only</strong>
                and will expire once you close or refresh the page.
                If you did not make this booking request, please disregard this email.
              </p>

            </td>
          </tr>

          <!-- Divider -->
          <tr>
            <td style="padding:0 40px;">
              <hr style="border:none;border-top:1px solid rgba(168,85,247,0.15);margin:0;"/>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:24px 40px 32px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td>
                    <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#c084fc;">
                      Medpoint Massage &amp; Spa
                    </p>
                    <p style="margin:0 0 12px;font-size:12px;color:#6b7280;">
                      medpointmassage.spa@gmail.com
                    </p>
                    <p style="margin:0;font-size:11px;color:#4b5563;line-height:1.6;">
                      This is an automated message — please do not reply directly to this email.
                      If you need assistance, contact us at medpointmassage.spa@gmail.com
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
        <!-- /Card -->

        <!-- Bottom note -->
        <p style="margin:20px 0 0;font-size:11px;color:#4b5563;text-align:center;">
          © 2025 Medpoint Massage &amp; Spa. All rights reserved.
        </p>

      </td>
    </tr>
  </table>

</body>
</html>"""

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=from_email,
            to=[email],
        )
        msg.attach_alternative(html_message, "text/html")
        msg.send(fail_silently=False)
        return True
    except Exception as e:
        # Log the error so it shows in the server console
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to send OTP email to {email}: {e}")
        if request:
            messages.warning(
                request,
                f'We could not send the OTP to <strong>{email}</strong>. '
                'Please check that your email address is correct, or contact the spa directly.'
            )
        return False

def verify_booking(request):
    """Verify email with OTP."""
    booking_ids = request.session.get('last_booking_ids', [])
    if not booking_ids:
        return redirect('website:booking')
        
    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '').strip()
        bookings = Booking.objects.filter(pk__in=booking_ids)
        
        first_booking = bookings.first()
        if first_booking and first_booking.verification_otp == entered_otp:
            bookings.update(is_verified=True, verification_otp=None, status='pending')
            
            is_family = len(booking_ids) > 1
            if is_family:
                messages.success(request, f'Family appointment verified successfully for {len(booking_ids)} members! We will confirm your appointments shortly.')
            else:
                messages.success(request, f'Your appointment has been verified successfully! Booking reference: #{first_booking.pk:04d}. We will confirm your appointment shortly.')
                
            return redirect('website:booking_success')
        else:
            messages.error(request, 'Invalid OTP. Please try again.')
            
    return render(request, 'website/booking_verify.html', {'booking_ids': booking_ids})


def resend_otp(request):
    """Resend OTP to the client's email."""
    booking_ids = request.session.get('last_booking_ids', [])
    if not booking_ids:
        return redirect('website:booking')
        
    bookings = Booking.objects.filter(pk__in=booking_ids)
    first_booking = bookings.first()
    
    if first_booking and not first_booking.is_verified:
        # Resend the OTP
        _send_booking_otp(request, bookings, first_booking.client_email)
        messages.success(request, f'A new verification code has been sent to {first_booking.client_email}.')
    else:
        messages.info(request, 'This booking is already verified or no longer exists.')
        
    return redirect('website:verify_booking')


def get_therapists_by_preference(request):
    """API endpoint: Return therapists filtered by gender preference.
    Used by booking form JS to dynamically update the therapist dropdown.
    """
    pref = request.GET.get('preference', 'random')
    client_gender = request.GET.get('client_gender', 'male')
    date_str = request.GET.get('date', None)

    if client_gender == 'female':
        # Female clients can only get female therapists
        therapists = Therapist.objects.filter(is_active=True, gender='female')
    elif pref == 'random':
        therapists = Therapist.objects.filter(is_active=True)
    else:
        therapists = Therapist.objects.filter(is_active=True, gender=pref)

    target_weekday = None
    target_date = None
    if date_str:
        import datetime
        try:
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            target_weekday = target_date.weekday()
        except ValueError:
            pass

    schedules_map = {}
    schedule_hours_map = {}  # therapist_id -> {'start': 'HH:MM', 'end': 'HH:MM'}
    closed_date_obj = None
    if target_date:
        from .models import StaffSchedule, ClosedDay, StaffLeave
        
        # Check Staff Leaves
        leaves = StaffLeave.objects.filter(is_active=True, start_date__lte=target_date, end_date__gte=target_date)
        for leave in leaves:
            schedules_map[leave.therapist_id] = True

        closed_date_obj = ClosedDay.objects.filter(date=target_date).first()
        if closed_date_obj:
            for t in therapists:
                schedules_map[t.pk] = True
        elif target_weekday is not None:
            scheds = StaffSchedule.objects.filter(therapist__in=therapists, day_of_week=target_weekday)
            for s in scheds:
                if not s.is_available:
                    schedules_map[s.therapist_id] = True
                else:
                    schedule_hours_map[s.therapist_id] = {
                        'start': s.start_time.strftime('%H:%M'),
                        'end': s.end_time.strftime('%H:%M'),
                        'start_time': s.start_time,
                        'end_time': s.end_time,
                    }

    overlap_map = {}
    outside_schedule_map = {}  # therapist_id -> True if requested time is outside schedule
    next_avail_map = {}
    time_str = request.GET.get('time', None)
    service_id = request.GET.get('service_id', None)
    
    if target_date and time_str and service_id:
        from .models import Service, Booking
        try:
            req_start_time = datetime.datetime.strptime(time_str, '%H:%M').time()
            svc_ids = [int(x) for x in service_id.split(',') if x]
            services = Service.objects.filter(pk__in=svc_ids)
            total_duration = sum(s.duration_minutes for s in services)
            duration = datetime.timedelta(minutes=total_duration)
            req_start_dt = datetime.datetime.combine(target_date, req_start_time)
            req_end_dt = req_start_dt + duration
            req_end_time = req_end_dt.time()

            # Check if requested time is outside therapist's schedule hours
            # Compare as total minutes-from-midnight to avoid the midnight rollover bug
            # (e.g. start=22:00 + 120 min → end=00:00 next day, time() wraps to 0)
            req_start_mins = req_start_time.hour * 60 + req_start_time.minute
            req_end_mins = req_start_mins + total_duration  # may exceed 1440 if past midnight

            for t in therapists:
                sched = schedule_hours_map.get(t.pk)
                if sched:
                    sched_start = sched['start_time']
                    sched_end = sched['end_time']
                    sched_start_mins = sched_start.hour * 60 + sched_start.minute
                    sched_end_mins = sched_end.hour * 60 + sched_end.minute
                    # Midnight (00:00) means end-of-day = 1440 mins, not 0
                    if sched_end_mins == 0:
                        sched_end_mins = 1440
                    # Booking must start at or after schedule start AND end at or before schedule end
                    if req_start_mins < sched_start_mins or req_end_mins > sched_end_mins:
                        outside_schedule_map[t.pk] = True
            
            existing_bookings = Booking.objects.filter(
                Q(booking_type='walk_in') | Q(is_verified=True) | Q(status__in=['pending', 'confirmed']),
                date=target_date,
                status__in=['pending', 'confirmed'],
            ).prefetch_related('services')

            therapist_bookings = {}
            for b in existing_bookings:
                if not b.therapist_id:
                    continue
                if b.therapist_id not in therapist_bookings:
                    therapist_bookings[b.therapist_id] = []
                b_start_time = datetime.datetime.strptime(b.time, '%H:%M').time()
                b_start_dt = datetime.datetime.combine(target_date, b_start_time)
                b_total_dur = sum(s.duration_minutes for s in b.services.all())
                b_dur = datetime.timedelta(minutes=b_total_dur)
                b_end_dt = b_start_dt + b_dur
                therapist_bookings[b.therapist_id].append((b_start_dt, b_end_dt))
            
            for t in therapists:
                t_bookings = therapist_bookings.get(t.pk, [])
                is_booked = False
                for b_s, b_e in t_bookings:
                    if max(req_start_dt, b_s) < min(req_end_dt, b_e):
                        is_booked = True
                        break
                        
                if is_booked:
                    overlap_map[t.pk] = True
                    sched = schedule_hours_map.get(t.pk)
                    max_hour = 21
                    if sched:
                        # If shift ends at midnight (00:00), treat as hour 24 for the loop
                        end_h = sched['end_time'].hour
                        max_hour = 24 if end_h == 0 else end_h
                    for hour in range(req_start_dt.hour + 1, max_hour):
                        test_start = datetime.datetime.combine(target_date, datetime.time(hour % 24, 0))
                        test_end = test_start + duration
                        # Also ensure next available is within schedule
                        if sched and test_start.time() < sched['start_time']:
                            continue
                        # For midnight end, any time up to 23:59 is within schedule
                        if sched and sched['end_time'].hour != 0 and test_end.time() > sched['end_time']:
                            continue
                        overlap = False
                        for b_s, b_e in t_bookings:
                            if max(test_start, b_s) < min(test_end, b_e):
                                overlap = True
                                break
                        if not overlap:
                            time_label = f"{hour - 12}:00 PM" if hour > 12 else (f"12:00 PM" if hour == 12 else f"{hour}:00 AM")
                            next_avail_map[t.pk] = time_label
                            break

        except Exception:
            pass

    data = []
    for t in therapists:
        is_closed = closed_date_obj is not None
        closed_reason = closed_date_obj.reason if closed_date_obj else None
        
        # Override is_off to True if it's a closed day, but we'll also pass the specific closed info
        is_off = schedules_map.get(t.pk, False) or is_closed
        is_booked = overlap_map.get(t.pk, False)
        is_outside_schedule = outside_schedule_map.get(t.pk, False)
        next_avail = next_avail_map.get(t.pk, None)
        sched = schedule_hours_map.get(t.pk)
        
        entry = {
            'id': t.pk,
            'name': t.name,
            'title': t.title,
            'gender': t.gender,
            'photo': t.photo.url if t.photo else None,
            'is_off': is_off,
            'is_closed': is_closed,
            'closed_reason': closed_reason,
            'is_booked': is_booked,
            'is_outside_schedule': is_outside_schedule,
            'next_avail': next_avail,
        }
        if sched:
            entry['schedule_hours'] = f"{sched['start']} - {sched['end']}"
        data.append(entry)
    return JsonResponse({'therapists': data})


def contact(request):
    """Contact page with form."""
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            obj = form.save()
            from portals.models import StaffNotification
            from django.urls import reverse
            StaffNotification.objects.create(
                notification_type='new_message',
                title='New Contact Message',
                message=f"Message from {obj.name}: {obj.subject}",
                target_role='admin',
                link=reverse('portals:message_list')
            )
            messages.success(
                request,
                'Thank you for your message! We will get back to you shortly.'
            )
            return redirect('website:contact')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ContactForm()

    context = {
        'form': form,
    }
    return render(request, 'website/contact.html', context)


def submit_testimonial(request):
    """Customer: Submit a new testimonial."""
    if request.method == 'POST':
        client_name = request.POST.get('client_name')
        service_id = request.POST.get('service')
        rating = request.POST.get('rating')
        content = request.POST.get('content')
        
        if client_name and rating and content:
            service = Service.objects.filter(pk=service_id).first() if service_id else None
            Testimonial.objects.create(
                client_name=client_name,
                service=service,
                rating=int(rating),
                content=content,
                is_approved=False,
                is_featured=False
            )
            messages.success(request, 'Thank you! Your testimonial has been submitted and is pending approval.')
        else:
            messages.error(request, 'Please provide your name, a rating, and your review.')
            
    referer = request.META.get('HTTP_REFERER')
    return redirect(referer if referer else 'website:home')


def client_message_thread(request, token):
    """Customer: View message conversation and reply back to staff."""
    contact_message = get_object_or_404(
        ContactMessage.objects.prefetch_related('replies'),
        access_token=token
    )

    if request.method == 'POST':
        reply_text = request.POST.get('reply_text', '').strip()
        if reply_text:
            MessageReply.objects.create(
                message=contact_message,
                sender_type=MessageReply.SENDER_CLIENT,
                sender_name=contact_message.name,
                sender_email=contact_message.email,
                body=reply_text,
            )
            contact_message.is_read = False
            contact_message.save(update_fields=['is_read'])
            messages.success(request, 'Your reply has been sent to our team! We will get back to you shortly.')
            return redirect('website:client_message_thread', token=token)
        else:
            messages.error(request, 'Reply message cannot be empty.')

    return render(request, 'website/client_message_reply.html', {
        'contact_message': contact_message,
    })


# ─── Staff Leave Rebooking Flow ──────────────────────────────────────────────

def _send_rebooking_confirmation_email(new_booking, old_booking=None, action_type='switch_therapist'):
    """Send an HTML confirmation email to the client when they rebook after staff leave cancellation."""
    import logging
    from django.core.mail import send_mail
    from django.conf import settings

    therapist_name = new_booking.therapist.name if new_booking.therapist else 'Assigned on arrival'
    time_display = new_booking.get_time_display()
    date_display = new_booking.date.strftime('%B %d, %Y')
    services_str = new_booking.service_names
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Medpoint Massage & Spa <noreply@medpoint.com>')
    price_display = f"PHP {new_booking.locked_price:,.2f}" if new_booking.locked_price else "Standard rates"

    action_text = "therapist selection" if action_type == 'switch_therapist' else "appointment rescheduling"
    subject = "Booking Rescheduled Confirmation – Medpoint Massage & Spa"

    plain_message = (
        f"Hi {new_booking.client_name},\n\n"
        f"Your booking at Medpoint Massage & Spa has been successfully updated following your {action_text}.\n\n"
        f"Updated Booking Details:\n"
        f"  Reference #: #{new_booking.pk:04d}\n"
        f"  Date: {date_display}\n"
        f"  Time: {time_display}\n"
        f"  Therapist: {therapist_name}\n"
        f"  Services: {services_str}\n"
        f"  Total Amount: {price_display}\n\n"
        f"We look forward to welcoming you!\n\n"
        f"– Medpoint Massage & Spa Team"
    )

    html_message = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Booking Rescheduled – Medpoint Massage & Spa</title>
</head>
<body style="margin:0;padding:0;background-color:#0f0f15;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:580px;margin:0 auto;padding:32px 16px;">
    <div style="background-color:#171724;border-radius:16px;overflow:hidden;border:1px solid rgba(168,85,247,0.25);box-shadow:0 20px 60px rgba(0,0,0,0.6);">
      <!-- Header -->
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
             style="background:linear-gradient(135deg,#4a1a7a 0%,#2d1060 50%,#1a0845 100%);padding:32px 28px;text-align:center;">
        <tr>
          <td>
            <div style="font-size:26px;font-weight:700;letter-spacing:4px;color:#ffffff;font-family:Georgia,serif;">MEDPOINT</div>
            <div style="font-size:11px;letter-spacing:2px;color:#c084fc;text-transform:uppercase;margin-top:4px;">Massage &amp; Spa Wellness</div>
          </td>
        </tr>
      </table>

      <!-- Status Banner -->
      <div style="background:rgba(34,197,94,0.12);border-bottom:1px solid rgba(34,197,94,0.25);padding:14px 28px;text-align:center;">
        <span style="color:#4ade80;font-size:13px;font-weight:600;letter-spacing:0.5px;">
          &#10003; REBOOKING CONFIRMED &bull; NEW BOOKING #{new_booking.pk:04d}
        </span>
      </div>

      <!-- Main Content -->
      <div style="padding:28px 32px;">
        <h2 style="margin:0 0 10px;color:#ffffff;font-size:18px;font-weight:600;">
          Hi {new_booking.client_name},
        </h2>
        <p style="margin:0 0 22px;color:#a1a1aa;font-size:14px;line-height:1.6;">
          Your appointment has been successfully updated. We have reserved your new schedule with our professional team.
        </p>

        <!-- Booking Details Card -->
        <div style="background-color:#1f1d2e;border:1px solid rgba(168,85,247,0.2);border-radius:12px;padding:20px;margin-bottom:24px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
            <tr>
              <td style="color:#71717a;font-size:12px;padding-bottom:10px;text-transform:uppercase;letter-spacing:1px;">Booking Reference</td>
              <td align="right" style="color:#a855f7;font-size:14px;font-weight:700;padding-bottom:10px;">#{new_booking.pk:04d}</td>
            </tr>
            <tr>
              <td style="color:#71717a;font-size:12px;padding-bottom:10px;text-transform:uppercase;letter-spacing:1px;">Services</td>
              <td align="right" style="color:#ffffff;font-size:13px;font-weight:500;padding-bottom:10px;">{services_str}</td>
            </tr>
            <tr>
              <td style="color:#71717a;font-size:12px;padding-bottom:10px;text-transform:uppercase;letter-spacing:1px;">Date</td>
              <td align="right" style="color:#ffffff;font-size:13px;font-weight:500;padding-bottom:10px;">{date_display}</td>
            </tr>
            <tr>
              <td style="color:#71717a;font-size:12px;padding-bottom:10px;text-transform:uppercase;letter-spacing:1px;">Time</td>
              <td align="right" style="color:#ffffff;font-size:13px;font-weight:500;padding-bottom:10px;">{time_display}</td>
            </tr>
            <tr>
              <td style="color:#71717a;font-size:12px;padding-bottom:10px;text-transform:uppercase;letter-spacing:1px;">Therapist</td>
              <td align="right" style="color:#38bdf8;font-size:13px;font-weight:600;padding-bottom:10px;">{therapist_name}</td>
            </tr>
            <tr>
              <td style="color:#71717a;font-size:12px;text-transform:uppercase;letter-spacing:1px;">Total Price</td>
              <td align="right" style="color:#4ade80;font-size:15px;font-weight:700;">{price_display}</td>
            </tr>
          </table>
        </div>

        <p style="margin:0;color:#71717a;font-size:12px;line-height:1.6;">
          If you have any questions or need further assistance, feel free to contact us at
          <a href="mailto:medpointmassage.spa@gmail.com" style="color:#c084fc;">medpointmassage.spa@gmail.com</a>.
        </p>
      </div>

      <!-- Footer -->
      <div style="border-top:1px solid rgba(255,255,255,0.06);padding:16px 32px;text-align:center;">
        <p style="margin:0;color:#52525b;font-size:12px;">
          &copy; Medpoint Massage &amp; Spa &bull; Dedicated to Your Peace &amp; Well-being
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
            recipient_list=[new_booking.client_email],
            html_message=html_message,
            fail_silently=True,
        )
    except Exception as e:
        logging.getLogger(__name__).warning(f'Failed to send rebooking confirmation email to {new_booking.client_email}: {e}')


def rebooking_options(request, token):
    """
    Public page for clients whose booking was auto-cancelled due to staff leave.
    Provides options to:
    1) Choose another available therapist on the same date/time
    2) Reschedule to another date/time
    """
    import datetime

    booking = Booking.objects.filter(
        rebooking_token=token,
        status='cancelled'
    ).select_related('therapist').prefetch_related('services').first()

    if not booking:
        return render(request, 'website/rebooking_options.html', {
            'expired': True,
        })

    if request.method == 'POST':
        return rebooking_submit(request, token)

    # Calculate total duration for this booking
    total_duration = sum(s.duration_minutes for s in booking.services.all())
    req_time_str = booking.time
    target_date = booking.date
    target_weekday = target_date.weekday()

    # Check closed day for original date
    is_closed_day = ClosedDay.objects.filter(date=target_date).exists()
    available_therapists = []

    if not is_closed_day:
        candidate_therapists = Therapist.objects.filter(is_active=True)
        if booking.therapist_id:
            candidate_therapists = candidate_therapists.exclude(pk=booking.therapist_id)

        # --- Gender filtering based on client gender ---
        # Female customers can ONLY choose female therapists.
        # Male customers can choose both male and female therapists.
        if booking.client_gender == 'female':
            candidate_therapists = candidate_therapists.filter(gender='female')

        # Exclude therapists on approved leave for target_date
        leave_therapist_ids = set(
            StaffLeave.objects.filter(
                is_active=True,
                status=StaffLeave.STATUS_APPROVED,
                start_date__lte=target_date,
                end_date__gte=target_date
            ).values_list('therapist_id', flat=True)
        )

        # Exclude therapists scheduled as day-off on this weekday
        day_off_therapist_ids = set(
            StaffSchedule.objects.filter(
                therapist__in=candidate_therapists,
                day_of_week=target_weekday,
                is_available=False
            ).values_list('therapist_id', flat=True)
        )

        try:
            req_start_time = datetime.datetime.strptime(req_time_str, '%H:%M').time()
            req_start_dt = datetime.datetime.combine(target_date, req_start_time)
            req_end_dt = req_start_dt + datetime.timedelta(minutes=total_duration)
            req_end_time = req_end_dt.time()
        except Exception:
            req_start_time = None

        for t in candidate_therapists:
            if t.pk in leave_therapist_ids:
                continue
            if t.pk in day_off_therapist_ids:
                continue

            sched = StaffSchedule.objects.filter(therapist=t, day_of_week=target_weekday, is_available=True).first()
            if sched and req_start_time:
                is_past_end = False
                if sched.end_time != datetime.time(0, 0):
                    if req_end_time > sched.end_time:
                        is_past_end = True
                if req_start_time < sched.start_time or is_past_end:
                    continue

            has_conflict = False
            if req_start_time:
                t_bookings = Booking.objects.filter(
                    therapist=t,
                    date=target_date
                ).exclude(status='cancelled').exclude(pk=booking.pk).prefetch_related('services')

                for tb in t_bookings:
                    try:
                        b_start = datetime.datetime.combine(target_date, datetime.datetime.strptime(tb.time, '%H:%M').time())
                        b_dur = sum(s.duration_minutes for s in tb.services.all())
                        b_end = b_start + datetime.timedelta(minutes=b_dur)
                        if max(req_start_dt, b_start) < min(req_end_dt, b_end):
                            has_conflict = True
                            break
                    except Exception:
                        pass

            if not has_conflict:
                available_therapists.append(t)

    # --- Reschedule tab: all therapists allowed for the new date
    # Female customers can only choose female therapists; male customers can choose both
    if booking.client_gender == 'female':
        all_therapists = Therapist.objects.filter(is_active=True, gender='female')
    else:
        all_therapists = Therapist.objects.filter(is_active=True)
    today = timezone.localdate()
    min_date = today.strftime('%Y-%m-%d')

    context = {
        'expired': False,
        'booking': booking,
        'available_therapists': available_therapists,
        'all_therapists': all_therapists,
        'is_closed_day': is_closed_day,
        'time_choices': Booking.TIME_CHOICES,
        'min_date': min_date,
        'token': token,
        'client_gender': booking.client_gender,
    }
    return render(request, 'website/rebooking_options.html', context)


def rebooking_therapists_api(request, token):
    """
    AJAX endpoint: returns available therapists for a given date when rescheduling.
    Respects client gender rules, leave exclusions, and day-off schedules.
    URL: /booking/rebook/<uuid:token>/therapists/?date=YYYY-MM-DD
    """
    import json
    import datetime

    booking = Booking.objects.filter(
        rebooking_token=token,
        status='cancelled'
    ).select_related('therapist').first()

    if not booking:
        return JsonResponse({'error': 'Invalid token'}, status=404)

    date_str = request.GET.get('date', '')
    try:
        target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date'}, status=400)

    if ClosedDay.objects.filter(date=target_date).exists():
        return JsonResponse({'closed': True, 'therapists': []})

    target_weekday = target_date.weekday()

    # Gender constraint: Female clients can only choose female therapists; Male clients can choose both
    if booking.client_gender == 'female':
        qs = Therapist.objects.filter(is_active=True, gender='female')
    else:
        qs = Therapist.objects.filter(is_active=True)

    # If rescheduling to the same date as the original booking, exclude the original therapist on leave
    if target_date == booking.date and booking.therapist_id:
        qs = qs.exclude(pk=booking.therapist_id)

    # Exclude therapists on approved leave on this date
    on_leave_ids = set(
        StaffLeave.objects.filter(
            is_active=True,
            status=StaffLeave.STATUS_APPROVED,
            start_date__lte=target_date,
            end_date__gte=target_date,
        ).values_list('therapist_id', flat=True)
    )

    # Exclude therapists on day-off on this weekday
    day_off_ids = set(
        StaffSchedule.objects.filter(
            therapist__in=qs,
            day_of_week=target_weekday,
            is_available=False,
        ).values_list('therapist_id', flat=True)
    )

    # Parse requested time and compute end time for conflict checking
    time_str = request.GET.get('time', '').strip()
    total_duration = sum(s.duration_minutes for s in booking.services.all()) or 60
    req_start_time = None
    req_start_dt = None
    req_end_dt = None
    req_end_time = None
    if time_str:
        try:
            req_start_time = datetime.datetime.strptime(time_str, '%H:%M').time()
            req_start_dt = datetime.datetime.combine(target_date, req_start_time)
            req_end_dt = req_start_dt + datetime.timedelta(minutes=total_duration)
            req_end_time = req_end_dt.time()
        except Exception:
            req_start_time = None

    result = []
    for t in qs:
        if t.pk in on_leave_ids:
            continue
        if t.pk in day_off_ids:
            continue

        # Check shift hours
        if req_start_time:
            sched = StaffSchedule.objects.filter(
                therapist=t, day_of_week=target_weekday, is_available=True
            ).first()
            if sched:
                is_past_end = False
                if sched.end_time != datetime.time(0, 0):
                    if req_end_time > sched.end_time:
                        is_past_end = True
                if req_start_time < sched.start_time or is_past_end:
                    continue

            # Check booking conflicts
            has_conflict = False
            t_bookings = Booking.objects.filter(
                therapist=t,
                date=target_date
            ).exclude(status='cancelled').prefetch_related('services')
            for tb in t_bookings:
                try:
                    b_start = datetime.datetime.combine(
                        target_date,
                        datetime.datetime.strptime(tb.time, '%H:%M').time()
                    )
                    b_dur = sum(s.duration_minutes for s in tb.services.all())
                    b_end = b_start + datetime.timedelta(minutes=b_dur)
                    if max(req_start_dt, b_start) < min(req_end_dt, b_end):
                        has_conflict = True
                        break
                except Exception:
                    pass
            if has_conflict:
                continue

        result.append({
            'id': t.pk,
            'name': t.name,
            'gender': t.gender,
            'gender_display': t.get_gender_display(),
        })

    return JsonResponse({'closed': False, 'therapists': result})


def rebooking_submit(request, token):
    """Process customer's rebooking choice (Switch Therapist OR Reschedule Date)."""
    import datetime

    if request.method != 'POST':
        return redirect('website:rebooking_options', token=token)

    booking = Booking.objects.filter(
        rebooking_token=token,
        status='cancelled'
    ).select_related('therapist').prefetch_related('services').first()

    if not booking:
        messages.error(request, 'This rebooking link has expired or has already been used.')
        return redirect('website:my_bookings')

    action = request.POST.get('action', '').strip()

    if action == 'switch_therapist':
        if ClosedDay.objects.filter(date=booking.date).exists():
            messages.error(request, 'The spa is closed on this date. Please choose another date to reschedule.')
            return redirect('website:rebooking_options', token=token)

        therapist_id = request.POST.get('therapist_id', '').strip()
        chosen_therapist = None

        if therapist_id and therapist_id != 'auto':
            chosen_therapist = Therapist.objects.filter(pk=therapist_id, is_active=True).first()
            if not chosen_therapist:
                messages.error(request, 'Selected specialist could not be found.')
                return redirect('website:rebooking_options', token=token)

            if booking.therapist_id and chosen_therapist.pk == booking.therapist_id:
                messages.error(request, f'{chosen_therapist.name} is on leave on this date. Please select another specialist.')
                return redirect('website:rebooking_options', token=token)

            if booking.client_gender == 'female' and chosen_therapist.gender != 'female':
                messages.error(request, 'Female clients may only choose female specialists.')
                return redirect('website:rebooking_options', token=token)

            if StaffLeave.objects.filter(
                therapist=chosen_therapist,
                is_active=True,
                status=StaffLeave.STATUS_APPROVED,
                start_date__lte=booking.date,
                end_date__gte=booking.date
            ).exists():
                messages.error(request, f'{chosen_therapist.name} is on leave on this date. Please select another therapist.')
                return redirect('website:rebooking_options', token=token)
        else:
            avail = Therapist.objects.filter(is_active=True)
            if booking.therapist_id:
                avail = avail.exclude(pk=booking.therapist_id)
            if booking.client_gender == 'female':
                avail = avail.filter(gender='female')
            on_leave_ids = StaffLeave.objects.filter(
                is_active=True,
                status=StaffLeave.STATUS_APPROVED,
                start_date__lte=booking.date,
                end_date__gte=booking.date
            ).values_list('therapist_id', flat=True)
            avail = avail.exclude(pk__in=on_leave_ids)

            if booking.therapist_preference in ('male', 'female'):
                avail_pref = avail.filter(gender=booking.therapist_preference)
                if avail_pref.exists():
                    avail = avail_pref

            chosen_therapist = avail.order_by('?').first()

        new_booking = Booking.objects.create(
            booking_type=booking.booking_type or 'online',
            client_name=booking.client_name,
            client_email=booking.client_email,
            client_phone=booking.client_phone,
            client_gender=booking.client_gender,
            therapist_preference='female' if booking.client_gender == 'female' else (booking.therapist_preference or 'random'),
            therapist=chosen_therapist,
            date=booking.date,
            time=booking.time,
            notes=booking.notes or '',
            status='pending',
            is_verified=True,
            locked_price=booking.locked_price,
            service_prices_snapshot=booking.service_prices_snapshot,
        )
        new_booking.services.set(booking.services.all())

        booking.rebooking_token = None
        booking.save(update_fields=['rebooking_token'])

        _create_booking_notifications(new_booking)
        _send_rebooking_confirmation_email(new_booking, booking, action_type='switch_therapist')

        request.session['last_booking_id'] = new_booking.pk
        request.session['last_booking_ids'] = [new_booking.pk]
        if 'my_bookings' not in request.session:
            request.session['my_bookings'] = []
        request.session['my_bookings'].append(new_booking.pk)
        request.session.modified = True

        therapist_label = chosen_therapist.name if chosen_therapist else 'an assigned therapist'
        messages.success(
            request,
            f'Your booking has been rebooked with {therapist_label} for '
            f'{new_booking.date.strftime("%B %d, %Y")} at {new_booking.get_time_display()}!'
        )
        return redirect('website:booking_success')

    elif action == 'reschedule_date':
        new_date_str = request.POST.get('new_date', '').strip()
        new_time_str = request.POST.get('new_time', '').strip()
        therapist_pref = request.POST.get('therapist_preference', booking.therapist_preference or 'random').strip()
        therapist_id = request.POST.get('therapist_id', '').strip()

        if not new_date_str:
            messages.error(request, 'Please select a new date.')
            return redirect('website:rebooking_options', token=token)

        try:
            new_date = datetime.datetime.strptime(new_date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Invalid date format.')
            return redirect('website:rebooking_options', token=token)

        today = timezone.localdate()
        if new_date < today:
            messages.error(request, 'You cannot select a past date.')
            return redirect('website:rebooking_options', token=token)

        if ClosedDay.objects.filter(date=new_date).exists():
            messages.error(request, 'The spa is closed on the selected date. Please choose another day.')
            return redirect('website:rebooking_options', token=token)

        if not new_time_str or new_time_str not in dict(Booking.TIME_CHOICES):
            messages.error(request, 'Please select a valid time slot.')
            return redirect('website:rebooking_options', token=token)

        chosen_therapist = None
        if therapist_id and therapist_id != 'auto':
            chosen_therapist = Therapist.objects.filter(pk=therapist_id, is_active=True).first()
            if chosen_therapist:
                if booking.client_gender == 'female' and chosen_therapist.gender != 'female':
                    messages.error(request, 'Female clients may only choose female specialists.')
                    return redirect('website:rebooking_options', token=token)

                if new_date == booking.date and booking.therapist_id and chosen_therapist.pk == booking.therapist_id:
                    messages.error(request, f'{chosen_therapist.name} is on leave on {new_date.strftime("%B %d, %Y")}. Please select another specialist.')
                    return redirect('website:rebooking_options', token=token)

                if StaffLeave.objects.filter(
                    therapist=chosen_therapist,
                    is_active=True,
                    status=StaffLeave.STATUS_APPROVED,
                    start_date__lte=new_date,
                    end_date__gte=new_date
                ).exists():
                    messages.error(request, f'{chosen_therapist.name} is on leave on {new_date.strftime("%B %d, %Y")}. Please select another therapist or choose auto-assign.')
                    return redirect('website:rebooking_options', token=token)

        assigned_pref = 'female' if booking.client_gender == 'female' else therapist_pref
        new_booking = Booking.objects.create(
            booking_type=booking.booking_type or 'online',
            client_name=booking.client_name,
            client_email=booking.client_email,
            client_phone=booking.client_phone,
            client_gender=booking.client_gender,
            therapist_preference=assigned_pref,
            therapist=chosen_therapist,
            date=new_date,
            time=new_time_str,
            notes=booking.notes or '',
            status='pending',
            is_verified=True,
            locked_price=booking.locked_price,
            service_prices_snapshot=booking.service_prices_snapshot,
        )
        new_booking.services.set(booking.services.all())

        if not new_booking.therapist:
            _auto_assign_therapist(new_booking)

        booking.rebooking_token = None
        booking.save(update_fields=['rebooking_token'])

        _create_booking_notifications(new_booking)
        _send_rebooking_confirmation_email(new_booking, booking, action_type='reschedule_date')

        request.session['last_booking_id'] = new_booking.pk
        request.session['last_booking_ids'] = [new_booking.pk]
        if 'my_bookings' not in request.session:
            request.session['my_bookings'] = []
        request.session['my_bookings'].append(new_booking.pk)
        request.session.modified = True

        messages.success(
            request,
            f'Your booking has been rescheduled for {new_booking.date.strftime("%B %d, %Y")} at '
            f'{new_booking.get_time_display()}!'
        )
        return redirect('website:booking_success')

    else:
        messages.error(request, 'Please select a valid rebooking option.')
        return redirect('website:rebooking_options', token=token)

