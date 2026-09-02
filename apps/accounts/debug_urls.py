from django.urls import path

from . import views

app_name = "accounts_debug"

urlpatterns = [
    path("login/", views.debug_login, name="login"),
]
