from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_existing_owner(apps, schema_editor):
    ReportSignatory = apps.get_model('portals', 'ReportSignatory')
    ReportSignatory.objects.get_or_create(
        name='REGENCIA, JOSHUA JAMES DEMECILIO',
        role='Owner',
    )


def remove_seeded_owner(apps, schema_editor):
    ReportSignatory = apps.get_model('portals', 'ReportSignatory')
    ReportSignatory.objects.filter(
        name='REGENCIA, JOSHUA JAMES DEMECILIO',
        role='Owner',
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('portals', '0002_staffnotification'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReportSignatory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('role', models.CharField(help_text='For example: Manager or Owner', max_length=100)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_report_signatories', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'Report signatories',
                'ordering': ['role', 'name'],
            },
        ),
        migrations.RunPython(seed_existing_owner, remove_seeded_owner),
    ]
