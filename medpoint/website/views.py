from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone

from .models import (
    Service, Therapist, Testimonial, GalleryImage,
    Booking, BookingNotification, ContactMessage,
)
from .forms import BookingForm, ContactForm


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
        all_services = all_services.filter(category=category)

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
    related_services = Service.objects.filter(
        category=service.category, is_active=True
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

            # Store booking reference in session for the success page and My Bookings
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
        notifications = BookingNotification.objects.filter(
            booking__client_email__iexact=email,
            is_read=False,
        ).select_related('booking')

    # Also include session-based bookings
    session_ids = request.session.get('my_bookings', [])
    if session_ids and not email:
        bookings = Booking.objects.filter(
            pk__in=session_ids
        ).select_related('service', 'therapist').order_by('-date', '-time')
        notifications = BookingNotification.objects.filter(
            booking__pk__in=session_ids,
            is_read=False,
        ).select_related('booking')
        searched = len(session_ids) > 0

    context = {
        'bookings': bookings,
        'notifications': notifications,
        'email': email,
        'searched': searched,
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

    if client_gender == 'female':
        # Female clients can only get female therapists
        therapists = Therapist.objects.filter(is_active=True, gender='female')
    elif pref == 'random':
        therapists = Therapist.objects.filter(is_active=True)
    else:
        therapists = Therapist.objects.filter(is_active=True, gender=pref)

    data = [
        {
            'id': t.pk,
            'name': t.name,
            'title': t.title,
            'gender': t.gender,
            'photo': t.photo.url if t.photo else None,
        }
        for t in therapists
    ]
    return JsonResponse({'therapists': data})


def contact(request):
    """Contact page with form."""
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()
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
