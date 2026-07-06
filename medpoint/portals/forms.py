from django import forms
from django.contrib.auth.models import User
from django.utils.text import slugify
from website.models import Service, Therapist, Booking, StaffSchedule


class ServiceForm(forms.ModelForm):
    """Admin form for creating/editing services."""
    category = forms.MultipleChoiceField(
        choices=Service.CATEGORY_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'category-checkboxes'}),
        help_text="Select one or more categories."
    )

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.category:
            self.initial['category'] = [c.strip() for c in self.instance.category.split(',')]

    def clean_category(self):
        data = self.cleaned_data['category']
        return ','.join(data)

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
    username = forms.CharField(max_length=150, required=False, widget=forms.TextInput(attrs={
        'class': 'portal-input', 'placeholder': 'Staff username (optional)',
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'portal-input', 'placeholder': 'Leave blank to keep current',
    }), required=False)

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and getattr(self.instance, 'user', None):
            self.fields['username'].initial = self.instance.user.username

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.slug:
            instance.slug = slugify(instance.name)
            original_slug = instance.slug
            counter = 1
            while Therapist.objects.filter(slug=instance.slug).exclude(pk=instance.pk).exists():
                instance.slug = f"{original_slug}-{counter}"
                counter += 1
        
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        
        if username:
            if instance.user:
                instance.user.username = username
                if password:
                    instance.user.set_password(password)
                instance.user.email = instance.email
                instance.user.save()
            else:
                user = User.objects.create_user(
                    username=username,
                    password=password if password else 'password123',
                    email=instance.email,
                    is_staff=True
                )
                instance.user = user

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
            'client_name', 'client_gender', 'client_email', 'client_phone',
            'service', 'therapist_preference', 'therapist', 'date', 'time', 'notes', 'status'
        ]
        widgets = {
            'client_name': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': 'Client full name',
            }),
            'client_gender': forms.Select(attrs={'class': 'portal-input'}),
            'client_email': forms.EmailInput(attrs={
                'class': 'portal-input', 'placeholder': 'client@example.com',
            }),
            'client_phone': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': '+63 9XX XXX XXXX',
            }),
            'service': forms.Select(attrs={'class': 'portal-input'}),
            'therapist_preference': forms.Select(attrs={'class': 'portal-input'}),
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
        required=False,
        widget=forms.TimeInput(attrs={
            'type': 'time', 'class': 'portal-input',
        })
    )
    end_time = forms.TimeField(
        required=False,
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
        import datetime
        cleaned_data = super().clean()
        is_available = cleaned_data.get('is_available', True)
        start = cleaned_data.get('start_time')
        end = cleaned_data.get('end_time')

        if is_available:
            if not start:
                self.add_error('start_time', "Start time is required when available.")
            if not end:
                self.add_error('end_time', "End time is required when available.")
            if start and end and start >= end:
                raise forms.ValidationError("End time must be after start time.")
        else:
            # Set dummy times if not available to satisfy database constraints
            if not start:
                cleaned_data['start_time'] = datetime.time(0, 0)
            if not end:
                cleaned_data['end_time'] = datetime.time(0, 0)

        return cleaned_data


class BulkStaffScheduleForm(forms.Form):
    """Form for assigning schedule to a therapist across multiple days."""
    
    therapist = forms.ModelChoiceField(
        queryset=Therapist.objects.none(),
        widget=forms.Select(attrs={'class': 'portal-input'})
    )
    day_of_week = forms.MultipleChoiceField(
        choices=StaffSchedule.DAY_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'day-checkboxes'})
    )
    is_available = forms.BooleanField(required=False, initial=True)
    start_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'portal-input'})
    )
    end_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'portal-input'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Optional notes...'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['therapist'].queryset = Therapist.objects.filter(is_active=True)

    def clean(self):
        import datetime
        cleaned_data = super().clean()
        is_available = cleaned_data.get('is_available', True)
        start = cleaned_data.get('start_time')
        end = cleaned_data.get('end_time')

        if is_available:
            if not start:
                self.add_error('start_time', "Start time is required when available.")
            if not end:
                self.add_error('end_time', "End time is required when available.")
            if start and end and start >= end:
                raise forms.ValidationError("End time must be after start time.")
        else:
            if not start:
                cleaned_data['start_time'] = datetime.time(0, 0)
            if not end:
                cleaned_data['end_time'] = datetime.time(0, 0)
                
        return cleaned_data

class AdminSettingsForm(forms.Form):
    """Form for updating Admin profile, username, password, and photo."""
    photo = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={'class': 'portal-input'}))
    first_name = forms.CharField(max_length=150, required=False, widget=forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'First Name'}))
    last_name = forms.CharField(max_length=150, required=False, widget=forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Last Name'}))
    username = forms.CharField(max_length=150, required=True, label="Admin ID (Username)", widget=forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Admin ID'}))
    password = forms.CharField(required=False, widget=forms.PasswordInput(attrs={'class': 'portal-input', 'placeholder': 'Leave blank to keep current password'}))

class AdminUserForm(forms.ModelForm):
    """Form for creating or editing other Administrator accounts."""
    password = forms.CharField(required=False, widget=forms.PasswordInput(attrs={'class': 'portal-input', 'placeholder': 'Leave blank to keep current password'}))

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Admin Username'}),
            'first_name': forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Last Name'}),
            'email': forms.EmailInput(attrs={'class': 'portal-input', 'placeholder': 'admin@medpoint.com'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        user.is_superuser = True
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        elif not user.pk:
            user.set_password('admin123') # fallback default password if not provided on creation
        if commit:
            user.save()
        return user

class StaffSettingsForm(forms.ModelForm):
    """Form for restricted staff profile updates."""
    password = forms.CharField(required=False, widget=forms.PasswordInput(attrs={'class': 'portal-input', 'placeholder': 'Leave blank to keep current password'}))

    class Meta:
        model = Therapist
        fields = ['photo', 'name', 'bio', 'phone', 'email']
        widgets = {
            'photo': forms.FileInput(attrs={'class': 'portal-file-input', 'accept': 'image/*'}),
            'name': forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Full Name'}),
            'bio': forms.Textarea(attrs={'class': 'portal-input', 'rows': 3, 'placeholder': 'Write a short bio...'}),
            'phone': forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Contact Number'}),
            'email': forms.EmailInput(attrs={'class': 'portal-input', 'placeholder': 'Email Address'}),
        }


class StaffLeaveForm(forms.ModelForm):
    """Form for assigning leave to a therapist."""
    class Meta:
        from website.models import StaffLeave
        model = StaffLeave
        fields = ['therapist', 'start_date', 'end_date', 'reason']
        widgets = {
            'therapist': forms.Select(attrs={'class': 'portal-input'}),
            'start_date': forms.DateInput(attrs={'class': 'portal-input', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'portal-input', 'type': 'date'}),
            'reason': forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Optional reason (e.g. Vacation, Sick Leave)'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("End date cannot be earlier than start date.")
        return cleaned_data
