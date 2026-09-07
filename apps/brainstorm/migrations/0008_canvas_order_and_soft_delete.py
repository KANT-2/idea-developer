from django.db import migrations, models


def initialize_display_order(apps, schema_editor):
    BrainstormCanvas = apps.get_model("brainstorm", "BrainstormCanvas")
    prd_ids = BrainstormCanvas.objects.values_list("prd_id", flat=True).distinct()
    for prd_id in prd_ids.iterator():
        canvas_ids = list(
            BrainstormCanvas.objects.filter(prd_id=prd_id)
            .order_by("-version_number", "-id")
            .values_list("id", flat=True)
        )
        for display_order, canvas_id in enumerate(canvas_ids):
            BrainstormCanvas.objects.filter(pk=canvas_id).update(display_order=display_order)


class Migration(migrations.Migration):
    # PostgreSQL cannot create the following index while the data migration has
    # pending trigger events in the same transaction.
    atomic = False
    dependencies = [("brainstorm", "0007_brainstormnode_held_from_section")]

    operations = [
        migrations.AddField(
            model_name="brainstormcanvas",
            name="display_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="brainstormcanvas",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="brainstormcanvas",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(initialize_display_order, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="brainstormcanvas",
            index=models.Index(
                fields=["prd", "is_deleted", "display_order"],
                name="brain_canvas_active_order_idx",
            ),
        ),
        migrations.AlterModelOptions(
            name="brainstormcanvas",
            options={"ordering": ["display_order", "-version_number", "-id"]},
        ),
    ]
