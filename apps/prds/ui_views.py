from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.views.decorators.http import require_GET


@login_required
@require_GET
def home_page(request):
    try:
        home_api_url = reverse("home_api:home")
        tutor_students_api_url = reverse("home_api:tutor-students")
        recent_activity_api_url = reverse("home_api:recent-activity")
        trash_api_url = reverse("prd_api:trash")
        delete_api_url_template = reverse("prd_api:delete", args=[0])
    except NoReverseMatch:
        # Minimal test/development URLConfs may mount only the product pages.
        home_api_url = "/api/v1/home/"
        tutor_students_api_url = "/api/v1/home/tutor-students/"
        recent_activity_api_url = "/api/v1/home/recent-activity/"
        trash_api_url = "/api/v1/prds/trash/"
        delete_api_url_template = "/api/v1/prds/0/delete/"
    return render(
        request,
        "prds/home.html",
        {
            "home_api_url": home_api_url,
            "tutor_students_api_url": tutor_students_api_url,
            "recent_activity_api_url": recent_activity_api_url,
            "new_prd_url": reverse("ideas:new-prd"),
            "trash_api_url": trash_api_url,
            "delete_api_url_template": delete_api_url_template,
        },
    )


@login_required
@require_GET
def new_prd_page(request):
    return render(
        request,
        "prds/new.html",
        {
            "create_api_url": reverse("prd_api:create"),
            "team_api_url": reverse("prd_api:current-team"),
            "search_api_url": reverse("prd_api:participant-search"),
        },
    )
