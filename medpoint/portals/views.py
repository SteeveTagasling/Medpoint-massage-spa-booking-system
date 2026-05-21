from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Q
from django.utils import timezone

from website.models import Service, Therapist, Testimonial, GalleryImage, Booking, ContactMessage


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
                # Store the selected role in the session
                request.session['portal_role'] = role
                next_url = request.GET.get('next', 'portals:dashboard')
                return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'portals/login.html')


@login_required(login_url='portals:login')
def portal_logout(request):
    """Logout and redirect to login."""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('portals:login')


def _is_admin(request):
    """Check if the current user is logged in as admin."""
    return request.user.is_superuser and request.session.get('portal_role') == 'admin'


def _is_staff_only(request):
    """Check if the current user is logged in as staff (not admin)."""
    return request.session.get('portal_role') == 'staff'


@login_required(login_url='portals:login')
def dashboard(request):
    """Portal dashboard with key metrics."""
    if not request.user.is_staff:
        return redirect('portals:login')

    today = timezone.now().date()

    # Key metrics
    total_bookings = Booking.objects.count()
    pending_bookings = Booking.objects.filter(status='pending').count()
    confirmed_bookings = Booking.objects.filter(status='confirmed').count()
    today_bookings = Booking.objects.filter(date=today).count()
    total_services = Service.objects.filter(is_active=True).count()
    total_therapists = Therapist.objects.filter(is_active=True).count()
    unread_messages = ContactMessage.objects.filter(is_read=False).count()

    # Recent bookings
    recent_bookings = Booking.objects.select_related('service', 'therapist').order_by('-created_at')[:8]

    # Booking status distribution
    status_counts = Booking.objects.values('status').annotate(count=Count('id'))

    context = {
        'total_bookings': total_bookings,
        'pending_bookings': pending_bookings,
        'confirmed_bookings': confirmed_bookings,
        'today_bookings': today_bookings,
        'total_services': total_services,
        'total_therapists': total_therapists,
        'unread_messages': unread_messages,
        'recent_bookings': recent_bookings,
        'status_counts': status_counts,
        'is_admin_role': _is_admin(request),
    }
    return render(request, 'portals/dashboard.html', context)


@login_required(login_url='portals:login')
def booking_list(request):
    """List and manage bookings."""
    if not request.user.is_staff:
        return redirect('portals:login')

    status_filter = request.GET.get('status', '')
    search = request.GET.get('search', '')

    bookings = Booking.objects.select_related('service', 'therapist').all()

    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if search:
        bookings = bookings.filter(
            Q(client_name__icontains=search) |
            Q(client_email__icontains=search) |
            Q(client_phone__icontains=search)
        )

    context = {
        'bookings': bookings,
        'status_filter': status_filter,
        'search': search,
        'status_choices': Booking.STATUS_CHOICES,
    }
    return render(request, 'portals/booking_list.html', context)


@login_required(login_url='portals:login')
def booking_update_status(request, pk):
    """Update booking status via AJAX."""
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
def service_list(request):
    """List services (admin only)."""
    if not request.user.is_staff:
        return redirect('portals:login')

    # Staff role cannot access service management
    if _is_staff_only(request):
        messages.error(request, 'You do not have permission to manage services. Admin access required.')
        return redirect('portals:dashboard')

    services = Service.objects.all()
    context = {'services': services}
    return render(request, 'portals/service_list.html', context)


@login_required(login_url='portals:login')
def message_list(request):
    """List contact messages."""
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
    """Toggle message read status."""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    if request.method == 'POST':
        msg = get_object_or_404(ContactMessage, pk=pk)
        msg.is_read = not msg.is_read
        msg.save()
        return JsonResponse({'success': True, 'is_read': msg.is_read})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required(login_url='portals:login')
def therapist_list(request):
    """List therapists/staff (admin only)."""
    if not request.user.is_staff:
        return redirect('portals:login')

    # Staff role cannot manage therapists
    if _is_staff_only(request):
        messages.error(request, 'You do not have permission to manage therapists. Admin access required.')
        return redirect('portals:dashboard')

    therapists = Therapist.objects.all()
    context = {'therapists': therapists}
    return render(request, 'portals/therapist_list.html', context)


@login_required(login_url='portals:login')
def testimonial_list(request):
    """List testimonials (admin only)."""
    if not request.user.is_staff:
        return redirect('portals:login')

    # Staff role cannot manage testimonials
    if _is_staff_only(request):
        messages.error(request, 'You do not have permission to manage testimonials. Admin access required.')
        return redirect('portals:dashboard')

    testimonials = Testimonial.objects.all()
    context = {'testimonials': testimonials}
    return render(request, 'portals/testimonial_list.html', context)


@login_required(login_url='portals:login')
def gallery_list(request):
    """List gallery images (admin only)."""
    if not request.user.is_staff:
        return redirect('portals:login')

    # Staff role cannot manage gallery
    if _is_staff_only(request):
        messages.error(request, 'You do not have permission to manage the gallery. Admin access required.')
        return redirect('portals:dashboard')

    images = GalleryImage.objects.all()
    context = {'images': images}
    return render(request, 'portals/gallery_list.html', context)
