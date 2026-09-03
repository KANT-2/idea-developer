import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0001_initial"),
        ("prds", "0003_prd_comments"),
    ]

    operations = [
        migrations.CreateModel(
            name="AiChatHistory",
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
                ("user_id", models.PositiveBigIntegerField()),
                ("prompt", models.TextField()),
                ("response", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "prd",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_chat_history",
                        to="prds.prd",
                    ),
                ),
            ],
            options={
                "db_table": "ai_chat_histories",
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["prd", "-created_at"],
                        name="ai_chat_prd_created_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(user_id__gt=0),
                        name="ai_chat_user_id_positive",
                    )
                ],
            },
        )
    ]
