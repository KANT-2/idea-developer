from django.db import models

from .exceptions import IntegrationReadOnlyError


class ReadOnlyViewQuerySet(models.QuerySet):
    def _deny_write(self, *args, **kwargs):
        raise IntegrationReadOnlyError("Parent integration VIEWs are read-only.")

    create = _deny_write
    update = _deny_write
    delete = _deny_write
    bulk_create = _deny_write
    bulk_update = _deny_write
    get_or_create = _deny_write
    update_or_create = _deny_write


class ReadOnlyViewModel(models.Model):
    objects = ReadOnlyViewQuerySet.as_manager()

    class Meta:
        abstract = True
        managed = False

    def save(self, *args, **kwargs):
        raise IntegrationReadOnlyError("Parent integration VIEWs are read-only.")

    def delete(self, *args, **kwargs):
        raise IntegrationReadOnlyError("Parent integration VIEWs are read-only.")


class AxUserTeamLoginView(ReadOnlyViewModel):
    user_id = models.BigIntegerField(primary_key=True)
    user_email = models.EmailField(null=True)
    first_name = models.CharField(max_length=150, null=True)
    last_name = models.CharField(max_length=150, null=True)
    role = models.CharField(max_length=50, null=True)
    approval_status = models.CharField(max_length=50, null=True)
    phone_number = models.CharField(max_length=50, null=True)
    is_onboarded = models.BooleanField(null=True)
    profile_image = models.CharField(max_length=500, null=True)
    last_login = models.DateTimeField(null=True)
    is_active = models.BooleanField()
    is_staff = models.BooleanField()
    is_superuser = models.BooleanField()
    is_social_account = models.BooleanField(null=True)
    date_joined = models.DateTimeField(null=True)
    primary_email = models.EmailField(null=True)
    participant_id = models.BigIntegerField(null=True)
    round_id = models.BigIntegerField(null=True)
    display_name_snapshot = models.CharField(max_length=255, null=True)
    team_id = models.BigIntegerField(null=True)
    team_name = models.CharField(max_length=255, null=True)

    class Meta:
        managed = False
        db_table = '"public"."ax_user_team_login_view"'


class UserRoundTeamView(ReadOnlyViewModel):
    participant_id = models.BigIntegerField(primary_key=True)
    user_id = models.BigIntegerField()
    email = models.EmailField(null=True)
    round_id = models.BigIntegerField()
    round_title = models.CharField(max_length=255)
    round_status = models.CharField(max_length=50)
    student_number_snapshot = models.CharField(max_length=100, null=True)
    display_name_snapshot = models.CharField(max_length=255, null=True)
    team_id = models.BigIntegerField()
    team_number = models.IntegerField(null=True)
    team_name = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = '"public"."user_round_team_view"'
