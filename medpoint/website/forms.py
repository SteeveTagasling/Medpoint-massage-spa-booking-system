from django import forms
from .models import Booking, ContactMessage, Service, Therapist


class BookingForm(forms.ModelForm):
    """Form for booking spa appointments."""

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
        fields = ['client_name', 'client_email', 'client_phone', 'service', 'therapist', 'date', 'time', 'notes']
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
            'service': forms.Select(attrs={
                'class': 'form-input',
                'id': 'booking-service',
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
