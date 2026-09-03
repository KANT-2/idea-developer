from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("prds", "0006_prd_contribution_status_prd_version_and_more")]

    operations = [
        migrations.RemoveConstraint(
            model_name="prd",
            name="prd_round_id_positive",
        ),
        migrations.RemoveConstraint(
            model_name="prdparticipant",
            name="prd_participant_external_id_positive",
        ),
        migrations.AlterField(
            model_name="prd",
            name="round_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="prdparticipant",
            name="participant_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="prd",
            constraint=models.CheckConstraint(
                condition=Q(round_id__isnull=True) | Q(round_id__gt=0),
                name="prd_round_id_null_or_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="prd",
            constraint=models.CheckConstraint(
                condition=Q(round_id__isnull=False) | Q(team_id__isnull=True),
                name="prd_round_null_requires_team_null",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdparticipant",
            constraint=models.CheckConstraint(
                condition=Q(participant_id__isnull=True) | Q(participant_id__gt=0),
                name="prd_participant_external_id_null_or_positive",
            ),
        ),
    ]
