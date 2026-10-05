import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from website.models import (
    Booking,
    Service,
    ServicePriceHistory,
    StaffSchedule,
    Therapist,
)

from .forms import WalkInBookingForm
from .views import _get_report_service_tables


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


class AdminBookingVisibilityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='booking-admin',
            password='test-password',
            email='admin@example.com',
        )
        self.client.force_login(self.admin)

    def test_unverified_online_request_is_visible_as_awaiting_verification(self):
        booking = Booking.objects.create(
            booking_type='online',
            client_name='Awaiting Client',
            client_email='awaiting@example.com',
            client_phone='639171234567',
            client_gender='male',
            therapist_preference='random',
            date=timezone.localdate() + datetime.timedelta(days=2),
            time='10:00',
            status='awaiting_verification',
            is_verified=False,
        )

        response = self.client.get(reverse('portals:booking_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'#{booking.pk}')
        self.assertContains(response, 'Awaiting Verification')

        filtered_response = self.client.get(
            reverse('portals:booking_list'),
            {'status': 'awaiting_verification'},
        )
        self.assertContains(filtered_response, f'#{booking.pk}')


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


class AdminBookingVisibilityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='booking-admin',
            password='test-password',
            email='admin@example.com',
        )
        self.client.force_login(self.admin)

    def test_unverified_online_request_is_visible_as_awaiting_verification(self):
        booking = Booking.objects.create(
            booking_type='online',
            client_name='Awaiting Client',
            client_email='awaiting@example.com',
            client_phone='639171234567',
            client_gender='male',
            therapist_preference='random',
            date=timezone.localdate() + datetime.timedelta(days=2),
            time='10:00',
            status='awaiting_verification',
            is_verified=False,
        )

        response = self.client.get(reverse('portals:booking_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'#{booking.pk}')
        self.assertContains(response, 'Awaiting Verification')

        filtered_response = self.client.get(
            reverse('portals:booking_list'),
            {'status': 'awaiting_verification'},
        )
        self.assertContains(filtered_response, f'#{booking.pk}')
