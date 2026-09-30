from django import forms
from django.core.exceptions import ValidationError
from .models import Booking, ContactMessage, Service, Therapist


DUPLICATE_BOOKING_ERROR = (
    'A booking for this client already exists on the selected date and time. '
    'Please choose a different date or time.'
)


def duplicate_booking_exists(client_name, booking_date, booking_time, exclude_booking_ids=None):
    """Return whether a non-cancelled booking already occupies this client's slot."""
    if not client_name or not booking_date or not booking_time:
        return False

    normalized_name = ' '.join(client_name.casefold().split())
    bookings = Booking.objects.filter(
        date=booking_date,
        time=booking_time,
    ).exclude(status='cancelled')

    if exclude_booking_ids:
        bookings = bookings.exclude(pk__in=exclude_booking_ids)

    return any(
        ' '.join(existing_name.casefold().split()) == normalized_name
        for existing_name in bookings.values_list('client_name', flat=True)
    )


def validate_full_name(value):
    """Allow human names, but reject digits and unrelated symbols."""
    value = value.strip()
    allowed_punctuation = " .'-"
    if not value or not any(character.isalpha() for character in value):
        raise ValidationError('Please enter a valid full name using letters only.')
    if any(not character.isalpha() and character not in allowed_punctuation for character in value):
        raise ValidationError(
            'Full name can contain letters, spaces, hyphens, apostrophes, and periods only.'
        )


def validate_phone_number(value):
    """Booking contact numbers are stored as digits only."""
    value = value.strip()
    if not value.isdigit():
        raise ValidationError('Contact number must contain numbers only.')
    if len(value) > 20:
        raise ValidationError('Contact number must not exceed 20 digits.')


class BookingForm(forms.ModelForm):
    """Form for booking spa appointments with therapist gender preference."""

    date = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'form-input',
                'id': 'booking-date',
            }
        )
    )

    class Meta:
        model = Booking
        fields = [
            'client_name', 'client_email', 'client_phone',
            'client_gender', 'services', 'additional_minutes', 'therapist_preference',
            'therapist', 'date', 'time', 'notes'
        ]
        widgets = {
            'client_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Your Full Name',
                'id': 'booking-name',
                'autocomplete': 'name',
            }),
            'client_email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'your.email@example.com',
                'id': 'booking-email',
            }),
            'client_phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '639XXXXXXXXX',
                'id': 'booking-phone',
                'inputmode': 'numeric',
                'pattern': '[0-9]+',
                'maxlength': '20',
                'autocomplete': 'tel',
            }),
            'client_gender': forms.Select(attrs={
                'class': 'form-input',
                'id': 'booking-client-gender',
            }),
            'services': forms.SelectMultiple(attrs={
                'class': 'form-input',
                'id': 'booking-service',
            }),
            'additional_minutes': forms.Select(attrs={
                'class': 'form-input',
                'id': 'booking-additional-minutes',
            }),
            'therapist_preference': forms.Select(attrs={
                'class': 'form-input',
                'id': 'booking-therapist-preference',
            }),
            'therapist': forms.Select(attrs={
                'class': 'form-input',
                'id': 'booking-therapist',
            }),
            'time': forms.Select(attrs={
                'class': 'form-input',
                'id': 'booking-time',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-input',
                'placeholder': 'Any special requests or notes...',
                'rows': 4,
                'id': 'booking-notes',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['services'].queryset = Service.objects.filter(is_active=True)
        self.fields['therapist'].queryset = Therapist.objects.filter(is_active=True)
        self.fields['therapist'].required = True
        self.fields['therapist'].error_messages = {'required': 'Please select a therapist.'}
        self.fields['notes'].required = False
        # Will be dynamically filtered via JS based on gender preference
        self.fields['therapist'].label = "Select Your Therapist"

    def clean_client_name(self):
        value = self.cleaned_data['client_name'].strip()
        validate_full_name(value)
        return value

    def clean_client_phone(self):
        value = self.cleaned_data['client_phone'].strip()
        validate_phone_number(value)
        return value

    def clean(self):
        cleaned_data = super().clean()
        client_name = cleaned_data.get('client_name')
        client_gender = cleaned_data.get('client_gender')
        therapist_preference = cleaned_data.get('therapist_preference')
        therapist = cleaned_data.get('therapist')
        date = cleaned_data.get('date')
        time = cleaned_data.get('time')

        excluded_ids = [self.instance.pk] if self.instance and self.instance.pk else None
        if duplicate_booking_exists(client_name, date, time, excluded_ids):
            self.add_error('client_name', DUPLICATE_BOOKING_ERROR)

        # Rule: Female customers can only choose female therapist
        if client_gender == 'female' and therapist_preference == 'male':
            raise forms.ValidationError(
                "Female customers can only be assigned to female therapists."
            )

        if not therapist:
            raise forms.ValidationError({
                'therapist': "Please select a therapist."
            })

        # If a specific therapist is selected, validate gender matches preference
        if therapist and therapist_preference != 'random':
            if therapist.gender != therapist_preference:
                raise forms.ValidationError(
                    f"The selected therapist ({therapist.name}) does not match "
                    f"your gender preference ({therapist_preference})."
                )

        from .models import Booking, StaffSchedule
        import datetime
        services = cleaned_data.get('services')

        if date and time and services and therapist:
            try:
                # Time is saved as string '09:00'
                req_start_time = datetime.datetime.strptime(time, '%H:%M').time()
                
                total_duration = (
                    sum(s.duration_minutes for s in services)
                    + cleaned_data.get('additional_minutes', 0)
                )
                duration = datetime.timedelta(minutes=total_duration)
                req_start_dt = datetime.datetime.combine(date, req_start_time)
                req_end_dt = req_start_dt + duration

                closing_dt = datetime.datetime.combine(
                    date + datetime.timedelta(days=1), datetime.time.min
                )
                if req_end_dt > closing_dt:
                    self.add_error(
                        'additional_minutes',
                        'The selected services and additional time would finish after closing. '
                        'Please choose less additional time or an earlier appointment.'
                    )
                
                from .models import StaffLeave
                # Check leaves
                leave = StaffLeave.objects.filter(
                    is_active=True,
                    therapist=therapist, 
                    start_date__lte=date, 
                    end_date__gte=date
                ).first()
                if leave:
                    raise forms.ValidationError(f"{therapist.name} is on leave on this date.")

                # Check if the booking time is within the therapist's schedule
                target_weekday = date.weekday()
                sched = StaffSchedule.objects.filter(
                    therapist=therapist,
                    day_of_week=target_weekday,
                    is_available=True,
                ).first()

                if sched:
                    if not sched.contains_booking(req_start_time, total_duration):
                        sched_start_label = sched.start_time.strftime('%I:%M %p')
                        sched_end_label = sched.end_time.strftime('%I:%M %p')
                        raise forms.ValidationError(
                            f"{therapist.name} is only available from "
                            f"{sched_start_label} to {sched_end_label} on this day. "
                            f"Please choose a time within their schedule."
                        )
                    if sched.booking_overlaps_break(req_start_time, total_duration):
                        raise forms.ValidationError(
                            f"{therapist.name} is on break from "
                            f"{sched.break_start_time.strftime('%I:%M %p')} to "
                            f"{sched.break_end_time.strftime('%I:%M %p')}. "
                            "Please select a time that does not overlap the break."
                        )
                elif StaffSchedule.objects.filter(therapist=therapist, day_of_week=target_weekday).exists():
                    # Schedule exists but is_available=False — therapist is off
                    raise forms.ValidationError(
                        f"{therapist.name} is not available on {date.strftime('%A')}s."
                    )

                existing_bookings = Booking.objects.filter(
                    date=date,
                    therapist=therapist,
                    status__in=['pending', 'confirmed'],
                    is_verified=True,
                ).prefetch_related('services')

                for b in existing_bookings:
                    b_start_time = datetime.datetime.strptime(b.time, '%H:%M').time()
                    b_start_dt = datetime.datetime.combine(date, b_start_time)
                    
                    b_total_dur = b.total_duration_minutes
                    b_dur = datetime.timedelta(minutes=b_total_dur)
                    b_end_dt = b_start_dt + b_dur

                    if max(req_start_dt, b_start_dt) < min(req_end_dt, b_end_dt):
                        raise forms.ValidationError(
                            f"The selected therapist ({therapist.name}) is fully booked during this specific timeframe. Please select a different time or therapist."
                        )
            except ValueError:
                pass

        return cleaned_data

    def save(self, commit=True):
        booking = super().save(commit=commit)
        if commit:
            booking.lock_current_price()
        return booking


class FamilyMemberForm(forms.Form):
    """Validates a single family member's fields for group bookings.

    Used server-side to validate each member independently. Shared fields
    (email, phone, date, time, notes) are handled by the parent view.
    """
    name = forms.CharField(max_length=200)
    gender = forms.ChoiceField(choices=Booking.GENDER_CHOICES)
    services = forms.ModelMultipleChoiceField(queryset=Service.objects.filter(is_active=True))
    additional_minutes = forms.TypedChoiceField(
        choices=Booking.ADDITIONAL_TIME_CHOICES,
        coerce=int,
        initial=0,
    )
    therapist_preference = forms.ChoiceField(choices=Booking.THERAPIST_PREF_CHOICES)
    therapist = forms.ModelChoiceField(
        queryset=Therapist.objects.filter(is_active=True),
        required=True,
        error_messages={'required': 'Please select a therapist.'}
    )

    def clean_name(self):
        value = self.cleaned_data['name'].strip()
        validate_full_name(value)
        return value

    def clean(self):
        cleaned_data = super().clean()
        gender = cleaned_data.get('gender')
        therapist_preference = cleaned_data.get('therapist_preference')
        therapist = cleaned_data.get('therapist')

        # Rule: Female customers can only choose female therapist
        if gender == 'female' and therapist_preference == 'male':
            raise forms.ValidationError(
                "Female customers can only be assigned to female therapists."
            )

        if not therapist:
            raise forms.ValidationError({
                'therapist': "Please select a therapist."
            })

        # If a specific therapist is selected, validate gender matches preference
        if therapist and therapist_preference != 'random':
            if therapist.gender != therapist_preference:
                raise forms.ValidationError(
                    f"The selected therapist ({therapist.name}) does not match "
                    f"the gender preference ({therapist_preference})."
                )

        return cleaned_data


class ContactForm(forms.ModelForm):
    """Form for contact page submissions."""

    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'phone', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Your Full Name',
                'id': 'contact-name',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'your.email@example.com',
                'id': 'contact-email',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+63 9XX XXX XXXX',
                'id': 'contact-phone',
            }),
            'subject': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Subject',
                'id': 'contact-subject',
            }),
            'message': forms.Textarea(attrs={
                'class': 'form-input',
                'placeholder': 'Your message...',
                'rows': 5,
                'id': 'contact-message',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone'].required = False
