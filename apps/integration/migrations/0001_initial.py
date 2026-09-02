from django.db import migrations, models


class Migration(migrations.Migration):
    """Django model state only; managed=False emits no VIEW DDL."""

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AxUserTeamLoginView",
            fields=[
                ("user_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("user_email", models.EmailField(max_length=254, null=True)),
                ("first_name", models.CharField(max_length=150, null=True)),
                ("last_name", models.CharField(max_length=150, null=True)),
                ("role", models.CharField(max_length=50, null=True)),
                ("approval_status", models.CharField(max_length=50, null=True)),
                ("phone_number", models.CharField(max_length=50, null=True)),
                ("is_onboarded", models.BooleanField(null=True)),
                ("profile_image", models.CharField(max_length=500, null=True)),
                ("last_login", models.DateTimeField(null=True)),
                ("is_active", models.BooleanField()),
                ("is_staff", models.BooleanField()),
                ("is_superuser", models.BooleanField()),
                ("is_social_account", models.BooleanField(null=True)),
                ("date_joined", models.DateTimeField(null=True)),
                ("primary_email", models.EmailField(max_length=254, null=True)),
                ("participant_id", models.BigIntegerField(null=True)),
                ("round_id", models.BigIntegerField(null=True)),
                (
                    "display_name_snapshot",
                    models.CharField(max_length=255, null=True),
                ),
                ("team_id", models.BigIntegerField(null=True)),
                ("team_name", models.CharField(max_length=255, null=True)),
            ],
            options={
                "db_table": '"public"."ax_user_team_login_view"',
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="UserRoundTeamView",
            fields=[
                (
                    "participant_id",
                    models.BigIntegerField(primary_key=True, serialize=False),
                ),
                ("user_id", models.BigIntegerField()),
                ("email", models.EmailField(max_length=254, null=True)),
                ("round_id", models.BigIntegerField()),
                ("round_title", models.CharField(max_length=255)),
                ("round_status", models.CharField(max_length=50)),
                (
                    "student_number_snapshot",
                    models.CharField(max_length=100, null=True),
                ),
                (
                    "display_name_snapshot",
                    models.CharField(max_length=255, null=True),
                ),
                ("team_id", models.BigIntegerField()),
                ("team_number", models.IntegerField(null=True)),
                ("team_name", models.CharField(max_length=255)),
            ],
            options={
                "db_table": '"public"."user_round_team_view"',
                "managed": False,
            },
        ),
    ]
