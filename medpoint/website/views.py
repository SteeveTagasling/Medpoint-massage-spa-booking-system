from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone

from .models import (
    Service, Therapist, Testimonial, GalleryImage,
    Booking, BookingNotification, ContactMessage,
)
from .forms import BookingForm, ContactForm
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


def booking(request):
    """Booking page with form — includes gender-preference validation."""
    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            booking_obj = form.save()

            # Auto-assign therapist if preference is set but no specific therapist chosen
            if not booking_obj.therapist and booking_obj.therapist_preference != 'random':
                matching = Therapist.objects.filter(
                    is_active=True, gender=booking_obj.therapist_preference
                )
                if matching.exists():
                    # Pick least-booked therapist for this date
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

            from .models import ClosedDay
            is_closed = ClosedDay.objects.filter(date=booking_obj.date).exists()
            if is_closed:
                booking_obj.delete()
                messages.error(request, 'The selected date is a Holiday. The spa is closed. Please select another date.')
                return redirect('website:booking')

            # Create notification
            BookingNotification.objects.create(
                booking=booking_obj,
                notification_type='confirmed',
                message=(
                    f"Your booking for {booking_obj.service.name} on "
                    f"{booking_obj.date.strftime('%B %d, %Y')} at "
                    f"{booking_obj.get_time_display()} has been received. "
                    f"We will confirm your appointment shortly."
                ),
            )

            from portals.models import StaffNotification
            from django.urls import reverse
            
            # Notify portal admins
            msg = f"New online booking #{booking_obj.pk:04d} from {booking_obj.client_name}"
            target_t = booking_obj.therapist
            
            StaffNotification.objects.create(
                notification_type='new_booking',
                title='New Online Booking',
                message=msg,
                target_role='all',
                target_therapist=target_t,
                link=reverse('portals:booking_list')
            )
            if 'my_bookings' not in request.session:
                request.session['my_bookings'] = []
            request.session['my_bookings'].append(booking_obj.pk)
            request.session.modified = True
            request.session['last_booking_id'] = booking_obj.pk

            messages.success(
                request,
                f'Your appointment has been booked successfully! '
                f'Booking reference: #{booking_obj.pk:04d}. '
                f'We will confirm your appointment shortly.'
            )
            return redirect('website:booking_success')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = BookingForm()

    services_list = Service.objects.filter(is_active=True)

    context = {
        'form': form,
        'services': services_list,
    }
    return render(request, 'website/booking.html', context)


def booking_success(request):
    """Booking success confirmation page."""
    last_booking_id = request.session.get('last_booking_id')
    booking_obj = None
    if last_booking_id:
        try:
            booking_obj = Booking.objects.select_related('service', 'therapist').get(pk=last_booking_id)
        except Booking.DoesNotExist:
            pass
    return render(request, 'website/booking_success.html', {'booking': booking_obj})


def my_bookings(request):
    """Customer: View booking history based on email lookup."""
    bookings = Booking.objects.none()
    notifications = BookingNotification.objects.none()
    email = request.GET.get('email', '').strip()
    searched = False

    if email:
        searched = True
        bookings = Booking.objects.filter(
            client_email__iexact=email
        ).select_related('service', 'therapist').order_by('-date', '-time')
    services = Service.objects.filter(is_active=True)

    context = {
        'bookings': bookings,
        'notifications': notifications,
        'email': email,
        'searched': searched,
        'services': services,
    }
    return render(request, 'website/my_bookings.html', context)



def cancel_booking(request, pk):
    """Customer: Cancel a booking with system rule (only pending/confirmed)."""
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
        booking_obj.status = 'cancelled'
        booking_obj.save()

        # Create cancellation notification
        BookingNotification.objects.create(
            booking=booking_obj,
            notification_type='cancelled',
            message=(
                f"Your booking #{booking_obj.pk:04d} for {booking_obj.service.name} on "
                f"{booking_obj.date.strftime('%B %d, %Y')} has been cancelled."
            ),
        )
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

    context = {'booking': booking_obj}
    return render(request, 'website/cancel_booking.html', context)


def mark_notification_read(request, pk):
    """AJAX: Mark a notification as read."""
    if request.method == 'POST':
        notif = get_object_or_404(BookingNotification, pk=pk)
        notif.is_read = True
        notif.save()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


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
    closed_date_obj = None
    if target_date:
        from .models import StaffSchedule, ClosedDay
        closed_date_obj = ClosedDay.objects.filter(date=target_date).first()
        if closed_date_obj:
            for t in therapists:
                schedules_map[t.pk] = True
        elif target_weekday is not None:
            scheds = StaffSchedule.objects.filter(therapist__in=therapists, day_of_week=target_weekday)
            for s in scheds:
                if not s.is_available:
                    schedules_map[s.therapist_id] = True

    overlap_map = {}
    next_avail_map = {}
    time_str = request.GET.get('time', None)
    service_id = request.GET.get('service_id', None)
    
    if target_date and time_str and service_id:
        from .models import Service, Booking
        try:
            req_start_time = datetime.datetime.strptime(time_str, '%H:%M').time()
            svc = Service.objects.get(pk=service_id)
            duration = datetime.timedelta(minutes=svc.duration_minutes)
            req_start_dt = datetime.datetime.combine(target_date, req_start_time)
            req_end_dt = req_start_dt + duration
            
            existing_bookings = Booking.objects.filter(
                date=target_date,
                status__in=['pending', 'confirmed']
            ).select_related('service')

            therapist_bookings = {}
            for b in existing_bookings:
                if not b.therapist_id:
                    continue
                if b.therapist_id not in therapist_bookings:
                    therapist_bookings[b.therapist_id] = []
                b_start_time = datetime.datetime.strptime(b.time, '%H:%M').time()
                b_start_dt = datetime.datetime.combine(target_date, b_start_time)
                b_dur = datetime.timedelta(minutes=b.service.duration_minutes)
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
                    for hour in range(req_start_dt.hour + 1, 21):
                        test_start = datetime.datetime.combine(target_date, datetime.time(hour, 0))
                        test_end = test_start + duration
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
        next_avail = next_avail_map.get(t.pk, None)
        
        data.append({
            'id': t.pk,
            'name': t.name,
            'title': t.title,
            'gender': t.gender,
            'photo': t.photo.url if t.photo else None,
            'is_off': is_off,
            'is_closed': is_closed,
            'closed_reason': closed_reason,
            'is_booked': is_booked,
            'next_avail': next_avail,
        })
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
