from django.db import migrations


LEGACY_CATEGORIES = [
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


def ensure_categories(apps, schema_editor):
    ServiceCategory = apps.get_model('website', 'ServiceCategory')
    for code, name, order in LEGACY_CATEGORIES:
        ServiceCategory.objects.get_or_create(
            code=code,
            defaults={'name': name, 'order': order, 'is_active': True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ('website', '0027_servicecategory'),
    ]

    operations = [
        migrations.RunPython(ensure_categories, migrations.RunPython.noop),
    ]
