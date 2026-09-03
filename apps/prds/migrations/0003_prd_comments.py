import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("prds", "0002_prd_team_sharing")]

    operations = [
        migrations.CreateModel(
            name="PrdComment",
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
                ("author_user_id", models.PositiveBigIntegerField()),
                (
                    "author_role_at_created",
                    models.CharField(
                        choices=[
                            ("owner", "소유자"),
                            ("editor", "편집자"),
                            ("tutor", "튜터"),
                            ("viewer", "열람자"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "comment_type",
                    models.CharField(
                        choices=[
                            ("general", "일반"),
                            ("guidance", "지도"),
                            ("review", "리뷰"),
                            ("post_completion_review", "완료 후 리뷰"),
                        ],
                        max_length=32,
                    ),
                ),
                ("content", models.TextField()),
                ("is_contribution_eligible", models.BooleanField()),
                ("is_deleted", models.BooleanField(default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "prd",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="prds.prd",
                    ),
                ),
                (
                    "section_question",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="comments",
                        to="prds.prdquestion",
                    ),
                ),
            ],
            options={
                "db_table": "prd_comments",
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["prd", "is_deleted", "-created_at"],
                        name="prd_comment_list_idx",
                    ),
                    models.Index(
                        fields=["prd", "section_question", "is_deleted"],
                        name="prd_comment_question_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(author_user_id__gt=0),
                        name="prd_comment_author_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            author_role_at_created__in=["owner", "editor", "tutor", "viewer"]
                        ),
                        name="prd_comment_author_role_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            comment_type__in=[
                                "general",
                                "guidance",
                                "review",
                                "post_completion_review",
                            ]
                        ),
                        name="prd_comment_type_valid",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(content=""),
                        name="prd_comment_content_not_blank",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("deleted_at__isnull", True), ("is_deleted", False)),
                            models.Q(("deleted_at__isnull", False), ("is_deleted", True)),
                            _connector="OR",
                        ),
                        name="prd_comment_deleted_consistent",
                    ),
                ],
            },
        )
    ]
