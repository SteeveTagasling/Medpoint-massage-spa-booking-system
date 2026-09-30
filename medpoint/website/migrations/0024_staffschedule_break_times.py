from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0023_booking_additional_minutes'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffschedule',
            name='break_start_time',
            field=models.TimeField(
                blank=True,
                help_text="Optional start of the staff member's break",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='staffschedule',
            name='break_end_time',
            field=models.TimeField(
                blank=True,
                help_text="Optional end of the staff member's break",
                null=True,
            ),
        ),
    ]
