from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("prds", "0009_backfill_existing_prds_from_templates")]

    operations = [
        migrations.AddField(
            model_name="prdquestion",
            name="is_held",
            field=models.BooleanField(default=False),
        ),
        migrations.RemoveIndex(
            model_name="prdquestion",
            name="prd_question_completion_idx",
        ),
        migrations.AddIndex(
            model_name="prdquestion",
            index=models.Index(
                fields=["section", "is_deleted", "is_held", "is_completed"],
                name="prd_question_progress_idx",
            ),
        ),
    ]
