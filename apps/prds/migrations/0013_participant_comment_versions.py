from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("prds", "0012_roundless_prd_idempotency")]

    operations = [
        migrations.AddField(
            model_name="prdparticipant",
            name="version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="prdcomment",
            name="version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddConstraint(
            model_name="prdparticipant",
            constraint=models.CheckConstraint(
                condition=models.Q(("version__gte", 1)),
                name="prd_participant_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdcomment",
            constraint=models.CheckConstraint(
                condition=models.Q(("version__gte", 1)),
                name="prd_comment_version_positive",
            ),
        ),
    ]
