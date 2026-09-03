from django.test import SimpleTestCase


class HealthCheckTests(SimpleTestCase):
    def test_health_check_uses_common_response_envelope(self):
        response = self.client.get("/api/v1/health/", HTTP_X_REQUEST_ID="health-test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "health-test")
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "data": {
                    "status": "ok",
                    "service": "idea-developer",
                    "api_version": "v1",
                },
                "error": None,
                "meta": {"request_id": "health-test"},
            },
        )

    def test_health_check_rejects_non_get_requests(self):
        response = self.client.post("/api/v1/health/")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"]["code"], "method_not_allowed")

    def test_unknown_api_uses_common_error_envelope(self):
        response = self.client.get("/api/v1/not-found/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")
