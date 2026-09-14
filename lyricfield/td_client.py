"""HTTP client for the TouchDesigner MCP server (Web Server DAT on :9988).

Speaks the same JSON-RPC over POST /mcp that Claude Code uses, so the UI and the
CLI drive TD through exactly one path. Stdlib only -- no dependency on an MCP SDK.

TD is frequently unresponsive under load (heavy per-frame Script TOPs block the
web server thread), so every call takes a generous timeout and `wait_until_ready`
exists for the common "it will come back in a minute" case.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


DEFAULT_URL = "http://localhost:9988/mcp"


class TDError(RuntimeError):
    """A tool call reached TD but failed inside it."""


class TDUnavailable(RuntimeError):
    """TD is not reachable: closed, project not open, or web server stalled."""


@dataclass
class TDClient:
    url: str = DEFAULT_URL
    timeout: float = 120.0
    _next_id: int = 1

    # ---------- transport ----------

    def _post(self, payload: dict, timeout: float | None = None) -> dict:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode()
        except TimeoutError as e:
            raise TDUnavailable(
                f"TouchDesigner did not respond within {timeout or self.timeout}s "
                "(it stalls under load; try again shortly)"
            ) from e
        except (OSError, http.client.HTTPException) as e:
            # OSError covers URLError and, importantly, ConnectionResetError:
            # loading a project tears the web server down mid-request, so the
            # socket is reset rather than refused. Letting that escape as a bare
            # OSError made every project switch look like a crash.
            raise TDUnavailable(f"cannot reach TouchDesigner at {self.url}: {e}") from e
        if not raw.strip():
            return {}
        return json.loads(raw)

    def _rpc(self, method: str, params: dict | None = None, timeout: float | None = None) -> Any:
        msg = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        self._next_id += 1
        if params is not None:
            msg["params"] = params
        out = self._post(msg, timeout=timeout)
        if isinstance(out, list):
            out = out[0] if out else {}
        if "error" in out:
            raise TDError(out["error"].get("message", str(out["error"])))
        return out.get("result", {})

    # ---------- lifecycle ----------

    def ping(self, timeout: float = 5.0) -> bool:
        """Is TouchDesigner answering? Never raises -- callers poll this in a
        loop precisely when TD is in the middle of going away."""
        try:
            self._rpc("tools/list", timeout=timeout)
            return True
        except Exception:
            return False

    def wait_until_ready(self, seconds: float = 300.0, interval: float = 3.0,
                         should_stop=None) -> bool:
        """TD routinely blocks for 1-3 minutes while saving or under render load."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if should_stop is not None and should_stop():
                return False
            if self.ping():
                return True
            time.sleep(interval)
        return False

    def tools(self) -> list[str]:
        return [t["name"] for t in self._rpc("tools/list").get("tools", [])]

    # ---------- tools ----------

    #: Operators TD reported as erroring, from the most recent `run`. The
    #: server attaches this to every response; see `run`.
    last_op_errors: list = field(default_factory=list)

    def op_errors(self, path: str) -> str:
        """What TouchDesigner says is wrong with one operator, or "".

        A Script TOP that raises is not a broken *render* until something looks:
        the picture simply stops changing, the recorder writes nothing, and the
        only symptom is a timeout much later.
        """
        try:
            raw = self.call("inspect", path=path)
            info = json.loads(raw)
        except (TDError, json.JSONDecodeError, TypeError):
            return ""
        if not isinstance(info, dict):
            return ""
        return str(info.get("errors") or "").strip()

    def call(self, tool: str, timeout: float | None = None, **arguments) -> str:
        result = self._rpc(
            "tools/call",
            {"name": tool, "arguments": arguments},
            timeout=timeout,
        )
        parts = [
            c.get("text", "")
            for c in result.get("content", [])
            if c.get("type") == "text"
        ]
        text = "\n".join(parts)
        if result.get("isError"):
            raise TDError(text or f"{tool} failed")
        # The server also reports failure *inside* the payload without setting
        # isError -- e.g. the read-before-write guard. Missing this made writes
        # silently no-op while reporting success.
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
        if isinstance(payload, dict):
            if payload.get("error"):
                raise TDError(str(payload["error"]))
            if payload.get("ok") is False:
                raise TDError(str(payload))
        return text

    def run(self, code: str, timeout: float | None = None) -> str:
        """Execute Python inside TD and return just what the code printed.

        Wrap multi-statement code in a function -- the exec scope gives
        module-level names no visibility inside nested defs or comprehensions.
        """
        raw = self.call("run", code=code, timeout=timeout)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        # The server scans the whole network for operators in an error state and
        # attaches the result to EVERY run response. Nothing ever read it. A
        # Script TOP raising NameError on every cook sat in these payloads for
        # thirty minutes while a render waited for a file that could not be
        # written, and the run finally failed reporting the missing file.
        # Keeping the last scan costs nothing and makes the real cause
        # available to anyone who asks.
        w = payload.get("warnings")
        if isinstance(w, list):
            self.last_op_errors = w
        # printed output lands in "output"; a bare expression lands in "result"
        if payload.get("output"):
            return payload["output"]
        res = payload.get("result")
        return "" if res is None else str(res)

    def read(self, path: str) -> str:
        """Display-formatted DAT contents -- every line carries a line-number
        prefix, so this is for looking at, not for parsing. Use `dat_text`
        when the contents need to be consumed."""
        return self.call("read", path=path)

    def dat_text(self, path: str) -> str:
        """A DAT's exact text, with no line numbering or truncation."""
        sentinel = "<<<lyricfield>>>"
        out = self.run(
            "def main():\n"
            f"    d = op({path!r})\n"
            "    if d is None:\n"
            "        return ''\n"
            "    rows = []\n"
            "    for r in range(d.numRows):\n"
            "        rows.append('\\t'.join(d[r, c].val for c in range(d.numCols)))\n"
            "    return '\\n'.join(rows)\n"
            f"print({sentinel!r})\n"
            "print(main())"
        )
        _, _, body = out.partition(sentinel)
        return body.lstrip("\n").rstrip("\n")

    def write(self, path: str, content: str) -> str:
        """Overwrite a DAT's contents.

        The server refuses to overwrite a DAT this session has not read, as a
        guard against clobbering work. Satisfy it by reading first -- otherwise
        the write is rejected inside the payload and looks like a success.
        """
        try:
            self.call("read", path=path)
        except TDError:
            pass                      # new DAT: nothing to read, write creates it
        return self.call("write", path=path, content=content)

    def render(self, output: str, duration: float, top: str,
               fps: int = 30, audio_chop: str | None = None) -> str:
        kw = dict(output=output, duration=duration, top=top, fps=fps)
        if audio_chop:
            kw["audio_chop"] = audio_chop
        return self.call("render", **kw)


def client_from_env() -> TDClient:
    import os
    return TDClient(url=os.environ.get("LYRICFIELD_TD_URL", DEFAULT_URL))
