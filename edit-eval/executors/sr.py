"""Strict SEARCH/REPLACE executor (the old_str/new_str protocol of review.py, as text blocks).

Grammar:
    *** File: <path>
    <<<<<<< SEARCH
    <old lines>
    =======
    <new lines>
    >>>>>>> REPLACE

Rules: SEARCH must match the current file byte-for-byte (after joining lines) and exactly once;
zero or more than one match is an error. Blocks apply in order. No fuzzy matching, no indent fixes.
"""


class EditError(ValueError):
    stage = "invalid_format"


class Ambiguous(EditError):
    stage = "ambiguous_match"


class ContextNotFound(EditError):
    stage = "context_not_found"


def _check_path(path):
    if not path or path.startswith("/") or ".." in path.split("/") or path.split("/")[0] == "":
        raise EditError(f"forbidden path: {path!r}")
    return path


def apply(text, files):
    lines = text.split("\n")
    i = 0
    n_blocks = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if not line.startswith("*** File: "):
            raise EditError(f"unexpected line: {line[:60]!r}")
        path = _check_path(line[len("*** File: "):].strip())
        i += 1
        if i >= len(lines) or lines[i] != "<<<<<<< SEARCH":
            raise EditError("expected <<<<<<< SEARCH after *** File:")
        i += 1
        old = []
        while i < len(lines) and lines[i] != "=======":
            if lines[i].startswith(">>>>>>>") or lines[i].startswith("<<<<<<<") or lines[i].startswith("*** File: "):
                raise EditError("unexpected marker inside SEARCH block")
            old.append(lines[i])
            i += 1
        if i >= len(lines):
            raise EditError("missing =======")
        i += 1
        new = []
        while i < len(lines) and lines[i] != ">>>>>>> REPLACE":
            if lines[i].startswith("<<<<<<<") or lines[i].startswith("=======") or lines[i].startswith("*** File: "):
                raise EditError("unexpected marker inside REPLACE block")
            new.append(lines[i])
            i += 1
        if i >= len(lines):
            raise EditError("missing >>>>>>> REPLACE")
        i += 1
        n_blocks += 1

        old_s, new_s = "\n".join(old), "\n".join(new)
        content = files.get(path)
        if content is None:
            raise EditError(f"no such file: {path}")
        n = content.count(old_s) if old_s else 0
        if n == 0:
            raise ContextNotFound(f"SEARCH block not found in {path}")
        if n > 1:
            raise Ambiguous(f"SEARCH block occurs {n} times in {path}; it must match exactly once")
        files[path] = content.replace(old_s, new_s, 1)

    if n_blocks == 0:
        raise EditError("no edit blocks in response")
    return files
