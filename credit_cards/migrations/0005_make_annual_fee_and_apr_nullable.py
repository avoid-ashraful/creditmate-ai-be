# Generated migration to make annual_fee and interest_rate_apr nullable
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("credit_cards", "0004_creditcard_lounge_access_condition"),
    ]

    operations = [
        migrations.AlterField(
            model_name="creditcard",
            name="annual_fee",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AlterField(
            model_name="creditcard",
            name="interest_rate_apr",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=5,
                null=True,
                validators=[
                    django.core.validators.MaxValueValidator(100),
                    django.core.validators.MinValueValidator(0),
                ],
            ),
        ),
    ]
