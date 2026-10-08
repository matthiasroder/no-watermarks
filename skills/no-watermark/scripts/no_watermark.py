#!/usr/bin/env python3
"""Send a prompt from stdin to OpenAI and save the conversation as JSON."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tomllib
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="~/.config/skills/no-watermark/config.toml")
    parser.add_argument("--log", help="JSON conversation file; reuse it for follow-up prompts")
    args = parser.parse_args()
    prompt = sys.stdin.read()
    if not prompt.strip():
        parser.error("Supply a nonempty prompt on stdin.")

    config_path = Path(args.config).expanduser().resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if not config["api_key"]:
        raise ValueError("Missing API key.")
    log_path = Path(args.log or f"~/.local/state/no-watermark/conversations/{uuid.uuid4()}.json").expanduser().resolve()
    if log_path == config_path:
        raise ValueError("Config and log must use different paths.")
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {"messages": [], "calls": []}
    messages = log["messages"] + [{"role": "user", "content": prompt}]
    payload = {"model": config["model"], "input": messages, "store": False}
    if config.get("instructions"):
        payload["instructions"] = config["instructions"]
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as reply:
            response = json.load(reply)
    except urllib.error.HTTPError as error:
        response = json.loads(error.read())

    text = "".join(
        part["text"]
        for item in response.get("output", []) if item.get("type") == "message"
        for part in item.get("content", []) if part.get("type") == "output_text"
    )
    completed = response.get("status") == "completed" and bool(text.strip())
    log["calls"].append({"timestamp": datetime.now(timezone.utc).isoformat(),
                         "request": payload, "response": response, "text": text})
    if completed:
        log["messages"] = messages + [{"role": "assistant", "content": text}]
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(json.dumps(log, ensure_ascii=False, indent=2).replace(config["api_key"], "[REDACTED]") + "\n")
    print(json.dumps({"log_path": str(log_path), "status": "completed" if completed else "failed"}))
    return 0 if completed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError):
        print("Could not read config/log or call OpenAI. Check configuration, files, and API access.", file=sys.stderr)
        sys.exit(1)
