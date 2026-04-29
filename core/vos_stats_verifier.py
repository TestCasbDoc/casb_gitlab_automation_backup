"""
core/vos_stats_verifier.py — Validate VOS statistics counters from vos_dump file.
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional


def _is_equals_separator(line: str) -> bool:
    """True if line is only '=' characters (typical VOS dump section rule)."""
    s = line.strip()
    return len(s) >= 5 and set(s) <= {"="}


def _get_section(content: str, title: str) -> str:
    """
    Extract body text for a titled section (linear scan — avoids regex backtracking).
    Looks for a line containing ``title``, then takes lines until the next === separator.
    """
    tl = title.lower()
    lines = content.splitlines()
    n = len(lines)
    for i, line in enumerate(lines):
        if tl not in line.lower():
            continue
        # Advance past header lines until a === line, then collect until next ===
        j = i + 1
        while j < n and not _is_equals_separator(lines[j]):
            j += 1
        if j >= n:
            continue
        j += 1
        body: list[str] = []
        while j < n and not _is_equals_separator(lines[j]):
            body.append(lines[j])
            j += 1
        return "\n".join(body)
    return ""


def _get_section_by_command(content: str, keyword: str) -> str:
    """
    Extract content after ``Command: ... keyword ...`` until the next === block.
    Linear scan — the old regex could hang (catastrophic backtracking) on big dumps.
    """
    kw = keyword.lower()
    lines = content.splitlines()
    n = len(lines)
    for i, line in enumerate(lines):
        low = line.lower()
        if "command:" not in low or kw not in low:
            continue
        body: list[str] = []
        for j in range(i + 1, n):
            if _is_equals_separator(lines[j]):
                break
            body.append(lines[j])
        return "\n".join(body)
    return ""


def _find_vos_dump(script_dir: str, tc_label: str) -> Optional[str]:
    """
    Resolve vos_dumps/*.txt for stats parsing.

    Preferred naming per test-case index (varies by run):
      TC1_post_vos_dump.txt, TC2_post_vos_dump.txt, ...
    We take the first TC<n> in tc_label (e.g. TC1_BaseSendPost -> TC1) and
    prefer <TCn>_post_vos_dump.txt when it exists. Fallback: files whose name
    contains the full tc_label (legacy).
    """
    dump_dir = os.path.join(script_dir, "vos_dumps")
    if not os.path.isdir(dump_dir):
        return None

    tc_lower = (tc_label or "").lower()
    candidates: list[str] = [
        f
        for f in os.listdir(dump_dir)
        if f.endswith("_vos_dump.txt") and tc_lower in f.lower()
    ]

    m = re.search(r"(TC\d+)", tc_label or "", re.I)
    preferred: Optional[str] = None
    if m:
        tcn = m.group(1)
        post_file = f"{tcn}_post_vos_dump.txt"
        path_post = os.path.join(dump_dir, post_file)
        if os.path.isfile(path_post):
            preferred = post_file
            if post_file not in candidates:
                candidates.append(post_file)

    if not candidates:
        return None

    def sort_key(f: str) -> tuple:
        fl = f.lower()
        if preferred and fl == preferred.lower():
            return (0, f)
        return (1 if "post" in fl else 2, f)

    candidates.sort(key=sort_key)
    return os.path.join(dump_dir, candidates[0])


def verify_vos_stats(
    script_dir: str,
    tc_label: str,
    casb_profile: str,
    casb_rule: str,
    casb_access_rule: str,
    decrypt_rule: str,
    decrypt_profile: str,
    qosmos: bool = True,
) -> dict:
    dump_file = _find_vos_dump(script_dir, tc_label)

    if not dump_file or not os.path.exists(dump_file):
        print(f"   [VOS-STATS] No vos_dump file found for {tc_label}", flush=True)
        return {
            "confirmed": False,
            "skipped": True,
            "checks": {},
            "fail_fields": [],
            "dump_file": None,
        }

    print(f"   [VOS-STATS] Reading: {dump_file}", flush=True)
    t_read = time.perf_counter()
    with open(dump_file, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    read_sec = time.perf_counter() - t_read
    print(
        f"   [VOS-STATS] Loaded {len(content):,} chars in {read_sec:.2f}s",
        flush=True,
    )

    checks: dict = {}
    t_parse = time.perf_counter()

    # 1. CASB Access-Policy Rule hit count
    s = _get_section_by_command(content, "access-policy-stats")
    cnt = -1
    if s:
        m = re.search(
            rf"{re.escape(casb_access_rule)}\s+(\d+)", s, re.IGNORECASE
        )
        cnt = int(m.group(1)) if m else -1
    checks["casb_access_rule_hit"] = (
        str(cnt) if cnt >= 0 else "not found",
        f">= 1 (rule: {casb_access_rule})",
        cnt >= 1,
    )

    # 2. CASB Profile rule hit count
    s = _get_section(content, "CASB Profile Statistics")
    cnt = -1
    if s:
        m = re.search(rf"{re.escape(casb_rule)}\s+(\d+)", s, re.IGNORECASE)
        cnt = int(m.group(1)) if m else -1
    checks["casb_profile_rule_hit"] = (
        str(cnt) if cnt >= 0 else "not found",
        f">= 1 (rule: {casb_rule})",
        cnt >= 1,
    )

    # 3. Decrypt Rule hit count
    s = _get_section(content, "Decrypt Rule Hit Count")
    cnt = -1
    if s:
        m = re.search(rf"{re.escape(decrypt_rule)}\s+(\d+)", s, re.IGNORECASE)
        if m:
            cnt = int(m.group(1))
        else:
            nums = re.findall(r"\b(\d+)\b", s)
            cnt = int(nums[-1]) if nums else -1
    checks["decrypt_rule_hit"] = (
        str(cnt) if cnt >= 0 else "not found",
        f">= 1 (rule: {decrypt_rule})",
        cnt >= 1,
    )

    # 4. Decrypt Profile ssl_pxy_url_decrypt counter
    s = _get_section(content, "Decrypt Profile Stats")
    cnt = -1
    if s:
        m = re.search(r"ssl_pxy_url_decrypt\s+(\d+)", s)
        cnt = int(m.group(1)) if m else -1
    checks["decrypt_profile_ssl_pxy_url_decrypt"] = (
        str(cnt) if cnt >= 0 else "not found",
        f">= 1 (profile: {decrypt_profile})",
        cnt >= 1,
    )

    # 5. appid report_metadata
    exp_meta = "enabled" if qosmos else "disabled"
    s = _get_section(content, "appid report_metadata")
    meta_val = ""
    if s:
        m = re.search(r"\b(enabled|disabled)\b", s, re.IGNORECASE)
        meta_val = m.group(1).lower() if m else ""
    checks["appid_report_metadata"] = (
        meta_val or "not found",
        exp_meta,
        meta_val == exp_meta,
    )

    parse_sec = time.perf_counter() - t_parse
    print(f"   [VOS-STATS] Parsed sections in {parse_sec:.2f}s", flush=True)

    fail_fields = [f for f, (_, _, p) in checks.items() if not p]
    confirmed = len(fail_fields) == 0

    print("\n   ------------------------------")
    print("   VOS STATS VERIFICATION")
    print("   ------------------------------")
    print(f"   Dump file : {os.path.basename(dump_file)}")
    for field, (actual, expected, passed) in checks.items():
        icon = "✓" if passed else "✗"
        print(
            f"   [{icon}] {field:<38} = {actual:<10} (expected: {expected})"
        )
    print(f"   Result    : {'CONFIRMED ✓' if confirmed else 'FAILED ✗'}")
    if fail_fields:
        print(f"   Failed    : {', '.join(fail_fields)}")
    print("   ------------------------------\n")

    return {
        "confirmed": confirmed,
        "skipped": False,
        "checks": checks,
        "fail_fields": fail_fields,
        "dump_file": dump_file,
    }