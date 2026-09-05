from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from apps.common.slack_notifications import (
    send_prd_comment_created,
    send_prd_participant_added,
)


@override_settings(SITE_URL="https://service.example")
class SlackNotificationGatewayTests(SimpleTestCase):
    @patch("apps.common.slack_notifications.import_module")
    def test_multiple_participants_use_parent_batch_sender(self, import_module):
        slack = Mock()
        import_module.return_value = slack

        send_prd_participant_added(
            prd_id=12,
            prd_title="새 서비스",
            user_ids=(8, 9, 8),
        )

        slack.send_slack_dm_ax_batch.assert_called_once_with(
            [8, 9],
            "새 PRD에 참여자로 추가되었습니다.",
            "‘새 서비스’ PRD에 참여자로 추가되었습니다. PRD를 열어 내용을 확인해 주세요.",
            "https://service.example/ideas/prds/12/",
        )
        slack.send_slack_dm_ax.assert_not_called()

    @patch("apps.common.slack_notifications.import_module")
    def test_single_comment_recipient_uses_parent_single_sender(self, import_module):
        slack = Mock()
        import_module.return_value = slack

        send_prd_comment_created(
            prd_id=3,
            prd_title="PRD",
            user_ids=(7,),
            comment_preview="질문을 더 구체적으로 작성해 주세요.",
            question_prompt="핵심 사용자는 누구인가요?",
        )

        args = slack.send_slack_dm_ax.call_args.args
        self.assertEqual(args[0], 7)
        self.assertIn("핵심 사용자는 누구인가요?", args[2])
        self.assertEqual(args[3], "https://service.example/ideas/prds/3/")

    @patch(
        "apps.common.slack_notifications.import_module",
        side_effect=ModuleNotFoundError,
    )
    def test_missing_parent_module_is_a_safe_noop(self, _import_module):
        send_prd_participant_added(prd_id=1, prd_title="PRD", user_ids=(7,))

    @override_settings(
        SLACK_DELIVERY_MAX_ATTEMPTS=3,
        SLACK_DELIVERY_RETRY_BASE_SECONDS=0.25,
    )
    @patch("apps.common.slack_notifications.time.sleep")
    @patch("apps.common.slack_notifications.import_module")
    def test_transient_failure_is_retried_until_success(self, import_module, sleep):
        slack = Mock()
        slack.send_slack_dm_ax.side_effect = [RuntimeError("temporary"), None]
        import_module.return_value = slack

        send_prd_participant_added(prd_id=1, prd_title="PRD", user_ids=(7,))

        self.assertEqual(slack.send_slack_dm_ax.call_count, 2)
        sleep.assert_called_once_with(0.25)

    @override_settings(
        SLACK_DELIVERY_MAX_ATTEMPTS=3,
        SLACK_DELIVERY_RETRY_BASE_SECONDS=0,
    )
    @patch("apps.common.slack_notifications.time.sleep")
    @patch("apps.common.slack_notifications.import_module")
    def test_permanent_failure_stops_after_limit_without_raising(
        self,
        import_module,
        sleep,
    ):
        slack = Mock()
        slack.send_slack_dm_ax.side_effect = RuntimeError("still unavailable")
        import_module.return_value = slack

        send_prd_participant_added(prd_id=1, prd_title="PRD", user_ids=(7,))

        self.assertEqual(slack.send_slack_dm_ax.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
