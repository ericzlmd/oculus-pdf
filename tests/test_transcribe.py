import json
import subprocess
from pathlib import Path

import pytest

from oculus_pdf.transcribe import PROMPT, PageResult, transcribe_page


def json_lines(*events: dict) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def text_event(text: str) -> dict:
    return {"type": "text", "part": {"type": "text", "text": text}}


def step_finish_event(input_tokens: int, output_tokens: int) -> dict:
    return {
        "type": "step_finish",
        "part": {
            "type": "step-finish",
            "reason": "stop",
            "cost": 0,
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "reasoning": 0,
                "cache": {"read": 0, "write": 0},
            },
        },
    }


def ok(stdout: str) -> dict:
    return {"returncode": 0, "stdout": stdout}


def failed(stderr: str) -> dict:
    return {"returncode": 1, "stdout": "", "stderr": stderr}


class FakeRun:
    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def __call__(self, args, **kwargs):
        self.calls.append({"args": args, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return subprocess.CompletedProcess(
            args=args,
            returncode=outcome.get("returncode", 0),
            stdout=outcome.get("stdout", ""),
            stderr=outcome.get("stderr", ""),
        )


def test_happy_path_joins_text_and_sums_tokens() -> None:
    run = FakeRun(
        [
            ok(
                json_lines(
                    {"type": "step_start", "part": {"type": "step-start"}},
                    text_event("# Report\n\n"),
                    text_event("Body\n"),
                    step_finish_event(100, 20),
                    step_finish_event(5, 7),
                )
            )
        ]
    )

    result = transcribe_page("provider/model", b"png-bytes", run=run)

    assert result == PageResult(
        markdown="# Report\n\nBody", input_tokens=105, output_tokens=27
    )


def test_command_shape_and_temp_file_lifetime() -> None:
    png = b"\x89PNG fake bytes"
    seen: dict = {}

    def run(args, **kwargs):
        path = Path(args[5])
        seen["args"] = args
        seen["kwargs"] = kwargs
        seen["existed"] = path.exists()
        seen["content"] = path.read_bytes()
        return subprocess.CompletedProcess(
            args, 0, stdout=json_lines(text_event("ok")), stderr=""
        )

    result = transcribe_page("provider/model", png, run=run)

    assert result == PageResult(markdown="ok", input_tokens=0, output_tokens=0)
    args = seen["args"]
    assert args[:5] == ["opencode", "run", "-m", "provider/model", "-f"]
    assert args[5].endswith(".png")
    assert args[args.index("--format") + 1] == "json"
    assert "--archived" in args
    assert args[-1] == PROMPT
    assert seen["existed"] is True
    assert seen["content"] == png
    assert not Path(args[5]).exists()
    assert seen["kwargs"] == {"capture_output": True, "text": True, "timeout": 300}


def test_no_step_finish_yields_zero_tokens() -> None:
    run = FakeRun([ok(json_lines(text_event("plain text")))])

    result = transcribe_page("model", b"png", run=run)

    assert result == PageResult(markdown="plain text", input_tokens=0, output_tokens=0)


def test_nonzero_returncode_raises_after_retries() -> None:
    run = FakeRun([failed("boom"), failed("boom"), failed("boom")])
    sleeps: list[float] = []

    with pytest.raises(RuntimeError, match="boom"):
        transcribe_page("model", b"png", sleep=sleeps.append, run=run)

    assert len(run.calls) == 3
    assert sleeps == [1, 2]


def test_error_event_raises() -> None:
    run = FakeRun([ok(json_lines({"type": "error", "error": "bad request"}))])

    with pytest.raises(RuntimeError, match="bad request"):
        transcribe_page("model", b"png", retries=0, run=run)


def test_fail_twice_then_succeeds() -> None:
    run = FakeRun(
        [
            subprocess.TimeoutExpired("opencode", 300),
            failed("boom"),
            ok(json_lines(text_event("ok"), step_finish_event(3, 4))),
        ]
    )
    sleeps: list[float] = []

    result = transcribe_page("model", b"png", sleep=sleeps.append, run=run)

    assert result == PageResult(markdown="ok", input_tokens=3, output_tokens=4)
    assert len(run.calls) == 3
    assert sleeps == [1, 2]


def test_temp_file_removed_after_failure() -> None:
    seen: dict = {}

    def run(args, **kwargs):
        path = Path(args[5])
        seen["path"] = path
        seen["existed"] = path.exists()
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    with pytest.raises(RuntimeError, match="boom"):
        transcribe_page("model", b"png", retries=0, run=run)

    assert seen["existed"] is True
    assert not seen["path"].exists()
