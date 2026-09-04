from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("prds", "0010_prdquestion_is_held")]

    operations = [
        migrations.AddField(
            model_name="prd",
            name="purge_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="prd",
            name="purge_requested_by_user_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="prd",
            index=models.Index(
                condition=models.Q(("is_deleted", True)),
                fields=["deleted_at"],
                name="prd_deleted_purge_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="prd",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        ("purge_requested_at__isnull", True),
                        ("purge_requested_by_user_id__isnull", True),
                    )
                    | models.Q(
                        ("is_deleted", True),
                        ("purge_requested_at__isnull", False),
                        ("purge_requested_by_user_id__isnull", False),
                    )
                ),
                name="prd_purge_request_consistent",
            ),
        ),
        migrations.CreateModel(
            name="PrdDeletionAuditLog",
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
                ("prd_id", models.PositiveBigIntegerField()),
                ("title_snapshot", models.CharField(max_length=255)),
                ("creator_user_id", models.PositiveBigIntegerField()),
                ("actor_user_id", models.PositiveBigIntegerField(blank=True, null=True)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("trashed", "휴지통 이동"),
                            ("restored", "복구"),
                            ("delete_completed", "삭제 완료"),
                            ("purged", "영구 삭제"),
                        ],
                        max_length=24,
                    ),
                ),
                ("details", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "prd_deletion_audit_logs",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="prddeletionauditlog",
            index=models.Index(
                fields=["prd_id", "-created_at"],
                name="prd_delete_audit_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="prddeletionauditlog",
            constraint=models.CheckConstraint(
                condition=models.Q(("prd_id__gt", 0)),
                name="prd_delete_audit_prd_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="prddeletionauditlog",
            constraint=models.CheckConstraint(
                condition=models.Q(("creator_user_id__gt", 0)),
                name="prd_delete_audit_creator_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="prddeletionauditlog",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("actor_user_id__isnull", True))
                    | models.Q(("actor_user_id__gt", 0))
                ),
                name="prd_delete_audit_actor_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="prddeletionauditlog",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("action__in", ["trashed", "restored", "delete_completed", "purged"])
                ),
                name="prd_delete_audit_action_valid",
            ),
        ),
    ]
