from django.conf import settings


def runtime_settings(request):
    return {
        "react_cdn_url": settings.REACT_CDN_URL,
        "react_dom_cdn_url": settings.REACT_DOM_CDN_URL,
        "polling_interval_ms": settings.POLLING_INTERVAL_MS,
    }
