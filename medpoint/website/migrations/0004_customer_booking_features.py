from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0003_therapist_commission_percentage'),
    ]

    operations = [
        migrations.AddField(
            model_name='therapist',
            name='gender',
            field=models.CharField(
                choices=[('male', 'Male'), ('female', 'Female')],
                default='female', max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='client_gender',
            field=models.CharField(
                choices=[('male', 'Male'), ('female', 'Female')],
                default='male', max_length=10,
                help_text='Customer gender (affects therapist preference options)',
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='therapist_preference',
            field=models.CharField(
                choices=[('male', 'Male Therapist'), ('female', 'Female Therapist'), ('random', 'Any / Random')],
                default='random', max_length=10,
                help_text='Preferred therapist gender. Female clients can only select Female.',
            ),
        ),
        migrations.CreateModel(
            name='BookingNotification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.TextField()),
                ('notification_type', models.CharField(
                    choices=[
                        ('confirmed', 'Booking Confirmed'),
                        ('cancelled', 'Booking Cancelled'),
                        ('completed', 'Service Completed'),
                        ('reminder', 'Reminder'),
                    ], default='confirmed', max_length=20,
                )),
                ('is_read', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('booking', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notifications', to='website.booking',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
