from types import SimpleNamespace

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from apps.integration.context import StandaloneSessionContextResolver


class StandaloneSessionContextResolverTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")
        self.request.session = {
            "participant_id": 10,
            "team_id": 20,
            "user_role": "member",
        }
        self.resolver = StandaloneSessionContextResolver()

    def test_maps_authenticated_external_identity_and_session_context(self):
        self.request.user = SimpleNamespace(
            is_authenticated=True,
            external_user_id=7,
            is_staff=False,
            is_superuser=False,
        )

        context = self.resolver.resolve(self.request, round_id=3)

        self.assertEqual(context.external_user_id, 7)
        self.assertEqual(context.round_id, 3)
        self.assertEqual(context.participant_id, 10)
        self.assertEqual(context.team_id, 20)

    def test_rejects_anonymous_user(self):
        self.request.user = SimpleNamespace(is_authenticated=False)

        with self.assertRaises(PermissionDenied):
            self.resolver.resolve(self.request, round_id=3)

    def test_rejects_user_without_external_mapping(self):
        self.request.user = SimpleNamespace(
            is_authenticated=True,
            is_staff=False,
            is_superuser=False,
        )

        with self.assertRaises(PermissionDenied):
            self.resolver.resolve(self.request, round_id=3)
