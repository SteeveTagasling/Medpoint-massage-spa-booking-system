from django import forms
from django.contrib.auth.models import User
from django.utils.text import slugify
from website.models import Service, Therapist, Booking, StaffSchedule


class ServiceForm(forms.ModelForm):
    """Admin form for creating/editing services."""

    class Meta:
        model = Service
        fields = [
            'name', 'category', 'description', 'short_description',
            'duration_minutes', 'price', 'discount_percentage',
            'image', 'is_featured', 'is_active', 'order'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': 'Service name',
            }),
            'category': forms.Select(attrs={'class': 'portal-input'}),
            'description': forms.Textarea(attrs={
                'class': 'portal-input', 'rows': 4,
                'placeholder': 'Detailed description...',
            }),
            'short_description': forms.TextInput(attrs={
                'class': 'portal-input',
                'placeholder': 'Short description for cards...',
            }),
            'duration_minutes': forms.NumberInput(attrs={
                'class': 'portal-input', 'placeholder': '60', 'min': 15,
            }),
            'price': forms.NumberInput(attrs={
                'class': 'portal-input', 'placeholder': '0.00', 'step': '0.01',
            }),
            'discount_percentage': forms.NumberInput(attrs={
                'class': 'portal-input', 'placeholder': '0',
                'min': 0, 'max': 100, 'step': '0.01',
            }),
            'image': forms.ClearableFileInput(attrs={'class': 'portal-input'}),
            'order': forms.NumberInput(attrs={
                'class': 'portal-input', 'placeholder': '0', 'min': 0,
            }),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.slug:
            instance.slug = slugify(instance.name)
            # Ensure uniqueness
            original_slug = instance.slug
            counter = 1
            while Service.objects.filter(slug=instance.slug).exclude(pk=instance.pk).exists():
                instance.slug = f"{original_slug}-{counter}"
                counter += 1
        if commit:
            instance.save()
        return instance


class TherapistForm(forms.ModelForm):
    """Admin form for creating/editing therapists/staff."""

    class Meta:
        model = Therapist
        fields = [
            'name', 'title', 'gender', 'bio', 'photo', 'specialties',
            'years_experience', 'phone', 'email', 'commission_percentage',
            'is_active', 'order'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': 'Full name',
            }),
            'title': forms.TextInput(attrs={
                'class': 'portal-input',
                'placeholder': 'e.g. Senior Massage Therapist',
            }),
            'gender': forms.Select(attrs={'class': 'portal-input'}),
            'bio': forms.Textarea(attrs={
                'class': 'portal-input', 'rows': 4,
                'placeholder': 'Brief bio...',
            }),
            'photo': forms.ClearableFileInput(attrs={'class': 'portal-input'}),
            'specialties': forms.CheckboxSelectMultiple(),
            'years_experience': forms.NumberInput(attrs={
                'class': 'portal-input', 'placeholder': '0', 'min': 0,
            }),
            'phone': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': '+63 9XX XXX XXXX',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'portal-input', 'placeholder': 'staff@medpoint.com',
            }),
            'commission_percentage': forms.NumberInput(attrs={
                'class': 'portal-input', 'placeholder': '30',
                'min': 0, 'max': 100, 'step': '0.01',
            }),
            'order': forms.NumberInput(attrs={
                'class': 'portal-input', 'placeholder': '0', 'min': 0,
            }),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.slug:
            instance.slug = slugify(instance.name)
            original_slug = instance.slug
            counter = 1
            while Therapist.objects.filter(slug=instance.slug).exclude(pk=instance.pk).exists():
                instance.slug = f"{original_slug}-{counter}"
                counter += 1
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class WalkInBookingForm(forms.ModelForm):
    """Form for creating walk-in bookings from the portal."""

    date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date', 'class': 'portal-input',
        })
    )

    class Meta:
        model = Booking
        fields = [
            'client_name', 'client_email', 'client_phone',
            'service', 'therapist', 'date', 'time', 'notes', 'status'
        ]
        widgets = {
            'client_name': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': 'Client full name',
            }),
            'client_email': forms.EmailInput(attrs={
                'class': 'portal-input', 'placeholder': 'client@example.com',
            }),
            'client_phone': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': '+63 9XX XXX XXXX',
            }),
            'service': forms.Select(attrs={'class': 'portal-input'}),
            'therapist': forms.Select(attrs={'class': 'portal-input'}),
            'time': forms.Select(attrs={'class': 'portal-input'}),
            'notes': forms.Textarea(attrs={
                'class': 'portal-input', 'rows': 3,
                'placeholder': 'Any special notes...',
            }),
            'status': forms.Select(attrs={'class': 'portal-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service'].queryset = Service.objects.filter(is_active=True)
        self.fields['therapist'].queryset = Therapist.objects.filter(is_active=True)
        self.fields['therapist'].required = False
        self.fields['notes'].required = False

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.booking_type = 'walk_in'
        if commit:
            instance.save()
        return instance


class StaffScheduleForm(forms.ModelForm):
    """Form for assigning schedule to a therapist."""

    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={
            'type': 'time', 'class': 'portal-input',
        })
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(attrs={
            'type': 'time', 'class': 'portal-input',
        })
    )

    class Meta:
        model = StaffSchedule
        fields = ['therapist', 'day_of_week', 'start_time', 'end_time', 'is_available', 'notes']
        widgets = {
            'therapist': forms.Select(attrs={'class': 'portal-input'}),
            'day_of_week': forms.Select(attrs={'class': 'portal-input'}),
            'notes': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': 'Optional notes...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['therapist'].queryset = Therapist.objects.filter(is_active=True)
        self.fields['notes'].required = False

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_time')
        end = cleaned_data.get('end_time')
        if start and end and start >= end:
            raise forms.ValidationError("End time must be after start time.")
        return cleaned_data
