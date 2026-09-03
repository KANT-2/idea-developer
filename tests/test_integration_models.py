import importlib

from django.db import migrations
from django.test import SimpleTestCase

from apps.integration.exceptions import IntegrationReadOnlyError
from apps.integration.models import AxUserTeamLoginView, UserRoundTeamView


class IntegrationViewModelTests(SimpleTestCase):
    def test_models_are_unmanaged_and_schema_qualified(self):
        self.assertFalse(AxUserTeamLoginView._meta.managed)
        self.assertFalse(UserRoundTeamView._meta.managed)
        self.assertEqual(
            AxUserTeamLoginView._meta.db_table,
            '"public"."ax_user_team_login_view"',
        )
        self.assertEqual(
            UserRoundTeamView._meta.db_table,
            '"public"."user_round_team_view"',
        )

    def test_model_instance_writes_are_denied_before_database_access(self):
        with self.assertRaises(IntegrationReadOnlyError):
            AxUserTeamLoginView(user_id=7).save()
        with self.assertRaises(IntegrationReadOnlyError):
            UserRoundTeamView(participant_id=10).delete()

    def test_queryset_writes_are_denied_before_database_access(self):
        with self.assertRaises(IntegrationReadOnlyError):
            UserRoundTeamView.objects.update(team_id=999)
        with self.assertRaises(IntegrationReadOnlyError):
            UserRoundTeamView.objects.create(participant_id=10)

    def test_state_migration_contains_no_view_ddl(self):
        migration_module = importlib.import_module("apps.integration.migrations.0001_initial")

        self.assertTrue(
            all(
                operation.options.get("managed") is False
                for operation in migration_module.Migration.operations
                if isinstance(operation, migrations.CreateModel)
            )
        )
        self.assertFalse(
            any(
                isinstance(operation, migrations.RunSQL)
                for operation in migration_module.Migration.operations
            )
        )
