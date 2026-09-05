from datetime import timedelta

from django.db import migrations
from django.db.models import Max


EMPTY_PROMPT = "[질문 내용 없음]"
EMPTY_RESPONSE = "[응답 내용 없음]"


def consolidate_chat_logs(apps, schema_editor):
    ChatLog = apps.get_model("ai", "AiCoachChatLog")
    Conversation = apps.get_model("ai", "AiCoachConversation")
    Message = apps.get_model("ai", "AiCoachMessage")
    database = schema_editor.connection.alias

    for log in ChatLog.objects.using(database).order_by("created_at", "id").iterator():
        mirrored = False
        assistants = Message.objects.using(database).filter(
            conversation__prd_id=log.prd_id,
            conversation__user_id=log.user_id,
            role="assistant",
            content=log.response,
        )
        for assistant in assistants.iterator():
            if (
                Message.objects.using(database)
                .filter(
                    conversation_id=assistant.conversation_id,
                    sequence__lt=assistant.sequence,
                    role="user",
                    content=log.prompt,
                )
                .exists()
            ):
                mirrored = True
                break
        if mirrored:
            continue

        conversation = (
            Conversation.objects.using(database)
            .filter(prd_id=log.prd_id, user_id=log.user_id, section_id__isnull=True)
            .first()
        )
        if conversation is None:
            conversation = Conversation.objects.using(database).create(
                prd_id=log.prd_id,
                user_id=log.user_id,
                expires_at=log.created_at + timedelta(days=30),
            )
        elif conversation.expires_at < log.created_at + timedelta(days=30):
            Conversation.objects.using(database).filter(pk=conversation.pk).update(
                expires_at=log.created_at + timedelta(days=30)
            )
        next_sequence = (
            Message.objects.using(database)
            .filter(conversation_id=conversation.id)
            .aggregate(value=Max("sequence"))["value"]
            or 0
        ) + 1
        user_message = Message.objects.using(database).create(
            conversation_id=conversation.id,
            sequence=next_sequence,
            role="user",
            content=log.prompt or EMPTY_PROMPT,
        )
        assistant_message = Message.objects.using(database).create(
            conversation_id=conversation.id,
            sequence=next_sequence + 1,
            role="assistant",
            content=log.response or EMPTY_RESPONSE,
        )
        Message.objects.using(database).filter(
            id__in=(user_message.id, assistant_message.id)
        ).update(created_at=log.created_at)


def restore_flat_chat_logs(apps, schema_editor):
    ChatLog = apps.get_model("ai", "AiCoachChatLog")
    Message = apps.get_model("ai", "AiCoachMessage")
    database = schema_editor.connection.alias

    assistants = (
        Message.objects.using(database)
        .filter(role="assistant")
        .select_related("conversation")
        .order_by("created_at", "id")
    )
    for assistant in assistants.iterator():
        user_messages = Message.objects.using(database).filter(
            conversation_id=assistant.conversation_id,
            role="user",
            sequence__lt=assistant.sequence,
        )
        if assistant.job_id:
            user_messages = user_messages.filter(job_id=assistant.job_id)
        user_message = user_messages.order_by("-sequence").first()
        log = ChatLog.objects.using(database).create(
            prd_id=assistant.conversation.prd_id,
            user_id=assistant.conversation.user_id,
            prompt=user_message.content if user_message else "",
            response=assistant.content,
        )
        ChatLog.objects.using(database).filter(pk=log.pk).update(created_at=assistant.created_at)


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0016_seed_prd_apply_prompt"),
    ]

    operations = [
        migrations.RunPython(consolidate_chat_logs, restore_flat_chat_logs),
        migrations.DeleteModel(name="AiCoachChatLog"),
    ]
