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
