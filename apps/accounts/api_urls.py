from django.urls import path

from . import views

app_name = "accounts_api"

urlpatterns = [
    path("otp/request/", views.request_otp, name="request-otp"),
    path("otp/verify/", views.verify_otp, name="verify-otp"),
]
