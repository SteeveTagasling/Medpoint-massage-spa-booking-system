import datetime
from decimal import Decimal

from django.core import mail
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from website.models import (
    Booking,
    BookingNotification,
    Service,
    ServiceCategory,
    ServicePriceHistory,
    StaffSchedule,
    Therapist,
)

from .forms import ServiceForm, WalkInBookingForm
from .views import _get_booking_category_groups, _get_report_service_tables


class WalkInBookingPricingTests(TestCase):
    def setUp(self):
        self.booking_date = timezone.localdate() + datetime.timedelta(days=14)
        self.therapist = Therapist.objects.create(
            name='Walk In Therapist',
            slug='walk-in-therapist',
            title='Massage Therapist',
            gender='male',
            bio='Test therapist',
        )
        StaffSchedule.objects.create(
            therapist=self.therapist,
            day_of_week=self.booking_date.weekday(),
            start_time=datetime.time(10, 0),
            end_time=datetime.time(0, 0),
            is_available=True,
        )

    def make_service(self, name, slug, price, duration=60):
        return Service.objects.create(
            name=name,
            slug=slug,
            category='massage',
            description=f'{name} description',
            duration_minutes=duration,
            price=price,
            is_active=True,
        )

    def form_data(self, services, **overrides):
        data = {
            'client_name': 'Walk In Client',
            'client_gender': 'male',
            'client_email': 'walkin@example.com',
            'client_phone': '639171234567',
            'services': [service.pk for service in services],
            'additional_minutes': 30,
            'therapist_preference': 'random',
            'therapist': self.therapist.pk,
            'date': self.booking_date.isoformat(),
            'time': '10:00',
            'notes': '',
        }
        data.update(overrides)
        return data

    def test_walk_in_saves_extension_without_multiple_service_fee(self):
        first = self.make_service('Shiatsu Massage', 'walkin-shiatsu', Decimal('400.00'))
        second = self.make_service('Swedish Massage', 'walkin-swedish', Decimal('500.00'))

        form = WalkInBookingForm(data=self.form_data([first, second]))
        self.assertTrue(form.is_valid(), form.errors)

        booking = form.save()
        booking.lock_current_price()
        booking.refresh_from_db()

        self.assertEqual(booking.additional_minutes, 30)
        self.assertEqual(booking.booking_type, 'walk_in')
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(booking.total_discounted_price, Decimal('1100.00'))

    def test_walk_in_extension_is_included_in_closing_time_validation(self):
        late_service = self.make_service(
            'Late Massage', 'walkin-late-massage', Decimal('700.00'), duration=100
        )
        form = WalkInBookingForm(data=self.form_data(
            [late_service],
            time='22:00',
            additional_minutes=30,
        ))

        self.assertFalse(form.is_valid())
        self.assertIn('finish after closing time', form.errors['services'][0])

    def test_walk_in_additional_time_choices_are_limited_to_thirty_minutes(self):
        form = WalkInBookingForm()
        values = [
            int(value)
            for value, _label in form.fields['additional_minutes'].choices
            if value != ''
        ]
        self.assertEqual(values, [0, 30])

    def test_female_client_only_has_female_therapist_preference_and_choices(self):
        female_therapist = Therapist.objects.create(
            name='Female Walk In Therapist',
            slug='female-walk-in-therapist',
            title='Massage Therapist',
            gender='female',
            bio='Test female therapist',
        )
        form = WalkInBookingForm(data={'client_gender': 'female'})

        preference_values = [value for value, _label in form.fields['therapist_preference'].choices]
        therapist_ids = list(form.fields['therapist'].queryset.values_list('pk', flat=True))

        self.assertEqual(preference_values, ['female'])
        self.assertEqual(therapist_ids, [female_therapist.pk])

    def test_female_client_cannot_submit_random_preference(self):
        service = self.make_service(
            'Female Client Massage', 'female-client-massage', Decimal('500.00')
        )
        female_therapist = Therapist.objects.create(
            name='Available Female Therapist',
            slug='available-female-therapist',
            title='Massage Therapist',
            gender='female',
            bio='Available for test booking',
        )
        StaffSchedule.objects.create(
            therapist=female_therapist,
            day_of_week=self.booking_date.weekday(),
            start_time=datetime.time(10, 0),
            end_time=datetime.time(0, 0),
            is_available=True,
        )
        form = WalkInBookingForm(data=self.form_data(
            [service],
            client_gender='female',
            therapist_preference='random',
            therapist=female_therapist.pk,
            additional_minutes=0,
        ))

        self.assertFalse(form.is_valid())
        self.assertIn('therapist_preference', form.errors)


class ServiceDiscountManagementTests(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(
            name='Form Test Massage',
            code='form-test-massage',
        )
        self.service = Service.objects.create(
            name='Discount Protected Service',
            slug='discount-protected-service',
            category=self.category.code,
            description='Existing service description',
            short_description='Existing service',
            duration_minutes=60,
            price=Decimal('500.00'),
            discount_percentage=Decimal('15.00'),
            is_active=True,
        )

    def test_service_form_does_not_expose_or_accept_discount(self):
        form = ServiceForm(data={
            'name': self.service.name,
            'category': [self.category.code],
            'description': self.service.description,
            'short_description': self.service.short_description,
            'duration_minutes': '60',
            'price': '550.00',
            'discount_percentage': '75.00',
            'is_active': 'on',
            'order': '0',
        }, instance=self.service)

        self.assertNotIn('discount_percentage', form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.service.refresh_from_db()

        self.assertEqual(self.service.discount_percentage, Decimal('15.00'))

    def test_service_form_only_exposes_active_visibility_toggle(self):
        self.service.is_featured = True
        self.service.save(update_fields=['is_featured'])
        form = ServiceForm(data={
            'name': self.service.name,
            'category': [self.category.code],
            'description': self.service.description,
            'short_description': self.service.short_description,
            'duration_minutes': '60',
            'price': '500.00',
            'is_featured': '',
            'is_active': 'on',
            'order': '0',
        }, instance=self.service)

        self.assertNotIn('is_featured', form.fields)
        self.assertIn('is_active', form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.service.refresh_from_db()

        self.assertTrue(self.service.is_featured)
        self.assertTrue(self.service.is_active)

    def test_active_non_featured_service_is_displayed_on_website(self):
        self.service.is_featured = False
        self.service.is_active = True
        self.service.save(update_fields=['is_featured', 'is_active'])

        response = self.client.get(reverse('website:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.service.name)

    def test_service_list_filters_active_and_inactive_services(self):
        admin = User.objects.create_superuser(
            username='service-filter-admin',
            password='test-password',
            email='service-filter-admin@example.com',
        )
        inactive_service = Service.objects.create(
            name='Inactive Filter Service',
            slug='inactive-filter-service',
            category=self.category.code,
            description='Inactive service for filter test',
            duration_minutes=60,
            price=Decimal('400.00'),
            is_active=False,
        )
        self.client.force_login(admin)

        active_response = self.client.get(
            reverse('portals:service_list'),
            {'status': 'active'},
        )
        inactive_response = self.client.get(
            reverse('portals:service_list'),
            {'status': 'inactive'},
        )

        active_ids = [service.pk for service in active_response.context['services']]
        inactive_ids = [service.pk for service in inactive_response.context['services']]
        self.assertIn(self.service.pk, active_ids)
        self.assertNotIn(inactive_service.pk, active_ids)
        self.assertIn(inactive_service.pk, inactive_ids)
        self.assertNotIn(self.service.pk, inactive_ids)


class StaffMyBookingsOrderingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='staff-ordering',
            password='test-password',
            is_staff=True,
        )
        self.therapist = Therapist.objects.create(
            user=self.user,
            name='Schedule Order Therapist',
            slug='schedule-order-therapist',
            title='Massage Therapist',
            gender='female',
            bio='Test therapist',
        )
        self.client.force_login(self.user)

    def make_booking(self, name, booking_date, status, time='10:00'):
        return Booking.objects.create(
            booking_type='walk_in',
            client_name=name,
            client_email=f'{name.lower().replace(" ", "")}@example.com',
            client_phone='639171234567',
            client_gender='female',
            therapist_preference='female',
            therapist=self.therapist,
            date=booking_date,
            time=time,
            status=status,
            is_verified=True,
        )

    def test_upcoming_bookings_are_nearest_first_and_completed_are_last(self):
        today = timezone.localdate()
        far_upcoming = self.make_booking(
            'Far Upcoming', today + datetime.timedelta(days=5), 'confirmed'
        )
        completed_today = self.make_booking('Completed Today', today, 'completed')
        past_unfinished = self.make_booking(
            'Past Unfinished', today - datetime.timedelta(days=1), 'pending'
        )
        near_upcoming = self.make_booking(
            'Near Upcoming', today + datetime.timedelta(days=1), 'pending'
        )

        response = self.client.get(reverse('portals:staff_my_bookings'))

        self.assertEqual(response.status_code, 200)
        ordered_ids = [booking.pk for booking in response.context['bookings']]
        self.assertEqual(ordered_ids, [
            near_upcoming.pk,
            far_upcoming.pk,
            past_unfinished.pk,
            completed_today.pk,
        ])


class AdminBookingVerificationVisibilityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='booking-admin',
            password='test-password',
            email='admin@example.com',
        )
        self.client.force_login(self.admin)

    def create_online_booking(self, *, name, verified, status):
        return Booking.objects.create(
            booking_type='online',
            client_name=name,
            client_email=f'{name.lower().replace(" ", "-")}@example.com',
            client_phone='639171234567',
            client_gender='male',
            therapist_preference='random',
            date=timezone.localdate() + datetime.timedelta(days=2),
            time='10:00',
            status=status,
            is_verified=verified,
        )

    def test_booking_list_shows_unverified_online_requests(self):
        unverified = self.create_online_booking(
            name='Awaiting Client', verified=False, status='awaiting_verification'
        )
        verified = self.create_online_booking(
            name='Verified Client', verified=True, status='pending'
        )

        response = self.client.get(reverse('portals:booking_list'))

        self.assertEqual(response.status_code, 200)
        booking_ids = [booking.pk for booking in response.context['bookings']]
        self.assertIn(unverified.pk, booking_ids)
        self.assertIn(verified.pk, booking_ids)
        self.assertIn('awaiting_verification', dict(response.context['status_choices']))

    def test_admin_calendar_hides_unverified_online_requests(self):
        unverified = self.create_online_booking(
            name='Calendar Awaiting Client', verified=False, status='awaiting_verification'
        )
        verified = self.create_online_booking(
            name='Calendar Verified Client', verified=True, status='pending'
        )

        response = self.client.get(reverse('portals:booking_calendar'), {
            'year': verified.date.year,
            'month': verified.date.month,
            'view': 'list',
        })

        self.assertEqual(response.status_code, 200)
        booking_ids = [booking.pk for booking in response.context['list_bookings']]
        self.assertNotIn(unverified.pk, booking_ids)
        self.assertIn(verified.pk, booking_ids)


class DashboardRecentBookingsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='dashboard-admin',
            password='test-password',
            email='dashboard-admin@example.com',
        )
        self.client.force_login(self.admin)

    def test_dashboard_shows_only_five_most_recent_bookings(self):
        bookings = []
        for index in range(7):
            bookings.append(Booking.objects.create(
                booking_type='walk_in',
                client_name=f'Recent Client {index}',
                client_email=f'recent-{index}@example.com',
                client_phone=f'6391712345{index}',
                client_gender='male',
                therapist_preference='random',
                date=timezone.localdate() + datetime.timedelta(days=index + 1),
                time='10:00',
                status='confirmed',
                is_verified=True,
            ))

        response = self.client.get(reverse('portals:dashboard'))

        self.assertEqual(response.status_code, 200)
        recent_ids = [booking.pk for booking in response.context['recent_bookings']]
        self.assertEqual(recent_ids, [booking.pk for booking in reversed(bookings[-5:])])


class BookingDetailTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='booking-detail-admin',
            password='test-password',
            email='detail-admin@example.com',
        )
        self.staff_user = User.objects.create_user(
            username='booking-detail-staff',
            password='test-password',
            is_staff=True,
        )
        self.therapist = Therapist.objects.create(
            user=self.staff_user,
            name='Detail Therapist',
            slug='detail-therapist',
            title='Massage Therapist',
            gender='female',
            bio='Test therapist',
        )
        self.service = Service.objects.create(
            name='Discounted Detail Massage',
            slug='discounted-detail-massage',
            category='massage',
            description='Test service',
            duration_minutes=60,
            price=Decimal('500.00'),
        )
        self.booking = Booking.objects.create(
            client_name='Detail Client',
            client_email='detail-client@example.com',
            client_phone='639171111111',
            client_gender='female',
            therapist_preference='female',
            therapist=self.therapist,
            date=timezone.localdate() + datetime.timedelta(days=3),
            time='10:00',
            status='confirmed',
            is_verified=True,
            locked_price=Decimal('450.00'),
            service_prices_snapshot=[{
                'service_id': self.service.pk,
                'name': self.service.name,
                'category_label': 'Massage',
                'base_price': 500.0,
                'discount_percentage': 10.0,
                'discounted_price': 450.0,
                'promo_effective_from': timezone.localdate().isoformat(),
                'promo_effective_to': (
                    timezone.localdate() + datetime.timedelta(days=10)
                ).isoformat(),
            }],
        )
        self.booking.services.add(self.service)

    def test_admin_detail_displays_complete_discounted_price_breakdown(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse('portals:booking_detail', args=[self.booking.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Detail Client')
        self.assertContains(response, 'detail-client@example.com')
        self.assertContains(response, 'Discount applied')
        self.assertContains(response, 'Discounted')
        self.assertContains(response, '10%')
        self.assertContains(response, '₱500.00')
        self.assertContains(response, '₱450.00')
        self.assertEqual(response.context['total_savings'], Decimal('50.00'))

        list_response = self.client.get(reverse('portals:booking_list'))
        self.assertContains(
            list_response,
            reverse('portals:booking_detail', args=[self.booking.pk]),
        )
        self.assertContains(list_response, 'booking-row-link')

    def test_staff_can_only_view_their_assigned_booking(self):
        other_booking = Booking.objects.create(
            client_name='Other Client',
            client_email='other-client@example.com',
            client_phone='639172222222',
            client_gender='male',
            therapist_preference='random',
            date=timezone.localdate() + datetime.timedelta(days=4),
            time='11:00',
            status='pending',
            is_verified=True,
        )
        other_booking.services.add(self.service)
        other_booking.lock_current_price()
        self.client.force_login(self.staff_user)

        assigned_response = self.client.get(
            reverse('portals:booking_detail', args=[self.booking.pk]),
        )
        other_response = self.client.get(
            reverse('portals:booking_detail', args=[other_booking.pk]),
        )

        self.assertEqual(assigned_response.status_code, 200)
        self.assertEqual(other_response.status_code, 404)


class BookingCompletionDateTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='completion-date-staff',
            password='test-password',
            is_staff=True,
        )
        self.client.force_login(self.staff_user)

    def make_booking(self, booking_date):
        return Booking.objects.create(
            client_name='Completion Date Client',
            client_email='',
            client_phone='639171111111',
            client_gender='female',
            therapist_preference='female',
            date=booking_date,
            time='10:00',
            status='confirmed',
            is_verified=True,
        )

    def complete(self, booking):
        return self.client.post(
            reverse('portals:booking_update_status', args=[booking.pk]),
            {'status': 'completed'},
        )

    def test_future_booking_cannot_be_completed(self):
        today = timezone.localdate()
        booking = self.make_booking(today + datetime.timedelta(days=17))

        response = self.complete(booking)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'booking_date_mismatch')
        self.assertEqual(response.json()['current_date'], today.isoformat())
        self.assertEqual(response.json()['booking_date'], booking.date.isoformat())
        self.assertIn('Only bookings scheduled for today', response.json()['error'])
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')

    def test_past_booking_cannot_be_completed(self):
        booking = self.make_booking(
            timezone.localdate() - datetime.timedelta(days=1),
        )

        response = self.complete(booking)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'booking_date_mismatch')
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')

    def test_booking_scheduled_for_today_can_be_completed(self):
        booking = self.make_booking(timezone.localdate())

        response = self.complete(booking)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'completed')


class BookingArchiveServicePreservationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='archive-admin',
            password='test-password',
            email='archive-admin@example.com',
        )
        self.staff_user = User.objects.create_user(
            username='archive-staff',
            password='test-password',
            is_staff=True,
        )
        self.therapist = Therapist.objects.create(
            user=self.staff_user,
            name='Archive Therapist',
            slug='archive-therapist',
            title='Massage Therapist',
            gender='female',
            bio='Archive test therapist',
        )
        self.service = Service.objects.create(
            name='Archive Safe Massage',
            slug='archive-safe-massage',
            category='massage',
            description='Archive preservation test',
            duration_minutes=60,
            price=Decimal('650.00'),
        )
        self.booking = Booking.objects.create(
            client_name='Archive Client',
            client_email='archive-client@example.com',
            client_phone='639171234567',
            client_gender='female',
            therapist_preference='female',
            therapist=self.therapist,
            date=timezone.localdate() + datetime.timedelta(days=5),
            time='10:00',
            status='confirmed',
            is_verified=True,
            locked_price=Decimal('650.00'),
            service_prices_snapshot=[],
        )
        self.booking.services.add(self.service)

    def test_admin_archive_preserves_snapshot_and_restore_repairs_relation(self):
        self.client.force_login(self.admin)

        archive_response = self.client.post(
            reverse('portals:booking_archive', args=[self.booking.pk]),
        )
        self.booking.refresh_from_db()

        self.assertEqual(archive_response.status_code, 200)
        self.assertTrue(self.booking.is_archived)
        self.assertEqual(list(self.booking.services.all()), [self.service])
        self.assertEqual(
            self.booking.service_prices_snapshot[0]['name'],
            self.service.name,
        )

        # Simulate a legacy lost M2M link: restore uses the preserved service ID.
        self.booking.services.clear()
        restore_response = self.client.post(
            reverse('portals:booking_restore', args=[self.booking.pk]),
        )
        self.booking.refresh_from_db()

        self.assertEqual(restore_response.status_code, 200)
        self.assertFalse(self.booking.is_archived)
        self.assertEqual(list(self.booking.services.all()), [self.service])

    def test_admin_and_staff_lists_fall_back_to_snapshot_after_service_deletion(self):
        self.booking.preserve_service_snapshot()
        self.booking.is_archived = True
        self.booking.save(update_fields=['is_archived'])
        service_name = self.service.name
        self.service.delete()

        self.client.force_login(self.admin)
        admin_response = self.client.get(
            reverse('portals:booking_list'),
            {'show': 'archived'},
        )
        self.assertContains(admin_response, service_name)

        self.client.force_login(self.staff_user)
        staff_response = self.client.get(
            reverse('portals:staff_my_bookings'),
            {'show': 'archived'},
        )
        self.assertContains(staff_response, service_name)


class ScheduledPriceRangeValidationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='price-admin',
            password='test-password',
            email='price-admin@example.com',
        )
        self.client.force_login(self.admin)
        self.service = Service.objects.create(
            name='Scheduled Price Service',
            slug='scheduled-price-service',
            category='massage',
            description='Test scheduled pricing validation',
            duration_minutes=60,
            price=Decimal('500.00'),
            is_active=True,
        )

    def add_payload(self, effective_from, effective_to=''):
        return {
            'service_id': self.service.pk,
            'base_price': '600.00',
            'discount_percentage': '10',
            'effective_from': effective_from.isoformat(),
            'effective_to': effective_to.isoformat() if effective_to else '',
            'notes': 'Scheduled test price',
        }

    def test_add_rejects_previous_start_date(self):
        yesterday = timezone.localdate() - datetime.timedelta(days=1)

        response = self.client.post(
            reverse('portals:price_checker_add_record'),
            self.add_payload(yesterday),
            follow=True,
        )

        self.assertFalse(ServicePriceHistory.objects.filter(
            service=self.service,
            notes='Scheduled test price',
        ).exists())
        self.assertContains(response, 'Effective From cannot be a previous date.')

    def test_add_rejects_end_date_before_start_date(self):
        start = timezone.localdate() + datetime.timedelta(days=5)
        end = start - datetime.timedelta(days=1)

        response = self.client.post(
            reverse('portals:price_checker_add_record'),
            self.add_payload(start, end),
            follow=True,
        )

        self.assertFalse(ServicePriceHistory.objects.filter(
            service=self.service,
            notes='Scheduled test price',
        ).exists())
        self.assertContains(response, 'Effective Until must be on or after Effective From.')

    def test_add_accepts_today_and_future_end_date(self):
        today = timezone.localdate()
        end = today + datetime.timedelta(days=7)

        response = self.client.post(
            reverse('portals:price_checker_add_record'),
            self.add_payload(today, end),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        record = ServicePriceHistory.objects.get(
            service=self.service,
            notes='Scheduled test price',
        )
        self.assertEqual(record.effective_from, today)
        self.assertEqual(record.effective_to, end)
        self.assertEqual(record.base_price, self.service.price)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_discount_updates_existing_booking_and_notifies_client(self):
        booking_date = timezone.localdate() + datetime.timedelta(days=5)
        booking = Booking.objects.create(
            client_name='Existing Promo Client',
            client_email='promo-client@example.com',
            client_phone='639171234567',
            client_gender='male',
            therapist_preference='random',
            date=booking_date,
            time='10:00',
            status='confirmed',
            is_verified=True,
        )
        booking.services.add(self.service)
        booking.lock_current_price()

        response = self.client.post(
            reverse('portals:price_checker_add_record'),
            self.add_payload(booking_date, booking_date),
            follow=True,
        )

        booking.refresh_from_db()
        snapshot = booking.service_prices_snapshot[0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(booking.locked_price, Decimal('450.00'))
        self.assertEqual(Decimal(str(snapshot['discount_percentage'])), Decimal('10.0'))
        self.assertEqual(Decimal(str(snapshot['discounted_price'])), Decimal('450.0'))
        notification = BookingNotification.objects.get(
            booking=booking,
            notification_type='reminder',
        )
        self.assertIn('reduced from ₱500.00 to ₱450.00', notification.message)
        self.assertContains(response, 'affected clients were notified')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('₱450.00', mail.outbox[0].body)
        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        html_email = mail.outbox[0].alternatives[0].content
        self.assertEqual(mail.outbox[0].alternatives[0].mimetype, 'text/html')
        self.assertIn('MEDPOINT', html_email)
        self.assertIn('10% OFF', html_email)
        self.assertIn('Your booking just got better!', html_email)
        self.assertIn('Updated Booking Total', html_email)

        my_bookings_response = self.client.get(
            reverse('website:my_bookings'),
            {'email': booking.client_email},
        )
        self.assertContains(my_bookings_response, notification.message)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_discount_updates_legacy_booking_without_price_snapshot(self):
        booking_date = timezone.localdate() + datetime.timedelta(days=6)
        booking = Booking.objects.create(
            client_name='Legacy Promo Client',
            client_email='legacy-promo@example.com',
            client_phone='639171234568',
            client_gender='female',
            therapist_preference='female',
            date=booking_date,
            time='11:00',
            status='pending',
            is_verified=True,
            locked_price=Decimal('500.00'),
            service_prices_snapshot=[],
        )
        booking.services.add(self.service)

        response = self.client.post(
            reverse('portals:price_checker_add_record'),
            self.add_payload(booking_date, booking_date),
            follow=True,
        )

        booking.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(booking.locked_price, Decimal('450.00'))
        self.assertEqual(
            booking.service_prices_snapshot[0]['category_label'],
            self.service.get_category_display,
        )
        self.assertTrue(BookingNotification.objects.filter(booking=booking).exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_applied_discount_reduces_admin_and_staff_report_commission(self):
        booking_date = timezone.localdate() + datetime.timedelta(days=7)
        staff_user = User.objects.create_user(
            username='promo-therapist',
            password='test-password',
            is_staff=True,
        )
        therapist = Therapist.objects.create(
            user=staff_user,
            name='Promo Therapist',
            slug='promo-therapist',
            title='Massage Therapist',
            gender='female',
            bio='Test therapist',
            commission_percentage=Decimal('30.00'),
        )
        booking = Booking.objects.create(
            client_name='Commission Promo Client',
            client_email='commission-promo@example.com',
            client_phone='639171234569',
            client_gender='female',
            therapist_preference='female',
            therapist=therapist,
            date=booking_date,
            time='12:00',
            status='confirmed',
            is_verified=True,
        )
        booking.services.add(self.service)
        booking.lock_current_price()

        self.client.post(
            reverse('portals:price_checker_add_record'),
            self.add_payload(booking_date, booking_date),
        )
        booking.refresh_from_db()
        booking.status = 'completed'
        booking.save(update_fields=['status'])

        date_filters = {
            'start_date': booking_date.isoformat(),
            'end_date': booking_date.isoformat(),
            'report_type': 'sales',
        }
        admin_report = self.client.get(
            reverse('portals:admin_reports'),
            date_filters,
        )
        self.assertEqual(admin_report.context['total_commission'], Decimal('135.0000'))
        self.assertEqual(admin_report.context['staff_data'][0]['total_revenue'], Decimal('450.00'))

        self.client.force_login(staff_user)
        staff_report = self.client.get(
            reverse('portals:staff_my_reports'),
            date_filters,
        )
        self.assertEqual(staff_report.context['total_revenue'], Decimal('450.00'))
        self.assertEqual(staff_report.context['commission_earned'], Decimal('135.0000'))

    def test_update_rejects_previous_start_date(self):
        original_start = timezone.localdate() + datetime.timedelta(days=10)
        record = ServicePriceHistory.objects.create(
            service=self.service,
            base_price=Decimal('600.00'),
            discount_percentage=Decimal('10.00'),
            effective_from=original_start,
            effective_to=original_start + datetime.timedelta(days=5),
            notes='Future schedule',
        )

        response = self.client.post(
            reverse('portals:price_checker_update_record', args=[record.pk]),
            {
                'base_price': '650.00',
                'discount_percentage': '5',
                'effective_from': (timezone.localdate() - datetime.timedelta(days=1)).isoformat(),
                'effective_to': '',
                'notes': 'Invalid update',
            },
            follow=True,
        )

        record.refresh_from_db()
        self.assertEqual(record.effective_from, original_start)
        self.assertEqual(record.base_price, Decimal('600.00'))
        self.assertContains(response, 'Effective From cannot be a previous date.')

    def test_update_ignores_submitted_base_catalog_price(self):
        original_start = timezone.localdate() + datetime.timedelta(days=10)
        record = ServicePriceHistory.objects.create(
            service=self.service,
            base_price=Decimal('600.00'),
            discount_percentage=Decimal('10.00'),
            effective_from=original_start,
            effective_to=original_start + datetime.timedelta(days=5),
            notes='Future schedule',
        )

        response = self.client.post(
            reverse('portals:price_checker_update_record', args=[record.pk]),
            {
                'base_price': '9999.00',
                'discount_percentage': '20',
                'effective_from': original_start.isoformat(),
                'effective_to': (original_start + datetime.timedelta(days=7)).isoformat(),
                'notes': 'Updated schedule',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.base_price, Decimal('600.00'))
        self.assertEqual(record.discount_percentage, Decimal('20.00'))

    def test_price_checker_marks_base_prices_read_only_and_removes_live_catalog_text(self):
        response = self.client.get(reverse('portals:price_checker'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'readonly aria-readonly="true"', count=2)
        self.assertContains(response, "Today's Catalog")
        self.assertNotContains(response, "Today's Live Catalog")
        self.assertNotContains(response, 'Push to live catalog immediately')


class PromotionalReportPeriodTests(TestCase):
    def test_uses_closest_matching_discount_history_for_legacy_snapshot(self):
        service = Service.objects.create(
            name='Report Promo Massage',
            slug='report-promo-massage',
            category='massage',
            description='Test',
            duration_minutes=60,
            price=Decimal('400.00'),
            discount_percentage=Decimal('10.00'),
        )
        promo_start = datetime.date(2026, 10, 4)
        promo_end = datetime.date(2026, 10, 5)
        ServicePriceHistory.objects.create(
            service=service,
            base_price=Decimal('400.00'),
            discount_percentage=Decimal('10.00'),
            effective_from=promo_start,
            effective_to=promo_end,
            notes='October promotion',
        )
        booking = Booking.objects.create(
            booking_type='online',
            client_name='Promo Client',
            client_email='promo@example.com',
            client_phone='639171234567',
            client_gender='male',
            therapist_preference='random',
            date=datetime.date(2026, 10, 6),
            time='10:00',
            status='completed',
            is_verified=True,
            locked_price=Decimal('360.00'),
            service_prices_snapshot=[{
                'service_id': service.pk,
                'name': service.name,
                'base_price': 400.0,
                'discount_percentage': 10.0,
                'discounted_price': 360.0,
            }],
        )
        booking.services.add(service)

        report_tables = _get_report_service_tables([booking])
        promo_row = report_tables['promotional_services'][0]

        self.assertEqual(promo_row['effective_from'], promo_start)
        self.assertEqual(promo_row['effective_to'], promo_end)

    def test_new_price_snapshot_keeps_promo_period(self):
        service = Service.objects.create(
            name='Snapshot Promo Massage',
            slug='snapshot-promo-massage',
            category='massage',
            description='Test',
            duration_minutes=60,
            price=Decimal('500.00'),
            discount_percentage=Decimal('20.00'),
        )
        promo_start = datetime.date(2026, 10, 1)
        promo_end = datetime.date(2026, 10, 31)
        ServicePriceHistory.objects.create(
            service=service,
            base_price=Decimal('500.00'),
            discount_percentage=Decimal('20.00'),
            effective_from=promo_start,
            effective_to=promo_end,
            notes='Monthly promotion',
        )
        booking = Booking.objects.create(
            client_name='Snapshot Client',
            client_email='snapshot@example.com',
            client_phone='639171234567',
            client_gender='male',
            therapist_preference='random',
            date=datetime.date(2026, 10, 12),
            time='10:00',
        )
        booking.services.add(service)

        booking.lock_current_price()

        snapshot = booking.service_prices_snapshot[0]
        self.assertEqual(snapshot['promo_effective_from'], '2026-10-01')
        self.assertEqual(snapshot['promo_effective_to'], '2026-10-31')


class BookingCategoryReportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='category-report-admin',
            password='test-password',
            email='category-report@example.com',
        )
        self.staff_user = User.objects.create_user(
            username='category-report-staff',
            password='test-password',
            is_staff=True,
        )
        self.therapist = Therapist.objects.create(
            user=self.staff_user,
            name='Category Report Therapist',
            slug='category-report-therapist',
            title='Massage Therapist',
            gender='female',
            bio='Test therapist',
        )
        ServiceCategory.objects.update_or_create(
            code='ordinary_room', defaults={'name': 'Ordinary Rooms', 'order': 1}
        )
        ServiceCategory.objects.update_or_create(
            code='shower_room', defaults={'name': 'Shower Rooms', 'order': 2}
        )
        ServiceCategory.objects.update_or_create(
            code='sauna_room', defaults={'name': 'Sauna Rooms', 'order': 3}
        )
        ordinary = Service.objects.create(
            name='Ordinary Massage', slug='ordinary-report-massage',
            category='ordinary_room', description='Test', duration_minutes=60,
            price=Decimal('800.00'),
        )
        shower = Service.objects.create(
            name='Shower Massage', slug='shower-report-massage',
            category='shower_room', description='Test', duration_minutes=60,
            price=Decimal('900.00'),
        )
        self.booking_date = timezone.localdate()
        self.booking = Booking.objects.create(
            client_name='Category Client',
            client_email='category-client@example.com',
            client_phone='639171212121',
            client_gender='female',
            therapist_preference='female',
            therapist=self.therapist,
            date=self.booking_date,
            time='10:00',
            status='completed',
            is_verified=True,
        )
        self.booking.services.set([ordinary, shower])
        self.booking.lock_current_price()

    def test_groups_booking_services_by_category_and_hides_empty_categories(self):
        groups = _get_booking_category_groups([self.booking])

        self.assertEqual([group['name'] for group in groups], ['Ordinary Rooms', 'Shower Rooms'])
        self.assertEqual(groups[0]['subtotal'], Decimal('800.00'))
        self.assertEqual(groups[1]['subtotal'], Decimal('900.00'))

    def test_admin_and_staff_booking_reports_render_category_tables(self):
        filters = {
            'start_date': self.booking_date.isoformat(),
            'end_date': self.booking_date.isoformat(),
        }
        self.client.force_login(self.admin)
        admin_response = self.client.get(reverse('portals:admin_reports'), filters)
        self.assertContains(admin_response, 'Ordinary Rooms')
        self.assertContains(admin_response, 'Shower Rooms')
        self.assertNotContains(admin_response, 'Sauna Rooms')
        self.assertContains(admin_response, 'SUBTOTAL', count=2)
        self.assertContains(admin_response, 'class="card booking-combined-revenue"')
        self.assertContains(admin_response, 'COMBINED TOTAL REVENUE')
        self.assertContains(admin_response, 'max-width: 100% !important;')
        self.assertEqual(admin_response.context['booking_category_total'], Decimal('1700.00'))
        self.assertContains(admin_response, 'BOOKING REPORT')

        self.client.force_login(self.staff_user)
        staff_response = self.client.get(reverse('portals:staff_my_reports'), filters)
        self.assertContains(staff_response, 'Ordinary Rooms')
        self.assertContains(staff_response, 'Shower Rooms')
        self.assertNotContains(staff_response, 'Sauna Rooms')
        self.assertContains(staff_response, 'SUBTOTAL', count=2)
        self.assertContains(staff_response, 'class="card booking-combined-revenue"')
        self.assertContains(staff_response, 'COMBINED TOTAL REVENUE')
        self.assertContains(staff_response, 'max-width: 100% !important;')
        self.assertEqual(staff_response.context['booking_category_total'], Decimal('1700.00'))

    def test_staff_report_status_and_booking_type_filters_apply_automatically(self):
        filters = {
            'start_date': self.booking_date.isoformat(),
            'end_date': self.booking_date.isoformat(),
            'status': 'completed',
            'booking_type': 'online',
        }
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse('portals:staff_my_reports'), filters)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['status_filter'], 'completed')
        self.assertEqual(response.context['booking_type_filter'], 'online')
        self.assertEqual(response.context['total_bookings_period'], 1)
        self.assertContains(response, 'id="staff-report-status-filter"')
        self.assertContains(response, 'id="staff-report-type-filter"')
        self.assertContains(response, 'id="staff-report-signatory-filter"')
        self.assertContains(response, 'class="report-filter-stack"')
        self.assertContains(response, 'class="report-filter-row"')
        self.assertContains(response, 'class="booking-filter-form"')
        self.assertContains(response, 'onchange="this.form.requestSubmit()"')


class ReportPrintDialogTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='report-preview-admin',
            email='preview@example.com',
            password='test-password',
        )
        self.client.force_login(self.user)

    def test_admin_and_staff_reports_open_native_print_dialog(self):
        report_urls = (
            reverse('portals:admin_reports'),
            reverse('portals:staff_my_reports'),
        )

        for report_url in report_urls:
            with self.subTest(report_url=report_url):
                response = self.client.get(report_url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'window.print()')
                self.assertNotContains(response, 'id="reportPreviewOverlay"')
                self.assertNotContains(response, 'Full Report Preview')
                self.assertContains(response, 'border: 1px solid #000 !important;')
                self.assertNotContains(response, '#f0f0f0 !important')
                self.assertNotContains(response, '#f7f7f7 !important')
                self.assertContains(
                    response,
                    'body.print-bookings .booking-category-card {',
                )
                self.assertContains(response, 'break-inside: auto !important;')
                self.assertContains(response, 'break-after: avoid-page !important;')
                self.assertNotContains(
                    response,
                    'body.print-bookings .booking-category-card { page-break-inside: avoid !important;',
                )

    def test_staff_booking_summary_includes_total_commission(self):
        response = self.client.get(reverse('portals:staff_my_reports'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total Commission')

    def test_staff_sales_print_title_is_sales_report(self):
        staff_response = self.client.get(reverse('portals:staff_my_reports'))
        admin_response = self.client.get(reverse('portals:admin_reports'))

        self.assertEqual(staff_response.status_code, 200)
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(staff_response, "titleEl.textContent = 'SALES REPORT'")
        self.assertContains(admin_response, "titleEl.textContent = 'SALES REPORT'")
        self.assertNotContains(staff_response, 'Sales & Commission Report')

    def test_admin_staff_performance_report_uses_reference_summary_layout(self):
        response = self.client.get(reverse('portals:admin_reports'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="staff-performance-summary-reference"')
        self.assertContains(response, 'class="staff-performance-summary-dates"')
        self.assertContains(response, 'Total Staff/Therapist (Active)')
        self.assertContains(response, 'Total Commission')
        self.assertContains(response, 'body.print-staff .print-global-meta')
        self.assertContains(response, 'body.print-staff .staff-performance-summary-reference')
        self.assertContains(response, "titleEl.textContent = 'STAFF PERFORMANCE REPORTS'")

    def test_admin_and_staff_sales_reports_use_reference_summary_layout(self):
        for report_url in (
            reverse('portals:admin_reports'),
            reverse('portals:staff_my_reports'),
        ):
            with self.subTest(report_url=report_url):
                response = self.client.get(report_url)
                self.assertContains(response, 'class="sales-summary-print-content"')
                self.assertContains(response, 'class="sales-summary-dates"')
                self.assertContains(response, '<td>Online Bookings</td>', html=True)
                self.assertContains(response, '<td>Walk-in</td>', html=True)
                self.assertContains(response, 'body.print-sales .print-global-meta')

    def test_admin_and_staff_business_reports_keep_sales_summary_in_sales_section(self):
        for report_url in (
            reverse('portals:admin_reports'),
            reverse('portals:staff_my_reports'),
        ):
            with self.subTest(report_url=report_url):
                response = self.client.get(report_url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="business-summary-reference"')
                self.assertContains(response, 'class="business-summary-dates"')
                self.assertContains(
                    response,
                    '<h3 class="business-summary-title">Booking Summary</h3>',
                    html=True,
                )
                self.assertNotContains(
                    response,
                    '<h3 class="business-summary-title">Sales Summary</h3>',
                    html=True,
                )
                self.assertContains(response, 'body.print-both .booking-summary-reference')
                self.assertNotContains(
                    response,
                    'body.print-both .sales-summary-print-wrap { display: none',
                )
                self.assertContains(response, "titleEl.textContent = 'BUSINESS REPORT'")
