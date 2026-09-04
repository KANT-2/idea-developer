from django.db import migrations

# 이름만 바꾼다. db_table("ai_chat_histories")은 그대로 두므로 실제 테이블은 움직이지 않는다.
# AiChatHistory라는 이름이 화면 대화(AiCoachMessage)와 헷갈려 생긴 정리다.


class Migration(migrations.Migration):
    dependencies = [("ai", "0010_seed_coaching_prompt")]

    operations = [
        migrations.RenameModel(
            old_name="AiChatHistory",
            new_name="AiCoachChatLog",
        ),
    ]
