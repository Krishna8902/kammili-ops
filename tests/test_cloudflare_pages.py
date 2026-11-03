"""Pages project summary must not leak environment values."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cloudflare_pages import git_disable_patch, safe_summary


class PagesConfigTests(unittest.TestCase):
    def test_summary_keeps_names_and_drops_values(self):
        result = {
            "production_branch": "main",
            "source": {
                "type": "github",
                "config": {
                    "owner": "Krishna8902",
                    "repo_name": "kammili-ops",
                    "production_branch": "main",
                    "production_deployments_enabled": True,
                    "preview_deployment_setting": "all",
                },
            },
            "build_config": {
                "build_command": "",
                "destination_dir": "/",
                "root_dir": "",
            },
            "deployment_configs": {
                "production": {
                    "env_vars": {
                        "OWNERREZ_TOKEN": {"value": "pt_secret_value"},
                        "OWNERREZ_USER": {"value": "owner@example.com"},
                    }
                }
            },
        }
        summary = safe_summary(result)
        self.assertEqual(summary["build_command"], "")
        self.assertEqual(summary["destination_dir"], "/")
        self.assertEqual(summary["env_var_names"], ["OWNERREZ_TOKEN", "OWNERREZ_USER"])
        blob = str(summary)
        self.assertNotIn("pt_secret_value", blob)
        self.assertNotIn("owner@example.com", blob)

        patch = git_disable_patch(result)
        self.assertFalse(patch["source"]["config"]["production_deployments_enabled"])
        self.assertEqual(patch["source"]["config"]["preview_deployment_setting"], "none")
        self.assertEqual(patch["source"]["config"]["owner"], "Krishna8902")
        self.assertNotIn("value", str(patch))

    def test_direct_upload_project_is_left_alone(self):
        self.assertIsNone(git_disable_patch({"source": None, "build_config": {}}))


if __name__ == "__main__":
    unittest.main()
