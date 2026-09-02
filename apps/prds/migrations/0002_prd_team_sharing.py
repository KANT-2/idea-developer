from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("prds", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="prd",
            name="is_team_shared",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="prd",
            index=models.Index(
                fields=["round_id", "team_id", "is_team_shared"],
                name="prd_team_shared_idx",
            ),
        ),
    ]
