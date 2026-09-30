from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('website', '0021_testimonial_featured_requires_approval'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteContent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.SlugField(max_length=100, unique=True)),
                ('group', models.CharField(db_index=True, max_length=80)),
                ('label', models.CharField(max_length=150)),
                ('value', models.TextField(blank=True)),
                ('default_value', models.TextField(blank=True)),
                ('input_type', models.CharField(choices=[('text', 'Short text'), ('textarea', 'Long text'), ('email', 'Email'), ('phone', 'Phone'), ('url', 'URL')], default='text', max_length=20)),
                ('help_text', models.CharField(blank=True, max_length=255)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_site_content', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Website content',
                'verbose_name_plural': 'Website content',
                'ordering': ['sort_order', 'id'],
            },
        ),
    ]
