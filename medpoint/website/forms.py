from django import forms
from .models import Booking, ContactMessage, Service, Therapist


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
            'client_gender', 'service', 'therapist_preference',
            'therapist', 'date', 'time', 'notes'
        ]
        widgets = {
            'client_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Your Full Name',
                'id': 'booking-name',
            }),
            'client_email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'your.email@example.com',
                'id': 'booking-email',
            }),
            'client_phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+63 9XX XXX XXXX',
                'id': 'booking-phone',
            }),
            'client_gender': forms.Select(attrs={
                'class': 'form-input',
                'id': 'booking-client-gender',
            }),
            'service': forms.Select(attrs={
                'class': 'form-input',
                'id': 'booking-service',
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
        self.fields['service'].queryset = Service.objects.filter(is_active=True)
        self.fields['therapist'].queryset = Therapist.objects.filter(is_active=True)
        self.fields['therapist'].required = False
        self.fields['notes'].required = False
        # Will be dynamically filtered via JS based on gender preference
        self.fields['therapist'].label = "Preferred Therapist (Optional)"

    def clean(self):
        cleaned_data = super().clean()
        client_gender = cleaned_data.get('client_gender')
        therapist_preference = cleaned_data.get('therapist_preference')
        therapist = cleaned_data.get('therapist')

        # Rule: Female customers can only choose female therapist
        if client_gender == 'female' and therapist_preference == 'male':
            raise forms.ValidationError(
                "Female customers can only be assigned to female therapists."
            )

        # If a specific therapist is selected, validate gender matches preference
        if therapist and therapist_preference != 'random':
            if therapist.gender != therapist_preference:
                raise forms.ValidationError(
                    f"The selected therapist ({therapist.name}) does not match "
                    f"your gender preference ({therapist_preference})."
                )

        from .models import Booking
        import datetime
        date = cleaned_data.get('date')
        time = cleaned_data.get('time')
        service = cleaned_data.get('service')

        if date and time and service and therapist:
            try:
                # Time is saved as string '09:00'
                req_start_time = datetime.datetime.strptime(time, '%H:%M').time()
                duration = datetime.timedelta(minutes=service.duration_minutes)
                req_start_dt = datetime.datetime.combine(date, req_start_time)
                req_end_dt = req_start_dt + duration

                existing_bookings = Booking.objects.filter(
                    date=date,
                    therapist=therapist,
                    status__in=['pending', 'confirmed']
                ).select_related('service')

                for b in existing_bookings:
                    b_start_time = datetime.datetime.strptime(b.time, '%H:%M').time()
                    b_start_dt = datetime.datetime.combine(date, b_start_time)
                    b_dur = datetime.timedelta(minutes=b.service.duration_minutes)
                    b_end_dt = b_start_dt + b_dur

                    if max(req_start_dt, b_start_dt) < min(req_end_dt, b_end_dt):
                        raise forms.ValidationError(
                            f"The selected therapist ({therapist.name}) is fully booked during this specific timeframe. Please select a different time or therapist."
                        )
            except ValueError:
                pass

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
