from django.urls import path

from . import views

app_name = "prd_api"

urlpatterns = [
    path("", views.create_prd, name="create"),
    path("participants/team/", views.current_team_participants, name="current-team"),
    path("participants/search/", views.search_participants, name="participant-search"),
]
