# -*- coding: utf-8 -*-
"""parsers.py —— 測試輸出 parser registry。

每個 parser:  (text: str) -> (passed: int|None, failed: int|None, failure_names: list[str])

text 是 profile 的 verify_command 的輸出（loop 的 run_command 會在最前面加 [exit=N]）。
- passed/failed 給人看的計數（None = 該框架沒提供）。
- failure_names 給「baseline 排除」用 —— loop 用它算「DeepSeek 引入的新紅燈」。
  框架若給不出逐測試名，回 [] 或一個佔位字串（baseline 排除就退化成「fail 數有沒有變」）。

新框架：在這裡加一個 parse_xxx + 註冊進 REGISTRY 即可。profile 用 "parser": "xxx" 選。
"""
import re


def _exit_code(text):
    m = re.search(r"\[exit=(-?\d+)\]", text)
    return int(m.group(1)) if m else None


def parse_generic(text):
    """只看 exit code：0 = 全過、非 0 = 失敗。沒有逐測試名（最通用的保底）。"""
    rc = _exit_code(text)
    if rc is None:
        return (None, None, [])
    return (None, 0, []) if rc == 0 else (None, 1, [f"<verify-exit-{rc}>"])


def parse_limn_lisp(text):
    """limn 測試框架：『N passed, M failed (T total)』+ 失敗名 [NAME]。"""
    totals = re.findall(r"(\d+)\s+passed,\s+(\d+)\s+failed\s*\(\d+\s+total\)", text)
    p, f = (int(totals[-1][0]), int(totals[-1][1])) if totals else (None, None)
    names = re.findall(r"^\s*\[([A-Z0-9][A-Z0-9\-]+)\]", text, re.MULTILINE)
    return (p, f, names)


def parse_pytest(text):
    """pytest：summary『... N passed, M failed ...』+ 失敗『FAILED path::test』。"""
    mp = re.search(r"(\d+)\s+passed", text)
    mf = re.search(r"(\d+)\s+failed", text)
    passed = int(mp.group(1)) if mp else None
    failed = int(mf.group(1)) if mf else (0 if passed is not None else None)
    names = re.findall(r"^FAILED\s+(\S+)", text, re.MULTILINE)
    return (passed, failed, names)


def parse_jest(text):
    """jest：『Tests: N failed, M passed, T total』+ 失敗『✕/× name』。"""
    mf = re.search(r"Tests:.*?(\d+)\s+failed", text)
    mp = re.search(r"(\d+)\s+passed", text)
    failed = int(mf.group(1)) if mf else None
    passed = int(mp.group(1)) if mp else None
    if failed is None and passed is not None:
        failed = 0
    names = re.findall(r"^\s*[✕×]\s+(.+)$", text, re.MULTILINE)
    return (passed, failed, [n.strip() for n in names])


def parse_cargo(text):
    """cargo test：『test result: ... N passed; M failed』+ 失敗『test NAME ... FAILED』。"""
    m = re.search(r"test result:.*?(\d+)\s+passed;\s+(\d+)\s+failed", text)
    passed, failed = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    names = re.findall(r"^test\s+(\S+)\s+\.\.\.\s+FAILED", text, re.MULTILINE)
    return (passed, failed, names)


REGISTRY = {
    "generic":   parse_generic,
    "limn-lisp": parse_limn_lisp,
    "pytest":    parse_pytest,
    "jest":      parse_jest,
    "cargo":     parse_cargo,
}


def get_parser(name):
    if name not in REGISTRY:
        raise ValueError(f"未知 parser: {name}（可用：{', '.join(REGISTRY)}）")
    return REGISTRY[name]
