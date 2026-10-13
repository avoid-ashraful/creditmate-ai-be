from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0002_alter_alertsubscription_unsubscribe_token"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="alertsubscription",
            index=models.Index(
                condition=models.Q(is_active=True),
                fields=["-created"],
                name="alerts_active_created_idx",
            ),
        ),
    ]
