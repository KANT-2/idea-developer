from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.ai import views as ai_views
from apps.brainstorm import views as brainstorm_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("api/v1/auth/", include("apps.accounts.api_urls")),
    path("api/v1/users/", include("apps.accounts.user_api_urls")),
    path("api/v1/prds/", include("apps.prds.api_urls")),
    path(
        "api/v1/prds/<int:prd_id>/ai/",
        include("apps.ai.api_urls"),
    ),
    path(
        "api/v1/prds/<int:prd_id>/brainstorm/",
        include("apps.brainstorm.api_urls"),
    ),
    path("api/v1/home/", include("apps.prds.home_urls")),
    path("api/v1/", include("apps.common.urls")),
    path("integration/", include("apps.integration.urls")),
    path(
        "ideas/prds/<int:prd_id>/brainstorm/",
        brainstorm_views.brainstorm_page,
        name="brainstorm-page",
    ),
    path(
        "ideas/prds/<int:prd_id>/",
        ai_views.prd_write_page,
        name="prd-write-page",
    ),
    path("ideas/", include("apps.common.ideas_urls")),
]

if settings.DEBUG:
    urlpatterns.append(path("accounts/dev/", include("apps.accounts.debug_urls")))

handler404 = "apps.common.views.api_not_found"
