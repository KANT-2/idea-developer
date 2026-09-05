from __future__ import annotations

import logging
import time
from importlib import import_module
from urllib.parse import urljoin

from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


def send_prd_participant_added(*, prd_id: int, prd_title: str, user_ids) -> None:
    recipients = _normalize_user_ids(user_ids)
    if not recipients:
        return
    _send(
        user_ids=recipients,
        title="새 PRD에 참여자로 추가되었습니다.",
        message=f"‘{prd_title}’ PRD에 참여자로 추가되었습니다. PRD를 열어 내용을 확인해 주세요.",
        url=_prd_url(prd_id),
    )


def send_prd_comment_created(
    *,
    prd_id: int,
    prd_title: str,
    user_ids,
    comment_preview: str,
    question_prompt: str | None,
) -> None:
    recipients = _normalize_user_ids(user_ids)
    if not recipients:
        return
    preview = " ".join(comment_preview.split())[:160]
    if question_prompt:
        question = " ".join(question_prompt.split())[:100]
        message = f"‘{prd_title}’의 “{question}” 질문에 새 코멘트가 등록되었습니다.\n“{preview}”"
    else:
        message = f"‘{prd_title}’ PRD에 새 코멘트가 등록되었습니다.\n“{preview}”"
    _send(
        user_ids=recipients,
        title="PRD에 새 코멘트가 등록되었습니다.",
        message=message,
        url=_prd_url(prd_id),
    )


def _send(*, user_ids: tuple[int, ...], title: str, message: str, url: str) -> None:
    """Use the parent Slack module when installed; never fail the domain transaction."""
    try:
        slack = import_module("notifications.slack")
    except ModuleNotFoundError:
        logger.info(
            "Parent Slack notification module is unavailable; notification skipped",
            extra={"recipient_count": len(user_ids)},
        )
        return

    max_attempts = max(1, min(int(getattr(settings, "SLACK_DELIVERY_MAX_ATTEMPTS", 3)), 5))
    retry_base_seconds = max(
        0.0,
        min(float(getattr(settings, "SLACK_DELIVERY_RETRY_BASE_SECONDS", 0.5)), 5.0),
    )

    for attempt in range(1, max_attempts + 1):
        try:
            if len(user_ids) == 1:
                slack.send_slack_dm_ax(user_ids[0], title, message, url)
            else:
                slack.send_slack_dm_ax_batch(list(user_ids), title, message, url)
            return
        except Exception:
            if attempt >= max_attempts:
                logger.exception(
                    "Slack notification delivery failed after retries",
                    extra={
                        "recipient_count": len(user_ids),
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                    },
                )
                return
            logger.warning(
                "Slack notification delivery failed; retrying",
                extra={
                    "recipient_count": len(user_ids),
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                },
                exc_info=True,
            )
            time.sleep(retry_base_seconds * (2 ** (attempt - 1)))


def _prd_url(prd_id: int) -> str:
    path = reverse("prd-write-page", kwargs={"prd_id": prd_id})
    base_url = getattr(settings, "SITE_URL", "").strip()
    if not base_url:
        return path
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def _normalize_user_ids(user_ids) -> tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            user_id
            for user_id in user_ids
            if isinstance(user_id, int) and not isinstance(user_id, bool) and user_id > 0
        )
    )
