from django import forms
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from django.db.models import Q
from website.forms import (
    DUPLICATE_BOOKING_ERROR,
    duplicate_booking_exists,
    validate_full_name,
    validate_phone_number,
)
from website.models import Service, ServiceCategory, Therapist, Booking, StaffSchedule


class ServiceForm(forms.ModelForm):
    """Admin form for creating/editing services."""
    category = forms.MultipleChoiceField(
        choices=(),
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
                'inputmode': 'decimal', 'onwheel': 'this.blur()',
            }),
            'discount_percentage': forms.NumberInput(attrs={
                'class': 'portal-input', 'placeholder': '0',
                'min': 0, 'max': 100, 'step': '0.01',
                'inputmode': 'decimal', 'onwheel': 'this.blur()',
            }),
            'image': forms.ClearableFileInput(attrs={'class': 'portal-input'}),
            'order': forms.NumberInput(attrs={
                'class': 'portal-input', 'placeholder': '0', 'min': 0,
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        selected_codes = []
        if self.instance and self.instance.pk and self.instance.category:
            selected_codes = [c.strip() for c in self.instance.category.split(',')]
            self.initial['category'] = selected_codes
        categories = ServiceCategory.objects.filter(is_active=True)
        if selected_codes:
            categories = ServiceCategory.objects.filter(Q(is_active=True) | Q(code__in=selected_codes))
        self.fields['category'].choices = list(categories.values_list('code', 'name'))

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


class ServiceCategoryForm(forms.ModelForm):
    """Admin form for catalog categories."""

    code = forms.SlugField(
        required=False,
        help_text='Used internally and in website links. It is generated from the name if left blank.',
        widget=forms.TextInput(attrs={
            'class': 'portal-input', 'placeholder': 'premium-packages',
        }),
    )

    class Meta:
        model = ServiceCategory
        fields = ['name', 'code', 'order', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': 'e.g. Premium Packages',
            }),
            'order': forms.NumberInput(attrs={
                'class': 'portal-input', 'min': 0,
            }),
        }
        help_texts = {
            'code': 'Used internally and in website links. It is generated from the name if left blank.',
            'order': 'Lower numbers appear first in Services, Book Now, and Walk-in Booking.',
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicate = ServiceCategory.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError('A category with this name already exists.')
        return name

    def clean_code(self):
        code = slugify(self.cleaned_data.get('code', '').strip())
        if not code:
            code = slugify(self.cleaned_data.get('name', ''))
        if not code:
            raise forms.ValidationError('Enter a valid category name or code.')
        duplicate = ServiceCategory.objects.filter(code__iexact=code).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError('A category with this code already exists.')
        return code


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
            'services', 'therapist_preference', 'therapist', 'date', 'time', 'notes'
        ]
        widgets = {
            'client_name': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': 'Client full name',
                'autocomplete': 'name',
            }),
            'client_gender': forms.Select(attrs={'class': 'portal-input'}),
            'client_email': forms.EmailInput(attrs={
                'class': 'portal-input', 'placeholder': 'client@example.com',
            }),
            'client_phone': forms.TextInput(attrs={
                'class': 'portal-input', 'placeholder': '639XXXXXXXXX',
                'inputmode': 'numeric', 'pattern': '[0-9]+',
                'maxlength': '20', 'autocomplete': 'tel',
            }),
            'services': forms.SelectMultiple(attrs={'class': 'portal-input'}),
            'therapist_preference': forms.Select(attrs={'class': 'portal-input'}),
            'therapist': forms.Select(attrs={'class': 'portal-input'}),
            'time': forms.Select(attrs={'class': 'portal-input'}),
            'notes': forms.Textarea(attrs={
                'class': 'portal-input', 'rows': 3,
                'placeholder': 'Any special notes...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['services'].queryset = Service.objects.filter(is_active=True)
        self.fields['therapist'].queryset = Therapist.objects.filter(is_active=True)
        self.fields['therapist'].required = True
        self.fields['therapist'].error_messages = {
            'required': 'Please select a therapist.'
        }
        self.fields['notes'].required = False
        from django.utils import timezone
        today_local = timezone.localtime(timezone.now()).date()
        self.fields['date'].widget.attrs['min'] = today_local.isoformat()

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
        time_val = cleaned_data.get('time')

        excluded_ids = [self.instance.pk] if self.instance and self.instance.pk else None
        if duplicate_booking_exists(client_name, date, time_val, excluded_ids):
            self.add_error('client_name', DUPLICATE_BOOKING_ERROR)

        services = cleaned_data.get('services')
        if time_val and services:
            try:
                start_hour, start_minute = (int(part) for part in time_val.split(':'))
                available_minutes = (24 * 60) - (start_hour * 60 + start_minute)
                total_duration = sum(service.duration_minutes for service in services)
                if total_duration > available_minutes:
                    self.add_error(
                        'services',
                        'The selected services would finish after closing time. '
                        'Please remove a service or select an earlier time.'
                    )
            except (TypeError, ValueError):
                pass

        if therapist:
            if client_gender == 'female' and therapist.gender != 'female':
                self.add_error(
                    'therapist',
                    'Female clients can only be assigned to female therapists.'
                )
            elif (
                therapist_preference in ('male', 'female')
                and therapist.gender != therapist_preference
            ):
                self.add_error(
                    'therapist',
                    'The selected therapist does not match the therapist preference.'
                )

        if date and time_val and services and therapist:
            import datetime
            from website.models import StaffLeave

            try:
                requested_start_time = datetime.datetime.strptime(time_val, '%H:%M').time()
                requested_start = datetime.datetime.combine(date, requested_start_time)
                total_duration = sum(service.duration_minutes for service in services)
                requested_end = requested_start + datetime.timedelta(minutes=total_duration)

                if StaffLeave.objects.filter(
                    is_active=True,
                    therapist=therapist,
                    start_date__lte=date,
                    end_date__gte=date,
                ).exists():
                    self.add_error(
                        'therapist',
                        f'{therapist.name} is on leave on the selected date.'
                    )

                weekday = date.weekday()
                schedule = StaffSchedule.objects.filter(
                    therapist=therapist,
                    day_of_week=weekday,
                    is_available=True,
                ).first()
                has_schedule_record = StaffSchedule.objects.filter(
                    therapist=therapist,
                    day_of_week=weekday,
                ).exists()

                if schedule:
                    if not schedule.contains_booking(requested_start_time, total_duration):
                        self.add_error(
                            'therapist',
                            f'{therapist.name} is not on shift for the complete '
                            'selected service time.'
                        )
                    if schedule.booking_overlaps_break(requested_start_time, total_duration):
                        self.add_error(
                            'therapist',
                            f'{therapist.name} is on break from '
                            f'{schedule.break_start_time.strftime("%I:%M %p")} to '
                            f'{schedule.break_end_time.strftime("%I:%M %p")}. '
                            'Select a time that does not overlap the break.'
                        )
                elif has_schedule_record:
                    self.add_error(
                        'therapist',
                        f'{therapist.name} is off on the selected date.'
                    )

                existing_bookings = Booking.objects.filter(
                    therapist=therapist,
                    date=date,
                    status__in=['pending', 'confirmed'],
                ).exclude(pk=self.instance.pk).prefetch_related('services')

                for existing in existing_bookings:
                    existing_start_time = datetime.datetime.strptime(
                        existing.time, '%H:%M'
                    ).time()
                    existing_start = datetime.datetime.combine(date, existing_start_time)
                    existing_duration = existing.total_duration_minutes
                    existing_end = existing_start + datetime.timedelta(
                        minutes=existing_duration
                    )
                    if max(requested_start, existing_start) < min(requested_end, existing_end):
                        self.add_error(
                            'therapist',
                            f'{therapist.name} is already booked during this timeframe. '
                            'Please select another therapist or time.'
                        )
                        break
            except (TypeError, ValueError):
                pass

        if date and time_val:
            from django.utils import timezone
            now_local = timezone.localtime(timezone.now())
            today_local = now_local.date()
            if date < today_local:
                self.add_error('date', 'You cannot select a previous date.')
            elif date == today_local:
                try:
                    slot_parts = time_val.split(':')
                    slot_mins = int(slot_parts[0]) * 60 + int(slot_parts[1])
                    now_mins = now_local.hour * 60 + now_local.minute
                    if slot_mins <= now_mins:
                        self.add_error('time', 'You cannot select a past time for today. Please select an available time.')
                except (ValueError, IndexError):
                    pass
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.booking_type = 'walk_in'
        instance.status = 'confirmed'
        instance.is_verified = True
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class StaffScheduleForm(forms.ModelForm):
    """Form for assigning schedule to a therapist."""

    start_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={
            'type': 'time', 'class': 'portal-input'
        })
    )
    end_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={
            'type': 'time', 'class': 'portal-input'
        })
    )
    has_break = forms.BooleanField(required=False, label='Enable break time')
    break_start_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'portal-input'}),
    )
    break_end_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'portal-input'}),
    )

    class Meta:
        model = StaffSchedule
        fields = [
            'therapist', 'day_of_week', 'start_time', 'end_time',
            'has_break', 'break_start_time', 'break_end_time', 'is_available', 'notes',
        ]
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
        if self.instance and self.instance.pk and self.instance.has_break:
            self.fields['has_break'].initial = True

    def clean(self):
        import datetime
        cleaned_data = super().clean()
        is_available = cleaned_data.get('is_available', True)
        start = cleaned_data.get('start_time')
        end = cleaned_data.get('end_time')
        has_break = cleaned_data.get('has_break', False)
        break_start = cleaned_data.get('break_start_time')
        break_end = cleaned_data.get('break_end_time')

        if is_available:
            if not start:
                self.add_error('start_time', "Start time is required when available.")
            elif start < datetime.time(10, 0):
                self.add_error('start_time', "Schedules cannot start before 10:00 AM.")
                
            if not end:
                self.add_error('end_time', "End time is required when available.")
            elif end != datetime.time(0, 0) and end < datetime.time(10, 0):
                self.add_error('end_time', "Schedules must end between 10:00 AM and 12 Midnight.")
                
            if start and end and start >= end and end != datetime.time(0, 0):
                raise forms.ValidationError("End time must be after start time.")

            if has_break:
                if not break_start:
                    self.add_error('break_start_time', 'Break start time is required.')
                if not break_end:
                    self.add_error('break_end_time', 'Break end time is required.')
                if break_start and break_end:
                    shift_start = start.hour * 60 + start.minute if start else 0
                    shift_end = 1440 if end == datetime.time(0, 0) else end.hour * 60 + end.minute
                    break_start_mins = break_start.hour * 60 + break_start.minute
                    break_end_mins = break_end.hour * 60 + break_end.minute
                    if break_start_mins >= break_end_mins:
                        self.add_error('break_end_time', 'Break end time must be after break start time.')
                    elif break_start_mins < shift_start or break_end_mins > shift_end:
                        self.add_error('break_start_time', 'Break time must be within the assigned shift.')
            else:
                cleaned_data['break_start_time'] = None
                cleaned_data['break_end_time'] = None
        else:
            # Set dummy times if not available to satisfy database constraints
            if not start:
                cleaned_data['start_time'] = datetime.time(0, 0)
            if not end:
                cleaned_data['end_time'] = datetime.time(0, 0)
            cleaned_data['break_start_time'] = None
            cleaned_data['break_end_time'] = None

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
    has_break = forms.BooleanField(required=False, label='Enable break time')
    break_start_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'portal-input'}),
    )
    break_end_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'portal-input'}),
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
        has_break = cleaned_data.get('has_break', False)
        break_start = cleaned_data.get('break_start_time')
        break_end = cleaned_data.get('break_end_time')

        if is_available:
            if not start:
                self.add_error('start_time', "Start time is required when available.")
            elif start < datetime.time(10, 0):
                self.add_error('start_time', "Schedules cannot start before 10:00 AM.")
                
            if not end:
                self.add_error('end_time', "End time is required when available.")
            elif end != datetime.time(0, 0) and end < datetime.time(10, 0):
                self.add_error('end_time', "Schedules must end between 10:00 AM and 12 Midnight.")
                
            if start and end and start >= end and end != datetime.time(0, 0):
                raise forms.ValidationError("End time must be after start time.")

            if has_break:
                if not break_start:
                    self.add_error('break_start_time', 'Break start time is required.')
                if not break_end:
                    self.add_error('break_end_time', 'Break end time is required.')
                if break_start and break_end:
                    shift_start = start.hour * 60 + start.minute if start else 0
                    shift_end = 1440 if end == datetime.time(0, 0) else end.hour * 60 + end.minute
                    break_start_mins = break_start.hour * 60 + break_start.minute
                    break_end_mins = break_end.hour * 60 + break_end.minute
                    if break_start_mins >= break_end_mins:
                        self.add_error('break_end_time', 'Break end time must be after break start time.')
                    elif break_start_mins < shift_start or break_end_mins > shift_end:
                        self.add_error('break_start_time', 'Break time must be within the assigned shift.')
            else:
                cleaned_data['break_start_time'] = None
                cleaned_data['break_end_time'] = None
        else:
            if not start:
                cleaned_data['start_time'] = datetime.time(0, 0)
            if not end:
                cleaned_data['end_time'] = datetime.time(0, 0)
            cleaned_data['break_start_time'] = None
            cleaned_data['break_end_time'] = None
                
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
    """Form for assigning leave to a therapist (Admin use)."""
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


class StaffLeaveRequestForm(forms.ModelForm):
    """Form for staff to apply for leave (no therapist selector; auto-filled in view)."""
    class Meta:
        from website.models import StaffLeave
        model = StaffLeave
        fields = ['start_date', 'end_date', 'reason']
        widgets = {
            'start_date': forms.DateInput(attrs={'class': 'portal-input', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'portal-input', 'type': 'date'}),
            'reason': forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'e.g. Vacation, Sick Leave, Personal'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate().isoformat()
        self.fields['start_date'].widget.attrs['min'] = today
        self.fields['end_date'].widget.attrs['min'] = today

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        today = timezone.localdate()

        if start_date and start_date < today:
            self.add_error('start_date', 'Start date cannot be earlier than today.')
        if end_date and end_date < today:
            self.add_error('end_date', 'End date cannot be earlier than today.')

        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("End date cannot be earlier than start date.")
        return cleaned_data

