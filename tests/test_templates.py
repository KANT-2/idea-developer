from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase
from django.urls import resolve

from apps.common.context_processors import session_identity
from apps.integration.repository import ParentUser, UserDisplaySummary


class TemplateContractTests(SimpleTestCase):
    @patch("apps.common.context_processors.get_default_integration_repository")
    def test_session_identity_uses_parent_name_email_and_tutor_role(self, get_repository):
        repository = MagicMock()
        repository.get_user.return_value = ParentUser(
            user_id=2,
            parent_role="tutor",
            approval_status="approved",
            is_active=True,
            is_staff=False,
            is_superuser=False,
            user_email="backup@example.test",
            primary_email="tutor@example.test",
        )
        repository.get_user_summaries.return_value = {
            2: UserDisplaySummary(user_id=2, display_name="김튜터")
        }
        get_repository.return_value = repository
        request = SimpleNamespace(
            user=SimpleNamespace(
                is_authenticated=True,
                external_user_id=2,
                email_snapshot="local@example.test",
            )
        )

        identity = session_identity(request)["session_identity"]

        self.assertEqual(identity["display_name"], "김튜터")
        self.assertEqual(identity["email"], "tutor@example.test")
        self.assertEqual(identity["role_label"], "튜터")

    def test_root_path_is_connected_to_the_entry_redirect(self):
        self.assertEqual(resolve("/").view_name, "root")

    def test_base_exposes_parent_compatible_blocks(self):
        source = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")

        for block in ("extra_head", "breadcrumb", "content", "modals", "extra_js"):
            self.assertIn(f"{{% block {block} %}}", source)
        self.assertIn("bootstrap@5.3.2", source)

    def test_base_shows_the_authenticated_session_identity(self):
        request = SimpleNamespace(
            user=SimpleNamespace(
                is_authenticated=True,
                email_snapshot="member@example.test",
            )
        )

        rendered = get_template("base.html").render(
            {
                "request": request,
                "session_identity": {
                    "display_name": "김아이디어",
                    "email": "member@example.test",
                    "role_label": "수강생",
                },
            }
        )

        self.assertIn("김아이디어", rendered)
        self.assertIn("member@example.test", rendered)
        self.assertIn("수강생", rendered)
        self.assertNotIn("외부 사용자 ID", rendered)

    def test_brainstorm_shell_can_be_rendered_without_browser_jsx(self):
        rendered = get_template("brainstorm/shell.html").render({})

        self.assertIn('id="brainstorm-root"', rendered)
        self.assertNotIn("babel", rendered.lower())
        self.assertNotIn('type="text/babel"', rendered.lower())

    def test_brainstorm_app_polls_incrementally_and_full_syncs_on_reconnect(self):
        source = (Path(settings.BASE_DIR) / "static" / "brainstorm" / "js" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('"events/?cursor="', source)
        self.assertIn('apiBase + "canvas/"', source)
        self.assertIn("response.text()", source)
        self.assertNotIn("response.json()", source)
        self.assertIn('invalidResponse.code = "invalid_response"', source)
        self.assertIn("fullSyncGenerationRef", source)
        self.assertIn("heldNodes.push(updated)", source)
        self.assertIn("function createConnection(nodeA, nodeB)", source)
        self.assertIn("connections.push(connection)", source)
        self.assertIn("function deleteConnection(connection)", source)
        self.assertIn('optimisticId = "pending-"', source)
        self.assertIn("window.ReactDOM.flushSync", source)
        self.assertIn('connection.pending ? " pending"', source)
        self.assertIn('request(apiBase + "canvas/"', source)
        self.assertIn('" 분류 결과"', source)
        self.assertNotIn('"✦ AI 분석"', source)
        self.assertNotIn('"AI 항목 분류"', source)
        self.assertNotIn('runAi("classification")', source)
        self.assertIn('addEventListener("online", reconnect)', source)
        self.assertIn("Math.min(5000, Math.max(2000", source)
        self.assertIn('"/assignee/"', source)
        self.assertIn("state.participants", source)
        self.assertIn('window.ReactDOM.createPortal', source)
        self.assertIn('"섹션 보드"', source)
        self.assertIn('"자유 캔버스"', source)
        self.assertIn('"아이디어 목록"', source)
        self.assertIn('className: "brain-assignee-menu"', source)
        self.assertIn('"담당자 지정"', source)
        self.assertNotIn('h("select", {value: String(node.assignee_id', source)
        self.assertNotIn("PRD 반영 후보", source)
        self.assertIn("var selectedDefaults = [];", source)
        self.assertNotIn("채택 취소", source)
        self.assertIn("function dropHeld(event)", source)
        self.assertIn('closest(".brain-held")', source)
        self.assertNotIn('export/markdown/', source)
        self.assertIn('useState("canvas")', source)
        self.assertIn("var CANVAS_W = 4800", source)
        self.assertIn("Math.max(.3, Math.min(2", source)
        self.assertIn("onWheel: wheelCanvas", source)
        self.assertNotIn("WebSocket", source)
        self.assertIn('onDragStart', source)
        self.assertIn('onDrop', source)
        self.assertNotIn('onDragOver: function (event) { moveNode', source)

    def test_prd_write_screen_exposes_inline_participant_management(self):
        base_dir = Path(settings.BASE_DIR)
        template = (base_dir / "templates" / "prds" / "write.html").read_text(
            encoding="utf-8"
        )
        script = (base_dir / "static" / "prds" / "js" / "write.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('data-participant-search-api=', template)
        self.assertIn('id="manage-participants"', template)
        self.assertIn('id="participant-modal"', template)
        self.assertIn('id="participant-search-form"', template)
        self.assertIn("can_manage_participants", script)
        self.assertIn('method: "DELETE"', script)
        self.assertIn('data-comments-api=', template)
        self.assertIn('id="comment-toggle"', template)
        self.assertIn('id="write-comments-panel"', template)
        self.assertIn('id="comment-form"', template)
        self.assertIn('id="comment-target"', template)
        self.assertIn('id="comment-pagination"', template)
        self.assertIn("can_review_comment", script)
        self.assertIn('data-contributions-api=', template)
        self.assertIn('id="contribution-toggle"', template)
        self.assertIn('id="write-contribution-panel"', template)
        self.assertIn("can_view_contributions", script)

    def test_frontend_has_no_runtime_transpiler_or_tailwind_runtime(self):
        base_dir = Path(settings.BASE_DIR)
        sources = [
            base_dir / "templates" / "base.html",
            base_dir / "templates" / "brainstorm" / "shell.html",
            base_dir / "static" / "brainstorm" / "js" / "app.js",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in sources).lower()
        self.assertNotIn("text/babel", combined)
        self.assertNotIn("tailwindcss.com", combined)
