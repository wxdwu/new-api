#!/usr/bin/env python3
"""Deterministic local mock upstream and fixed-arrival HTTP load sampler."""

from __future__ import annotations

import argparse
import http.client
import json
import math
import re
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


REQUEST_TIMEOUT_S = 15.0
MAX_REQUEST_BODY = 1024 * 1024
BENCHMARK_ID_RE = re.compile(r"BENCH:[A-Za-z0-9._:-]{1,240}")


class ControlError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class MockState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.channels = {
            "a": {"capacity": 16, "fault_period_s": None, "fault_window_s": None},
            "b": {"capacity": 16, "fault_period_s": None, "fault_window_s": None},
        }
        self.duration_s = 0.05
        self.first_token_s = 0.01
        self.fault_period_s = 0.0
        self.fault_window_s = 0.0
        self.control_monotonic = time.monotonic()
        self._reset_metrics_locked()

    def _reset_metrics_locked(self) -> None:
        self.metrics = {
            name: {
                "attempts": 0,
                "success": 0,
                "rejected": 0,
                "fault": 0,
                "inflight": 0,
                "max_inflight": 0,
                "rows": [],
            }
            for name in ("a", "b")
        }

    @staticmethod
    def _number(payload: dict[str, Any], key: str, current: float) -> float:
        if key not in payload:
            return current
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ControlError(f"{key} must be a number")
        value = float(value)
        if not math.isfinite(value) or value < 0 or value > 60:
            raise ControlError(f"{key} must be between 0 and 60")
        return value

    @staticmethod
    def _capacity(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 100000:
            raise ControlError("capacity must be an integer between 0 and 100000")
        return value

    @staticmethod
    def _optional_number(value: Any, key: str) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ControlError(f"{key} must be a number or null")
        number = float(value)
        if not math.isfinite(number) or number < 0 or number > 60:
            raise ControlError(f"{key} must be between 0 and 60")
        return number

    def apply_control(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ControlError("control body must be a JSON object")
        reset = payload.get("reset", False)
        if not isinstance(reset, bool):
            raise ControlError("reset must be boolean")

        with self.lock:
            if reset and any(item["inflight"] for item in self.metrics.values()):
                raise ControlError("cannot reset while requests are in flight", 409)

            next_channels = {name: dict(config) for name, config in self.channels.items()}
            channel_payload = payload.get("channels", {})
            if channel_payload is None:
                channel_payload = {}
            if not isinstance(channel_payload, dict):
                raise ControlError("channels must be an object")
            for name in ("a", "b"):
                config = channel_payload.get(name, payload.get(name))
                if config is None:
                    continue
                if not isinstance(config, dict):
                    raise ControlError(f"channel {name} must be an object")
                unknown = set(config) - {"capacity", "fault_period_s", "fault_window_s"}
                if unknown:
                    raise ControlError(f"unknown channel {name} fields: {sorted(unknown)}")
                if "capacity" in config:
                    next_channels[name]["capacity"] = self._capacity(config["capacity"])
                if "fault_period_s" in config:
                    next_channels[name]["fault_period_s"] = self._optional_number(config["fault_period_s"], "fault_period_s")
                if "fault_window_s" in config:
                    next_channels[name]["fault_window_s"] = self._optional_number(config["fault_window_s"], "fault_window_s")

            duration_s = self._number(payload, "duration_s", self.duration_s)
            first_token_s = self._number(payload, "first_token_s", self.first_token_s)
            fault_period_s = self._number(payload, "fault_period_s", self.fault_period_s)
            fault_window_s = self._number(payload, "fault_window_s", self.fault_window_s)
            if fault_period_s == 0 and fault_window_s != 0:
                raise ControlError("fault_window_s must be 0 when fault_period_s is 0")
            if fault_period_s > 0 and fault_window_s > fault_period_s:
                raise ControlError("fault_window_s cannot exceed fault_period_s")
            for name, config in next_channels.items():
                effective_period = config["fault_period_s"] if config["fault_period_s"] is not None else fault_period_s
                effective_window = config["fault_window_s"] if config["fault_window_s"] is not None else fault_window_s
                if effective_period == 0 and effective_window != 0:
                    raise ControlError(f"channel {name}: fault_window_s must be 0 when fault_period_s is 0")
                if effective_period > 0 and effective_window > effective_period:
                    raise ControlError(f"channel {name}: fault_window_s cannot exceed fault_period_s")

            self.channels = next_channels
            self.duration_s = duration_s
            self.first_token_s = first_token_s
            self.fault_period_s = fault_period_s
            self.fault_window_s = fault_window_s
            self.control_monotonic = time.monotonic()
            if reset:
                self._reset_metrics_locked()
            return self._snapshot_locked(include_rows=False)

    def _effective_fault_locked(self, channel: str) -> tuple[float, float]:
        config = self.channels[channel]
        period = config["fault_period_s"] if config["fault_period_s"] is not None else self.fault_period_s
        window = config["fault_window_s"] if config["fault_window_s"] is not None else self.fault_window_s
        return float(period), float(window)

    def _fault_active_locked(self, channel: str, now_monotonic: float) -> bool:
        period, window = self._effective_fault_locked(channel)
        if period <= 0 or window <= 0:
            return False
        phase = (now_monotonic - self.control_monotonic) % period
        return phase < window

    def begin(self, channel: str, benchmark_id: str) -> tuple[dict[str, Any], dict[str, float], int | None]:
        now_wall = time.time()
        now_monotonic = time.monotonic()
        with self.lock:
            metric = self.metrics[channel]
            metric["attempts"] += 1
            if self._fault_active_locked(channel, now_monotonic):
                metric["fault"] += 1
                row = {
                    "benchmark_id": benchmark_id,
                    "channel": channel,
                    "status": 503,
                    "start": now_wall,
                    "end": now_wall,
                    "inflight": metric["inflight"],
                }
                metric["rows"].append(row)
                return row, {}, 503
            if metric["inflight"] >= self.channels[channel]["capacity"]:
                metric["rejected"] += 1
                row = {
                    "benchmark_id": benchmark_id,
                    "channel": channel,
                    "status": 429,
                    "start": now_wall,
                    "end": now_wall,
                    "inflight": metric["inflight"],
                }
                metric["rows"].append(row)
                return row, {}, 429

            metric["inflight"] += 1
            metric["max_inflight"] = max(metric["max_inflight"], metric["inflight"])
            row = {
                "benchmark_id": benchmark_id,
                "channel": channel,
                "status": None,
                "start": now_wall,
                "end": None,
                "inflight": metric["inflight"],
            }
            metric["rows"].append(row)
            timing = {
                "duration_s": self.duration_s,
                "first_token_s": min(self.first_token_s, self.duration_s),
            }
            return row, timing, None

    def finish(self, channel: str, row: dict[str, Any], success: bool) -> None:
        with self.lock:
            metric = self.metrics[channel]
            metric["inflight"] -= 1
            row["end"] = time.time()
            row["status"] = 200 if success else "client_disconnect"
            if success:
                metric["success"] += 1

    def _snapshot_locked(self, include_rows: bool) -> dict[str, Any]:
        channels: dict[str, Any] = {}
        for name, metric in self.metrics.items():
            item = {key: value for key, value in metric.items() if key != "rows"}
            period, window = self._effective_fault_locked(name)
            item["effective_config"] = {
                "capacity": self.channels[name]["capacity"],
                "fault_period_s": period,
                "fault_window_s": window,
            }
            item["overrides"] = {
                "fault_period_s": self.channels[name]["fault_period_s"],
                "fault_window_s": self.channels[name]["fault_window_s"],
            }
            if include_rows:
                item["rows"] = [dict(row) for row in metric["rows"]]
            channels[name] = item
        return {
            "control_epoch": time.time() - (time.monotonic() - self.control_monotonic),
            "duration_s": self.duration_s,
            "first_token_s": self.first_token_s,
            "fault_period_s": self.fault_period_s,
            "fault_window_s": self.fault_window_s,
            "channels": channels,
        }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return self._snapshot_locked(include_rows=True)


def _extract_benchmark_id(value: Any) -> str:
    if isinstance(value, dict):
        metadata = value.get("metadata")
        if isinstance(metadata, dict):
            candidate = metadata.get("benchmark_id")
            if isinstance(candidate, str) and candidate:
                return candidate[:256]
        for nested in value.values():
            found = _extract_benchmark_id(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _extract_benchmark_id(nested)
            if found:
                return found
    elif isinstance(value, str):
        match = BENCHMARK_ID_RE.search(value)
        if match:
            return match.group(0)[6:]
    return "missing"


def _responses_object(benchmark_id: str) -> dict[str, Any]:
    text = f"benchmark response {benchmark_id}"
    return {
        "id": f"resp_{benchmark_id}",
        "object": "response",
        "status": "completed",
        "model": "gpt-4o-mini",
        "output_text": text,
        "output": [{
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        }],
        "usage": {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
    }


def _chat_object(benchmark_id: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl_{benchmark_id}",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": f"benchmark response {benchmark_id}"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }


class MockHandler(BaseHTTPRequestHandler):
    server_version = "BenchmarkMock/1"

    @property
    def state(self) -> MockState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ControlError("invalid Content-Length") from exc
        if length < 0 or length > MAX_REQUEST_BODY:
            raise ControlError("request body too large", 413)
        data = self.rfile.read(length)
        try:
            payload = json.loads(data or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ControlError("invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ControlError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/ready":
            self._send_json(200, {"ready": True})
        elif path == "/metrics":
            self._send_json(200, self.state.snapshot())
        else:
            self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/control":
            try:
                result = self.state.apply_control(self._read_json())
                self._send_json(200, result)
            except ControlError as exc:
                self._send_json(exc.status, {"error": str(exc)})
            return

        match = re.fullmatch(r"/(a|b)/v1/(responses|chat/completions)", path)
        if not match:
            self._send_json(404, {"error": "not_found"})
            return
        channel, endpoint = match.groups()
        try:
            payload = self._read_json()
        except ControlError as exc:
            self._send_json(exc.status, {"error": str(exc)})
            return
        benchmark_id = _extract_benchmark_id(payload)
        row, timing, reject_status = self.state.begin(channel, benchmark_id)
        if reject_status is not None:
            self._send_json(reject_status, {"error": {"message": "simulated upstream rejection", "type": "benchmark_error"}})
            return

        stream = payload.get("stream") is True
        success = False
        try:
            if stream:
                self._serve_stream(endpoint, benchmark_id, timing)
            else:
                time.sleep(timing["duration_s"])
                response = _responses_object(benchmark_id) if endpoint == "responses" else _chat_object(benchmark_id)
                self._send_json(200, response)
            success = True
        except (BrokenPipeError, ConnectionResetError, OSError):
            success = False
        finally:
            self.state.finish(channel, row, success)

    def _write_sse(self, event: str | None, payload: Any) -> None:
        if event:
            self.wfile.write(f"event: {event}\n".encode("utf-8"))
        data = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _serve_stream(self, endpoint: str, benchmark_id: str, timing: dict[str, float]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        started = time.monotonic()
        if endpoint == "responses":
            self._write_sse("response.created", {"type": "response.created", "response": {"id": f"resp_{benchmark_id}", "status": "in_progress"}})
            time.sleep(timing["first_token_s"])
            self._write_sse("response.output_text.delta", {"type": "response.output_text.delta", "delta": f"benchmark response {benchmark_id}"})
            time.sleep(max(0.0, timing["duration_s"] - (time.monotonic() - started)))
            self._write_sse("response.completed", {"type": "response.completed", "response": _responses_object(benchmark_id)})
        else:
            time.sleep(timing["first_token_s"])
            self._write_sse(None, {"id": f"chatcmpl_{benchmark_id}", "choices": [{"delta": {"content": f"benchmark response {benchmark_id}"}, "finish_reason": None}]})
            time.sleep(max(0.0, timing["duration_s"] - (time.monotonic() - started)))
            self._write_sse(None, {"id": f"chatcmpl_{benchmark_id}", "choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}})
            self._write_sse(None, "[DONE]")


def make_server(host: str, port: int, state: MockState | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), MockHandler)
    server.daemon_threads = True
    server.state = state or MockState()  # type: ignore[attr-defined]
    return server


def _connection(url: str, timeout: float = REQUEST_TIMEOUT_S) -> tuple[http.client.HTTPConnection, str]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("URL must use http or https and include a host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if parts.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(parts.hostname, port, timeout=timeout, context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(parts.hostname, port, timeout=timeout)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return conn, path


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    conn, path = _connection(url)
    body = json.dumps(payload).encode("utf-8")
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
        response = conn.getresponse()
        data = response.read(MAX_REQUEST_BODY)
        parsed = json.loads(data)
        if response.status >= 400:
            raise ControlError(parsed.get("error", f"HTTP {response.status}"), response.status)
        return parsed
    finally:
        conn.close()


def get_json(url: str) -> dict[str, Any]:
    conn, path = _connection(url)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        data = response.read(MAX_REQUEST_BODY)
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}")
        return json.loads(data)
    finally:
        conn.close()


def _extract_responses_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    texts: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"].strip():
                    texts.append(part["text"].strip())
    return " ".join(texts)


def _extract_chat_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return ""
    texts: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            texts.append(message["content"].strip())
    return " ".join(item for item in texts if item)


def _set_read_timeout(response: http.client.HTTPResponse, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("request deadline exceeded")
    sock = None
    try:
        sock = response.fp.raw._sock  # type: ignore[union-attr]
    except AttributeError:
        pass
    if sock is not None:
        sock.settimeout(remaining)


def _read_sse(response: http.client.HTTPResponse, is_responses: bool, started: float, deadline: float) -> tuple[bool, float | None]:
    first_output_latency: float | None = None
    saw_text = False
    completed = False
    while True:
        _set_read_timeout(response, deadline)
        line = response.readline()
        if not line:
            break
        if not line.startswith(b"data:"):
            continue
        raw = line[5:].strip()
        if not raw or raw == b"[DONE]":
            continue
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if is_responses:
            event_type = event.get("type") if isinstance(event, dict) else None
            if event_type == "response.output_text.delta" and isinstance(event.get("delta"), str) and event["delta"].strip():
                saw_text = True
                if first_output_latency is None:
                    first_output_latency = time.monotonic() - started
            if event_type == "response.completed":
                final_response = event.get("response", event)
                completed = isinstance(final_response, dict) and final_response.get("status") == "completed" and bool(_extract_responses_text(final_response))
        else:
            choices = event.get("choices") if isinstance(event, dict) else None
            if isinstance(choices, list):
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta")
                    if isinstance(delta, dict) and isinstance(delta.get("content"), str) and delta["content"].strip():
                        saw_text = True
                        if first_output_latency is None:
                            first_output_latency = time.monotonic() - started
                    if choice.get("finish_reason") == "stop":
                        completed = True
    return saw_text and completed, first_output_latency


def _request_once(
    url: str,
    token: str,
    model: str,
    stream: bool,
    benchmark_id: str,
    scheduled_monotonic: float,
    scheduled_wall: float,
) -> dict[str, Any]:
    started_monotonic = time.monotonic()
    started_wall = time.time()
    deadline = started_monotonic + REQUEST_TIMEOUT_S
    row: dict[str, Any] = {
        "benchmark_id": benchmark_id,
        "scheduled_at": scheduled_wall,
        "started_at": started_wall,
        "ended_at": None,
        "scheduling_delay_s": max(0.0, started_monotonic - scheduled_monotonic),
        "status_code": None,
        "outcome": "transport_error",
        "latency_s": None,
        "first_output_latency_s": None,
    }
    is_responses = urlsplit(url).path.rstrip("/").endswith("/responses")
    prompt = f"BENCH:{benchmark_id} Return a short benchmark response."
    payload = {
        "model": model,
        "input" if is_responses else "messages": prompt if is_responses else [{"role": "user", "content": prompt}],
        "metadata": {"benchmark_id": benchmark_id},
        "stream": stream,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    conn: http.client.HTTPConnection | None = None
    try:
        conn, path = _connection(url, REQUEST_TIMEOUT_S)
        conn.request("POST", path, body=body, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Accept": "text/event-stream" if stream else "application/json",
        })
        response = conn.getresponse()
        row["status_code"] = response.status
        if response.status < 200 or response.status >= 300:
            _set_read_timeout(response, deadline)
            response.read(MAX_REQUEST_BODY)
            row["outcome"] = "http_error"
        elif stream:
            complete, first_output = _read_sse(response, is_responses, started_monotonic, deadline)
            row["first_output_latency_s"] = first_output
            row["outcome"] = "success" if complete else "stream_interrupted"
        else:
            _set_read_timeout(response, deadline)
            raw = response.read(MAX_REQUEST_BODY + 1)
            if len(raw) > MAX_REQUEST_BODY:
                row["outcome"] = "invalid_response"
            else:
                try:
                    parsed = json.loads(raw)
                    if is_responses:
                        complete = parsed.get("status") == "completed" and bool(_extract_responses_text(parsed))
                    else:
                        complete = bool(_extract_chat_text(parsed))
                    row["outcome"] = "success" if complete else "invalid_response"
                    if complete:
                        row["first_output_latency_s"] = time.monotonic() - started_monotonic
                except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                    row["outcome"] = "invalid_response"
    except Exception:
        row["outcome"] = "stream_interrupted" if stream and row["status_code"] is not None and 200 <= row["status_code"] < 300 else "transport_error"
    finally:
        if conn is not None:
            conn.close()
        ended_monotonic = time.monotonic()
        row["ended_at"] = time.time()
        row["latency_s"] = ended_monotonic - started_monotonic
    return row


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[rank]


def run_load(
    *,
    url: str,
    token_file: str,
    run_id: str,
    rps: float,
    duration: float,
    output: str | None,
    model: str,
    stream: bool,
) -> dict[str, Any]:
    if not math.isfinite(rps) or rps <= 0:
        raise ValueError("rps must be greater than zero")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be greater than zero")
    if not run_id or len(run_id) > 160:
        raise ValueError("run-id must contain 1 to 160 characters")
    token = Path(token_file).read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("token file is empty")
    planned = int(math.floor(rps * duration + 1e-9))
    if planned <= 0:
        raise ValueError("rps * duration must schedule at least one request")
    workers = min(128, max(1, int(math.ceil(rps * REQUEST_TIMEOUT_S))))
    interval = 1.0 / rps
    run_start_monotonic = time.monotonic()
    run_start_wall = time.time()
    futures = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="benchmark-load") as executor:
        for index in range(planned):
            target_monotonic = run_start_monotonic + index * interval
            delay = target_monotonic - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            benchmark_id = f"{run_id}-{index}"
            target_wall = run_start_wall + index * interval
            futures.append(executor.submit(
                _request_once,
                url,
                token,
                model,
                stream,
                benchmark_id,
                target_monotonic,
                target_wall,
            ))
        rows = [future.result() for future in as_completed(futures)]
    rows.sort(key=lambda item: item["scheduled_at"])
    whole_run_elapsed = time.monotonic() - run_start_monotonic
    send_window_ended_at = run_start_wall + duration
    last_actual_start_at = max((float(row["started_at"]) for row in rows), default=None)
    actual_started_within_window = sum(1 for row in rows if float(row["started_at"]) <= send_window_ended_at)

    outcomes = {name: 0 for name in ("success", "http_error", "stream_interrupted", "invalid_response", "transport_error")}
    for row in rows:
        outcomes[row["outcome"]] += 1
    success_rows = [row for row in rows if row["outcome"] == "success"]
    success_latencies = [float(row["latency_s"]) for row in success_rows]
    first_latencies = [float(row["first_output_latency_s"]) for row in success_rows if row["first_output_latency_s"] is not None]
    scheduling_delays = [float(row["scheduling_delay_s"]) for row in rows]
    summary = {
        "planned_requests": planned,
        "actual_sent": len(rows),
        "total_completed": outcomes["success"],
        **outcomes,
        "run_started_at": run_start_wall,
        "send_window_s": duration,
        "send_window_ended_at": send_window_ended_at,
        "last_actual_start_at": last_actual_start_at,
        "last_actual_start_offset_s": (last_actual_start_at - run_start_wall) if last_actual_start_at is not None else None,
        "actual_started_within_send_window": actual_started_within_window,
        "actual_start_rate_during_window_rps": actual_started_within_window / duration,
        "drain_elapsed_s": max(0.0, whole_run_elapsed - duration),
        "whole_run_elapsed_s": whole_run_elapsed,
        "whole_run_completed_rps": outcomes["success"] / whole_run_elapsed if whole_run_elapsed else 0.0,
        "latency_p95_s": _percentile(success_latencies, 0.95),
        "latency_p99_s": _percentile(success_latencies, 0.99),
        "first_output_p95_s": _percentile(first_latencies, 0.95),
        "first_output_p99_s": _percentile(first_latencies, 0.99),
        "scheduling_delay_p95_s": _percentile(scheduling_delays, 0.95),
        "scheduling_delay_p99_s": _percentile(scheduling_delays, 0.99),
        "workers": workers,
    }
    result = {
        "run_id": run_id,
        "url": url,
        "model": model,
        "stream": stream,
        "rps": rps,
        "duration_s": duration,
        "request_timeout_s": REQUEST_TIMEOUT_S,
        "summary": summary,
        "rows": rows,
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the mock upstream")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=18081)

    load = subparsers.add_parser("load", help="run a fixed-arrival load sample")
    load.add_argument("--url", required=True)
    load.add_argument("--token-file", required=True)
    load.add_argument("--run-id", required=True)
    load.add_argument("--rps", type=float, required=True)
    load.add_argument("--duration", type=float, required=True)
    load.add_argument("--output", required=True)
    load.add_argument("--model", default="gpt-4o-mini")
    load.add_argument("--stream", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "serve":
        server = make_server(args.host, args.port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0

    try:
        result = run_load(
            url=args.url,
            token_file=args.token_file,
            run_id=args.run_id,
            rps=args.rps,
            duration=args.duration,
            output=args.output,
            model=args.model,
            stream=args.stream,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result["summary"], ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
