import uuid

import django.utils.timezone
from django.db import migrations, models

import apps.accounts.managers


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="LocalUserMapping",
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
                ("password", models.CharField(max_length=128, verbose_name="password")),
                (
                    "last_login",
                    models.DateTimeField(blank=True, null=True, verbose_name="last login"),
                ),
                ("external_user_id", models.BigIntegerField(unique=True)),
                ("email_snapshot", models.EmailField(blank=True, max_length=254)),
                ("is_active", models.BooleanField(default=True)),
                ("last_verified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "idea_local_user_mapping",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("password__startswith", "!")),
                        name="local_user_password_unusable",
                    )
                ],
            },
            managers=[("objects", apps.accounts.managers.LocalUserMappingManager())],
        ),
        migrations.CreateModel(
            name="LoginOtpChallenge",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("normalized_email", models.EmailField(db_index=True, max_length=254)),
                ("external_user_id", models.BigIntegerField(blank=True, null=True)),
                ("code_hash", models.CharField(max_length=255)),
                ("ip_hash", models.CharField(db_index=True, max_length=64)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("failed_attempts", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "db_table": "idea_login_otp_challenge",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("failed_attempts__lte", 5)),
                        name="login_otp_failed_attempts_lte_5",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="LoginAuditLog",
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
                ("external_user_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
                (
                    "event",
                    models.CharField(
                        choices=[
                            ("otp_requested", "OTP requested"),
                            ("login_success", "Login success"),
                            ("login_failure", "Login failure"),
                            ("logout", "Logout"),
                            ("debug_login", "Debug login"),
                        ],
                        max_length=32,
                    ),
                ),
                ("occurred_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("ip_hash", models.CharField(blank=True, max_length=64)),
                ("user_agent_summary", models.CharField(blank=True, max_length=255)),
                ("details", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "db_table": "idea_login_audit_log",
                "ordering": ["-occurred_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="loginotpchallenge",
            index=models.Index(
                fields=["normalized_email", "created_at"],
                name="login_otp_email_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="loginotpchallenge",
            index=models.Index(
                fields=["ip_hash", "created_at"],
                name="login_otp_ip_created_idx",
            ),
        ),
    ]
