from pathlib import Path

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase


class TemplateContractTests(SimpleTestCase):
    def test_base_exposes_parent_compatible_blocks(self):
        source = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")

        for block in ("extra_head", "breadcrumb", "content", "modals", "extra_js"):
            self.assertIn(f"{{% block {block} %}}", source)
        self.assertIn("bootstrap@5.3.2", source)

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
        self.assertIn('addEventListener("online", reconnect)', source)
        self.assertIn("Math.min(5000, Math.max(2000", source)
        self.assertNotIn("WebSocket", source)
        self.assertNotIn("drag", source.lower())
