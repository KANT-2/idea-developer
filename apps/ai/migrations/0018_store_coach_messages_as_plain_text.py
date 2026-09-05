from django.db import migrations


def _decode_previous_storage(value):
    # quote=False HTML escaping produced only these entities.  Restrict the
    # conversion so unrelated named entities such as &copy; keep their meaning.
    return (value or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def restore_plain_text_messages(apps, schema_editor):
    Message = apps.get_model("ai", "AiCoachMessage")
    database = schema_editor.connection.alias
    pending = []
    for message in Message.objects.using(database).only("id", "content").iterator(
        chunk_size=500
    ):
        decoded = _decode_previous_storage(message.content)
        if decoded != message.content:
            message.content = decoded
            pending.append(message)
        if len(pending) >= 500:
            Message.objects.using(database).bulk_update(pending, ["content"])
            pending.clear()
    if pending:
        Message.objects.using(database).bulk_update(pending, ["content"])


def restore_escaped_messages(apps, schema_editor):
    Message = apps.get_model("ai", "AiCoachMessage")
    database = schema_editor.connection.alias
    pending = []
    for message in Message.objects.using(database).only("id", "content").iterator(
        chunk_size=500
    ):
        encoded = (message.content or "").replace("&", "&amp;").replace("<", "&lt;").replace(
            ">", "&gt;"
        )
        if encoded != message.content:
            message.content = encoded
            pending.append(message)
        if len(pending) >= 500:
            Message.objects.using(database).bulk_update(pending, ["content"])
            pending.clear()
    if pending:
        Message.objects.using(database).bulk_update(pending, ["content"])


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0017_consolidate_coach_chat_storage"),
    ]

    operations = [
        migrations.RunPython(restore_plain_text_messages, restore_escaped_messages),
    ]
