import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/package_skill.py"
spec = importlib.util.spec_from_file_location("package_skill", SCRIPT)
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class PackageTests(unittest.TestCase):
    def build(self, mcp_url=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "skill.zip"
        packager.build(output, mcp_url)
        return output

    def test_skills_only_package_has_one_skill_and_no_mcp_or_secrets(self):
        output = self.build()
        self.assertLess(output.stat().st_size, 25 * 1024 * 1024)
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            self.assertEqual([name for name in names if name.endswith("/SKILL.md")],
                             ["no-watermark/skills/no-watermark/SKILL.md"])
            self.assertIn("no-watermark/plugin.json", names)
            self.assertNotIn("no-watermark/mcp.json", names)
            self.assertFalse(any("__pycache__" in name or name.endswith((".pyc", ".pyo")) for name in names))
            combined = b"\n".join(archive.read(name) for name in names)
            self.assertNotIn(b"sk-test-secret", combined)
            self.assertNotIn(b"OPENAI_API_KEY=sk-", combined)

    def test_mcp_package_uses_exact_https_endpoint(self):
        output = self.build("https://writer.example.com/mcp")
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("no-watermark/mcp.json"))
            self.assertEqual(manifest["mcpServers"]["no-watermark-api"]["url"],
                             "https://writer.example.com/mcp")

    def test_mcp_url_rejects_insecure_or_embedded_credentials(self):
        with self.assertRaises(ValueError):
            self.build("http://writer.example.com/mcp")
        with self.assertRaises(ValueError):
            self.build("https://user:secret@writer.example.com/mcp")


if __name__ == "__main__":
    unittest.main()
