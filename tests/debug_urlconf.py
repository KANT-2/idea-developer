from django.urls import include, path

urlpatterns = [
    path("accounts/", include("apps.accounts.urls")),
    path("accounts/dev/", include("apps.accounts.debug_urls")),
    path("ideas/", include("apps.common.ideas_urls")),
]
