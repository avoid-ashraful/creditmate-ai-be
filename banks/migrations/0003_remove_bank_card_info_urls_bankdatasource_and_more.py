# Generated by Django 5.2.2 on 2025-06-10 19:44

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("banks", "0002_rename_created_at_bank_created_and_more"),
        ("credit_cards", "0002_rename_created_at_creditcard_created_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="bank",
            name="card_info_urls",
        ),
        migrations.CreateModel(
            name="BankDataSource",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("modified", models.DateTimeField(auto_now=True)),
                (
                    "url",
                    models.URLField(
                        max_length=1024,
                        validators=[django.core.validators.URLValidator()],
                    ),
                ),
                (
                    "content_type",
                    models.CharField(
                        choices=[
                            ("pdf", "PDF"),
                            ("webpage", "Webpage"),
                            ("image", "Image"),
                            ("csv", "CSV"),
                        ],
                        max_length=20,
                    ),
                ),
                ("description", models.CharField(blank=True, default="", max_length=500)),
                ("failed_attempt_count", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("last_crawled_at", models.DateTimeField(blank=True, null=True)),
                ("last_successful_crawl_at", models.DateTimeField(blank=True, null=True)),
                (
                    "bank",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="data_sources",
                        to="banks.bank",
                    ),
                ),
            ],
            options={
                "db_table": "banks_bankdatasource",
                "ordering": ["bank__name", "url"],
                "unique_together": {("bank", "url")},
            },
        ),
        migrations.CreateModel(
            name="CrawledContent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("modified", models.DateTimeField(auto_now=True)),
                ("raw_content", models.TextField(blank=True, default="")),
                ("extracted_content", models.TextField(blank=True, default="")),
                ("parsed_json", models.JSONField(blank=True, default=dict)),
                ("crawl_date", models.DateTimeField(auto_now_add=True)),
                (
                    "processing_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("error_message", models.TextField(blank=True, default="")),
                (
                    "credit_card",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="crawled_contents",
                        to="credit_cards.creditcard",
                    ),
                ),
                (
                    "data_source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="crawled_contents",
                        to="banks.bankdatasource",
                    ),
                ),
            ],
            options={
                "db_table": "banks_crawledcontent",
                "ordering": ["-crawl_date"],
            },
        ),
    ]
