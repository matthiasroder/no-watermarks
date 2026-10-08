import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SCRIPT = Path(__file__).resolve().parents[1] / "skills/no-watermark/scripts/no_watermark.py"
spec = importlib.util.spec_from_file_location("no_watermark", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def response(text="Grüße — exact copy.\n\nNo trailing newline", status="completed"):
    return {"id": "resp_test", "status": status, "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": text},
        ]},
    ]}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.config = self.directory / "config.toml"
        self.config.write_text('api_key = "sk-test-secret"\nmodel = "test-model"\ninstructions = "Keep facts."\n')
        self.log_path = self.directory / "logs/conversation.json"

    def run_bridge(self, prompt, result):
        stdout = io.StringIO()
        reply = io.BytesIO(json.dumps(result).encode())
        with patch.object(sys, "argv", [str(SCRIPT), "--config", str(self.config), "--log", str(self.log_path)]), \
                patch.object(sys, "stdin", io.StringIO(prompt)), \
                patch.object(bridge.urllib.request, "urlopen", return_value=reply) as call, \
                contextlib.redirect_stdout(stdout):
            code = bridge.main()
        return code, json.loads(stdout.getvalue()), call.call_args.args[0]

    def read_log(self):
        return json.loads(self.log_path.read_text())

    def test_request_exact_text_log_and_key_exclusion(self):
        result = response()
        code, summary, request = self.run_bridge("Write our announcement.", result)
        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test-secret")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["instructions"], "Keep facts.")
        self.assertFalse(payload["store"])
        log = self.read_log()
        self.assertEqual(log["calls"][-1]["response"], result)
        self.assertEqual(log["calls"][-1]["request"], payload)
        self.assertEqual(log["calls"][-1]["text"], result["output"][1]["content"][0]["text"])
        self.assertNotIn("sk-test-secret", self.log_path.read_text())
        self.assertNotIn("Authorization", self.log_path.read_text())
        self.assertEqual(self.log_path.stat().st_mode & 0o777, 0o600)

    def test_followup_sends_successful_conversation(self):
        self.run_bridge("Draft it.", response("First draft."))
        previous = copy.deepcopy(self.read_log()["messages"])
        code, _, request = self.run_bridge("Make it warmer.", response("Revised draft."))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(request.data)["input"], previous + [{"role": "user", "content": "Make it warmer."}])
        self.assertEqual(len(self.read_log()["calls"]), 2)
        self.assertEqual(len(self.read_log()["messages"]), 4)

    def test_incomplete_turn_is_logged_but_excluded_from_history(self):
        self.run_bridge("Draft it.", response("Good draft."))
        history = copy.deepcopy(self.read_log()["messages"])
        code, summary, _ = self.run_bridge("Revise it.", response("Partial", "incomplete"))
        self.assertEqual(code, 1)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(self.read_log()["messages"], history)
        self.assertEqual(self.read_log()["calls"][-1]["text"], "Partial")

    def test_http_error_is_saved(self):
        error_response = {"error": {"message": "Invalid API key: sk-test-secret", "code": "invalid_api_key"}}
        error = urllib.error.HTTPError("https://api.openai.com/v1/responses", 401, "Unauthorized", {},
                                       io.BytesIO(json.dumps(error_response).encode()))
        with patch.object(bridge.urllib.request, "urlopen", side_effect=error):
            with patch.object(sys, "argv", [str(SCRIPT), "--config", str(self.config), "--log", str(self.log_path)]), \
                    patch.object(sys, "stdin", io.StringIO("Write it.")), contextlib.redirect_stdout(io.StringIO()):
                code = bridge.main()
        self.assertEqual(code, 1)
        self.assertEqual(self.read_log()["calls"][-1]["response"]["error"]["code"], "invalid_api_key")
        self.assertNotIn("sk-test-secret", self.log_path.read_text())
        self.assertEqual(self.read_log()["messages"], [])

    def test_empty_prompt_does_not_call_api(self):
        with patch.object(sys, "argv", [str(SCRIPT)]), patch.object(sys, "stdin", io.StringIO("  ")), \
                patch.object(bridge.urllib.request, "urlopen") as call, contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            bridge.main()
        call.assert_not_called()

    def test_log_cannot_overwrite_config(self):
        original = self.config.read_bytes()
        with patch.object(sys, "argv", [str(SCRIPT), "--config", str(self.config), "--log", str(self.config)]), \
                patch.object(sys, "stdin", io.StringIO("Write it.")), \
                patch.object(bridge.urllib.request, "urlopen") as call, self.assertRaises(ValueError):
            bridge.main()
        call.assert_not_called()
        self.assertEqual(self.config.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
