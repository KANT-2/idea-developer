from django.urls import path

from . import views

app_name = "ai_api"

urlpatterns = [
    path("conversation/", views.conversation, name="conversation"),
    path("chat/", views.request_chat, name="request-chat"),
    path("drafts/", views.request_draft, name="request-draft"),
    path("evaluation/", views.latest_evaluation, name="latest-evaluation"),
    path("evaluation/run/", views.request_evaluation, name="request-evaluation"),
    path("drafts/<uuid:job_id>/apply/", views.apply_draft, name="apply-draft"),
    path("chat/<uuid:job_id>/apply/", views.apply_chat_proposal, name="apply-chat-proposal"),
    path("jobs/<uuid:job_id>/", views.job_status, name="job-status"),
    path("jobs/<uuid:job_id>/cancel/", views.cancel_job, name="cancel-job"),
    path("jobs/<uuid:job_id>/retry/", views.retry_job, name="retry-job"),
]
