from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.common.urls")),
    path("integration/", include("apps.integration.urls")),
]

handler404 = "apps.common.views.api_not_found"
