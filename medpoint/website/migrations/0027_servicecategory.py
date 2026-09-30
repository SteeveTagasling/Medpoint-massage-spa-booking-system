from django.db import migrations, models


INITIAL_CATEGORIES = [
    ('ordinary_room', 'Ordinary Rooms', 10),
    ('shower_room', 'Shower Rooms', 20),
    ('sauna_room', 'Sauna Rooms', 30),
    ('promo_package', 'Promo Packages', 40),
    ('massage', 'Massage', 50),
    ('facial', 'Facial', 60),
    ('body', 'Body Treatment', 70),
    ('aromatherapy', 'Aromatherapy', 80),
    ('package', 'Package', 90),
]


def seed_categories(apps, schema_editor):
    ServiceCategory = apps.get_model('website', 'ServiceCategory')
    for code, name, order in INITIAL_CATEGORIES:
        ServiceCategory.objects.get_or_create(
            code=code,
            defaults={'name': name, 'order': order, 'is_active': True},
        )


def remove_seeded_categories(apps, schema_editor):
    ServiceCategory = apps.get_model('website', 'ServiceCategory')
    ServiceCategory.objects.filter(code__in=[item[0] for item in INITIAL_CATEGORIES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('website', '0026_rename_website_policy_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('code', models.SlugField(max_length=100, unique=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name_plural': 'Service categories',
                'ordering': ['order', 'name'],
            },
        ),
        migrations.RunPython(seed_categories, remove_seeded_categories),
    ]
