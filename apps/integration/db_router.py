from django.conf import settings


class IntegrationViewRouter:
    """Routes future unmanaged VIEW models and never migrates them."""

    route_app_label = "integration"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.route_app_label:
            return "integration" if "integration" in settings.DATABASES else "default"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.route_app_label:
            return None
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.route_app_label:
            return False
        return None
