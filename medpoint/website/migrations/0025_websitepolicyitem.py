from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


LEGACY_ITEMS = {
    'booking_policy': [
        ('', 'booking_policy_1', 'Bookings are confirmed via email or SMS within 1 hour.'),
        ('', 'booking_policy_2', 'Please arrive 15 minutes before your appointment.'),
        ('', 'booking_policy_3', 'Bookings are automatically cancelled if the customer is more than 15 minutes late for the scheduled appointment.'),
        ('', 'booking_policy_4', 'Cancellations must be made at least 4 hours in advance.'),
        ('', 'booking_policy_5', 'Walk-ins are welcome based on availability.'),
        ('', 'booking_policy_6', 'Female clients are assigned female therapists only.'),
        ('', 'booking_policy_7', 'Family/group bookings support up to 5 members.'),
    ],
    'privacy_policy': [
        ('Introduction', 'privacy_intro', 'MEDPOINT Massage & Spa respects your privacy. This policy explains how we handle the information you provide when you book a service, contact us, or use our website.'),
        ('Information we collect', 'privacy_collection', 'We may collect your name, contact details, appointment preferences, selected services, booking history, and any information you voluntarily provide about your visit.'),
        ('How we use your information', 'privacy_use', 'We use your information to manage appointments, provide requested services, send booking-related updates, respond to inquiries, maintain service records, and improve our customer experience.'),
        ('Sharing and protection', 'privacy_protection', 'We do not sell your personal information. We only share it when necessary to provide our services, comply with legal obligations, or protect our customers and business. We use reasonable safeguards to prevent unauthorized access, loss, or misuse.'),
        ('Retention and your choices', 'privacy_retention', 'We keep information only as long as reasonably needed for business, safety, and legal purposes. You may contact us to ask about, correct, or request deletion of your personal information, subject to applicable requirements.'),
        ('Contact us', None, 'For privacy questions or requests, email medpointmassage.spa@gmail.com.'),
    ],
    'terms_conditions': [
        ('Introduction', 'terms_intro', 'By booking an appointment or using the MEDPOINT Massage & Spa website, you agree to the following terms.'),
        ('Bookings and availability', 'terms_bookings', 'Appointments are subject to therapist and service availability. Please provide accurate contact and booking details. We may contact you when confirmation or a schedule adjustment is required.'),
        ('Arrival, changes, and cancellations', 'terms_arrival', 'Please arrive on time for your appointment. Late arrivals may shorten the service or cause cancellation. Cancellations should be made at least four hours in advance.'),
        ('Health and safety', 'terms_health', 'Tell your therapist about relevant medical conditions, allergies, injuries, pregnancy, or other concerns before treatment. Services may be adjusted or declined when necessary for safety.'),
        ('Guest conduct', 'terms_conduct', 'Respectful conduct is required. We may end or refuse service in cases of inappropriate, unsafe, or abusive behavior.'),
        ('Prices and updates', 'terms_prices', 'Prices, promotions, operating hours, and these terms may change. The applicable price and policy are those presented when your booking is confirmed.'),
        ('Contact us', None, 'For questions about these terms, email medpointmassage.spa@gmail.com.'),
    ],
}


def migrate_policy_content(apps, schema_editor):
    SiteContent = apps.get_model('website', 'SiteContent')
    WebsitePolicyItem = apps.get_model('website', 'WebsitePolicyItem')
    legacy_keys = []

    for section, definitions in LEGACY_ITEMS.items():
        for index, (title, key, fallback) in enumerate(definitions, start=1):
            body = fallback
            if key:
                legacy_keys.append(key)
                legacy = SiteContent.objects.filter(key=key).first()
                if legacy and legacy.value.strip():
                    body = legacy.value.strip()
            WebsitePolicyItem.objects.create(
                section=section,
                title=title,
                body=body,
                sort_order=index * 10,
            )

    SiteContent.objects.filter(key__in=legacy_keys).delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('website', '0024_staffschedule_break_times'),
    ]

    operations = [
        migrations.CreateModel(
            name='WebsitePolicyItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('section', models.CharField(choices=[('booking_policy', 'Booking Policy'), ('privacy_policy', 'Privacy Policy'), ('terms_conditions', 'Terms & Conditions')], db_index=True, max_length=30)),
                ('title', models.CharField(blank=True, max_length=160)),
                ('body', models.TextField()),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_website_policy_items', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['section', 'sort_order', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='websitepolicyitem',
            index=models.Index(fields=['section', 'sort_order'], name='website_web_section_b7f110_idx'),
        ),
        migrations.AlterField(
            model_name='sitecontent',
            name='input_type',
            field=models.CharField(choices=[('text', 'Short text'), ('textarea', 'Long text'), ('email', 'Email'), ('phone', 'Phone'), ('number', 'Number'), ('url', 'URL')], default='text', max_length=20),
        ),
        migrations.RunPython(migrate_policy_content, migrations.RunPython.noop),
    ]
