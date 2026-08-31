from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone

from .models import (
    Service, Therapist, Testimonial, GalleryImage,
    Booking, BookingNotification, ContactMessage,
)
from .forms import BookingForm, ContactForm, FamilyMemberForm
from portals.models import StaffNotification


def home(request):
    """Homepage view with featured services, testimonials, and gallery."""
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
    }
    return render(request, 'website/home.html', context)


def services(request):
    """Services listing page."""
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
    }
    return render(request, 'website/about.html', context)


def _auto_assign_therapist(booking_obj):
    """Auto-assign a therapist to a booking based on preference/gender rules."""
    import random as rand_module
    if not booking_obj.therapist and booking_obj.therapist_preference != 'random':
        matching = Therapist.objects.filter(
            is_active=True, gender=booking_obj.therapist_preference
        )
        if matching.exists():
            available = list(matching)
            rand_module.shuffle(available)
            booking_obj.therapist = available[0]
            booking_obj.save()
    elif not booking_obj.therapist and booking_obj.therapist_preference == 'random':
        if booking_obj.client_gender == 'female':
            matching = Therapist.objects.filter(is_active=True, gender='female')
        else:
            matching = Therapist.objects.filter(is_active=True)
        if matching.exists():
            available = list(matching)
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
                    date=booking_date,
                    status__in=['pending', 'confirmed']
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
            status='pending',
        )
        booking_obj.services.set(cd['services'])
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
    if email:
        searched = True
        bookings = Booking.objects.filter(
            client_email__iexact=email
        ).select_related('therapist').prefetch_related('services').order_by('-created_at')
        has_completed_booking = bookings.filter(status='completed').exists()

    services = Service.objects.filter(is_active=True)

    context = {
        'bookings': bookings,
        'notifications': notifications,
        'email': email,
        'searched': searched,
        'services': services,
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
            bookings.update(is_verified=True, verification_otp=None)
            
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
                date=target_date,
                status__in=['pending', 'confirmed']
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
