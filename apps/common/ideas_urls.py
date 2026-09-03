from django.urls import path

from apps.prds import ui_views

app_name = "ideas"

urlpatterns = [
    path("", ui_views.home_page, name="home"),
    path("prds/new/", ui_views.new_prd_page, name="new-prd"),
]
