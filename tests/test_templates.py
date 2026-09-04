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
        self.assertNotIn("회차·팀", rendered)
        self.assertNotIn("/integration/round/", rendered)

    def test_home_separates_my_prds_and_viewer_prds(self):
        base_dir = Path(settings.BASE_DIR)
        template = (base_dir / "templates" / "prds" / "home.html").read_text(encoding="utf-8")
        script = (base_dir / "static" / "prds" / "js" / "home.js").read_text(encoding="utf-8")

        self.assertIn('data-scope="mine"', template)
        self.assertIn('data-scope="viewer"', template)
        self.assertIn("뷰어로 참여한 PRD", template)
        self.assertIn('id="home-weekly-activity"', template)
        self.assertIn('id="home-recent-activity"', template)
        self.assertIn('id="recent-activity-more"', template)
        self.assertIn('id="recent-activity-modal"', template)
        self.assertIn('class="home-trash-icon"', template)
        self.assertIn('id="home-delete-confirm-modal"', template)
        self.assertIn("prd-card-menu", script)
        self.assertIn("prd-card-brainstorm", script)
        self.assertIn("pendingDeletion.version", script)
        self.assertIn("data-recent-activity-api-url=", template)
        self.assertIn('scope: "mine"', script)
        self.assertIn("state.scope", script)
        self.assertIn("renderActivity(data)", script)
        self.assertIn("fetchRecentActivity(page)", script)

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
        self.assertIn("window.ReactDOM.createPortal", source)
        self.assertIn('"섹션 보드"', source)
        self.assertIn('"자유 캔버스"', source)
        self.assertIn('"아이디어 목록"', source)
        self.assertIn('className: "brain-assignee-menu"', source)
        self.assertIn('"담당자 지정"', source)
        self.assertNotIn('h("select", {value: String(node.assignee_id', source)
        selected_actions = source.split(
            'selected && canEdit ? h("div", {className: "brain-note-actions"', 1
        )[1].split(") : null);", 1)[0]
        self.assertNotIn("editNode(node)", selected_actions)
        self.assertIn('"보류"', selected_actions)
        self.assertIn("assigneeButton(node)", selected_actions)
        css = (
            Path(settings.BASE_DIR) / "static" / "brainstorm" / "css" / "brainstorm.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".brain-note-actions{min-width:270px;flex-wrap:nowrap}", css)
        self.assertNotIn("PRD 반영 후보", source)
        self.assertIn("var selectedDefaults = [];", source)
        self.assertNotIn("채택 취소", source)
        self.assertIn("function dropHeld(event)", source)
        self.assertIn('closest(".brain-held")', source)
        self.assertIn("heldExpandedPair", source)
        self.assertIn('className: "brain-held-toggle"', source)
        self.assertIn('"aria-expanded": heldExpanded', source)
        self.assertIn('heldExpanded ? "접기" : "펼치기"', source)
        self.assertNotIn("export/markdown/", source)
        self.assertIn('useState("canvas")', source)
        self.assertIn("var CANVAS_W = 4800", source)
        self.assertIn("Math.max(.3, Math.min(2", source)
        self.assertIn("onWheel: wheelCanvas", source)
        self.assertNotIn("WebSocket", source)
        self.assertIn("onDragStart", source)
        self.assertIn("onDrop", source)
        self.assertNotIn("onDragOver: function (event) { moveNode", source)

    def test_prd_write_screen_exposes_inline_participant_management(self):
        base_dir = Path(settings.BASE_DIR)
        template = (base_dir / "templates" / "prds" / "write.html").read_text(encoding="utf-8")
        script = (base_dir / "static" / "prds" / "js" / "write.js").read_text(encoding="utf-8")
        stylesheet = (base_dir / "static" / "prds" / "css" / "write.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("data-participant-search-api=", template)
        self.assertIn('id="manage-participants"', template)
        self.assertIn('id="participant-modal"', template)
        self.assertIn('id="participant-search-form"', template)
        self.assertIn("can_manage_participants", script)
        self.assertIn('method: "DELETE"', script)
        self.assertIn("data-comments-api=", template)
        self.assertIn('id="comment-toggle"', template)
        self.assertIn('id="write-comments-panel"', template)
        self.assertIn('id="comment-form"', template)
        self.assertIn('id="comment-target"', template)
        self.assertIn('id="comment-pagination"', template)
        self.assertIn("can_review_comment", script)
        self.assertIn("data-contributions-api=", template)
        self.assertIn('id="contribution-toggle"', template)
        self.assertIn('id="write-contribution-panel"', template)
        self.assertIn("can_view_contributions", script)
        self.assertNotIn('"✦ AI 초안"', script)
        self.assertIn("write-question-group", script)
        self.assertIn("write-question-list-intro", script)
        self.assertIn("질문 리스트로 보기", template)
        self.assertIn('id="save-all-answers"', template)
        self.assertIn("saveAllAnswers", script)
        self.assertIn('"저장"', script)
        self.assertNotIn("개별 저장 또는 전체 저장", script)
        self.assertNotIn("이 질문 저장", script)
        self.assertIn("bi-lightbulb-fill brainstorm-launch-icon", template)
        self.assertIn("세 관점을 모두 진단합니다", template)
        self.assertIn('const evaluationPersonas = ["pm", "engineering", "investor"]', script)
        self.assertIn("Promise.allSettled(evaluationPersonas.map", script)
        self.assertIn("data.jobs?.[persona]", script)
        self.assertIn("let activeSectionId = undefined;", script)
        self.assertIn("activeSectionId === undefined && data.sections.length", script)
        self.assertNotIn("activeSectionId === null && data.sections.length", script)
        self.assertIn('"question-hold-button"', script)
        self.assertIn('"/hold/"', script)
        self.assertIn("!question.is_held", script)
        self.assertIn('contentType.includes("application/json")', script)
        self.assertIn('"alert write-alert alert-"', script)
        self.assertIn('"alert write-alert d-none"', script)
        self.assertIn("data-export-api=", template)
        self.assertIn('id="prd-status-control"', template)
        self.assertIn('id="prd-status-picker"', template)
        self.assertIn('data-prd-status-option="in_progress"', template)
        self.assertIn("changePrdStatus", script)
        self.assertIn('id="write-deadline-input"', template)
        self.assertIn('id="prd-settings-button"', template)
        self.assertIn('id="prd-settings-modal"', template)
        self.assertIn('id="prd-summary-title"', template)
        self.assertIn('id="prd-summary-description"', template)
        self.assertNotIn('id="prd-summary-modal"', template)
        self.assertIn('id="write-delete-confirm-modal"', template)
        self.assertIn("showAfterHidden(settingsModalElement, deleteConfirmModal)", script)
        self.assertIn("settingsEditSection.classList.toggle", script)
        self.assertIn('detailApi + "metadata/"', script)
        self.assertIn("can_change_status", script)
        self.assertIn("can_edit_deadline", script)
        self.assertIn("window.setTimeout(clearAlert", script)
        self.assertIn('id="export-prd"', template)
        self.assertIn('id="export-modal"', template)
        self.assertIn("PRD 완성도 점검 및 내보내기", template)
        self.assertIn(".md 다운로드", template)
        self.assertIn("loadMarkdownPreview", script)
        self.assertIn(".write-evaluation-title{position:sticky", stylesheet)
        self.assertIn(".write-panel-head,.write-evaluation-title{height:58px", stylesheet)

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
