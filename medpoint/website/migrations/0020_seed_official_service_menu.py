from datetime import date

from django.db import migrations


SERVICE_MENU = [
    # Ordinary Rooms
    {
        'slug': 'ordinary-room-shiatsu-massage',
        'name': 'Shiatsu Massage',
        'category': 'ordinary_room',
        'duration_minutes': 60,
        'price': '400.00',
        'description': 'A combination of Shiatsu and Thai massage techniques.',
    },
    {
        'slug': 'ordinary-room-swedish-massage',
        'name': 'Swedish Massage',
        'category': 'ordinary_room',
        'duration_minutes': 60,
        'price': '400.00',
        'description': 'A combination of Swedish, Shiatsu, and Thai massage techniques.',
    },
    {
        'slug': 'ordinary-room-stone-massage',
        'name': 'Stone Massage',
        'category': 'ordinary_room',
        'duration_minutes': 90,
        'price': '600.00',
        'description': 'One hour Swedish massage followed by a 30-minute hot stone treatment.',
    },
    {
        'slug': 'ordinary-room-buhang-vacuum-massage',
        'name': 'Buhang (Vacuum) Massage',
        'category': 'ordinary_room',
        'duration_minutes': 90,
        'price': '600.00',
        'description': 'One hour Swedish massage followed by 30 minutes of Korean-style vacuum cupping.',
    },
    {
        'slug': 'ordinary-room-body-scrub',
        'name': 'Body Scrub',
        'category': 'ordinary_room',
        'duration_minutes': 60,
        'price': '600.00',
        'description': 'An exfoliating salt, honey, milk, and lotion treatment that leaves skin fresh, smooth, and soft.',
    },
    {
        'slug': 'ordinary-room-facial',
        'name': 'Facial',
        'category': 'ordinary_room',
        'duration_minutes': 60,
        'price': '400.00',
        'description': 'A skincare beauty treatment designed to exfoliate and give the face a youthful glow.',
    },
    {
        'slug': 'ordinary-room-foot-massage',
        'name': 'Foot Massage',
        'category': 'ordinary_room',
        'duration_minutes': 60,
        'price': '400.00',
        'description': 'A relaxing foot massage finished with a brief head, arm, neck, and upper-back massage.',
    },
    {
        'slug': 'ordinary-room-foot-spa',
        'name': 'Foot Spa',
        'category': 'ordinary_room',
        'duration_minutes': 60,
        'price': '350.00',
        'description': 'Removal of calluses and dry, dead skin from the feet.',
    },
    {
        'slug': 'ordinary-room-eyelash-extensions',
        'name': 'Eyelash Extensions',
        'category': 'ordinary_room',
        'duration_minutes': 60,
        'price': '600.00',
        'description': 'Semi-permanent fibers applied to natural lashes for a longer, thicker, and darker appearance.',
    },

    # Shower Rooms
    {
        'slug': 'shower-room-shiatsu-60',
        'name': 'Shiatsu Massage + Shower/Rest',
        'category': 'shower_room',
        'duration_minutes': 90,
        'price': '550.00',
        'description': 'One hour Shiatsu massage with 30 minutes for shower and rest in an air-conditioned room, including a bathrobe and complimentary drink.',
    },
    {
        'slug': 'shower-room-swedish-60',
        'name': 'Swedish Massage + Shower/Rest',
        'category': 'shower_room',
        'duration_minutes': 90,
        'price': '550.00',
        'description': 'One hour Swedish massage with 30 minutes for shower and rest in an air-conditioned room, including a bathrobe and complimentary drink.',
    },
    {
        'slug': 'shower-room-body-scrub',
        'name': 'Body Scrub + Shower/Rest',
        'category': 'shower_room',
        'duration_minutes': 90,
        'price': '600.00',
        'description': 'Body scrub treatment with shower and rest in an air-conditioned room, including a bathrobe and complimentary drink.',
    },
    {
        'slug': 'shower-room-shiatsu-90',
        'name': '90-Minute Shiatsu Massage + Shower/Rest',
        'category': 'shower_room',
        'duration_minutes': 120,
        'price': '700.00',
        'description': 'A 90-minute Shiatsu massage with 30 minutes for shower and rest in an air-conditioned room, including a bathrobe and complimentary drink.',
    },
    {
        'slug': 'shower-room-swedish-90',
        'name': '90-Minute Swedish Massage + Shower/Rest',
        'category': 'shower_room',
        'duration_minutes': 120,
        'price': '700.00',
        'description': 'A 90-minute Swedish massage with 30 minutes for shower and rest in an air-conditioned room, including a bathrobe and complimentary drink.',
    },
    {
        'slug': 'shower-room-stone-massage',
        'name': 'Stone Massage + Shower/Rest',
        'category': 'shower_room',
        'duration_minutes': 120,
        'price': '750.00',
        'description': 'A 90-minute stone massage treatment with 30 minutes for shower and rest in an air-conditioned room, including a bathrobe and complimentary drink.',
    },
    {
        'slug': 'shower-room-buhang-treatment',
        'name': 'Buhang (Vacuum) Treatment + Shower/Rest',
        'category': 'shower_room',
        'duration_minutes': 120,
        'price': '750.00',
        'description': 'A 90-minute massage and vacuum treatment with 30 minutes for shower and rest in an air-conditioned room, including a bathrobe and complimentary drink.',
    },

    # Sauna Rooms — individual and two-person rates from the menu
    {
        'slug': 'sauna-oil-body-massage-60',
        'name': '1-Hour Oil Body Massage + Sauna',
        'category': 'sauna_room',
        'duration_minutes': 90,
        'price': '800.00',
        'description': 'One hour oil body massage followed by a sauna session.',
    },
    {
        'slug': 'sauna-oil-body-massage-60-couple',
        'name': '1-Hour Oil Body Massage + Sauna (2 Persons)',
        'category': 'sauna_room',
        'duration_minutes': 90,
        'price': '1500.00',
        'description': 'Two-person rate for a one-hour oil body massage followed by a sauna session.',
    },
    {
        'slug': 'sauna-oil-body-massage-90',
        'name': '90-Minute Oil Body Massage + Sauna',
        'category': 'sauna_room',
        'duration_minutes': 120,
        'price': '950.00',
        'description': 'A 90-minute oil body massage followed by a sauna session.',
    },
    {
        'slug': 'sauna-oil-body-massage-90-couple',
        'name': '90-Minute Oil Body Massage + Sauna (2 Persons)',
        'category': 'sauna_room',
        'duration_minutes': 120,
        'price': '1800.00',
        'description': 'Two-person rate for a 90-minute oil body massage followed by a sauna session.',
    },
    {
        'slug': 'sauna-oil-buhang-treatment',
        'name': '90-Minute Oil Body Massage + Buhang Treatment + Sauna',
        'category': 'sauna_room',
        'duration_minutes': 120,
        'price': '1000.00',
        'description': 'A 90-minute oil body massage with Buhang vacuum treatment and sauna.',
    },
    {
        'slug': 'sauna-oil-buhang-treatment-couple',
        'name': '90-Minute Oil Body Massage + Buhang + Sauna (2 Persons)',
        'category': 'sauna_room',
        'duration_minutes': 120,
        'price': '1900.00',
        'description': 'Two-person rate for a 90-minute oil body massage with Buhang treatment and sauna.',
    },
    {
        'slug': 'sauna-oil-stone-massage',
        'name': '90-Minute Oil Body Massage + Stone Massage + Sauna',
        'category': 'sauna_room',
        'duration_minutes': 120,
        'price': '1000.00',
        'description': 'A 90-minute oil body massage with stone treatment and sauna.',
    },
    {
        'slug': 'sauna-oil-stone-massage-couple',
        'name': '90-Minute Oil Body Massage + Stone + Sauna (2 Persons)',
        'category': 'sauna_room',
        'duration_minutes': 120,
        'price': '1900.00',
        'description': 'Two-person rate for a 90-minute oil body massage with stone treatment and sauna.',
    },
    {
        'slug': 'sauna-additional-30-minute-massage',
        'name': 'Additional 30 Minutes of Massage (Add-on)',
        'category': 'sauna_room',
        'duration_minutes': 30,
        'price': '200.00',
        'description': 'Adds 30 minutes of massage to an eligible massage service. This is an add-on and must be selected with a main treatment.',
    },

    # Promo Packages
    {
        'slug': 'promo-swedish-body-scrub',
        'name': 'Swedish Massage + Body Scrub',
        'category': 'promo_package',
        'duration_minutes': 120,
        'price': '900.00',
        'description': 'One hour Swedish massage paired with a body scrub treatment.',
    },
    {
        'slug': 'promo-swedish-foot-massage',
        'name': 'Swedish Massage + 40-Minute Foot Massage',
        'category': 'promo_package',
        'duration_minutes': 100,
        'price': '550.00',
        'description': 'One hour Swedish massage paired with a 40-minute foot massage.',
    },
    {
        'slug': 'promo-shiatsu-foot-massage',
        'name': 'Shiatsu Massage + 40-Minute Foot Massage',
        'category': 'promo_package',
        'duration_minutes': 100,
        'price': '550.00',
        'description': 'One hour Shiatsu massage paired with a 40-minute foot massage.',
    },
    {
        'slug': 'promo-foot-spa-foot-massage',
        'name': 'Foot Spa + Foot Massage',
        'category': 'promo_package',
        'duration_minutes': 90,
        'price': '500.00',
        'description': 'A 90-minute combination of foot spa and foot massage.',
    },
    {
        'slug': 'promo-facial-foot-spa-massage',
        'name': 'Facial + Foot Spa + 30-Minute Foot Massage',
        'category': 'promo_package',
        'duration_minutes': 150,
        'price': '850.00',
        'description': 'A facial and foot spa package finished with a 30-minute foot massage.',
    },
    {
        'slug': 'promo-swedish-buhang',
        'name': '90-Minute Swedish Massage + Buhang Treatment',
        'category': 'promo_package',
        'duration_minutes': 120,
        'price': '700.00',
        'description': 'A two-hour package combining a 90-minute Swedish massage and Buhang vacuum treatment.',
    },
    {
        'slug': 'promo-swedish-stone',
        'name': '90-Minute Swedish Massage + Stone Massage',
        'category': 'promo_package',
        'duration_minutes': 120,
        'price': '700.00',
        'description': 'A two-hour package combining a 90-minute Swedish massage and stone treatment.',
    },
]


def seed_service_menu(apps, schema_editor):
    Service = apps.get_model('website', 'Service')
    ServicePriceHistory = apps.get_model('website', 'ServicePriceHistory')

    for order, service_data in enumerate(SERVICE_MENU, start=10):
        data = service_data.copy()
        slug = data.pop('slug')
        description = data['description']
        data.update({
            'short_description': description[:300],
            'discount_percentage': '0.00',
            'is_active': True,
            'order': order,
        })
        service, _ = Service.objects.update_or_create(slug=slug, defaults=data)

        history = ServicePriceHistory.objects.filter(
            service=service,
            effective_from=date(2026, 9, 25),
        ).order_by('-id').first()
        history_defaults = {
            'base_price': data['price'],
            'discount_percentage': data['discount_percentage'],
            'effective_to': None,
            'notes': 'Official printed service menu',
        }
        if history:
            for field, value in history_defaults.items():
                setattr(history, field, value)
            history.save(update_fields=list(history_defaults))
        else:
            ServicePriceHistory.objects.create(
                service=service,
                effective_from=date(2026, 9, 25),
                **history_defaults,
            )


def keep_service_menu_on_reverse(apps, schema_editor):
    # Service records can be referenced by bookings, so reversing the schema
    # migration must not delete customer booking history.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0019_booking_rebooking_token'),
    ]

    operations = [
        migrations.RunPython(seed_service_menu, keep_service_menu_on_reverse),
    ]
