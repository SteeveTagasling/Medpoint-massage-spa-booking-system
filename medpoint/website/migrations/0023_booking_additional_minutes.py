from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0022_sitecontent'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='additional_minutes',
            field=models.PositiveIntegerField(
                choices=[
                    (0, 'No additional time'),
                    (30, '30 minutes (+₱200.00)'),
                    (60, '60 minutes (+₱400.00)'),
                    (90, '90 minutes (+₱600.00)'),
                    (120, '120 minutes (+₱800.00)'),
                ],
                default=0,
                help_text='Optional massage extension charged at ₱200 per 30 minutes',
            ),
        ),
    ]
