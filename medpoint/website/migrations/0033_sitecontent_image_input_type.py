from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0032_alter_booking_rebooking_token'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitecontent',
            name='input_type',
            field=models.CharField(
                choices=[
                    ('text', 'Short text'),
                    ('textarea', 'Long text'),
                    ('email', 'Email'),
                    ('phone', 'Phone'),
                    ('number', 'Number'),
                    ('url', 'URL'),
                    ('image', 'Image'),
                ],
                default='text',
                max_length=20,
            ),
        ),
    ]
