import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SCRIPT = Path(__file__).resolve().parents[1] / "skills/no-watermark/scripts/no_watermark.py"
spec = importlib.util.spec_from_file_location("no_watermark", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def response(text="A precise draft.\n", status="completed", identifier="resp_test"):
    return {"id": identifier, "status": status, "output": [
        {"type": "reasoning", "id": "rs_test", "summary": [], "encrypted_content": "opaque-state"},
        {"type": "message", "id": "msg_test", "role": "assistant", "status": "completed",
         "content": [{"type": "output_text", "text": text, "annotations": []}]},
    ], "usage": {"total_tokens": 20}}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.config = self.directory / "private/config.toml"
        with patch.dict(os.environ, {"BRIDGE_TEST_KEY": "sk-test-secret"}):
            bridge.init_config(self.config, "BRIDGE_TEST_KEY")
        content = self.config.read_text().replace(bridge.DEFAULT_LOGS, str(self.directory / "logs"))
        bridge.atomic_write(self.config, content)

    def args(self, *options):
        return bridge.parser().parse_args(["generate", "--config", str(self.config), *options])

    def log(self, summary):
        return json.loads(Path(summary["log_path"]).read_text())

    def test_exact_output_transcript_request_and_private_files(self):
        request = self.directory / "request.json"
        request.write_text(json.dumps({"user_message": "Write the announcement.",
                                       "prompt": "Write the announcement. Source: verified facts.",
                                       "messages": [{"role": "user", "content": "Our earlier brief."}],
                                       "instructions": "Use my voice.", "model": "fast"}))
        calls = []
        text = "  Grüße — exact copy.\n\nFinal line without newline"

        def transport(payload, config):
            calls.append(copy.deepcopy(payload))
            self.assertEqual(config["openai"]["api_key"], "sk-test-secret")
            return response(text), "req_test"

        summary = bridge.generate(self.args("--request-file", str(request)), transport)
        log = self.log(summary)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(Path(summary["text_path"]).read_bytes(), text.encode("utf-8"))
        self.assertEqual(log["messages"][1]["content"], "Write the announcement.")
        self.assertEqual(log["messages"][1]["api_prompt"], calls[0]["input"][-1]["content"])
        self.assertEqual(log["messages"][-1]["content"], text)
        self.assertEqual(calls[0]["model"], "gpt-6-luna")
        self.assertFalse(calls[0]["store"])
        self.assertEqual(calls[0]["include"], ["reasoning.encrypted_content"])
        self.assertFalse(log["provenance"]["verified"])
        self.assertNotIn("sk-test-secret", Path(summary["log_path"]).read_text())
        self.assertNotIn("Authorization", Path(summary["log_path"]).read_text())
        for path in (self.config, Path(summary["log_path"]), Path(summary["text_path"])):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_followup_replays_full_output_and_keeps_instructions_and_model(self):
        first_request = self.directory / "first.json"
        first_request.write_text(json.dumps({"prompt": "Draft it.", "instructions": "Be concise.", "model": "fast"}))
        first = bridge.generate(self.args("--request-file", str(first_request)), lambda *_: (response(), "req_one"))
        history = self.log(first)["api_history"]
        sent = []

        def followup(payload, _):
            sent.append(payload)
            return response("Revised text.", identifier="resp_two"), "req_two"

        second = bridge.generate(self.args("--prompt", "Make it warmer.", "--conversation", first["log_path"]), followup)
        self.assertEqual(sent[0]["input"], history + [{"role": "user", "content": "Make it warmer."}])
        self.assertEqual(sent[0]["instructions"], "Be concise.")
        self.assertEqual(sent[0]["model"], "gpt-6-luna")
        self.assertEqual(self.log(second)["api_history"][1]["encrypted_content"], "opaque-state")
        self.assertEqual(len(self.log(second)["messages"]), 4)
        self.assertEqual(Path(second["text_path"]).read_text(), "Revised text.")

    def test_failed_revision_keeps_good_text_and_does_not_replay_failure(self):
        first = bridge.generate(self.args("--prompt", "Draft it."), lambda *_: (response("Good text."), "req_one"))
        good_history = self.log(first)["api_history"]
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.generate(self.args("--prompt", "Bad revision.", "--conversation", first["log_path"]),
                            lambda *_: ({"status": "http_error", "http_status": 401,
                                         "error": {"message": "Rejected sk-test-secret"}}, "req_fail"))
        self.assertEqual(caught.exception.summary["status"], "failed")
        log = self.log(first)
        self.assertEqual(log["latest_output_text"], "Good text.")
        self.assertEqual(log["api_history"], good_history)
        self.assertEqual(Path(first["text_path"]).read_text(), "Good text.")
        self.assertNotIn("sk-test-secret", Path(first["log_path"]).read_text())
        self.assertEqual(log["calls"][-1]["response"]["http_status"], 401)

    def test_incomplete_and_refusal_are_logged_without_export(self):
        refusal = {"status": "completed", "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "refusal", "refusal": "Cannot comply."}]}]}
        for result, status in ((response("Partial", "incomplete"), "incomplete"), (refusal, "failed")):
            with self.subTest(status=status), self.assertRaises(bridge.BridgeError) as caught:
                bridge.generate(self.args("--prompt", "Write."), lambda *_: (result, None))
            summary = caught.exception.summary
            self.assertEqual(summary["status"], status)
            self.assertIsNone(summary["text_path"])
            self.assertFalse(Path(summary["log_path"]).with_suffix(".md").exists())
            self.assertEqual(self.log(summary)["api_history"], [])

    def test_dry_run_does_not_call_transport_or_require_key(self):
        bridge.atomic_write(self.config, self.config.read_text().replace("sk-test-secret", ""))
        with patch.object(bridge, "call_api", side_effect=AssertionError("must not call")):
            summary = bridge.generate(self.args("--prompt", "Prepare it.", "--dry-run"),
                                      lambda *_: self.fail("Transport called in dry run"))
        self.assertEqual(summary["status"], "prepared")
        self.assertIsNone(self.log(summary)["calls"][0]["response"])
        self.assertEqual(self.log(summary)["api_history"], [])

    def test_config_init_is_exclusive_private_and_does_not_print_key(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.init_config(self.config)
        destination = self.directory / "other/config.toml"
        with patch.dict(os.environ, {"BRIDGE_TEST_KEY": "sk-new-secret"}), contextlib.redirect_stdout(io.StringIO()) as stdout:
            status = bridge.main(["init-config", "--config", str(destination), "--key-env", "BRIDGE_TEST_KEY"])
        self.assertEqual(status, 0)
        self.assertNotIn("sk-new-secret", stdout.getvalue())
        self.assertTrue(json.loads(stdout.getvalue())["api_key_configured"])
        self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)

    def test_invalid_requests_and_open_config_fail_before_call(self):
        invalid = [{"prompt": ""}, {"prompt": "x", "max_output_tokens": True},
                   {"prompt": "x", "instructions": []}, {"prompt": "x", "extra": "x"},
                   {"prompt": "x", "messages": [{"role": "system", "content": "x"}]}]
        for value in invalid:
            with self.subTest(value=value):
                request = self.directory / "bad.json"
                request.write_text(json.dumps(value))
                with self.assertRaises(bridge.BridgeError):
                    bridge.generate(self.args("--request-file", str(request)), lambda *_: self.fail("Invalid request reached API"))
        self.config.chmod(0o644)
        with self.assertRaisesRegex(bridge.BridgeError, "private"):
            bridge.generate(self.args("--prompt", "x"), lambda *_: self.fail("Unsafe config reached API"))

    def test_locked_or_pending_conversation_is_never_retried(self):
        first = bridge.generate(self.args("--prompt", "x"), lambda *_: (response(), None))
        args = self.args("--prompt", "Next", "--conversation", first["log_path"])
        lock = Path(first["log_path"] + ".lock")
        lock.write_text("123")
        with self.assertRaisesRegex(bridge.BridgeError, "locked"):
            bridge.generate(args, lambda *_: self.fail("Locked call retried"))
        lock.unlink()
        log = self.log(first)
        log["calls"][-1]["status"] = "pending"
        bridge.save_log(Path(first["log_path"]), log, "sk-test-secret")
        with self.assertRaisesRegex(bridge.BridgeError, "pending"):
            bridge.generate(args, lambda *_: self.fail("Pending call retried"))

    def test_export_failure_retains_successful_response(self):
        original_write = bridge.atomic_write

        def disk_error(path, text):
            if path.suffix == ".md":
                raise OSError("disk full")
            original_write(path, text)

        with patch.object(bridge, "atomic_write", side_effect=disk_error), self.assertRaises(bridge.BridgeError) as caught:
            bridge.generate(self.args("--prompt", "x"), lambda *_: (response("Recover this."), "req_one"))
        self.assertEqual(caught.exception.summary["status"], "export_failed")
        log = self.log(caught.exception.summary)
        self.assertEqual(log["calls"][-1]["status"], "completed")
        self.assertEqual(log["latest_output_text"], "Recover this.")
        self.assertIsNone(log["latest_text_file"])

    def test_key_in_output_is_redacted_and_not_exported(self):
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.generate(self.args("--prompt", "x"), lambda *_: (response("Leaked sk-test-secret"), None))
        self.assertNotIn("sk-test-secret", Path(caught.exception.summary["log_path"]).read_text())
        self.assertIsNone(caught.exception.summary["text_path"])

    def test_transport_auth_headers_endpoint_and_no_redirect(self):
        config = bridge.read_config(self.config, False)
        config["openai"].update(project="proj_test", organization="org_test")
        reply = io.BytesIO(json.dumps(response()).encode())
        reply.headers = {"x-request-id": "req_transport"}
        captured = []

        class Opener:
            def open(self, request, timeout):
                captured.append((request, timeout))
                return reply

        with patch.object(bridge.urllib.request, "build_opener", return_value=Opener()) as build:
            result, request_id = bridge.call_api({"model": "gpt-6-luna"}, config)
        request, timeout = captured[0]
        self.assertEqual(request.full_url, bridge.ENDPOINT)
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test-secret")
        self.assertEqual(request.get_header("Openai-project"), "proj_test")
        self.assertEqual(request.get_header("Openai-organization"), "org_test")
        self.assertEqual(request.get_method(), "POST")
        self.assertIsInstance(build.call_args.args[0], bridge.NoRedirect)
        self.assertEqual(request_id, "req_transport")
        self.assertEqual(result["status"], "completed")

    def test_transport_failure_has_no_secret_and_does_not_retry(self):
        config = bridge.read_config(self.config, False)
        opener = unittest.mock.Mock()
        opener.open.side_effect = urllib.error.URLError("Secret: sk-test-secret")
        with patch.object(bridge.urllib.request, "build_opener", return_value=opener):
            result, _ = bridge.call_api({}, config)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(result["status"], "transport_error")
        self.assertNotIn("sk-test-secret", json.dumps(result))

    def test_invalid_remote_encoding_is_logged_as_failure(self):
        reply = io.BytesIO(b"\xff invalid response")
        reply.headers = {"x-request-id": "req_bad_encoding"}
        opener = unittest.mock.Mock()
        opener.open.return_value = reply
        with patch.object(bridge.urllib.request, "build_opener", return_value=opener), self.assertRaises(bridge.BridgeError) as caught:
            bridge.generate(self.args("--prompt", "x"), bridge.call_api)
        log = self.log(caught.exception.summary)
        self.assertEqual(log["calls"][-1]["status"], "failed")
        self.assertEqual(log["calls"][-1]["response"]["status"], "invalid_response")
        self.assertEqual(log["calls"][-1]["request_id"], "req_bad_encoding")
        self.assertEqual(opener.open.call_count, 1)


if __name__ == "__main__":
    unittest.main()
