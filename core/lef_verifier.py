"""
core/lef_verifier.py — LEF (Log Event Format) verification via Analytics SSH.

Connects to the Versa Analytics node as root (via sudo su), runs:
  cat /var/tmp/log/tenant-<org>/VSN0-<gateway_name>/*.txt* | egrep "casbLog|accessLog"

All field values are strictly verified against CLI args passed at runtime.
"""

import os
import re
import time
import paramiko


# Regex to extract all fields from a casbLog line
CASB_LOG_PATTERN = re.compile(
    r'applianceName=(?P<applianceName>[^,\s]+)'
    r'.*?tenantName=(?P<tenantName>[^,\s]+)'
    r'.*?casbProfileName=(?P<casbProfileName>[^,\s]*)'
    r'.*?casbRuleName=(?P<casbRuleName>[^,\s]*)'
    r'.*?casbAppName=(?P<casbAppName>[^,\s]+)'
    r'.*?casbAppActivity=(?P<casbAppActivity>[^,\s]+)'
    r'.*?casbAction=(?P<casbAction>[^,\s]+)'
    r'.*?fromUser=(?P<fromUser>[^,\s]*)'
    r'.*?threatType=(?P<threatType>[^,\s]*)'
    r'.*?threatSeverity=(?P<threatSeverity>[^,\s]*)',
    re.DOTALL
)

# Regex to extract fields from an accessLog line
ACCESS_LOG_PATTERN = re.compile(
    r'applianceName=(?P<applianceName>[^,\s]+)'
    r'.*?tenantName=(?P<tenantName>[^,\s]+)'
    r'.*?rule=(?P<rule>[^,\s]+)'
    r'.*?fromUser=(?P<fromUser>[^,\s]*)',
    re.DOTALL
)

FROM_USER_PATTERN = re.compile(r'.+@versa-lab\.net$', re.IGNORECASE)


class LefVerifier:

    def __init__(self, host: str, user: str, password: str,
                 org: str, gateway_name: str, script_dir: str,
                 casb_profile: str = "", casb_rule: str = "",
                 casb_profile_rule: str = "",
                 port: int = 22):
        self.host              = host
        self.user              = user
        self.password          = password
        self.org               = org                 # --org
        self.gateway_name      = gateway_name        # --gateway-name
        self.script_dir        = script_dir
        self.casb_profile      = casb_profile        # --casb-profile
        self.casb_rule         = casb_rule            # --casb-access-policy-rule
        self.casb_profile_rule = casb_profile_rule   # --casb-profile-rule (casbRuleName in LEF)
        self.port              = port

        self._grep_cmd = (
            f'cat /var/tmp/log/tenant-{org}/VSN0-{gateway_name}/*.txt*'
            f' | egrep "casbLog|accessLog"'
        )

    # ──────────────────────────────────────────────────────────────────────────
    def _run_as_root(self, command: str) -> tuple:
        """SSH in, sudo su -, run command, return (output_lines, error)."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        output_lines = []
        error        = None

        try:
            print(f"   [LEF] Connecting: {self.user}@{self.host}:{self.port}")
            client.connect(
                hostname      = self.host,
                port          = self.port,
                username      = self.user,
                password      = self.password,
                timeout       = 10,
                look_for_keys = False,
                allow_agent   = False,
            )
            print(f"   [LEF] Connected. Escalating to root via sudo su...")

            shell = client.invoke_shell(width=220, height=50)
            shell.settimeout(2.0)

            def _read(timeout=3.0):
                buf = b""
                deadline = time.time() + timeout
                while time.time() < deadline:
                    try:
                        chunk = shell.recv(4096)
                        if chunk:
                            buf += chunk
                    except Exception:
                        time.sleep(0.1)
                return buf.decode("utf-8", errors="replace")

            _read(2.0)
            shell.send("sudo su -\n")
            time.sleep(0.5)
            banner = _read(3.0)

            if "password" in banner.lower():
                shell.send(self.password + "\n")
                time.sleep(0.5)
                _read(2.0)

            print(f"   [LEF] Root shell ready. Waiting 5s for logs to flush...")
            time.sleep(5.0)
            print(f"   [LEF] Running: {command}")
            shell.send(command + "\n")
            time.sleep(3.0)
            raw_output = _read(10.0)

            for line in raw_output.splitlines():
                line = line.strip()
                if "casbLog" in line and "casbAppName" in line:
                    output_lines.append(line)
                elif "accessLog" in line and "applianceName" in line:
                    output_lines.append(line)

            casb_count   = sum(1 for l in output_lines if "casbLog"   in l)
            access_count = sum(1 for l in output_lines if "accessLog" in l)
            print(f"   [LEF] Done. {casb_count} casbLog line(s), {access_count} accessLog line(s) found.")

            shell.send("exit\n")
            time.sleep(0.3)
            shell.close()

        except Exception as e:
            error = str(e)
            print(f"   [LEF] SSH/sudo error: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass

        return output_lines, error

    # ──────────────────────────────────────────────────────────────────────────
    def _validate_line(self, line: str,
                       expected_app: str, expected_activity: str,
                       expected_action: str) -> tuple:
        """Parse and strictly verify all casbLog fields against CLI args."""
        m = CASB_LOG_PATTERN.search(line)
        if not m:
            return {}, False

        g = m.groupdict()
        exp_severity    = "critical" if expected_action.lower() == "block" else ""
        exp_threat_type = f"casb_{expected_app}_{expected_activity}_{expected_action}"

        checks = {
            "applianceName"   : (g["applianceName"],   self.gateway_name,
                                  g["applianceName"]   == self.gateway_name),
            "tenantName"      : (g["tenantName"],       self.org,
                                  g["tenantName"]       == self.org),
            "casbProfileName" : (g["casbProfileName"],  self.casb_profile,
                                  g["casbProfileName"]  == self.casb_profile
                                  if self.casb_profile else bool(g["casbProfileName"])),
            "casbRuleName"    : (g["casbRuleName"],     self.casb_profile_rule,
                                  g["casbRuleName"]     == self.casb_profile_rule
                                  if self.casb_profile_rule else bool(g["casbRuleName"])),
            "casbAppName"     : (g["casbAppName"],      expected_app,
                                  g["casbAppName"].lower()     == expected_app.lower()),
            "casbAppActivity" : (g["casbAppActivity"],  expected_activity,
                                  g["casbAppActivity"].lower() == expected_activity.lower()),
            "casbAction"      : (g["casbAction"],       expected_action,
                                  g["casbAction"].lower()      == expected_action.lower()),
            "fromUser"        : (g["fromUser"],         ".*@versa-lab.net",
                                  bool(FROM_USER_PATTERN.match(g["fromUser"]))),
            "threatType"      : (g["threatType"],       exp_threat_type,
                                  g["threatType"].lower()      == exp_threat_type),
            "threatSeverity"  : (g["threatSeverity"],   exp_severity or "present",
                                  g["threatSeverity"].lower()  == exp_severity
                                  if exp_severity else bool(g["threatSeverity"])),
        }

        all_passed = all(passed for _, _, passed in checks.values())
        return checks, all_passed

    # ──────────────────────────────────────────────────────────────────────────
    def _validate_access_line(self, line: str) -> tuple:
        """Parse and validate an accessLog line against CLI args."""
        m = ACCESS_LOG_PATTERN.search(line)
        if not m:
            return {}, False
        g = m.groupdict()
        checks = {
            "applianceName" : (g["applianceName"], self.gateway_name,
                                g["applianceName"] == self.gateway_name),
            "tenantName"    : (g["tenantName"],    self.org,
                                g["tenantName"]    == self.org),
            "rule"          : (g["rule"],          self.casb_rule,
                                g["rule"]          == self.casb_rule
                                if self.casb_rule else bool(g["rule"])),
            "fromUser"      : (g["fromUser"],      ".*@versa-lab.net",
                                bool(FROM_USER_PATTERN.match(g["fromUser"]))),
        }
        all_passed = all(passed for _, _, passed in checks.values())
        return checks, all_passed

    # ──────────────────────────────────────────────────────────────────────────
    def _save_to_file(self, tc_label: str,
                      casb_lines: list, access_lines: list,
                      matched_lines: list, field_results: list,
                      confirmed: bool, expected_app: str,
                      expected_activity: str, expected_action: str,
                      access_results: list = None,
                      access_confirmed: bool = False,
                      error: str = None):
        """Save casbLog + accessLog raw lines and field validation to txt file."""
        lef_dir  = os.path.join(self.script_dir, "lef_logs")
        os.makedirs(lef_dir, exist_ok=True)
        filepath = os.path.join(lef_dir, f"{tc_label}_lef_dump.txt")
        cmd_used = (
            f"cat /var/tmp/log/tenant-{self.org}/VSN0-{self.gateway_name}/*.txt*"
            f' | egrep "casbLog|accessLog"'
        )
        both_ok  = confirmed and access_confirmed

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=" * 70 + "\n")
            f.write(f"  LEF DUMP — {tc_label}\n")
            f.write("=" * 70 + "\n")
            f.write(f"  Analytics host         : {self.host}\n")
            f.write(f"  Org (--org)            : {self.org}\n")
            f.write(f"  Gateway (--gateway-name)       : {self.gateway_name}\n")
            f.write(f"  CASB Profile (--casb-profile)  : {self.casb_profile}\n")
            f.write(f"  CASB Rule (--casb-access-policy-rule) : {self.casb_rule}\n")
            f.write(f"  CASB Profile Rule (--casb-profile-rule): {self.casb_profile_rule}\n")
            f.write(f"  Expected app           : {expected_app}\n")
            f.write(f"  Expected activity      : {expected_activity}\n")
            f.write(f"  Expected action        : {expected_action}\n")
            f.write(f"  Command                : {cmd_used}\n")
            f.write(f"  casbLog lines found    : {len(casb_lines)}\n")
            f.write(f"  accessLog lines found  : {len(access_lines)}\n")
            f.write(f"  casbLog  result        : {'CONFIRMED' if confirmed       else 'NOT FOUND / FIELD MISMATCH'}\n")
            f.write(f"  accessLog result       : {'CONFIRMED' if access_confirmed else 'NOT FOUND / MISMATCH'}\n")
            f.write(f"  OVERALL RESULT         : {'VERIFIED (casbLog + accessLog)' if both_ok else 'FAILED'}\n")
            if error:
                f.write(f"  SSH Error              : {error}\n")
            f.write("=" * 70 + "\n\n")

            # ── casbLog raw lines
            f.write(f"ALL casbLog LINES CAPTURED ({len(casb_lines)}):\n")
            f.write("-" * 70 + "\n")
            if casb_lines:
                for line in casb_lines:
                    f.write(line + "\n")
            else:
                f.write("(no casbLog lines found)\n")

            # ── accessLog raw lines
            f.write(f"\nALL accessLog LINES CAPTURED ({len(access_lines)}):\n")
            f.write("-" * 70 + "\n")
            if access_lines:
                for line in access_lines:
                    f.write(line + "\n")
            else:
                f.write("(no accessLog lines found)\n")

            # ── casbLog strict field validation
            if field_results:
                f.write(f"\nCASBLOG FIELD VALIDATION ({len(matched_lines)} matched line(s)):\n")
                f.write("-" * 70 + "\n")
                for i, (line, checks, all_passed) in enumerate(field_results, 1):
                    f.write(f"\nLine [{i}]: {line}\n")
                    f.write(f"Overall : {'PASS' if all_passed else 'FAIL'}\n\n")
                    for field, (actual, expected, passed) in checks.items():
                        status = "PASS" if passed else "FAIL"
                        f.write(f"  [{status}] {field:<22} actual={actual:<40} expected={expected}\n")

            # ── accessLog field validation
            f.write(f"\nACCESSLOG FIELD VALIDATION ({len(access_results or [])} line(s) checked):\n")
            f.write("-" * 70 + "\n")
            if access_results:
                for i, (line, checks, all_passed) in enumerate(access_results, 1):
                    f.write(f"\nLine [{i}]: {line[:200]}...\n")
                    f.write(f"Overall : {'PASS' if all_passed else 'FAIL'}\n\n")
                    for field, (actual, expected, passed) in checks.items():
                        status = "PASS" if passed else "FAIL"
                        f.write(f"  [{status}] {field:<22} actual={actual:<40} expected={expected}\n")
            else:
                f.write("(no accessLog lines found)\n")

        print(f"   [LEF] Log saved: {filepath}")
        return filepath

    # ──────────────────────────────────────────────────────────────────────────
    def fetch_and_validate(self, tc_label: str,
                           expected_app: str, expected_activity: str,
                           expected_action: str = "block") -> dict:
        """
        Run cat/egrep on Analytics after activity completes.
        Strictly verify casbLog and accessLog fields against CLI args.
        Always saves txt file regardless of pass/fail.
        """
        exp_app    = (expected_app      or "").lower().strip()
        exp_act    = (expected_activity or "").lower().strip()
        exp_action = (expected_action   or "block").lower().strip()

        all_lines, error = self._run_as_root(self._grep_cmd)
        connected = error is None

        # Split into casbLog and accessLog
        casb_lines   = [l for l in all_lines if "casbLog"   in l]
        access_lines = [l for l in all_lines if "accessLog" in l]

        # ── casbLog validation ────────────────────────────────────────────────
        matched       = []
        field_results = []
        confirmed     = False
        fail_fields   = []

        for line in casb_lines:
            low = line.lower().replace(" ", "")
            if (f"casbappname={exp_app}"      in low and
                f"casbappactivity={exp_act}"  in low and
                f"casbaction={exp_action}"    in low):
                matched.append(line)
                checks, all_passed = self._validate_line(line, exp_app, exp_act, exp_action)
                field_results.append((line, checks, all_passed))
                if all_passed:
                    confirmed = True

        if field_results:
            _, checks, _ = field_results[0]
            fail_fields = [
                (field, actual, expected)
                for field, (actual, expected, passed) in checks.items()
                if not passed
            ]

        # ── accessLog validation ──────────────────────────────────────────────
        access_results   = []
        access_confirmed = False
        for line in access_lines:
            checks, all_passed = self._validate_access_line(line)
            if checks:
                access_results.append((line, checks, all_passed))
                if all_passed:
                    access_confirmed = True

        # Always save to file
        self._save_to_file(
            tc_label          = tc_label,
            casb_lines        = casb_lines,
            access_lines      = access_lines,
            matched_lines     = matched,
            field_results     = field_results,
            confirmed         = confirmed,
            expected_app      = exp_app,
            expected_activity = exp_act,
            expected_action   = exp_action,
            access_results    = access_results,
            access_confirmed  = access_confirmed,
            error             = error,
        )

        # ── Console output ────────────────────────────────────────────────────
        cmd_used = (
            f"cat /var/tmp/log/tenant-{self.org}/VSN0-{self.gateway_name}/*.txt*"
            f' | egrep "casbLog|accessLog"'
        )
        both_ok = confirmed and access_confirmed
        W = 70

        print(f"\n   {'-' * W}")
        print(f"   LEF VALIDATION")
        print(f"   {'-' * W}")
        print(f"   Analytics host   : {self.host}")
        print(f"   Org              : {self.org}")
        print(f"   Gateway          : {self.gateway_name}")
        print(f"   Command          : {cmd_used}")
        print(f"   {'-' * W}")

        # casbLog section
        print(f"   casbLog lines    : {len(casb_lines)} found   |   matched: {len(matched)}")
        if not connected:
            print(f"   casbLog result   : SKIPPED (SSH error: {error})")
        else:
            print(f"   casbLog result   : {'CONFIRMED ✓' if confirmed else 'NOT FOUND / FIELD MISMATCH ✗'}")
        if field_results:
            _, checks, _ = field_results[0]
            print(f"   Field checks (strict):")
            for field, (actual, expected, passed) in checks.items():
                icon = "✓" if passed else "✗"
                print(f"     [{icon}] {field:<22} = {actual:<35} (expected: {expected})")

        print(f"   {'-' * W}")

        # accessLog section
        print(f"   accessLog lines  : {len(access_lines)} found   |   validated: {len(access_results)}")
        print(f"   accessLog result : {'CONFIRMED ✓' if access_confirmed else 'NOT FOUND / MISMATCH ✗' if access_results else 'NO LINES'}")
        if access_results:
            _, first_checks, _ = access_results[0]
            print(f"   Field checks (first matching line):")
            for field, (actual, expected, passed) in first_checks.items():
                icon = "✓" if passed else "✗"
                print(f"     [{icon}] {field:<22} = {actual:<35} (expected: {expected})")

        print(f"   {'-' * W}")
        if not connected:
            print(f"   OVERALL          : SKIPPED")
        elif both_ok:
            print(f"   OVERALL          : ✓ VERIFIED (casbLog + accessLog)")
        else:
            print(f"   OVERALL          : ✗ FAILED")
        print(f"   {'-' * W}\n")

        return {
            "lef_confirmed"      : confirmed,
            "lef_skipped"        : not connected,
            "ssh_connected"      : connected,
            "matched_lines"      : matched,
            "all_lines"          : all_lines,
            "matched_count"      : len(matched),
            "fail_fields"        : fail_fields,
            "access_confirmed"   : access_confirmed,
            "access_line_count"  : len(access_lines),
            "access_log_lines"   : access_lines,
            "error"              : error,
        }