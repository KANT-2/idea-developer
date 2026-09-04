from django.urls import path

from . import ai_views, views

app_name = "brainstorm_api"

urlpatterns = [
    path("canvas/", views.canvas, name="canvas"),
    path("boards/", views.canvas_versions, name="canvas-versions"),
    path("export/markdown/", views.export_markdown, name="export-markdown"),
    path("nodes/", views.create_node, name="node-create"),
    path("nodes/<uuid:node_id>/content/", views.node_content, name="node-content"),
    path("nodes/<uuid:node_id>/assignee/", views.node_assignee, name="node-assignee"),
    path("nodes/<uuid:node_id>/status/", views.node_status, name="node-status"),
    path("nodes/<uuid:node_id>/position/", views.node_position, name="node-position"),
    path("nodes/<uuid:node_id>/", views.node_delete, name="node-delete"),
    path("nodes/<uuid:node_id>/restore/", views.node_restore, name="node-restore"),
    path("connections/", views.create_connection, name="connection-create"),
    path(
        "connections/<uuid:connection_id>/",
        views.connection_delete,
        name="connection-delete",
    ),
    path("viewport/", views.viewport, name="viewport"),
    path("auto-layout/", views.auto_layout, name="auto-layout"),
    path("events/", views.events, name="events"),
    path("changes/", views.change_history, name="change-history"),
    path("ai/analysis/", ai_views.request_analysis, name="ai-analysis"),
    path("ai/classification/", ai_views.request_classification, name="ai-classification"),
    path(
        "ai/classification/apply/",
        ai_views.apply_classification,
        name="ai-classification-apply",
    ),
    path(
        "ai/prd-apply/preview/",
        ai_views.request_prd_apply_preview,
        name="ai-prd-apply-preview",
    ),
    path(
        "ai/prd-apply/apply/",
        ai_views.apply_prd_preview,
        name="ai-prd-apply-apply",
    ),
    path("ai/jobs/<uuid:job_id>/", ai_views.job_status, name="ai-job"),
    path("ai/jobs/<uuid:job_id>/cancel/", ai_views.cancel_job, name="ai-job-cancel"),
    path("ai/jobs/<uuid:job_id>/retry/", ai_views.retry_job, name="ai-job-retry"),
]
