from django.urls import path

from . import views

app_name = "brainstorm_api"

urlpatterns = [
    path("canvas/", views.canvas, name="canvas"),
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
]
