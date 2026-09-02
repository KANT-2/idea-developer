from django.contrib.auth.base_user import BaseUserManager


class LocalUserMappingManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, external_user_id, email_snapshot="", **extra_fields):
        user = self.model(
            external_user_id=external_user_id,
            email_snapshot=self.normalize_email(email_snapshot),
            **extra_fields,
        )
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, *args, **kwargs):
        raise ValueError("Local mappings cannot be promoted to local superusers.")
