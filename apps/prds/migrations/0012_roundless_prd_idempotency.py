from django.db import migrations, models
from django.db.models import Count, Q


def validate_existing_idempotency_rows(apps, schema_editor):
    prd = apps.get_model("prds", "Prd")
    duplicate_roundless = (
        prd.objects.filter(round_id__isnull=True)
        .values("creator_user_id", "creation_idempotency_key")
        .annotate(row_count=Count("id"))
        .filter(row_count__gt=1)
        .exists()
    )
    if duplicate_roundless:
        raise RuntimeError(
            "Duplicate roundless PRD idempotency rows exist. Resolve them explicitly "
            "before applying prds.0012; this migration will not delete user data."
        )


class Migration(migrations.Migration):
    dependencies = [("prds", "0011_prd_trash_retention")]

    operations = [
        migrations.RunPython(
            validate_existing_idempotency_rows,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveConstraint(
            model_name="prd",
            name="uniq_prd_creation_request",
        ),
        migrations.AddConstraint(
            model_name="prd",
            constraint=models.UniqueConstraint(
                fields=("creator_user_id", "round_id", "creation_idempotency_key"),
                condition=Q(round_id__isnull=False),
                name="uniq_prd_creation_round_request",
            ),
        ),
        migrations.AddConstraint(
            model_name="prd",
            constraint=models.UniqueConstraint(
                fields=("creator_user_id", "creation_idempotency_key"),
                condition=Q(round_id__isnull=True),
                name="uniq_prd_creation_roundless_request",
            ),
        ),
    ]
