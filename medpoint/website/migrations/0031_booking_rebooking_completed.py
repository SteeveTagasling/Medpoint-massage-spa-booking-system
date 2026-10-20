from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0030_limit_booking_additional_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='rebooking_completed',
            field=models.BooleanField(
                default=False,
                help_text='Whether the client has completed rebooking with this token.',
            ),
        ),
    ]
