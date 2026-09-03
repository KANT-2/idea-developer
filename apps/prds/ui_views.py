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
    except NoReverseMatch:
        # Minimal test/development URLConfs may mount only the product pages.
        home_api_url = "/api/v1/home/"
    return render(
        request,
        "prds/home.html",
        {
            "home_api_url": home_api_url,
            "new_prd_url": reverse("ideas:new-prd"),
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
