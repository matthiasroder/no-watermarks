#!/usr/bin/env python3
"""Publication-writing API bridge. Python 3.11+, standard library only."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import tomllib
from typing import Any
import urllib.error
import urllib.request
import uuid


ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_CONFIG = Path("~/.config/skills/no-watermark/config.toml").expanduser()
DEFAULT_LOGS = "~/.local/state/no-watermark/conversations"
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}


class BridgeError(Exception):
    def __init__(self, message: str, summary: dict | None = None):
        super().__init__(message)
        self.summary = summary


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, secret) for key, item in value.items()}
    return value


def private_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise BridgeError(f"Expected a directory: {path}")
        return
    private_directory(path.parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if not path.is_dir():
            raise BridgeError(f"Expected a directory: {path}")


def atomic_write(path: Path, content: str) -> None:
    private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_log(path: Path, log: dict, secret: str) -> None:
    log["updated_at"] = now()
    atomic_write(path, json.dumps(redact(log, secret), ensure_ascii=False, indent=2) + "\n")


@contextmanager
def conversation_lock(path: Path):
    lock = path.with_suffix(path.suffix + ".lock")
    private_directory(lock.parent)
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise BridgeError(f"Conversation is locked: {lock}. Check for a running call before recovering it.")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def init_config(path: Path, key_env: str | None = None) -> dict:
    template = Path(__file__).resolve().parents[1] / "config.example.toml"
    key = os.environ.get(key_env, "").strip() if key_env else ""
    if key_env and not key:
        raise BridgeError(f"Environment variable {key_env} is empty; no config created.")
    content = template.read_text(encoding="utf-8").replace('api_key = ""', f"api_key = {json.dumps(key)}", 1)
    private_directory(path.parent)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise BridgeError(f"Config already exists; it was not overwritten: {path}")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
        stream.write(content)
    return {"status": "configured", "config_path": str(path), "api_key_configured": bool(key), "default_model": "writing"}


def read_config(path: Path, dry_run: bool) -> dict:
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BridgeError(f"Config missing: {path}. Run init-config first.")
    except (tomllib.TOMLDecodeError, UnicodeError):
        # A TOML parser diagnostic could include a line containing the key.
        raise BridgeError("Invalid TOML config; inspect it locally.")
    for section in ("openai", "generation", "models", "logging"):
        if not isinstance(config.get(section, {}), dict):
            raise BridgeError(f"Config section {section} must be a table.")
    connection = config.get("openai", {})
    secret = connection.get("api_key", "")
    if not isinstance(secret, str) or any(ch in secret for ch in "\r\n"):
        raise BridgeError("openai.api_key must be a single-line string.")
    if secret and os.name == "posix" and path.stat().st_mode & 0o077:
        raise BridgeError(f"Config with an API key must be private. Run chmod 600 on {path}.")
    if not secret and not dry_run:
        raise BridgeError(f"Set openai.api_key in the private config: {path}")
    for field in ("organization", "project"):
        value = connection.get(field, "")
        if not isinstance(value, str) or any(ch in value for ch in "\r\n"):
            raise BridgeError(f"openai.{field} must be a single-line string.")
    timeout = connection.get("timeout_seconds", 180)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise BridgeError("openai.timeout_seconds must be a positive finite number.")
    return config


def read_text(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).expanduser().read_text(encoding="utf-8")


def validate_messages(messages: Any) -> list:
    if not isinstance(messages, list):
        raise BridgeError("messages must be a list.")
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] not in ("user", "assistant") or not isinstance(message["content"], str)):
            raise BridgeError("Each initial message needs only role (user/assistant) and string content.")
    return messages


def read_request(args: argparse.Namespace) -> dict:
    if args.request_file:
        try:
            request = json.loads(read_text(args.request_file))
        except (ValueError, UnicodeError):
            raise BridgeError("Invalid UTF-8 request JSON.")
        allowed = {"prompt", "user_message", "instructions", "messages", "model", "max_output_tokens"}
        if not isinstance(request, dict) or set(request) - allowed:
            raise BridgeError("Request must be an object with only supported fields.")
    else:
        request = {"prompt": args.prompt if args.prompt is not None else read_text(args.prompt_file)}
    if not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
        raise BridgeError("A nonempty prompt is required.")
    for field in ("user_message", "instructions", "model"):
        if field in request and not isinstance(request[field], str):
            raise BridgeError(f"{field} must be a string.")
    if "messages" in request:
        validate_messages(request["messages"])
    if args.instructions_file:
        if args.instructions_file == "-" and (args.request_file == "-" or args.prompt_file == "-"):
            raise BridgeError("Only one input may read stdin.")
        request["instructions"] = read_text(args.instructions_file)
    if args.model:
        request["model"] = args.model
    if args.max_output_tokens is not None:
        request["max_output_tokens"] = args.max_output_tokens
    return request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call_api(payload: dict, config: dict) -> tuple[dict, str | None]:
    connection = config.get("openai", {})
    headers = {"Authorization": f"Bearer {connection['api_key']}", "Content-Type": "application/json"}
    for field, header in (("organization", "OpenAI-Organization"), ("project", "OpenAI-Project")):
        if connection.get(field):
            headers[header] = connection[field]
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=connection.get("timeout_seconds", 180)) as response:
            request_id = response.headers.get("x-request-id")
            body = response.read()
    except urllib.error.HTTPError as exc:
        request_id = exc.headers.get("x-request-id") if exc.headers else None
        try:
            error = json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeError):
            error = {"error": {"message": f"HTTP {exc.code}"}}
        return {"status": "http_error", "http_status": exc.code, "error": error}, request_id
    except (urllib.error.URLError, TimeoutError, OSError):
        # Do not expose credentials from exception details or retry ambiguous calls.
        return {"status": "transport_error", "error": {"message": "Connection failed or timed out. The request may have reached OpenAI; no automatic retry."}}, None
    try:
        result = json.loads(body)
    except (ValueError, UnicodeError):
        return {"status": "invalid_response", "error": {"message": "OpenAI returned an invalid JSON response; no automatic retry."}}, request_id
    if not isinstance(result, dict):
        return {"status": "invalid_response", "error": {"message": "OpenAI returned a non-object response."}}, request_id
    return result, request_id


def output_text(response: dict) -> str:
    output = response.get("output", [])
    if not isinstance(output, list):
        raise BridgeError("Response output must be a list.")
    parts = []
    for item in output:
        if not isinstance(item, dict):
            raise BridgeError("Malformed response output item.")
        if item.get("type") == "message" and item.get("role") == "assistant":
            content = item.get("content", [])
            if not isinstance(content, list):
                raise BridgeError("Malformed response message content.")
            for part in content:
                if not isinstance(part, dict):
                    raise BridgeError("Malformed response content item.")
                if part.get("type") == "output_text":
                    if not isinstance(part.get("text"), str):
                        raise BridgeError("Malformed response text.")
                    parts.append(part["text"])
    return "".join(parts)


def choose_model(config: dict, request: dict, log: dict) -> tuple[str, str, dict | None, int]:
    generation = config.get("generation", {})
    previous = next((call for call in reversed(log["calls"]) if call["status"] == "completed"), None)
    alias = request.get("model", previous["model_alias"] if previous else generation.get("default_model", "writing"))
    if not isinstance(alias, str) or not alias.strip():
        raise BridgeError("Choose a nonempty model alias or model ID.")
    model = config.get("models", {}).get(alias, {"id": alias})
    if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not model["id"].strip():
        raise BridgeError("Each model alias must be a table with a nonempty id.")
    effort = model.get("reasoning_effort")
    if effort is not None and (not isinstance(effort, str) or effort not in EFFORTS):
        raise BridgeError("Unsupported configured reasoning_effort.")
    limit = request.get("max_output_tokens", generation.get("max_output_tokens", 8192))
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise BridgeError("max_output_tokens must be a positive integer.")
    return alias, model["id"], {"effort": effort} if effort else None, limit


def conversation_path(value: str | None, directory: Path) -> Path:
    if not value:
        return directory / f"{uuid.uuid4()}.json"
    try:
        identifier = str(uuid.UUID(value))
    except ValueError:
        return Path(value).expanduser().resolve()
    return directory / f"{identifier}.json"


def load_conversation(path: Path) -> dict:
    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise BridgeError("Invalid conversation JSON; inspect the file locally.")
    if (not isinstance(log, dict) or log.get("schema_version") != 1
            or not isinstance(log.get("conversation_id"), str)
            or not all(isinstance(log.get(key), list) for key in ("messages", "calls", "api_history"))
            or not all(isinstance(call, dict) and "status" in call and "model_alias" in call for call in log["calls"])):
        raise BridgeError("Unsupported or malformed conversation log.")
    if any(call["status"] == "pending" for call in log["calls"]):
        raise BridgeError("Conversation contains a pending call. Investigate its outcome before continuing; it will not be retried automatically.")
    return log


def generate(args: argparse.Namespace, transport=call_api) -> dict:
    config_path = Path(args.config).expanduser().resolve()
    config = read_config(config_path, args.dry_run)
    secret = config.get("openai", {}).get("api_key", "")
    request = read_request(args)
    directory = config.get("logging", {}).get("directory", DEFAULT_LOGS)
    if not isinstance(directory, str) or not directory.strip():
        raise BridgeError("logging.directory must be a nonempty path string.")
    log_path = conversation_path(args.conversation, Path(directory).expanduser().resolve())
    text_path = Path(args.output_file).expanduser().resolve() if args.output_file else log_path.with_suffix(".md")
    if log_path == config_path or text_path in (config_path, log_path, log_path.with_suffix(log_path.suffix + ".lock")):
        raise BridgeError("Config, conversation log, lock, and text output must use different paths.")
    with conversation_lock(log_path):
        if args.conversation:
            log = load_conversation(log_path)
            if request.get("messages"):
                raise BridgeError("Initial messages cannot replace an existing conversation.")
        else:
            timestamp = now()
            initial = request.get("messages", [])
            log = {"schema_version": 1, "conversation_id": log_path.stem, "created_at": timestamp,
                   "updated_at": timestamp, "instructions": None,
                   "messages": [{**item, "source": "host_context", "created_at": timestamp} for item in initial],
                   "api_history": list(initial), "calls": [], "latest_output_text": None, "latest_text_file": None,
                   "provenance": {"api_text_watermarking": "project_or_organization_controlled",
                                  "verified": False, "per_request_override": False}}
        alias, model, reasoning, limit = choose_model(config, request, log)
        instructions = request.get("instructions", log.get("instructions") if log.get("instructions") is not None
                                   else config.get("generation", {}).get("instructions", ""))
        if not isinstance(instructions, str):
            raise BridgeError("Writing instructions must be a string.")
        turn_id = str(uuid.uuid4())
        user_input = {"role": "user", "content": request["prompt"]}
        payload = {"model": model, "input": log["api_history"] + [user_input], "instructions": instructions,
                   "max_output_tokens": limit, "store": False, "include": ["reasoning.encrypted_content"]}
        if reasoning:
            payload["reasoning"] = reasoning
        call = {"turn_id": turn_id, "started_at": now(), "completed_at": None,
                "status": "prepared" if args.dry_run else "pending", "model_alias": alias,
                "request": {"method": "POST", "url": ENDPOINT, "payload": payload},
                "response": None, "request_id": None, "output_text": None, "error": None}
        message = {"role": "user", "content": request.get("user_message", request["prompt"]), "source": "user",
                   "created_at": call["started_at"], "turn_id": turn_id, "status": call["status"]}
        if message["content"] != request["prompt"]:
            message["api_prompt"] = request["prompt"]
        log["calls"].append(call)
        log["messages"].append(message)
        save_log(log_path, log, secret)
        summary = {"status": call["status"], "conversation_id": log["conversation_id"], "turn_id": turn_id,
                   "log_path": str(log_path), "text_path": None, "model": model, "response_id": None, "request_id": None}
        if args.dry_run:
            return summary
        response, request_id = transport(payload, config)
        call["completed_at"] = now()
        call["response"] = redact(response, secret)
        call["request_id"] = request_id
        summary.update(response_id=redact(response.get("id"), secret), request_id=redact(request_id, secret))
        try:
            text = output_text(response)
            if secret in text:
                raise BridgeError("Response contained the API key; export was refused and the log was redacted.")
            call["output_text"] = text
            if response.get("status") != "completed" or not text.strip():
                raise BridgeError("API did not complete with publishable text. Inspect the saved response; no automatic retry.")
        except BridgeError as exc:
            call["status"] = "incomplete" if response.get("status") == "incomplete" else "failed"
            call["error"] = {"message": str(exc), "http_status": response.get("http_status")}
            message["status"] = call["status"]
            summary.update(status=call["status"], error=str(exc))
            save_log(log_path, log, secret)
            raise BridgeError(str(exc), summary)
        call["status"] = message["status"] = "completed"
        log["instructions"] = instructions
        log["api_history"].extend([user_input, *response["output"]])
        log["messages"].append({"role": "assistant", "content": text, "source": "openai_api", "created_at": now(),
                                "turn_id": turn_id, "model": model, "response_id": response.get("id")})
        log["latest_output_text"] = text
        log["latest_text_file"] = None
        # Persist the successful response before exporting, so a disk error never requires a second API call.
        save_log(log_path, log, secret)
        try:
            atomic_write(text_path, text)
        except (OSError, BridgeError):
            summary.update(status="export_failed", error="API succeeded but text export failed. Recover latest_output_text from the JSON log; do not repeat the call.")
            raise BridgeError(summary["error"], summary)
        log["latest_text_file"] = str(text_path)
        save_log(log_path, log, secret)
        summary.update(status="completed", text_path=str(text_path))
        return summary


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-config", help="Create a private config without overwriting one")
    init.add_argument("--config", default=str(DEFAULT_CONFIG))
    init.add_argument("--key-env", help="Import the key from this environment variable without displaying it")
    run = commands.add_parser("generate", help="Generate or revise text and save the conversation")
    run.add_argument("--config", default=str(DEFAULT_CONFIG))
    inputs = run.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--prompt")
    inputs.add_argument("--prompt-file", help="UTF-8 file, or - for stdin")
    inputs.add_argument("--request-file", help="Structured JSON file, or - for stdin")
    run.add_argument("--instructions-file", help="Override writing instructions using a UTF-8 file")
    run.add_argument("--conversation", help="Existing JSON log path or conversation UUID")
    run.add_argument("--model", help="Configured alias or API model ID")
    run.add_argument("--max-output-tokens", type=int)
    run.add_argument("--output-file", help="Exact text export path; replaced only after successful generation")
    run.add_argument("--dry-run", action="store_true", help="Log the request without calling OpenAI")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = init_config(Path(args.config).expanduser().resolve(), args.key_env) if args.command == "init-config" else generate(args)
    except BridgeError as exc:
        print(json.dumps(exc.summary or {"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    except (OSError, UnicodeError):
        print(json.dumps({"status": "error", "error": "Local file operation failed. Inspect file paths and permissions; check any saved pending call before retrying."}))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "error": "Check the conversation log for a pending request before retrying."}))
        return 130
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
