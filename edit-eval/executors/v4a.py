"""V4A executor: strict outer envelope + OpenAI's official apply_diff.py (openai-agents-python, vendored).

Outer grammar (codex V4A):
    *** Begin Patch
    *** Update File: <path>      [optional: *** Move to: <path>]  then a diff body
    *** Add File: <path>         body of "+" lines only
    *** Delete File: <path>      no body
    *** End Patch

The inner diff of Update File is handed to the official apply_diff(), whose anchoring is
exact-line -> rstrip-tolerant -> strip-tolerant (fuzz counter), anchored by "@@ <anchor>" headers.
"""
import os
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")
sys.path.insert(0, _VENDOR)
from apply_diff import apply_diff  # noqa: E402


class EditError(ValueError):
    stage = "invalid_format"


class ContextNotFound(EditError):
    stage = "context_not_found"


def _check_path(path):
    if not path or path.startswith("/") or ".." in path.split("/") or path.split("/")[0] == "":
        raise EditError(f"forbidden path: {path!r}")
    return path


def apply(text, files):
    """Apply a V4A patch to the in-memory {path: content} dict. Raises EditError on any problem."""
    lines = text.split("\n")
    # tolerate leading/trailing blank lines only; anything else before Begin Patch is a format error
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or lines[i] != "*** Begin Patch":
        raise EditError("response must start with *** Begin Patch")
    i += 1

    ops = []
    closed = False
    while i < len(lines):
        line = lines[i]
        if line == "*** End Patch":
            closed = True
            i += 1
            break
        matched = False
        for prefix, op in (("*** Update File: ", "update"),
                           ("*** Add File: ", "add"),
                           ("*** Delete File: ", "delete")):
            if line.startswith(prefix):
                path = _check_path(line[len(prefix):].strip())
                i += 1
                move_to = None
                if op == "update" and i < len(lines) and lines[i].startswith("*** Move to: "):
                    move_to = _check_path(lines[i][len("*** Move to: "):].strip())
                    i += 1
                body = []
                while i < len(lines) and not lines[i].startswith("***"):
                    body.append(lines[i])
                    i += 1
                ops.append((op, path, move_to, body))
                matched = True
                break
        if not matched:
            if not line.strip():  # blank line between sections is tolerated
                i += 1
                continue
            raise EditError(f"unexpected line: {line[:60]!r}")

    if not closed:
        raise EditError("missing *** End Patch")
    trailing = [l for l in lines[i:] if l.strip()]
    if trailing:
        raise EditError("content after *** End Patch")
    if not ops:
        raise EditError("no operations in patch")

    for op, path, move_to, body in ops:
        if op == "add":
            if path in files:
                raise EditError(f"Add File: {path} already exists")
            try:
                files[path] = apply_diff("", "\n".join(body), mode="create")
            except ValueError as e:
                raise EditError(f"Add File {path}: {e}")
        elif op == "delete":
            if path not in files:
                raise EditError(f"Delete File: {path} missing")
            del files[path]
        else:
            if path not in files:
                raise EditError(f"Update File: {path} missing")
            try:
                files[path] = apply_diff(files[path], "\n".join(body))
            except ValueError as e:
                msg = str(e)
                if "Invalid Context" in msg or "Invalid Anchor" in msg or "Invalid EOF" in msg:
                    raise ContextNotFound(msg[:200])
                raise EditError(msg[:200])
            if move_to:
                if move_to in files:
                    raise EditError(f"Move to: {move_to} already exists")
                files[move_to] = files.pop(path)
    return files
