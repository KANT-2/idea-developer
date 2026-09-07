from django.db import migrations, models


def populate_introduced_versions(apps, schema_editor):
    BrainstormNode = apps.get_model("brainstorm", "BrainstormNode")

    lineage_versions = {}
    nodes = (
        BrainstormNode.objects.select_related("canvas")
        .order_by("canvas__prd_id", "lineage_id", "canvas__version_number", "created_at", "id")
        .iterator()
    )
    for node in nodes:
        key = (node.canvas.prd_id, node.lineage_id)
        introduced_version = lineage_versions.setdefault(key, node.canvas.version_number)
        if node.introduced_in_version != introduced_version:
            BrainstormNode.objects.filter(pk=node.pk).update(
                introduced_in_version=introduced_version
            )


class Migration(migrations.Migration):

    dependencies = [
        ("brainstorm", "0005_canvas_versions"),
    ]

    operations = [
        migrations.AddField(
            model_name="brainstormnode",
            name="introduced_in_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunPython(populate_introduced_versions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="brainstormnode",
            constraint=models.CheckConstraint(
                condition=models.Q(("introduced_in_version__gte", 1)),
                name="brain_node_introduced_ver_positive",
            ),
        ),
    ]
