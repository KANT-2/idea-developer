import uuid

from django.db import migrations, models
import django.db.models.deletion


def populate_node_lineages(apps, schema_editor):
    BrainstormNode = apps.get_model("brainstorm", "BrainstormNode")
    for node_id in BrainstormNode.objects.values_list("pk", flat=True).iterator():
        BrainstormNode.objects.filter(pk=node_id).update(lineage_id=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ("brainstorm", "0004_normalize_note_status_by_section"),
    ]

    operations = [
        migrations.AlterField(
            model_name="brainstormcanvas",
            name="prd",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="brainstorm_canvases",
                to="prds.prd",
            ),
        ),
        migrations.AddField(
            model_name="brainstormcanvas",
            name="version_number",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="brainstormcanvas",
            name="source_canvas",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="derived_canvases",
                to="brainstorm.brainstormcanvas",
            ),
        ),
        migrations.AddField(
            model_name="brainstormcanvas",
            name="created_by_user_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="brainstormnode",
            name="lineage_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RunPython(populate_node_lineages, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="brainstormnode",
            name="lineage_id",
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False),
        ),
        migrations.AddIndex(
            model_name="brainstormcanvas",
            index=models.Index(
                fields=["prd", "-version_number"],
                name="brain_canvas_prd_ver_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="brainstormcanvas",
            constraint=models.UniqueConstraint(
                fields=("prd", "version_number"),
                name="uniq_brain_canvas_prd_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="brainstormcanvas",
            constraint=models.UniqueConstraint(
                condition=models.Q(("creation_idempotency_key", ""), _negated=True),
                fields=("prd", "creation_idempotency_key"),
                name="uniq_brain_canvas_request",
            ),
        ),
        migrations.AddConstraint(
            model_name="brainstormcanvas",
            constraint=models.CheckConstraint(
                condition=models.Q(("version_number__gte", 1)),
                name="brain_canvas_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="brainstormcanvas",
            constraint=models.CheckConstraint(
                condition=models.Q(("created_by_user_id__isnull", True))
                | models.Q(("created_by_user_id__gt", 0)),
                name="brain_canvas_creator_positive",
            ),
        ),
        migrations.AlterModelOptions(
            name="brainstormcanvas",
            options={"ordering": ["-version_number", "-id"]},
        ),
    ]
