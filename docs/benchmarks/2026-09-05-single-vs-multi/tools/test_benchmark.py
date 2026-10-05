import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import benchmark


class _IncompleteHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def do_POST(self):
        body = json.dumps({"status": "in_progress", "output": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BenchmarkContractTest(unittest.TestCase):
    def setUp(self):
        self.state = benchmark.MockState()
        self.server = benchmark.make_server("127.0.0.1", 0, self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.tmp = tempfile.TemporaryDirectory()
        self.token_file = Path(self.tmp.name) / "token"
        self.token_file.write_text("test-token\n", encoding="utf-8")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def control(self, payload):
        return benchmark.post_json(f"{self.base}/control", payload)

    def load(self, *, stream=False, rps=5, duration=0.4):
        return benchmark.run_load(
            url=f"{self.base}/a/v1/responses",
            token_file=str(self.token_file),
            run_id="selftest",
            rps=rps,
            duration=duration,
            output=None,
            model="gpt-4o-mini",
            stream=stream,
        )

    def test_json_responses_are_complete_successes(self):
        self.control({"channels": {"a": {"capacity": 8}}, "duration_s": 0.02, "reset": True})
        result = self.load()
        self.assertEqual(result["summary"]["success"], result["summary"]["actual_sent"])
        self.assertEqual(result["summary"]["http_error"], 0)

    def test_capacity_produces_429_without_exceeding_inflight(self):
        self.control({"channels": {"a": {"capacity": 1}}, "duration_s": 0.2, "reset": True})
        result = self.load(rps=30, duration=0.35)
        self.assertGreater(result["summary"]["http_error"], 0)
        metrics = benchmark.get_json(f"{self.base}/metrics")
        self.assertGreater(metrics["channels"]["a"]["rejected"], 0)
        self.assertEqual(metrics["channels"]["a"]["max_inflight"], 1)

    def test_fault_window_produces_503(self):
        self.control({"fault_period_s": 60, "fault_window_s": 60, "reset": True})
        result = self.load(rps=2, duration=0.5)
        self.assertEqual(result["summary"]["success"], 0)
        self.assertGreater(result["summary"]["http_error"], 0)
        self.assertTrue(all(row["status_code"] == 503 for row in result["rows"]))

    def test_channel_fault_override_keeps_other_channel_healthy(self):
        self.control({
            "channels": {
                "a": {"capacity": 8, "fault_period_s": 60, "fault_window_s": 60},
                "b": {"capacity": 8, "fault_period_s": 0, "fault_window_s": 0},
            },
            "duration_s": 0.02,
            "fault_period_s": 0,
            "fault_window_s": 0,
            "reset": True,
        })
        a_result = self.load(rps=2, duration=0.5)
        b_result = benchmark.run_load(
            url=f"{self.base}/b/v1/responses",
            token_file=str(self.token_file),
            run_id="healthy-b",
            rps=2,
            duration=0.5,
            output=None,
            model="gpt-4o-mini",
            stream=False,
        )
        self.assertEqual(a_result["rows"][0]["status_code"], 503)
        self.assertEqual(b_result["summary"]["success"], 1)
        metrics = benchmark.get_json(f"{self.base}/metrics")
        self.assertEqual(metrics["channels"]["a"]["effective_config"]["fault_window_s"], 60)
        self.assertEqual(metrics["channels"]["b"]["effective_config"]["fault_window_s"], 0)

    def test_backup_c_has_independent_capacity_and_fault_state(self):
        self.control({"channels": {
            "a": {"fault_period_s": 60, "fault_window_s": 60},
            "b": {"fault_period_s": 60, "fault_window_s": 60},
            "c": {"capacity": 2, "fault_period_s": 0, "fault_window_s": 0}},
            "duration_s": 0.02, "reset": True})
        result = benchmark.run_load(
            url=f"{self.base}/c/v1/responses", token_file=str(self.token_file),
            run_id="backup-c", rps=2, duration=0.5, output=None,
            model="gpt-4o-mini", stream=True)
        self.assertEqual(result["summary"]["success"], 1)
        metrics = benchmark.get_json(f"{self.base}/metrics")
        self.assertEqual(metrics["channels"]["c"]["success"], 1)
        self.assertEqual(metrics["channels"]["c"]["effective_config"]["capacity"], 2)
        self.assertEqual(metrics["channels"]["a"]["attempts"], 0)
        self.assertEqual(metrics["channels"]["b"]["attempts"], 0)

    def test_sse_requires_text_and_completed_event(self):
        self.control({"channels": {"a": {"capacity": 8}}, "duration_s": 0.04, "first_token_s": 0.01, "fault_period_s": 0, "fault_window_s": 0, "reset": True})
        result = self.load(stream=True)
        self.assertEqual(result["summary"]["success"], result["summary"]["actual_sent"])
        self.assertTrue(all(row["first_output_latency_s"] is not None for row in result["rows"]))

    def test_http_200_incomplete_response_is_not_success(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _IncompleteHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = benchmark.run_load(
                url=f"http://127.0.0.1:{server.server_port}/v1/responses",
                token_file=str(self.token_file),
                run_id="incomplete",
                rps=2,
                duration=0.5,
                output=None,
                model="gpt-4o-mini",
                stream=False,
            )
            self.assertEqual(result["summary"]["success"], 0)
            self.assertEqual(result["summary"]["invalid_response"], result["summary"]["actual_sent"])
            self.assertIn("send_window_ended_at", result["summary"])
            self.assertIn("last_actual_start_at", result["summary"])
            self.assertIn("drain_elapsed_s", result["summary"])
            self.assertIn("whole_run_completed_rps", result["summary"])
            self.assertNotIn("achieved_send_rate_rps", result["summary"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
