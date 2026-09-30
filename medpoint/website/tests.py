import datetime

from django.test import TestCase

from .email_sync import clean_email_body, find_matching_contact_message
from .models import ContactMessage, StaffSchedule


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
