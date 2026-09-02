from django.urls import path

from apps.accounts import views

app_name = "ideas"

urlpatterns = [path("", views.session_home, name="home")]
