#!/usr/bin/env python3
"""Build a ChatGPT plugin ZIP containing exactly one no-watermark skill."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlparse
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "no-watermark"
PACKAGING = ROOT / "packaging"


def validate_mcp_url(value):
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("MCP URL must be a public HTTPS URL without embedded credentials.")
    return value.rstrip("/")


def add_tree(archive, directory, top_level):
    for path in sorted(directory.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            relative = Path(top_level) / path.relative_to(directory)
            info = zipfile.ZipInfo(relative.as_posix())
            info.date_time = (2020, 1, 1, 0, 0, 0)
            info.external_attr = (0o755 if path.suffix == ".py" else 0o644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)


def build(output, mcp_url=None):
    mcp_url = validate_mcp_url(mcp_url)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        plugin = Path(temporary) / "no-watermark"
        shutil.copytree(SKILL, plugin / "skills" / "no-watermark")
        shutil.copy2(PACKAGING / "plugin.json", plugin / "plugin.json")
        if mcp_url:
            template = json.loads((PACKAGING / "mcp.json.template").read_text(encoding="utf-8"))
            template["mcpServers"]["no-watermark-api"]["url"] = mcp_url
            (plugin / "mcp.json").write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
        with zipfile.ZipFile(output, "w") as archive:
            add_tree(archive, plugin, plugin.name)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "skill.zip"))
    parser.add_argument("--mcp-url", help="Deployed HTTPS endpoint ending in /mcp")
    args = parser.parse_args()
    path = build(args.output, args.mcp_url)
    print(path)


if __name__ == "__main__":
    main()
