from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0033_sitecontent_image_input_type'),
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
                    ('range', 'Range'),
                ],
                default='text',
                max_length=20,
            ),
        ),
    ]
