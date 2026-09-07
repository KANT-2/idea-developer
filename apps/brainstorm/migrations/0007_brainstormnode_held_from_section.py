from django.db import migrations, models
import django.db.models.deletion


def populate_held_origins(apps, schema_editor):
    BrainstormNode = apps.get_model("brainstorm", "BrainstormNode")
    BrainstormChangeLog = apps.get_model("brainstorm", "BrainstormChangeLog")
    PrdSection = apps.get_model("prds", "PrdSection")

    held_nodes = BrainstormNode.objects.filter(status="held").select_related("canvas")
    for node in held_nodes.iterator():
        section_id = None
        change = (
            BrainstormChangeLog.objects.filter(
                canvas_id=node.canvas_id,
                target_type="node",
                target_id=str(node.pk),
                action="node_status_updated",
            )
            .order_by("-created_at", "-id")
            .first()
        )
        if change:
            section_id = (change.before_data or {}).get("section_id")
        if not section_id:
            section_id = (
                BrainstormNode.objects.filter(
                    canvas__prd_id=node.canvas.prd_id,
                    lineage_id=node.lineage_id,
                    canvas__version_number__lt=node.canvas.version_number,
                    section_id__isnull=False,
                )
                .order_by("-canvas__version_number", "-created_at")
                .values_list("section_id", flat=True)
                .first()
            )
        if section_id and PrdSection.objects.filter(
            pk=section_id,
            prd_id=node.canvas.prd_id,
            is_deleted=False,
        ).exists():
            BrainstormNode.objects.filter(pk=node.pk).update(
                held_from_section_id=section_id
            )


class Migration(migrations.Migration):

    dependencies = [
        ("brainstorm", "0006_brainstormnode_introduced_in_version"),
        ("prds", "0013_participant_comment_versions"),
    ]

    operations = [
        migrations.AddField(
            model_name="brainstormnode",
            name="held_from_section",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="prds.prdsection",
            ),
        ),
        migrations.RunPython(populate_held_origins, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="brainstormnode",
            constraint=models.CheckConstraint(
                condition=models.Q(("status", "held"))
                | models.Q(("held_from_section__isnull", True)),
                name="brain_hold_origin_only_while_held",
            ),
        ),
    ]
