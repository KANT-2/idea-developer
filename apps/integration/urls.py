from django.urls import path

from . import views

app_name = "integration"

urlpatterns = [
    path("round/", views.round_context, name="round-context"),
]
