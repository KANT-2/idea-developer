from django.urls import path

from . import views

app_name = "common"

urlpatterns = [
    path("health/", views.health, name="health"),
]
