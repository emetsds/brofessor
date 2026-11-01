"""Offline runner boundary tests. Never consume a provider subscription in CI."""

import json
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from brofessor import executors as ex

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}


@pytest.fixture(autouse=True)
def no_inherited_billing(monkeypatch):
    for name in ex._BILLING_ENV:
        monkeypatch.delenv(name, raising=False)


def fake_runner(monkeypatch, provider="codex", result=None, fail=None):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if "status" in args:
            if provider == "codex":
                return "", "Logged in using ChatGPT"
            return json.dumps(
                {"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}
            ), ""
        if fail:
            raise RuntimeError(fail)
        if provider == "codex":
            Path(args[args.index("-o") + 1]).write_text(json.dumps(result or {"answer": "ok"}))
            return "irrelevant event stream", ""
        return json.dumps(
            result
            or {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "structured_output": {"answer": "ok"},
            }
        ), ""

    monkeypatch.setattr(ex, "_run_process", run)
    monkeypatch.setattr(ex.shutil, "which", lambda name: "/fake/" + name)
    return calls


def test_codex_uses_stdin_subscription_and_restricted_isolated_session(tmp_path, monkeypatch):
    calls = fake_runner(monkeypatch)
    assert ex.generate("$(do not execute) private prompt", SCHEMA, "codex", workdir=tmp_path) == {
        "answer": "ok"
    }
    args, kwargs = calls[-1]
    assert "$(do not execute) private prompt" not in args
    assert kwargs["prompt"].endswith("$(do not execute) private prompt")
    for flag in (
        "--ignore-user-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--output-schema",
        "--ignore-rules",
    ):
        assert flag in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "features.shell_tool=false" in args
    assert 'web_search="disabled"' in args
    assert not kwargs["cwd"].exists()
    assert list(tmp_path.iterdir()) == []
    assert SCHEMA.get("required") is None


def test_claude_preserves_oauth_and_disables_tools(tmp_path, monkeypatch):
    calls = fake_runner(monkeypatch, "claude")
    assert ex.generate("hello", SCHEMA, "claude", "sonnet", workdir=tmp_path)["answer"] == "ok"
    args, _ = calls[-1]
    assert "--bare" not in args
    assert "--safe-mode" in args
    assert args[args.index("--tools") + 1] == ""
    assert "--no-session-persistence" in args
    assert args[args.index("--model") + 1] == "sonnet"


@pytest.mark.parametrize(
    "result",
    [
        {"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "secret"},
        {"type": "assistant", "structured_output": {"answer": "ok"}},
        {"type": "result", "subtype": "success", "result": '{"answer":"not structured"}'},
        {"type": "result", "subtype": "success", "structured_output": []},
    ],
)
def test_claude_requires_successful_structured_terminal_result(tmp_path, monkeypatch, result):
    fake_runner(monkeypatch, "claude", result=result)
    with pytest.raises(RuntimeError):
        ex.generate("hello", SCHEMA, "claude", workdir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_api_key_rejected_without_disclosing_value(tmp_path, monkeypatch):
    calls = fake_runner(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-leak-this")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY") as error:
        ex.generate("hello", SCHEMA, "codex", workdir=tmp_path)
    assert "do-not-leak-this" not in str(error.value)
    assert calls == []


def test_saved_api_auth_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(ex.shutil, "which", lambda name: name)
    monkeypatch.setattr(ex, "_run_process", lambda *a, **k: ("", "Logged in using an API key"))
    with pytest.raises(RuntimeError, match="ChatGPT"):
        ex.generate("hello", SCHEMA, "codex", workdir=tmp_path)


def test_cancelled_before_auth_never_spawns(tmp_path, monkeypatch):
    calls = fake_runner(monkeypatch)
    with pytest.raises(ex.CancelledError):
        ex.generate("hello", SCHEMA, "codex", workdir=tmp_path, cancelled=lambda: True)
    assert calls == []


def test_failed_process_cleans_up_tempfiles(tmp_path, monkeypatch):
    fake_runner(monkeypatch, fail="runner failed")
    with pytest.raises(RuntimeError, match="runner failed"):
        ex.generate("hello", SCHEMA, "codex", workdir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_subprocess_uses_input_without_shell_and_handles_output(tmp_path):
    result = ex._run_process(
        [sys.executable, "-c", "import sys; print(sys.stdin.read())"],
        cwd=tmp_path,
        prompt="$(echo unsafe)",
        timeout=2,
    )
    assert result[0].strip() == "$(echo unsafe)"


@pytest.mark.parametrize("cancel", [False, True])
def test_subprocess_timeout_and_cancel_terminate_group(tmp_path, cancel):
    marker = tmp_path / "descendant.txt"
    script = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable, '-c', "
        "'import time,pathlib; time.sleep(0.8); pathlib.Path(sys.argv[1]).write_text(\"alive\")', "
        "sys.argv[1]]); time.sleep(30)"
    )
    # Child imports sys itself; use a marker to verify grandchildren do not survive cancellation.
    script = script.replace("'import time,pathlib;", "'import time,pathlib,sys;")
    started = time.monotonic()
    with pytest.raises(ex.CancelledError if cancel else RuntimeError, match="cancel|timed out"):
        ex._run_process(
            [sys.executable, "-c", script, str(marker)],
            cwd=tmp_path,
            timeout=5 if cancel else 0.2,
            cancelled=(lambda: time.monotonic() - started > 0.2) if cancel else None,
        )
    time.sleep(0.9)
    assert not marker.exists()
    assert time.monotonic() - started < 3


def ollama_transport(monkeypatch, *, cloud_disabled=True, remote=False, chunks=None, status=200):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/status":
            return httpx.Response(status, json={"cloud": {"disabled": cloud_disabled}})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": "tiny:latest", "size": 1000, "digest": "sha256:abc"}]},
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "remote_host": "https://example.com" if remote else "",
                    "details": {"format": "gguf"},
                },
            )
        if request.url.path == "/api/chat":
            data = (
                chunks
                if chunks is not None
                else [
                    {"message": {"content": '{"answer":'}, "done": False},
                    {"message": {"content": '"local"}'}, "done": True, "done_reason": "stop"},
                ]
            )
            return httpx.Response(200, content="\n".join(json.dumps(row) for row in data))
        raise AssertionError(request.url)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        ex.httpx, "AsyncClient", lambda **kwargs: real_client(**kwargs, transport=transport)
    )
    return requests


@pytest.mark.parametrize("options,port", [({}, 11434), ({"ollama_port": 11435}, 11435)])
def test_ollama_checks_server_and_weights_before_sending_source(
    tmp_path, monkeypatch, options, port
):
    requests = ollama_transport(monkeypatch)
    assert ex.generate("hello", SCHEMA, "ollama", "tiny", workdir=tmp_path, **options) == {
        "answer": "local"
    }
    assert [r.url.path for r in requests] == ["/api/status", "/api/tags", "/api/show", "/api/chat"]
    assert all(str(r.url) == f"http://127.0.0.1:{port}{r.url.path}" for r in requests)
    body = json.loads(requests[-1].content)
    assert body["format"] == SCHEMA
    assert body["stream"] is True
    assert "tools" not in body


@pytest.mark.parametrize("options,port", [({}, 11434), ({"ollama_port": 11435}, 11435)])
@pytest.mark.parametrize("model", [None, "tiny"])
def test_ollama_doctor_uses_selected_port_without_generation(monkeypatch, options, port, model):
    requests = ollama_transport(monkeypatch)
    result = ex.doctor("ollama", model, **options)
    assert result["available"] is True
    assert result["local_only_verified"] is True
    paths = ["/api/status", "/api/tags"] + (["/api/show"] if model else [])
    assert [str(r.url) for r in requests] == [f"http://127.0.0.1:{port}{path}" for path in paths]


@pytest.mark.parametrize("port", [1, 11434, 65535])
def test_ollama_url_accepts_tcp_ports_on_fixed_loopback(port):
    assert ex.ollama_url(port) == f"http://127.0.0.1:{port}"


@pytest.mark.parametrize("port", [0, -1, 65536, True, False, 11435.0, "11435", None])
def test_invalid_ollama_port_fails_before_network(tmp_path, monkeypatch, port):
    requests = ollama_transport(monkeypatch)
    with pytest.raises(ValueError, match="Ollama port"):
        ex.ollama_url(port)
    with pytest.raises(ValueError, match="Ollama port"):
        ex.generate("hello", SCHEMA, "ollama", "tiny", workdir=tmp_path, ollama_port=port)
    result = ex.doctor("ollama", "tiny", ollama_port=port)
    assert result["available"] is False
    assert "Ollama port" in result["diagnostic"]
    assert requests == []


@pytest.mark.parametrize("port", [11434, 11435])
@pytest.mark.parametrize("options", [{"cloud_disabled": False}, {"remote": True}, {"status": 404}])
def test_ollama_localhost_is_not_proof_of_local_inference(tmp_path, monkeypatch, options, port):
    requests = ollama_transport(monkeypatch, **options)
    with pytest.raises(RuntimeError, match="cloud|remote|local-only"):
        ex.generate("private source", SCHEMA, "ollama", "tiny", workdir=tmp_path, ollama_port=port)
    assert "/api/chat" not in [r.url.path for r in requests]
    assert all(b"private source" not in r.content for r in requests)


@pytest.mark.parametrize(
    "model", ["tiny:cloud", "gpt-oss:120b-cloud", "cloud/model", "https://remote/model"]
)
def test_cloud_model_names_rejected_before_network(tmp_path, monkeypatch, model):
    requests = ollama_transport(monkeypatch)
    with pytest.raises(RuntimeError):
        ex.generate("hello", SCHEMA, "ollama", model, workdir=tmp_path)
    assert requests == []


@pytest.mark.parametrize(
    "chunks",
    [
        [{"message": {"content": '{"answer":"x"}'}, "done": False}],
        [{"message": {"content": '{"answer":"x"}'}, "done": True, "done_reason": "length"}],
        [{"message": {"content": "not json"}, "done": True}],
    ],
)
def test_incomplete_ollama_response_rejected(tmp_path, monkeypatch, chunks):
    ollama_transport(monkeypatch, chunks=chunks)
    with pytest.raises(RuntimeError):
        ex.generate("hello", SCHEMA, "ollama", "tiny", workdir=tmp_path)


def test_ollama_cancel_closes_pending_request(tmp_path, monkeypatch):
    import asyncio

    closed = threading.Event()

    async def stall(*args):
        try:
            await asyncio.sleep(20)
        finally:
            closed.set()

    monkeypatch.setattr(ex, "_ollama_request", stall)
    started = time.monotonic()
    with pytest.raises(ex.CancelledError):
        ex.generate(
            "hello",
            SCHEMA,
            "ollama",
            "tiny",
            workdir=tmp_path,
            cancelled=lambda: time.monotonic() - started > 0.1,
        )
    assert closed.is_set()
    assert time.monotonic() - started < 1


def test_process_output_limit_and_error_redaction(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "_MAX_BYTES", 128)
    with pytest.raises(RuntimeError, match="output limit"):
        ex._run_process([sys.executable, "-c", "print('x'*500)"], cwd=tmp_path)
    with pytest.raises(RuntimeError) as error:
        ex._run_process(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('secret-source-text'); sys.exit(4)",
            ],
            cwd=tmp_path,
        )
    assert "code 4" in str(error.value)
    assert "secret-source-text" not in str(error.value)


def test_ollama_deadline_cancels_pending_request(tmp_path, monkeypatch):
    import asyncio

    closed = threading.Event()

    async def stall(*args):
        try:
            await asyncio.sleep(20)
        finally:
            closed.set()

    monkeypatch.setattr(ex, "_ollama_request", stall)
    with pytest.raises(RuntimeError, match="timed out"):
        ex.generate("hello", SCHEMA, "ollama", "tiny", workdir=tmp_path, timeout=0.1)
    assert closed.is_set()


def test_ollama_network_failure_is_clear_runtime_error(tmp_path, monkeypatch):
    async def failed(*args):
        raise httpx.ConnectError("do not copy raw server diagnostics")

    monkeypatch.setattr(ex, "_ollama_request", failed)
    with pytest.raises(RuntimeError, match="Cannot reach local Ollama"):
        ex.generate("hello", SCHEMA, "ollama", "tiny", workdir=tmp_path)


def test_strict_schema_keeps_nullable_properties_and_does_not_mutate():
    schema = {
        "type": "object",
        "properties": {
            "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            "nested": {"type": "object", "properties": {"value": {"type": "integer"}}},
        },
    }
    result = ex._strict_schema(schema)
    assert result["additionalProperties"] is False
    assert result["required"] == ["maybe", "nested"]
    assert result["properties"]["nested"]["required"] == ["value"]
    assert result["properties"]["maybe"]["anyOf"][-1] == {"type": "null"}
    assert schema["properties"]["maybe"]["default"] is None


def test_successful_cli_does_not_leave_term_resistant_descendant(tmp_path):
    marker = tmp_path / "survived.txt"
    child = (
        "import pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "time.sleep(0.6); pathlib.Path(sys.argv[1]).write_text('alive')"
    )
    command = [sys.executable, "-c", child, str(marker)]
    parent = (
        "import subprocess,time; subprocess.Popen(" + repr(command) + "); "
        "time.sleep(0.1); print('complete')"
    )
    out, _ = ex._run_process([sys.executable, "-c", parent], cwd=tmp_path, timeout=3)
    assert out.strip() == "complete"
    time.sleep(0.7)
    assert not marker.exists()


def test_worker_sigkill_stops_owned_cli_without_touching_another_process(tmp_path):
    import os
    import signal
    import subprocess

    heartbeat = tmp_path / "heartbeat.txt"
    grandchild = (
        "import pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "path=pathlib.Path(sys.argv[1]); "
        "exec('while True:\\n path.write_text(str(time.monotonic_ns()))\\n time.sleep(.02)')"
    )
    cli = (
        "import subprocess,sys,time; subprocess.Popen("
        + repr([sys.executable, "-c", grandchild, str(heartbeat)])
        + "); time.sleep(30)"
    )
    parent = (
        "from pathlib import Path; from brofessor.executors import _run_process; "
        "_run_process("
        + repr([sys.executable, "-c", cli])
        + ", cwd=Path("
        + repr(str(tmp_path))
        + "), timeout=30)"
    )
    worker = subprocess.Popen([sys.executable, "-c", parent], start_new_session=True)
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], start_new_session=True
    )
    try:
        deadline = time.monotonic() + 5
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert heartbeat.exists(), "The synthetic CLI must start before killing its worker"
        os.kill(worker.pid, signal.SIGKILL)
        worker.wait(timeout=2)
        # Allow the lifeline reader, TERM grace, and SIGKILL cleanup to finish.
        time.sleep(0.5)
        stopped = heartbeat.read_text()
        time.sleep(0.25)
        assert heartbeat.read_text() == stopped
        assert unrelated.poll() is None
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=2)
        unrelated.terminate()
        unrelated.wait(timeout=2)
