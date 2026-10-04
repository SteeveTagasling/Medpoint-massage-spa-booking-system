from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0029_clean_synced_email_replies'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='additional_minutes',
            field=models.PositiveIntegerField(
                choices=[
                    (0, 'No additional time'),
                    (30, '30 minutes (+₱200.00)'),
                ],
                default=0,
                help_text='Optional massage extension charged at ₱200 per 30 minutes',
            ),
        ),
    ]
