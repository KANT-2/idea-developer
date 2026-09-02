import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [("prds", "0002_prd_team_sharing")]

    operations = [
        migrations.CreateModel(
            name="AiUsageLog",
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
                (
                    "feature_type",
                    models.CharField(choices=[("COACHING", "AI 코칭")], max_length=32),
                ),
                (
                    "action_type",
                    models.CharField(
                        choices=[("chat", "대화"), ("draft", "초안")],
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("success", "성공"),
                            ("failed", "실패"),
                            ("cancelled", "취소"),
                        ],
                        max_length=16,
                    ),
                ),
                ("total_tokens", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "prd",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_usage_logs",
                        to="prds.prd",
                    ),
                ),
            ],
            options={
                "db_table": "ai_usage_logs",
                "indexes": [
                    models.Index(
                        fields=["prd", "feature_type", "action_type", "status"],
                        name="ai_usage_home_kpi_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(user_id__gt=0),
                        name="ai_usage_user_id_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(feature_type__in=["COACHING"]),
                        name="ai_usage_feature_type_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(action_type__in=["chat", "draft"]),
                        name="ai_usage_action_type_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(status__in=["success", "failed", "cancelled"]),
                        name="ai_usage_status_valid",
                    ),
                ],
            },
        )
    ]
