import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import LocalUserMapping
from apps.common.middleware import ApiExceptionMiddleware
from apps.common.views import server_error


class UiNavigationIntegrationTests(TestCase):
    def test_root_sends_anonymous_user_to_login_with_safe_home_next(self):
        response = self.client.get("/")

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('ideas:home')}",
            fetch_redirect_response=False,
        )

    def test_protected_pages_preserve_the_requested_internal_destination(self):
        for destination in (reverse("ideas:home"), reverse("ideas:new-prd")):
            with self.subTest(destination=destination):
                response = self.client.get(destination)
                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={destination}",
                    fetch_redirect_response=False,
                )

    def test_authenticated_root_home_and_new_prd_navigation_render(self):
        user = LocalUserMapping.objects.create_user(901, "navigation@example.test")
        self.client.force_login(user)

        root = self.client.get("/")
        self.assertRedirects(root, reverse("ideas:home"), fetch_redirect_response=False)

        home = self.client.get(reverse("ideas:home"))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, f'href="{reverse("ideas:new-prd")}"')

        new_prd = self.client.get(reverse("ideas:new-prd"))
        self.assertEqual(new_prd.status_code, 200)
        self.assertContains(new_prd, 'id="new-prd-form"')

    def test_unknown_page_is_a_recoverable_html_screen_but_unknown_api_is_json(self):
        page = self.client.get("/ideas/not-a-real-page/")
        self.assertEqual(page.status_code, 404)
        self.assertTrue(page["Content-Type"].startswith("text/html"))
        self.assertContains(page, "페이지를 찾을 수 없습니다.", status_code=404)
        self.assertContains(page, "홈으로", status_code=404)

        api = self.client.get("/api/v1/not-a-real-endpoint/")
        self.assertEqual(api.status_code, 404)
        self.assertTrue(api["Content-Type"].startswith("application/json"))
        self.assertEqual(api.json()["error"]["code"], "not_found")

    @override_settings(DEBUG=True)
    def test_debug_mode_does_not_expose_the_technical_404_screen(self):
        response = self.client.get("/ideas/not-a-real-page/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "페이지를 찾을 수 없습니다.", status_code=404)
        self.assertNotContains(response, "Using the URLconf", status_code=404)

    def test_fetch_clients_guard_against_non_json_and_network_failures(self):
        base = Path(settings.BASE_DIR)
        sources = {
            "home": (base / "static/prds/js/home.js").read_text(encoding="utf-8"),
            "new": (base / "static/prds/js/new.js").read_text(encoding="utf-8"),
            "write": (base / "static/prds/js/write.js").read_text(encoding="utf-8"),
            "login": (base / "static/accounts/js/login.js").read_text(encoding="utf-8"),
            "brainstorm": (base / "static/brainstorm/js/api-client.js").read_text(encoding="utf-8"),
        }

        for name, source in sources.items():
            with self.subTest(client=name):
                self.assertIn("서버에 연결하지 못했습니다", source)
                if name == "brainstorm":
                    self.assertIn("response.text()", source)
                    self.assertIn("JSON.parse(body)", source)
                else:
                    self.assertIn("content-type", source)

    def test_unhandled_api_exception_is_json_and_page_500_is_recoverable(self):
        factory = RequestFactory()
        api_request = factory.get("/api/v1/forced-error/")
        api_request.request_id = "request-500"

        def raise_error(_request):
            raise RuntimeError("sensitive internal detail")

        with self.assertLogs("apps.common.middleware", level="ERROR"):
            api_response = ApiExceptionMiddleware(raise_error)(api_request)
        self.assertEqual(api_response.status_code, 500)
        self.assertEqual(json.loads(api_response.content)["error"]["code"], "internal_error")
        self.assertNotIn("sensitive internal detail", api_response.content.decode())

        page_request = factory.get("/broken-page/")
        page_request.user = AnonymousUser()
        page_response = server_error(page_request)
        self.assertEqual(page_response.status_code, 500)
        self.assertIn("다시 시도", page_response.content.decode())
