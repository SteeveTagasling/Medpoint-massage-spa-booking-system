from django.db import migrations, models


def clear_unapproved_featured_testimonials(apps, schema_editor):
    Testimonial = apps.get_model('website', 'Testimonial')
    Testimonial.objects.filter(is_approved=False, is_featured=True).update(is_featured=False)


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0020_seed_official_service_menu'),
    ]

    operations = [
        migrations.RunPython(
            clear_unapproved_featured_testimonials,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='testimonial',
            constraint=models.CheckConstraint(
                condition=models.Q(is_approved=True) | models.Q(is_featured=False),
                name='testimonial_featured_requires_approval',
            ),
        ),
    ]
