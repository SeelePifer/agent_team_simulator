import json
import os
import urllib.error
import urllib.request
from pathlib import Path

API_ROOT = "https://api.x.ai/v1"
MAX_TOOL_ROUNDS = 8


class GrokError(RuntimeError):
    pass


def load_env() -> None:
    path = Path(__file__).resolve().parents[3] / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def grok_api_key() -> str:
    load_env()
    key = os.environ.get("XAI_API_KEY", "").strip()
    if not key:
        raise GrokError("XAI_API_KEY is not set. Add it to the project .env file.")
    return key


def resolve_model(api_key: str) -> str:
    override = os.environ.get("XAI_MODEL", "").strip()
    if override:
        return override
    try:
        payload = _request("GET", "/models", api_key, None)
    except GrokError:
        return "grok-4"
    ids = [item.get("id", "") for item in payload.get("data", []) if item.get("id")]
    by_lower = {model_id.lower(): model_id for model_id in ids}
    for preferred in ("grok-4", "grok-4-fast", "grok-3", "grok-2-latest"):
        if preferred in by_lower:
            return by_lower[preferred]
    for model_id in ids:
        if "grok" in model_id.lower():
            return model_id
    return ids[0] if ids else "grok-4"


class GrokSession:
    def __init__(self, role: str, model: str, directory: Path, allow_write: bool) -> None:
        self.role = role
        self.model = model
        self.directory = directory.resolve()
        self.allow_write = allow_write
        self.messages: list[dict] = [{"role": "system", "content": _system_prompt(role, allow_write)}]

    def complete(self, prompt: str) -> str:
        self.messages.append({"role": "user", "content": prompt})
        api_key = grok_api_key()
        tools = _tools(self.allow_write)
        for _ in range(MAX_TOOL_ROUNDS):
            body: dict = {"model": self.model, "messages": self.messages, "temperature": 0.2}
            if tools:
                body["tools"] = tools
                body["tool_choice"] = "auto"
            payload = _request("POST", "/chat/completions", api_key, body)
            message = payload["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            self.messages.append(message)
            if not tool_calls:
                return message.get("content") or ""
            for call in tool_calls:
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": _run_tool(self.directory, self.allow_write, call),
                    }
                )
        raise GrokError(f"{self.role} stopped after {MAX_TOOL_ROUNDS} tool rounds")


def _request(method: str, path: str, api_key: str, body: dict | None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise GrokError(f"Grok request failed with HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise GrokError(f"Grok request failed: {exc.reason}") from None


def _system_prompt(role: str, allow_write: bool) -> str:
    if role == "reviewer":
        return (
            "You are the reviewer. Reply with only a JSON object, no markdown: "
            '{"score": <float 0 to 1>, "passed": <true or false>, "notes": "<one sentence>"}'
        )
    write_rule = "Use write_file to change files. Never edit test_stats.py." if allow_write else ""
    return (
        "You are a specialist on a small Python task. Use list_files and read_file before editing. "
        f"{write_rule} Stay inside the task directory."
    )


def _tools(allow_write: bool) -> list[dict]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files in the task directory.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a text file in the task directory.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
    ]
    if allow_write:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write a text file in the task directory. test_stats.py is forbidden.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    return tools


def _run_tool(directory: Path, allow_write: bool, call: dict) -> str:
    function = call.get("function") or {}
    name = function.get("name", "")
    try:
        arguments = json.loads(function.get("arguments") or "{}")
        if name == "list_files":
            names = sorted(path.name for path in directory.iterdir() if path.is_file())
            return "\n".join(names)
        if name == "read_file":
            return _read(directory, str(arguments.get("path", "")))
        if name == "write_file" and allow_write:
            return _write(directory, str(arguments.get("path", "")), str(arguments.get("content", "")))
        return f"unknown tool {name}"
    except (GrokError, OSError, json.JSONDecodeError) as exc:
        return str(exc)


def _read(directory: Path, relative: str) -> str:
    path = _safe_path(directory, relative)
    if not path.exists() or not path.is_file():
        return "file not found"
    return path.read_text(encoding="utf-8")[:40000]


def _write(directory: Path, relative: str, content: str) -> str:
    path = _safe_path(directory, relative)
    if path.name == "test_stats.py":
        return "refused: test_stats.py is read-only"
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.name}"


def _safe_path(directory: Path, relative: str) -> Path:
    candidate = (directory / relative).resolve()
    if not candidate.is_relative_to(directory):
        raise GrokError("path escapes the task directory")
    return candidate
