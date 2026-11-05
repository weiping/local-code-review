#!/usr/bin/env python3
"""Materialize tasks/ and validate: initial code FAILS tests, reference code PASSES."""
import json, os, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import run_tests

ROOT = os.path.dirname(os.path.abspath(__file__))

TASKS = [
    # --- 简单局部修改 ---
    {"id": "a1-const-timeout", "category": "simple-local",
     "instruction": "config.py 里的超时时间 TIMEOUT 从 30 秒改为 60 秒，其余行为不变。",
     "files": {"config.py": 'TIMEOUT = 30\n\n\ndef build_request(url):\n    return {"url": url, "timeout": TIMEOUT}\n'},
     "reference": {"config.py": 'TIMEOUT = 60\n\n\ndef build_request(url):\n    return {"url": url, "timeout": TIMEOUT}\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
import config
assert config.TIMEOUT == 60, f"TIMEOUT={config.TIMEOUT}"
assert config.build_request("http://x")["timeout"] == 60
print("ok")
''', "allowed": ["config.py"]},

    {"id": "a2-default-param", "category": "simple-local",
     "instruction": '给 greet 增加一个可选参数 greeting，默认值 "Hello"；调用方传入 greeting 时用传入的问候语。',
     "files": {"greet.py": 'def greet(name):\n    return f"Hello, {name}!"\n'},
     "reference": {"greet.py": 'def greet(name, greeting="Hello"):\n    return f"{greeting}, {name}!"\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
from greet import greet
assert greet("Tom") == "Hello, Tom!"
assert greet("Tom", "Hi") == "Hi, Tom!"
print("ok")
''', "allowed": ["greet.py"]},

    {"id": "a3-off-by-one", "category": "simple-local",
     "instruction": "take 应该返回前 n 个元素，但当前实现跳过了第一个元素还越界多取，修复它。",
     "files": {"listutil.py": 'def take(xs, n):\n    """Return the first n elements."""\n    return xs[1:n + 1]\n'},
     "reference": {"listutil.py": 'def take(xs, n):\n    """Return the first n elements."""\n    return xs[:n]\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
from listutil import take
assert take([1, 2, 3, 4], 2) == [1, 2]
assert take([], 3) == []
assert take("abc", 2) == "ab"
print("ok")
''', "allowed": ["listutil.py"]},

    # --- 重复代码中的指定修改 ---
    {"id": "b1-ambig-methods", "category": "repeated-code",
     "instruction": "counters.py 里三个类的 reset 方法完全相同。只在 ClientB.reset 里、self.count = 0 之后加一行 self.logged = True；ClientA 和 ClientC 一行都不能动。",
     "files": {"counters.py": 'class ClientA:\n    def reset(self):\n        self.count = 0\n\n\nclass ClientB:\n    def reset(self):\n        self.count = 0\n\n\nclass ClientC:\n    def reset(self):\n        self.count = 0\n'},
     "reference": {"counters.py": 'class ClientA:\n    def reset(self):\n        self.count = 0\n\n\nclass ClientB:\n    def reset(self):\n        self.count = 0\n        self.logged = True\n\n\nclass ClientC:\n    def reset(self):\n        self.count = 0\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
from counters import ClientA, ClientB, ClientC
a, b, c = ClientA(), ClientB(), ClientC()
b.reset()
assert getattr(b, "logged", None) is True, "ClientB.reset did not set logged"
a.reset(); c.reset()
assert not hasattr(a, "logged"), "ClientA was modified"
assert not hasattr(c, "logged"), "ClientC was modified"
print("ok")
''', "allowed": ["counters.py"]},

    {"id": "b2-ambig-dict", "category": "repeated-code",
     "instruction": 'services.py 里 web 和 api 两个服务的配置行完全相同。只把 api 服务的 timeout 改为 60，web 服务的保持 30 不变。',
     "files": {"services.py": 'SERVICES = {\n    "web": {"host": "0.0.0.0", "timeout": 30},\n    "api": {"host": "0.0.0.0", "timeout": 30},\n}\n'},
     "reference": {"services.py": 'SERVICES = {\n    "web": {"host": "0.0.0.0", "timeout": 30},\n    "api": {"host": "0.0.0.0", "timeout": 60},\n}\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
from services import SERVICES
assert SERVICES["api"]["timeout"] == 60, SERVICES["api"]
assert SERVICES["web"]["timeout"] == 30, SERVICES["web"]
print("ok")
''', "allowed": ["services.py"]},

    {"id": "b3-ambig-block", "category": "repeated-code",
     "instruction": 'validate.py 里两个函数的空值校验块完全相同。只把 validate_email 的报错信息从 "empty" 改为 "email empty"；validate_name 一个字都不改。',
     "files": {"validate.py": 'def validate_name(value):\n    if not value:\n        raise ValueError("empty")\n    return value.strip()\n\n\ndef validate_email(value):\n    if not value:\n        raise ValueError("empty")\n    return value.strip().lower()\n'},
     "reference": {"validate.py": 'def validate_name(value):\n    if not value:\n        raise ValueError("empty")\n    return value.strip()\n\n\ndef validate_email(value):\n    if not value:\n        raise ValueError("email empty")\n    return value.strip().lower()\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
from validate import validate_name, validate_email
try:
    validate_name(""); raise SystemExit("validate_name did not raise")
except ValueError as e:
    assert str(e) == "empty", str(e)
try:
    validate_email(""); raise SystemExit("validate_email did not raise")
except ValueError as e:
    assert str(e) == "email empty", str(e)
assert validate_email(" A@B.C ") == "a@b.c"
assert validate_name("  x ") == "x"
print("ok")
''', "allowed": ["validate.py"]},

    # --- 缩进、空行、文件末尾 ---
    {"id": "c1-eof-version", "category": "whitespace-eof",
     "instruction": 'meta.py 里的版本号从 "1.0" 升到 "1.1"。',
     "files": {"meta.py": 'NAME = "demo"\nVERSION = "1.0"\n'},
     "reference": {"meta.py": 'NAME = "demo"\nVERSION = "1.1"\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
from meta import NAME, VERSION
assert VERSION == "1.1", VERSION
assert NAME == "demo"
print("ok")
''', "allowed": ["meta.py"]},

    {"id": "c2-indent-return", "category": "whitespace-eof",
     "instruction": "stats.py 的 total_positive 有缩进错误：return 语句在循环体里，导致只处理第一个元素就返回。把 return 移到循环结束后执行。",
     "files": {"stats.py": 'def total_positive(xs):\n    total = 0\n    for x in xs:\n        if x > 0:\n            total += x\n        return total\n'},
     "reference": {"stats.py": 'def total_positive(xs):\n    total = 0\n    for x in xs:\n        if x > 0:\n            total += x\n    return total\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
from stats import total_positive
assert total_positive([1, -1, 2]) == 3
assert total_positive([-5]) == 0
assert total_positive([]) == 0
print("ok")
''', "allowed": ["stats.py"]},

    {"id": "c3-blank-lines", "category": "whitespace-eof",
     "instruction": 'render 的分隔符从换行符改为分号加空格（"; "），函数里的空行保持原样。',
     "files": {"format.py": 'def render(items):\n    lines = []\n\n    for it in items:\n        lines.append(str(it))\n\n    return "\\n".join(lines)\n'},
     "reference": {"format.py": 'def render(items):\n    lines = []\n\n    for it in items:\n        lines.append(str(it))\n\n    return "; ".join(lines)\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
from format import render
assert render([1, 2, 3]) == "1; 2; 3", repr(render([1, 2, 3]))
assert render([]) == ""
print("ok")
''', "allowed": ["format.py"]},

    # --- 单文件多处修改 ---
    {"id": "d1-two-hunks", "category": "multi-hunk",
     "instruction": "config.py 里两处修改：TIMEOUT 从 30 改为 60；fetch 的重试次数从 3 次改为 5 次。",
     "files": {"config.py": 'import hashlib\n\nTIMEOUT = 30\n\n\ndef get(url, timeout):\n    raise ConnectionError("down")\n\n\ndef fetch(url):\n    for _ in range(3):\n        try:\n            return get(url, timeout=TIMEOUT)\n        except ConnectionError:\n            pass\n    raise ConnectionError("unreachable")\n\n\ndef cache_key(url):\n    return hashlib.md5(url.encode()).hexdigest()\n'},
     "reference": {"config.py": 'import hashlib\n\nTIMEOUT = 60\n\n\ndef get(url, timeout):\n    raise ConnectionError("down")\n\n\ndef fetch(url):\n    for _ in range(5):\n        try:\n            return get(url, timeout=TIMEOUT)\n        except ConnectionError:\n            pass\n    raise ConnectionError("unreachable")\n\n\ndef cache_key(url):\n    return hashlib.md5(url.encode()).hexdigest()\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
import config
assert config.TIMEOUT == 60, config.TIMEOUT
calls = {"n": 0}
def fake_get(url, timeout):
    calls["n"] += 1
    raise ConnectionError("down")
config.get = fake_get
try:
    config.fetch("http://x"); raise SystemExit("fetch did not raise")
except ConnectionError:
    pass
assert calls["n"] == 5, calls
assert config.cache_key("http://x")
print("ok")
''', "allowed": ["config.py"]},

    {"id": "d2-consistent-two-spots", "category": "multi-hunk",
     "instruction": "limits.py 默认重试次数从 3 改为 5；失败时报错信息里写死的次数也要跟着变（用 retries 变量，不要再写死 3）。两处一起改。",
     "files": {"limits.py": 'MAX_RETRIES = 3\n\n\ndef retry(fn, retries=MAX_RETRIES):\n    for _ in range(retries):\n        try:\n            return fn()\n        except Exception:\n            pass\n    raise RuntimeError("failed after %d attempts" % 3)\n'},
     "reference": {"limits.py": 'MAX_RETRIES = 5\n\n\ndef retry(fn, retries=MAX_RETRIES):\n    for _ in range(retries):\n        try:\n            return fn()\n        except Exception:\n            pass\n    raise RuntimeError("failed after %d attempts" % retries)\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
import limits
calls = {"n": 0}
def fail():
    calls["n"] += 1
    raise ValueError("x")
try:
    limits.retry(fail); raise SystemExit("no raise")
except RuntimeError as e:
    assert "5" in str(e), str(e)
assert calls["n"] == 5, calls
print("ok")
''', "allowed": ["limits.py"]},

    # --- 跨两个文件 ---
    {"id": "e1-cross-file-ttl", "category": "cross-file",
     "instruction": "默认缓存 TTL 从 300 秒改为 600 秒：settings.py 的 CACHE_TTL 和 cache.py 的 DEFAULT_TTL 要保持一致，两个文件都改。",
     "files": {"settings.py": 'CACHE_TTL = 300\n',
               "cache.py": 'DEFAULT_TTL = 300  # keep in sync with settings.CACHE_TTL\n\n\ndef ttl_for(key, default=None):\n    if default is not None:\n        return default\n    return DEFAULT_TTL\n'},
     "reference": {"settings.py": 'CACHE_TTL = 600\n',
                   "cache.py": 'DEFAULT_TTL = 600  # keep in sync with settings.CACHE_TTL\n\n\ndef ttl_for(key, default=None):\n    if default is not None:\n        return default\n    return DEFAULT_TTL\n'},
     "test": '''
import sys, os
sys.path.insert(0, os.environ["EVAL_WORKSPACE"])
import settings, cache
assert settings.CACHE_TTL == 600, settings.CACHE_TTL
assert cache.DEFAULT_TTL == 600, cache.DEFAULT_TTL
assert cache.ttl_for("x") == 600
assert cache.ttl_for("x", 7) == 7
print("ok")
''', "allowed": ["settings.py", "cache.py"]},
]


def materialize():
    tasks_dir = os.path.join(ROOT, "tasks")
    if os.path.isdir(tasks_dir):
        shutil.rmtree(tasks_dir)
    for t in TASKS:
        d = os.path.join(tasks_dir, t["id"])
        os.makedirs(os.path.join(d, "workspace"))
        os.makedirs(os.path.join(d, "tests"))
        for rel, content in t["files"].items():
            p = os.path.join(d, "workspace", rel)
            os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(rel) else None
            open(p, "w").write(content)
        open(os.path.join(d, "tests", f"test_{t['id']}.py"), "w").write(t["test"].lstrip())
        open(os.path.join(d, "task.json"), "w").write(json.dumps(
            {"id": t["id"], "category": t["category"], "instruction": t["instruction"],
             "visible_files": sorted(t["files"]), "allowed_write_files": t["allowed"],
             "timeout_seconds": 30}, indent=2, ensure_ascii=False))
        os.makedirs(os.path.join(d, "reference"))
        for rel, content in t["reference"].items():
            p = os.path.join(d, "reference", rel)
            open(p, "w").write(content)


def validate():
    tasks_dir = os.path.join(ROOT, "tasks")
    bad = 0
    for t in TASKS:
        d = os.path.join(tasks_dir, t["id"])
        test_file = os.path.join(d, "tests", f"test_{t['id']}.py")
        ok_initial, out_i = run_tests(os.path.join(d, "workspace"), test_file)
        ok_ref, out_r = run_tests(os.path.join(d, "reference"), test_file)
        status = []
        status.append("init-FAILS" if not ok_initial else "init-PASSES(!)")
        status.append("ref-PASSES" if ok_ref else "ref-FAILS(!)")
        flag = "ok" if (not ok_initial and ok_ref) else "BAD"
        if flag == "BAD":
            bad += 1
            print(f"[{flag}] {t['id']}: {' '.join(status)}")
            print("  initial out:", out_i[-200:])
            print("  reference out:", out_r[-200:])
        else:
            print(f"[{flag}] {t['id']}")
    return bad


if __name__ == "__main__":
    materialize()
    bad = validate()
    print(f"\n{len(TASKS)} tasks, {bad} bad")
    sys.exit(1 if bad else 0)
