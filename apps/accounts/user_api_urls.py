from django.urls import path

from . import views

app_name = "user_api"

urlpatterns = [
    path("search/", views.user_search, name="search"),
]
