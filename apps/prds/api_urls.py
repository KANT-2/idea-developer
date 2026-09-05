from django.urls import path

from . import detail_views, history_views, views

app_name = "prd_api"

urlpatterns = [
    path("", views.create_prd, name="create"),
    path("trash/", detail_views.trash_prds, name="trash"),
    path("trash/<int:prd_id>/restore/", detail_views.restore_prd, name="trash-restore"),
    path(
        "trash/<int:prd_id>/delete/",
        detail_views.confirm_prd_deletion,
        name="trash-delete",
    ),
    path("participants/team/", views.current_team_participants, name="current-team"),
    path("participants/search/", views.search_participants, name="participant-search"),
    path("<int:prd_id>/", detail_views.prd_detail, name="detail"),
    path("<int:prd_id>/metadata/", detail_views.prd_metadata, name="metadata"),
    path("<int:prd_id>/delete/", detail_views.delete_prd, name="delete"),
    path(
        "<int:prd_id>/export/markdown/",
        detail_views.export_markdown,
        name="export-markdown",
    ),
    path(
        "<int:prd_id>/questions/<int:question_id>/answer/",
        detail_views.question_answer,
        name="question-answer",
    ),
    path(
        "<int:prd_id>/questions/<int:question_id>/hold/",
        detail_views.question_hold,
        name="question-hold",
    ),
    path("<int:prd_id>/participants/", detail_views.participants, name="participants"),
    path(
        "<int:prd_id>/participants/<int:user_id>/",
        detail_views.participant_item,
        name="participant-item",
    ),
    path("<int:prd_id>/complete/", detail_views.complete_prd, name="complete"),
    path("<int:prd_id>/reopen/", detail_views.reopen_prd, name="reopen"),
    path(
        "<int:prd_id>/contributions/",
        history_views.contribution_results,
        name="contributions",
    ),
    path(
        "<int:prd_id>/contributions/<int:calculation_version>/retry/",
        history_views.retry_contribution,
        name="contribution-retry",
    ),
    path("<int:prd_id>/comments/", detail_views.comments, name="comments"),
    path(
        "<int:prd_id>/comments/<int:comment_id>/",
        detail_views.comment_item,
        name="comment-item",
    ),
    path("<int:prd_id>/ai-usage/", history_views.ai_usage_history, name="ai-usage"),
    path("<int:prd_id>/ai-chats/", history_views.ai_chat_history, name="ai-chats"),
    path(
        "<int:prd_id>/change-history/",
        history_views.change_history,
        name="change-history",
    ),
]
