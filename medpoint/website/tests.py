import datetime
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.template.loader import render_to_string
from django.urls import reverse

from .email_sync import clean_email_body, find_matching_contact_message
from .forms import ContactForm
from .models import (
    Booking,
    ContactMessage,
    Service,
    ServiceCategory,
    StaffSchedule,
    Testimonial,
    Therapist,
)
from .views import _send_booking_otp


class BookingVerificationMessageTests(TestCase):
    def test_failed_otp_message_formats_email_without_exposing_raw_html(self):
        request = RequestFactory().get(reverse('website:verify_booking'))
        request.user = AnonymousUser()
        SessionMiddleware(lambda req: None).process_request(request)
        request._messages = FallbackStorage(request)

        with patch(
            'website.views.EmailMultiAlternatives.send',
            side_effect=RuntimeError('Email service unavailable'),
        ):
            sent = _send_booking_otp(
                request,
                [],
                'client@example.com<script>alert(1)</script>',
            )

        rendered = render_to_string(
            'website/booking_verify.html',
            {'booking_ids': []},
            request=request,
        )

        self.assertFalse(sent)
        self.assertIn(
            '<strong class="font-semibold text-white">client@example.com&lt;script&gt;alert(1)&lt;/script&gt;</strong>',
            rendered,
        )
        self.assertNotIn('&lt;strong&gt;', rendered)
        self.assertNotIn('<script>alert(1)</script>', rendered)
        self.assertIn('fa-triangle-exclamation', rendered)


class FooterServiceCategoryTests(TestCase):
    def test_footer_uses_current_active_categories(self):
        active_category = ServiceCategory.objects.create(
            name='Wellness Packages Test',
            code='wellness-packages-test',
            order=901,
            is_active=True,
        )
        inactive_category = ServiceCategory.objects.create(
            name='Hidden Footer Category Test',
            code='hidden-footer-category-test',
            order=902,
            is_active=False,
        )

        response = self.client.get(reverse('website:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, active_category.name)
        self.assertContains(
            response,
            f'?category={active_category.code}',
        )
        self.assertNotContains(response, inactive_category.name)


class AboutAverageRatingTests(TestCase):
    def test_average_rating_uses_approved_testimonials(self):
        Testimonial.objects.create(
            client_name='Five Star Client',
            rating=5,
            content='Excellent service.',
            is_approved=True,
            is_featured=True,
        )
        Testimonial.objects.create(
            client_name='Three Star Client',
            rating=3,
            content='Good service.',
            is_approved=True,
            is_featured=False,
        )
        Testimonial.objects.create(
            client_name='Unapproved Client',
            rating=1,
            content='Still awaiting moderation.',
            is_approved=False,
            is_featured=False,
        )

        response = self.client.get(reverse('website:about'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['average_rating'], 4.0)
        self.assertContains(response, '>4.0<', html=False)

    def test_average_rating_is_zero_without_approved_testimonials(self):
        Testimonial.objects.create(
            client_name='Unapproved Client',
            rating=5,
            content='Still awaiting moderation.',
            is_approved=False,
            is_featured=False,
        )

        response = self.client.get(reverse('website:about'))

        self.assertEqual(response.context['average_rating'], 0.0)
        self.assertContains(response, '>0.0<', html=False)


class BookingPricingRuleTests(TestCase):
    def setUp(self):
        self.first = Service.objects.create(
            name='Shiatsu Massage', slug='pricing-shiatsu', category='ordinary_room',
            description='Test', duration_minutes=60, price='400.00',
        )
        self.second = Service.objects.create(
            name='Swedish Massage', slug='pricing-swedish', category='ordinary_room',
            description='Test', duration_minutes=60, price='500.00',
        )
        self.non_massage = Service.objects.create(
            name='Facial', slug='pricing-facial', category='facial',
            description='Test', duration_minutes=60, price='350.00',
        )
        self.booking = Booking.objects.create(
            client_name='Pricing Test', client_email='pricing@example.com',
            client_phone='639123456789', client_gender='male',
            therapist_preference='random', date=datetime.date(2026, 10, 10),
            time='10:00',
        )

    def test_two_massage_services_charge_two_hundred_each(self):
        self.booking.services.set([self.first, self.second])
        self.assertEqual(self.booking.multiple_massage_service_count, 2)
        self.assertEqual(self.booking.multiple_massage_service_fee, 400)
        self.booking.lock_current_price()
        self.assertEqual(self.booking.locked_price, 1300)

    def test_two_mixed_services_charge_two_hundred_each(self):
        self.booking.services.set([self.first, self.non_massage])
        self.assertEqual(self.booking.multiple_service_count, 2)
        self.assertEqual(self.booking.multiple_service_fee, 400)

    def test_booking_summary_displays_additional_service_charge(self):
        self.booking.services.set([self.first, self.non_massage])
        self.booking.lock_current_price()
        session = self.client.session
        session['last_booking_id'] = self.booking.pk
        session['last_booking_ids'] = [self.booking.pk]
        session.save()

        response = self.client.get(reverse('website:booking_success'))

        self.assertContains(response, 'Additional Service Charge')
        self.assertContains(response, '2 services')
        self.assertContains(response, '₱400')

    def test_only_thirty_minute_extension_is_offered(self):
        self.assertEqual(
            [value for value, _label in Booking.ADDITIONAL_TIME_CHOICES],
            [0, 30],
        )


class ContactFormValidationTests(TestCase):
    def valid_data(self, **overrides):
        data = {
            'name': 'Maria Dela Cruz',
            'email': 'maria@example.com',
            'phone': '639123456789',
            'subject': 'Booking question',
            'message': 'Please send more information.',
        }
        data.update(overrides)
        return data

    def test_accepts_valid_contact_information(self):
        self.assertTrue(ContactForm(data=self.valid_data()).is_valid())

    def test_rejects_numbers_in_name_and_subject(self):
        form = ContactForm(data=self.valid_data(name='Maria 2', subject='Booking 2'))
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)
        self.assertIn('subject', form.errors)

    def test_rejects_letters_in_phone_and_invalid_email(self):
        form = ContactForm(data=self.valid_data(phone='0917ABC', email='not-an-email'))
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)
        self.assertIn('email', form.errors)


class BookingSubmissionErrorTests(TestCase):
    def valid_booking_data(self):
        booking_date = datetime.date.today() + datetime.timedelta(days=7)
        service = Service.objects.create(
            name='Valid Submission Massage',
            slug='valid-submission-massage',
            category='massage',
            description='Test',
            duration_minutes=60,
            price='400.00',
        )
        therapist = Therapist.objects.create(
            name='Submission Therapist',
            slug='submission-therapist',
            title='Massage Therapist',
            gender='male',
            bio='Test therapist',
        )
        StaffSchedule.objects.create(
            therapist=therapist,
            day_of_week=booking_date.weekday(),
            start_time=datetime.time(10, 0),
            end_time=datetime.time(18, 0),
            is_available=True,
        )
        return {
            'booking_mode': 'single',
            'client_name': 'Valid Client',
            'client_email': 'valid@example.com',
            'client_phone': '639171234567',
            'client_gender': 'male',
            'services': [service.pk],
            'additional_minutes': 0,
            'therapist_preference': 'random',
            'therapist': therapist.pk,
            'date': booking_date.isoformat(),
            'time': '10:00',
            'notes': '',
        }

    def test_missing_therapist_error_is_shown_and_booking_is_not_created(self):
        service = Service.objects.create(
            name='Submission Test Massage',
            slug='submission-test-massage',
            category='massage',
            description='Test',
            duration_minutes=60,
            price='400.00',
        )
        response = self.client.post(reverse('website:booking'), {
            'booking_mode': 'single',
            'client_name': 'Test Client',
            'client_email': 'client@example.com',
            'client_phone': '639171234567',
            'client_gender': 'male',
            'services': [service.pk],
            'additional_minutes': 0,
            'therapist_preference': 'random',
            'therapist': '',
            'date': (datetime.date.today() + datetime.timedelta(days=7)).isoformat(),
            'time': '10:00',
            'notes': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please select a therapist.')
        self.assertEqual(Booking.objects.count(), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_valid_confirmation_creates_one_booking_and_repeated_post_is_blocked(self):
        data = self.valid_booking_data()

        first_response = self.client.post(reverse('website:booking'), data)

        self.assertRedirects(first_response, reverse('website:verify_booking'))
        self.assertEqual(Booking.objects.count(), 1)
        booking = Booking.objects.get()
        self.assertEqual(booking.status, 'awaiting_verification')
        self.assertFalse(booking.is_verified)

        second_response = self.client.post(reverse('website:booking'), data)

        self.assertEqual(second_response.status_code, 200)
        self.assertContains(second_response, 'already exists on the selected date and time')
        self.assertEqual(Booking.objects.count(), 1)


class StaffScheduleBookingWindowTests(TestCase):
    def setUp(self):
        self.schedule = StaffSchedule(
            start_time=datetime.time(11, 0),
            end_time=datetime.time(0, 0),
            is_available=True,
        )

    def test_midnight_shift_accepts_daytime_service_that_fits(self):
        self.assertTrue(
            self.schedule.contains_booking(datetime.time(20, 0), 90)
        )

    def test_midnight_shift_accepts_service_ending_at_midnight(self):
        self.assertTrue(
            self.schedule.contains_booking(datetime.time(23, 0), 60)
        )

    def test_midnight_shift_rejects_service_ending_after_midnight(self):
        self.assertFalse(
            self.schedule.contains_booking(datetime.time(23, 30), 60)
        )


class EmailReplyCleaningTests(TestCase):
    def test_removes_single_line_gmail_quote(self):
        body = "WHAT ARE YOU DOING\n\nOn Mon, Sep 28, 2026 at 8:11 PM Medpoint <spa@example.com> wrote:\nOld reply"
        self.assertEqual(clean_email_body(body), "WHAT ARE YOU DOING")

    def test_removes_wrapped_gmail_quote(self):
        body = (
            "WHAT ARE YOU DOING\n\n"
            "On Mon, Sep 28, 2026 at 8:11 PM Medpoint Massage & Spa <\n"
            "medpointmassage.spa@gmail.com> wrote:\nOld reply"
        )
        self.assertEqual(clean_email_body(body), "WHAT ARE YOU DOING")

    def test_removes_outlook_original_message(self):
        body = "My new response\n\n-----Original Message-----\nFrom: Medpoint\nOld reply"
        self.assertEqual(clean_email_body(body), "My new response")


class EmailThreadMatchingTests(TestCase):
    def setUp(self):
        self.first = ContactMessage.objects.create(
            name='Client', email='client@example.com', subject='First', message='One'
        )
        self.second = ContactMessage.objects.create(
            name='Client', email='client@example.com', subject='Second', message='Two'
        )

    def test_matches_one_ticket_and_owner_email(self):
        match = find_matching_contact_message(
            f'Re: [Ticket #{self.first.pk}] First', 'CLIENT@example.com'
        )
        self.assertEqual(match, self.first)

    def test_rejects_sender_from_another_conversation(self):
        match = find_matching_contact_message(
            f'Re: [Ticket #{self.first.pk}] First', 'someone-else@example.com'
        )
        self.assertIsNone(match)

    def test_rejects_conflicting_subject_and_reference_tickets(self):
        match = find_matching_contact_message(
            f'Re: [Ticket #{self.first.pk}] First',
            'client@example.com',
            f'<ticket-{self.second.pk}-reply@example.com>',
        )
        self.assertIsNone(match)
