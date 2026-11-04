from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0034_sitecontent_range_input_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('payment_method', models.CharField(choices=[('cash', 'Cash'), ('card', 'Card'), ('bank_transfer', 'Bank transfer'), ('e_wallet', 'E-wallet'), ('staff_verified', 'Staff verified'), ('other', 'Other')], max_length=20)),
                ('reference', models.CharField(blank=True, max_length=120)),
                ('status', models.CharField(choices=[('successful', 'Successful'), ('failed', 'Failed'), ('refunded', 'Refunded')], default='successful', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='payment_transactions', to='website.booking')),
                ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
