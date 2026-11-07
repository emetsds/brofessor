"""Offline runner boundary tests. Never consume a provider subscription in CI."""

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import httpx2 as httpx
import pytest

from brofessor.contracts.jobs import JobKind
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.text import runners as ex

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}


def test_ollama_waits_for_model_cleanup_and_can_cancel_before_sending_source(tmp_path, monkeypatch):
    from brofessor.infrastructure.storage.locks import models_lock

    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= 3

    async def unexpected(*args):
        pytest.fail("Source must not be sent while model cleanup holds the lock")

    monkeypatch.setattr(ex, "_bounded_ollama", unexpected)
    with models_lock(exclusive=True):
        with pytest.raises(ex.CancelledError):
            ex.generate(
                "source",
                SCHEMA,
                TextProvider.OLLAMA,
                "local",
                workdir=tmp_path,
                cancelled=cancelled,
            )


@pytest.fixture(autouse=True)
def no_inherited_billing(monkeypatch):
    for name in ex._BILLING_ENV:
        monkeypatch.delenv(name, raising=False)


def fake_runner(monkeypatch, provider="codex", result=None, fail=None, auth_status=None):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if "status" in args:
            if provider == "codex":
                return "", "Logged in using ChatGPT"
            return json.dumps(
                auth_status
                or {"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}
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
        "--json",
        "--ignore-rules",
    ):
        assert flag in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "features.shell_tool=false" in args
    assert 'web_search="disabled"' in args
    assert not kwargs["cwd"].exists()
    assert list(tmp_path.iterdir()) == []
    assert SCHEMA.get("required") is None


@pytest.mark.parametrize("auth_method", ["oauth_token", "claude.ai", "claude_ai"])
def test_claude_preserves_oauth_and_disables_tools(tmp_path, monkeypatch, auth_method):
    calls = fake_runner(
        monkeypatch,
        "claude",
        auth_status={"loggedIn": True, "authMethod": auth_method, "apiProvider": "firstParty"},
    )
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
        ex.generate("hello", SCHEMA, TextProvider.CLAUDE, workdir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_api_key_rejected_without_disclosing_value(tmp_path, monkeypatch):
    calls = fake_runner(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-leak-this")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY") as error:
        ex.generate("hello", SCHEMA, TextProvider.CODEX, workdir=tmp_path)
    assert "do-not-leak-this" not in str(error.value)
    assert calls == []


def test_saved_api_auth_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(ex.shutil, "which", lambda name: name)
    monkeypatch.setattr(ex, "_run_process", lambda *a, **k: ("", "Logged in using an API key"))
    with pytest.raises(RuntimeError, match="ChatGPT"):
        ex.generate("hello", SCHEMA, TextProvider.CODEX, workdir=tmp_path)


@pytest.mark.parametrize(
    "status",
    [
        {"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"},
        {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"},
        {"loggedIn": True, "authMethod": "api_key_helper", "apiProvider": "firstParty"},
        {"loggedIn": True, "authMethod": "third_party", "apiProvider": "bedrock"},
        {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "vertex"},
    ],
)
def test_claude_rejects_missing_subscription_or_other_billing_before_generation(
    tmp_path, monkeypatch, status
):
    calls = fake_runner(monkeypatch, "claude", auth_status=status)
    with pytest.raises(RuntimeError, match="claude auth login"):
        ex.generate("private source", SCHEMA, TextProvider.CLAUDE, workdir=tmp_path)
    assert len(calls) == 1
    assert "prompt" not in calls[0][1]
    assert list(tmp_path.iterdir()) == []


def test_claude_logged_out_status_is_actionable_without_generation(tmp_path, monkeypatch):
    binary = tmp_path / "claude-fixture"
    marker = tmp_path / "inference-started"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('2.1.317 (Claude Code)')\n"
        "elif sys.argv[1:] == ['auth', 'status', '--json']:\n"
        "    print(json.dumps({'loggedIn': False, 'authMethod': 'none', "
        "'apiProvider': 'firstParty'}))\n"
        "    sys.exit(1)\n"
        "else:\n"
        f"    pathlib.Path({str(marker)!r}).touch()\n"
        "    sys.exit(88)\n"
    )
    binary.chmod(0o700)
    monkeypatch.setenv("BROFESSOR_CLAUDE_BIN", str(binary))
    diagnosis = ex.doctor("claude")
    assert not diagnosis["available"]
    assert "claude auth login" in diagnosis["diagnostic"]
    with pytest.raises(RuntimeError, match="claude auth login"):
        ex.generate("private source", SCHEMA, TextProvider.CLAUDE, workdir=tmp_path / "jobs")
    assert not marker.exists()
    assert list((tmp_path / "jobs").iterdir()) == []


def test_cancelled_before_auth_never_spawns(tmp_path, monkeypatch):
    calls = fake_runner(monkeypatch)
    with pytest.raises(ex.CancelledError):
        ex.generate("hello", SCHEMA, TextProvider.CODEX, workdir=tmp_path, cancelled=lambda: True)
    assert calls == []


def test_failed_process_cleans_up_tempfiles(tmp_path, monkeypatch):
    fake_runner(monkeypatch, fail="runner failed")
    with pytest.raises(RuntimeError, match="runner failed"):
        ex.generate("hello", SCHEMA, TextProvider.CODEX, workdir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_subprocess_uses_input_without_shell_and_handles_output(tmp_path):
    result = ex._run_process(
        [sys.executable, "-c", "import sys; print(sys.stdin.read())"],
        cwd=tmp_path,
        prompt="$(echo unsafe)",
        timeout=10,
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


def ollama_chunk(content, finish_reason=None, **delta):
    return {
        "id": "local",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "tiny",
        "choices": [
            {"index": 0, "delta": {"content": content, **delta}, "finish_reason": finish_reason}
        ],
    }


class PendingOllamaStream(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = threading.Event()
        self.started = None

    async def __aiter__(self):
        self.started = time.monotonic()
        await asyncio.sleep(20)
        yield b""

    async def aclose(self):
        self.closed.set()


def ollama_transport(
    monkeypatch,
    *,
    cloud_disabled=True,
    remote=False,
    chunks=None,
    status=200,
    thinking=None,
    redirect_to=None,
    generation_status=200,
    stream=None,
    response_headers=None,
):
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
                    **({"thinking": thinking} if thinking is not None else {}),
                },
            )
        if request.url.path == "/v1/chat/completions":
            if redirect_to and request.url.host != "untrusted.invalid":
                return httpx.Response(307, headers={"Location": redirect_to})
            data = (
                chunks
                if chunks is not None
                else [
                    ollama_chunk('{"answer":'),
                    ollama_chunk('"local"}', "stop"),
                ]
            )
            return httpx.Response(
                generation_status,
                **(
                    {"stream": stream}
                    if stream is not None
                    else {
                        "content": "".join("data: " + json.dumps(row) + "\n\n" for row in data)
                        + "data: [DONE]\n\n"
                    }
                ),
                headers={"content-type": "text/event-stream", **(response_headers or {})},
            )
        raise AssertionError(request.url)

    transport = httpx.MockTransport(handler)

    async def send(self, request):
        return await transport.handle_async_request(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    return requests


@pytest.mark.parametrize(
    "options,address",
    [
        ({}, "127.0.0.1:11434"),
        ({"ollama_address": "192.168.50.10:11435"}, "192.168.50.10:11435"),
        ({"ollama_address": "[::1]:11435"}, "[::1]:11435"),
        ({"ollama_address": "127.0.0.1:1"}, "127.0.0.1:1"),
        ({"ollama_address": "192.168.50.10:65535"}, "192.168.50.10:65535"),
    ],
)
def test_ollama_checks_server_and_weights_before_sending_source(
    tmp_path, monkeypatch, options, address
):
    requests = ollama_transport(monkeypatch)
    assert ex.generate("hello", SCHEMA, "ollama", "tiny", workdir=tmp_path, **options) == {
        "answer": "local"
    }
    assert [r.url.path for r in requests] == [
        "/api/status",
        "/api/tags",
        "/api/show",
        "/v1/chat/completions",
    ]
    assert all(str(r.url) == f"http://{address}{r.url.path}" for r in requests)
    body = json.loads(requests[-1].content)
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert body["messages"] == ex.prompts.messages("hello", "ollama")
    assert body["stream"] is True
    assert "tools" not in body


@pytest.mark.parametrize(
    "thinking,disabled",
    [
        ({"values": [False, "medium"], "default": "medium"}, True),
        ({"values": [False]}, True),
        ({"values": ["low", "high"], "default": "high"}, False),
        ({"values": [0]}, False),
        (None, False),
    ],
)
def test_ollama_disables_thinking_only_when_model_advertises_support(
    tmp_path, monkeypatch, thinking, disabled
):
    requests = ollama_transport(monkeypatch, thinking=thinking)
    ex.generate("hello", SCHEMA, TextProvider.OLLAMA, "tiny", workdir=tmp_path)
    body = json.loads(requests[-1].content)
    if disabled:
        assert body["reasoning_effort"] == "none"
    else:
        assert "reasoning_effort" not in body


@pytest.mark.parametrize(
    "options,address,model",
    [
        ({}, "127.0.0.1:11434", None),
        ({"ollama_address": "192.168.50.10:11435"}, "192.168.50.10:11435", "tiny"),
    ],
)
def test_ollama_doctor_checks_selected_server_without_generating(
    monkeypatch, options, address, model
):
    requests = ollama_transport(monkeypatch)
    result = ex.doctor("ollama", model, **options)
    assert result["available"] is True and result["cloud_disabled_verified"] is True
    paths = ["/api/status", "/api/tags"] + (["/api/show"] if model else [])
    assert [str(r.url) for r in requests] == [f"http://{address}{path}" for path in paths]


def test_ollama_address_normalizes_equivalent_inputs():
    assert ex.normalize_ollama_address(" 192.168.50.10:011435 ") == "192.168.50.10:11435"
    assert ex.normalize_ollama_address("[0:0:0:0:0:0:0:1]:11434") == "[::1]:11434"


@pytest.mark.parametrize(
    "address",
    [
        None,
        True,
        11434,
        "127.0.0.1",
        "localhost:11434",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "http://127.0.0.1:11434",
        "user:pass@127.0.0.1:11434",
        "127.0.0.1:11434/path",
        "127.0.0.1:11434?x=1",
        "127.0.0.1:11434#x",
        "@127.0.0.1:11434",
        "127.0.0.1:11434?",
        "127.0.0.1:11434#",
        "127.0.0.1\n:11434",
    ],
)
def test_invalid_ollama_address_is_rejected(address):
    with pytest.raises(ValueError, match="Ollama address"):
        ex.normalize_ollama_address(address)


def test_invalid_server_settings_never_receive_source_and_doctor_explains_failure(
    tmp_path, monkeypatch
):
    requests = ollama_transport(monkeypatch)
    address = "192.168.50.10:65536"
    with pytest.raises(ValueError, match="Ollama address"):
        ex.generate(
            "A private source marker",
            SCHEMA,
            TextProvider.OLLAMA,
            "tiny",
            workdir=tmp_path,
            ollama_address=address,
        )
    result = ex.doctor("ollama", "tiny", ollama_address=address)
    assert result["available"] is False and "Ollama address" in result["diagnostic"]
    assert requests == []


@pytest.mark.parametrize("address", ["127.0.0.1:11434", "192.168.50.10:11435", "[::1]:11434"])
@pytest.mark.parametrize("options", [{"cloud_disabled": False}, {"remote": True}, {"status": 404}])
def test_ollama_address_is_not_proof_of_server_local_inference(
    tmp_path, monkeypatch, options, address
):
    requests = ollama_transport(monkeypatch, **options)
    with pytest.raises(RuntimeError, match="cloud|remote|local-only"):
        ex.generate(
            "private source",
            SCHEMA,
            TextProvider.OLLAMA,
            "tiny",
            workdir=tmp_path,
            ollama_address=address,
        )
    assert "/v1/chat/completions" not in [r.url.path for r in requests]
    assert all(b"private source" not in r.content for r in requests)


@pytest.mark.parametrize(
    "model", ["tiny:cloud", "gpt-oss:120b-cloud", "cloud/model", "https://remote/model"]
)
def test_cloud_model_names_rejected_before_network(tmp_path, monkeypatch, model):
    requests = ollama_transport(monkeypatch)
    with pytest.raises(RuntimeError):
        ex.generate("hello", SCHEMA, TextProvider.OLLAMA, model, workdir=tmp_path)
    assert requests == []


@pytest.mark.parametrize(
    "chunks",
    [
        [ollama_chunk('{"answer":"x"}')],
        [ollama_chunk('{"answer":"x"}', "length")],
        [ollama_chunk("not json", "stop")],
        [
            ollama_chunk(
                '{"answer":"x"}',
                "tool_calls",
                tool_calls=[
                    {
                        "index": 0,
                        "id": "unexpected",
                        "type": "function",
                        "function": {"name": "shell", "arguments": "{}"},
                    }
                ],
            )
        ],
    ],
)
def test_incomplete_ollama_response_rejected(tmp_path, monkeypatch, chunks):
    ollama_transport(monkeypatch, chunks=chunks)
    with pytest.raises(RuntimeError):
        ex.generate("hello", SCHEMA, TextProvider.OLLAMA, "tiny", workdir=tmp_path)


def test_ollama_redirect_never_forwards_source_to_another_host(tmp_path, monkeypatch):
    requests = ollama_transport(
        monkeypatch, redirect_to="http://untrusted.invalid/v1/chat/completions"
    )
    with pytest.raises(RuntimeError):
        ex.generate(
            "Synthetic private-source marker; do not forward.",
            SCHEMA,
            TextProvider.OLLAMA,
            "tiny",
            ollama_address="192.168.50.10:11435",
            workdir=tmp_path,
        )
    assert not any(request.url.host == "untrusted.invalid" for request in requests)


def test_ollama_cancel_closes_pending_request(tmp_path, monkeypatch):
    stream = PendingOllamaStream()
    ollama_transport(monkeypatch, stream=stream)
    with pytest.raises(ex.CancelledError):
        ex.generate(
            "hello",
            SCHEMA,
            TextProvider.OLLAMA,
            "tiny",
            workdir=tmp_path,
            cancelled=lambda: (
                stream.started is not None and time.monotonic() - stream.started > 0.1
            ),
        )
    assert stream.closed.is_set()
    assert time.monotonic() - stream.started < 1


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
    stream = PendingOllamaStream()
    ollama_transport(monkeypatch, stream=stream)
    with pytest.raises(RuntimeError, match="timed out"):
        ex.generate("hello", SCHEMA, TextProvider.OLLAMA, "tiny", workdir=tmp_path, timeout=1)
    assert stream.closed.is_set()


def test_ollama_sdk_failure_has_no_hidden_retry_or_source_in_diagnostic(tmp_path, monkeypatch):
    requests = ollama_transport(monkeypatch, generation_status=503)
    with pytest.raises(RuntimeError, match="HTTP 503") as error:
        ex.generate("private source marker", SCHEMA, TextProvider.OLLAMA, "tiny", workdir=tmp_path)
    assert "private source marker" not in str(error.value)
    assert sum(r.url.path == "/v1/chat/completions" for r in requests) == 1


def test_ollama_sdk_preserves_schema_and_ignores_cloud_client_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid/v1")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://untrusted.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "private-key-marker")
    monkeypatch.setenv("OLLAMA_API_KEY", "private-key-marker")
    schema = {
        **SCHEMA,
        "title": "SavedResult",
        "properties": {
            "answer": {"type": "string", "minLength": 1, "maxLength": 200},
            "nested": {
                "type": "object",
                "properties": {"optional": {"type": "null", "default": None}},
            },
        },
    }
    original = json.loads(json.dumps(schema))
    requests = ollama_transport(monkeypatch)
    ex.generate("hello", schema, TextProvider.OLLAMA, "tiny", workdir=tmp_path)
    body = json.loads(requests[-1].content)
    assert body["response_format"]["json_schema"]["schema"] == original == schema
    assert all(r.url.host == "127.0.0.1" for r in requests)
    assert requests[-1].headers["authorization"] == "Bearer ollama"


def test_ollama_sdk_checkpoint_preserves_user_edit_without_another_request(tmp_path, monkeypatch):
    from brofessor.application import pipeline, service
    from brofessor.infrastructure.storage.workspace import Workspace

    source = tmp_path / "source.md"
    source.write_text("A bridge carried 1200 kilograms. Flood resistance is unknown.")
    workspace = Workspace(tmp_path / "project")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    answer = {
        "answer": "1200 kilograms; flood resistance is unknown.",
        "citations": [citation],
        "quotes": [{"citation": citation, "text": "1200 kilograms"}],
    }
    requests = ollama_transport(monkeypatch, chunks=[ollama_chunk(json.dumps(answer), "stop")])
    job = service.submit(
        workspace,
        JobKind.ASK,
        focus="Load?",
        provider=TextProvider.OLLAMA,
        model="tiny",
        start_worker=False,
    )
    pipeline.execute(workspace, job)
    draft = workspace.draft(job["id"])
    service.edit_draft(workspace, job["id"], {**draft["data"], "answer": "My saved edit"}, 1)
    before = len(requests)
    pipeline.execute(workspace, job)
    assert len(requests) == before
    assert workspace.draft(job["id"])["revision"] == 2
    assert workspace.draft(job["id"])["data"]["answer"] == "My saved edit"


def test_ollama_wire_limit_stops_sdk_before_buffering_large_output(tmp_path, monkeypatch):
    class LargeStream(httpx.AsyncByteStream):
        closed = False
        reads = 0

        async def __aiter__(self):
            for _ in range(20):
                self.reads += 1
                yield b"x" * 1024

        async def aclose(self):
            self.closed = True

    stream = LargeStream()
    ollama_transport(monkeypatch, stream=stream)
    monkeypatch.setattr(ex, "_MAX_BYTES", 4096)
    with pytest.raises(RuntimeError, match="output limit"):
        ex.generate("hello", SCHEMA, TextProvider.OLLAMA, "tiny", workdir=tmp_path)
    assert stream.closed
    assert stream.reads < 20


def test_ollama_compression_cannot_bypass_output_limit(tmp_path, monkeypatch):
    stream = PendingOllamaStream()
    requests = ollama_transport(
        monkeypatch, stream=stream, response_headers={"content-encoding": "gzip"}
    )
    with pytest.raises(RuntimeError):
        ex.generate("hello", SCHEMA, TextProvider.OLLAMA, "tiny", workdir=tmp_path)
    assert requests[-1].headers["accept-encoding"] == "identity"
    assert stream.started is None
    assert stream.closed.is_set()


def test_ollama_network_failure_is_clear_runtime_error(tmp_path, monkeypatch):
    async def failed(*args):
        raise httpx.ConnectError("do not copy raw server diagnostics")

    monkeypatch.setattr(ex, "_ollama_request", failed)
    with pytest.raises(RuntimeError, match="Cannot reach the selected Ollama server"):
        ex.generate("hello", SCHEMA, TextProvider.OLLAMA, "tiny", workdir=tmp_path)


def test_strict_schema_keeps_nullable_properties_and_does_not_mutate():
    schema = {
        "type": "object",
        "properties": {
            "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            "nested": {"type": "object", "properties": {"value": {"type": "integer"}}},
            "answers": {"type": "object", "additionalProperties": {"type": "string"}},
        },
    }
    result = ex._strict_schema(schema)
    assert result["additionalProperties"] is False
    assert result["required"] == ["maybe", "nested", "answers"]
    assert result["properties"]["nested"]["required"] == ["value"]
    assert result["properties"]["maybe"]["anyOf"][-1] == {"type": "null"}
    assert schema["properties"]["maybe"]["default"] is None
    # Official Codex rejects an object without properties, even when it must be empty.
    assert result["properties"]["answers"] == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


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
        "from pathlib import Path; from brofessor.infrastructure.text.runners import _run_process; "
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
