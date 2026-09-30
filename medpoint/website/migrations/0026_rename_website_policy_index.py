from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0025_websitepolicyitem'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='websitepolicyitem',
            old_name='website_web_section_b7f110_idx',
            new_name='website_web_section_42a906_idx',
        ),
    ]
