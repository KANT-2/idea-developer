from __future__ import annotations

import json
import logging

from django.test import SimpleTestCase

from apps.common.context import request_id_var
from apps.common.logging import JsonFormatter


def make_record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="apps.ai.worker",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="AI job attempt failed",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class JsonFormatterTests(SimpleTestCase):
    def format(self, record: logging.LogRecord) -> dict:
        return json.loads(JsonFormatter().format(record))

    def test_keeps_standard_fields(self):
        payload = self.format(make_record())

        self.assertEqual(payload["level"], "WARNING")
        self.assertEqual(payload["logger"], "apps.ai.worker")
        self.assertEqual(payload["message"], "AI job attempt failed")
        self.assertIn("timestamp", payload)

    def test_includes_extra_fields(self):
        # extra=로 넘긴 값을 버리면 어떤 작업이 왜 실패했는지 로그만 보고는 알 수 없다.
        payload = self.format(make_record(ai_job_id="job-1", ai_error_code="invalid_output"))

        self.assertEqual(payload["ai_job_id"], "job-1")
        self.assertEqual(payload["ai_error_code"], "invalid_output")

    def test_extra_field_cannot_overwrite_standard_field(self):
        payload = self.format(make_record(logger="스푸핑", timestamp="2000-01-01"))

        self.assertEqual(payload["logger"], "apps.ai.worker")
        self.assertNotEqual(payload["timestamp"], "2000-01-01")

    def test_unserializable_extra_value_does_not_lose_the_log(self):
        payload = self.format(make_record(request=object()))

        self.assertEqual(payload["message"], "AI job attempt failed")
        self.assertIn("object", payload["request"])

    def test_includes_request_id_when_set(self):
        token = request_id_var.set("req-1")
        try:
            payload = self.format(make_record())
        finally:
            request_id_var.reset(token)

        self.assertEqual(payload["request_id"], "req-1")
