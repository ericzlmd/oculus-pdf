import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PROMPT = (
    "Transcribe this page to Markdown. "
    "Preserve headings, lists, and reading order. "
    "Render tables as Markdown tables. "
    "For charts and images, add a one-line description in `[Figure: …]`. "
    "Do not summarize, add commentary, or guess illegible text; use `[illegible]`. "
    "Output only the Markdown."
)

TIMEOUT = 300


@dataclass(frozen=True)
class PageResult:
    markdown: str
    input_tokens: int
    output_tokens: int


def _parse(stdout: str) -> PageResult:
    markdown = ""
    input_tokens = 0
    output_tokens = 0
    for line in stdout.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event["type"] == "error":
            raise RuntimeError(json.dumps(event))
        if event["type"] == "text":
            markdown += event["part"]["text"]
        elif event["type"] == "step_finish":
            tokens = event["part"]["tokens"]
            input_tokens += tokens["input"]
            output_tokens += tokens["output"]
    return PageResult(
        markdown=markdown.strip(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def transcribe_page(
    model: str,
    png: bytes,
    retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> PageResult:
    for attempt in range(retries + 1):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                png_path = Path(tmp) / "page.png"
                png_path.write_bytes(png)
                completed = run(
                    [
                        "opencode",
                        "run",
                        "-m",
                        model,
                        "-f",
                        str(png_path),
                        "--format",
                        "json",
                        "--archived",
                        PROMPT,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT,
                )
            if completed.returncode != 0:
                raise RuntimeError(
                    completed.stderr.strip()
                    or f"opencode exited with code {completed.returncode}"
                )
            return _parse(completed.stdout)
        except Exception:
            if attempt == retries:
                raise
            sleep(2**attempt)
