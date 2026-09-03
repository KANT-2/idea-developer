from django.db import migrations, models


def normalize_note_status_by_section(apps, schema_editor):
    node = apps.get_model("brainstorm", "BrainstormNode")
    notes = node.objects.filter(node_type="note").exclude(status="held")
    notes.filter(section__isnull=True).update(status="default")
    notes.filter(section__isnull=False).update(status="accepted")


class Migration(migrations.Migration):
    dependencies = [("brainstorm", "0003_brainstormcanvas_creation_idempotency_key_and_more")]

    operations = [
        migrations.RunPython(normalize_note_status_by_section, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="brainstormnode",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(node_type="title")
                    | models.Q(node_type="note", status="held", section__isnull=True)
                    | models.Q(node_type="note", status="default", section__isnull=True)
                    | models.Q(node_type="note", status="accepted", section__isnull=False)
                ),
                name="brain_note_status_matches_section",
            ),
        ),
    ]
