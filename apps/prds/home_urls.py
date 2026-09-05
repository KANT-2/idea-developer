from django.urls import path

from . import home_views

app_name = "home_api"

urlpatterns = [
    path("", home_views.home, name="home"),
    path("tutor-students/", home_views.tutor_students, name="tutor-students"),
    path("recent-activity/", home_views.recent_activity, name="recent-activity"),
]
