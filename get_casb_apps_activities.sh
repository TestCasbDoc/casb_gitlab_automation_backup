#!/usr/bin/env bash
# get_casb_apps_activities.sh — read app_activity_v1.xml from the current directory (or path arg).
# Table 1: SaaS Applications | Activities Supported (non-deprecated md_name only, one row per app).
#   Apps whose activities are all deprecated are omitted from table 1.
# Table 2: SaaS Applications | Deprecated activities (deprecated=1 per md_name).
# Default: remote validate (CASB_SSH_* or argv; see usage). Use "format" for local tables.
set -euo pipefail

REMOTE_VERSA_CONFIG_DIR="/opt/versa/etc/spack/installed/current/config/21.1"
REMOTE_XML_NAME="app_activity_v1.xml"

resolve_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo python3
  elif command -v python >/dev/null 2>&1; then
    echo python
  else
    echo ""
  fi
}

parse_ssh_cli_args() {
  if [[ $# -ge 3 ]]; then
    CASB_SSH_USER="$1"
    CASB_SSH_PASSWORD="$2"
    CASB_SSH_HOST="$3"
    export CASB_SSH_USER CASB_SSH_PASSWORD CASB_SSH_HOST
  elif [[ $# -eq 2 ]]; then
    CASB_SSH_USER="$1"
    CASB_SSH_HOST="$2"
    export CASB_SSH_USER CASB_SSH_HOST
  fi
}

validate_remote_app_activity_xml() {
  local host="${CASB_SSH_HOST:-${CASB_SSH_IP:-}}"
  local user="${CASB_SSH_USER:-}"
  local pass="${CASB_SSH_PASSWORD:-}"
  local port="${CASB_SSH_PORT:-22}"

  if [[ -z "$host" || -z "$user" || -z "$pass" ]]; then
    echo "$0 validate-remote: need SSH credentials." >&2
    echo "  $0 validate-remote <username> <password> <ip_or_host>" >&2
    echo "  $0 validate-remote <username> <ip_or_host>   # plus CASB_SSH_PASSWORD" >&2
    echo "  or env: CASB_SSH_USER, CASB_SSH_PASSWORD, CASB_SSH_HOST (or CASB_SSH_IP)" >&2
    return 1
  fi

  if ! command -v sshpass >/dev/null 2>&1; then
    echo "$0 validate-remote: sshpass is required for password SSH." >&2
    return 1
  fi

  export SSHPASS="$pass"
  echo "SSH ${user}@${host} -> ${REMOTE_VERSA_CONFIG_DIR}/${REMOTE_XML_NAME}"

  sshpass -e ssh -o StrictHostKeyChecking=accept-new -p "$port" "${user}@${host}" bash -s <<'REMOTE_VALIDATION'
set -euo pipefail
REMOTE_VERSA_CONFIG_DIR="/opt/versa/etc/spack/installed/current/config/21.1"
REMOTE_XML_NAME="app_activity_v1.xml"
cd "$REMOTE_VERSA_CONFIG_DIR"
XML_PATH="$REMOTE_VERSA_CONFIG_DIR/$REMOTE_XML_NAME"
if [[ ! -f "$XML_PATH" ]]; then
  echo "ERROR: file not found: $XML_PATH" >&2
  exit 2
fi
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "ERROR: need python3 or python on remote host to validate XML." >&2
  exit 3
fi
export FORMAT_APP_ACTIVITY_XML="$XML_PATH"
set -o pipefail
_casb_emit_remote() {
  "$PY" - <<'PYFORMAT'
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

path = os.environ["FORMAT_APP_ACTIVITY_XML"]
which = os.environ.get("CASB_EMIT_TABLE", "main")
NS = "http://www.versa-networks.com/predefined-appid-casb-metadata"


def q(tag):
    return "{%s}%s" % (NS, tag)


def esc(s):
    return s.replace("\t", " ").replace("\r", " ").replace("\n", " ")


try:
    root = ET.parse(path).getroot()
except ET.ParseError as e:
    print("XML parse error:", e, file=sys.stderr)
    sys.exit(1)

casb_blocks = list(root.iter(q("casb-metadata")))
if not casb_blocks:
    print("ERROR: no casb-metadata elements found (wrong file or namespace).", file=sys.stderr)
    sys.exit(1)


def uniq_ordered(seq):
    seen = set()
    out = []
    for n in seq:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


active = defaultdict(list)
deprecated = defaultdict(list)

for cm in root.iter(q("casb-metadata")):
    app_el = cm.find(q("app_name"))
    if app_el is None or not (app_el.text or "").strip():
        continue
    app_name = (app_el.text or "").strip()
    for md in cm.findall(q("metadata")):
        mn = md.find(q("md_name"))
        if mn is None or not (mn.text or "").strip():
            continue
        md_name = (mn.text or "").strip()
        dep_el = md.find(q("deprecated"))
        if dep_el is not None and (dep_el.text or "").strip() == "1":
            deprecated[app_name].append(md_name)
        else:
            active[app_name].append(md_name)

all_apps = set(active.keys()) | set(deprecated.keys())

main_rows = []
for app_name in all_apps:
    names = uniq_ordered(active.get(app_name, []))
    if names:
        main_rows.append((app_name, ", ".join(names)))
main_rows.sort(key=lambda r: r[0].lower())

dep_rows = []
for app_name in all_apps:
    names = uniq_ordered(deprecated.get(app_name, []))
    if names:
        dep_rows.append((app_name, ", ".join(names)))
dep_rows.sort(key=lambda r: r[0].lower())

out = sys.stdout
if which == "main":
    out.write("SaaS Applications\tActivities Supported\n")
    for app_name, activities in main_rows:
        out.write("%s\t%s\n" % (esc(app_name), esc(activities)))
elif which == "deprecated":
    out.write("SaaS Applications\tDeprecated activities\n")
    for app_name, activities in dep_rows:
        out.write("%s\t%s\n" % (esc(app_name), esc(activities)))
else:
    print("ERROR: CASB_EMIT_TABLE must be main or deprecated", file=sys.stderr)
    sys.exit(1)
PYFORMAT
}
if command -v column >/dev/null 2>&1; then
  CASB_EMIT_TABLE=main _casb_emit_remote | column -t -s $'\t'
  echo ""
  CASB_EMIT_TABLE=deprecated _casb_emit_remote | column -t -s $'\t'
else
  CASB_EMIT_TABLE=main _casb_emit_remote
  echo ""
  CASB_EMIT_TABLE=deprecated _casb_emit_remote
fi
REMOTE_VALIDATION
}

run_format() {
  local XML_FILE="$1"

  if [[ ! -f "$XML_FILE" ]]; then
    echo "For local tables: $0 format [path/to/app_activity_v1.xml]" >&2
    echo "Default action is remote validate; see $0 --help" >&2
    echo "File not found: $XML_FILE (cwd: $(pwd))" >&2
    exit 1
  fi

  local py
  py="$(resolve_python)"
  if [[ -z "$py" ]]; then
    echo "$0: need python3 or python." >&2
    exit 1
  fi

  export FORMAT_APP_ACTIVITY_XML="$XML_FILE"

  emit_tsv() {
    "$py" - <<'PY'
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

path = os.environ["FORMAT_APP_ACTIVITY_XML"]
which = os.environ.get("CASB_EMIT_TABLE", "main")
NS = "http://www.versa-networks.com/predefined-appid-casb-metadata"


def q(tag):
    return "{%s}%s" % (NS, tag)


def esc(s):
    return s.replace("\t", " ").replace("\r", " ").replace("\n", " ")


try:
    root = ET.parse(path).getroot()
except ET.ParseError as e:
    print("XML parse error:", e, file=sys.stderr)
    sys.exit(1)


def uniq_ordered(seq):
    seen = set()
    out = []
    for n in seq:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


active = defaultdict(list)
deprecated = defaultdict(list)

for cm in root.iter(q("casb-metadata")):
    app_el = cm.find(q("app_name"))
    if app_el is None or not (app_el.text or "").strip():
        continue
    app_name = (app_el.text or "").strip()
    for md in cm.findall(q("metadata")):
        mn = md.find(q("md_name"))
        if mn is None or not (mn.text or "").strip():
            continue
        md_name = (mn.text or "").strip()
        dep_el = md.find(q("deprecated"))
        if dep_el is not None and (dep_el.text or "").strip() == "1":
            deprecated[app_name].append(md_name)
        else:
            active[app_name].append(md_name)

all_apps = set(active.keys()) | set(deprecated.keys())

main_rows = []
for app_name in all_apps:
    names = uniq_ordered(active.get(app_name, []))
    if names:
        main_rows.append((app_name, ", ".join(names)))
main_rows.sort(key=lambda r: r[0].lower())

dep_rows = []
for app_name in all_apps:
    names = uniq_ordered(deprecated.get(app_name, []))
    if names:
        dep_rows.append((app_name, ", ".join(names)))
dep_rows.sort(key=lambda r: r[0].lower())

out = sys.stdout
if which == "main":
    out.write("SaaS Applications\tActivities Supported\n")
    for app_name, activities in main_rows:
        out.write("%s\t%s\n" % (esc(app_name), esc(activities)))
elif which == "deprecated":
    out.write("SaaS Applications\tDeprecated activities\n")
    for app_name, activities in dep_rows:
        out.write("%s\t%s\n" % (esc(app_name), esc(activities)))
else:
    print("ERROR: CASB_EMIT_TABLE must be main or deprecated", file=sys.stderr)
    sys.exit(1)
PY
  }

  if command -v column >/dev/null 2>&1; then
    CASB_EMIT_TABLE=main emit_tsv | column -t -s $'\t'
    echo ""
    CASB_EMIT_TABLE=deprecated emit_tsv | column -t -s $'\t'
  else
    CASB_EMIT_TABLE=main emit_tsv
    echo ""
    CASB_EMIT_TABLE=deprecated emit_tsv
  fi
}

usage() {
  echo "Usage:" >&2
  echo "  $0                                    # default: remote validate (CASB_SSH_* env)" >&2
  echo "  $0 <user> <password> <host>           # remote validate (password on argv)" >&2
  echo "  $0 <user> <host>                      # remote validate (CASB_SSH_PASSWORD in env)" >&2
  echo "  $0 validate-remote|remote-validate [same args as above]" >&2
  echo "  $0 format [path/to/app_activity_v1.xml]   # local tables; default file: ./app_activity_v1.xml" >&2
  echo "  $0 path/to/app_activity_v1.xml        # local tables (single existing file)" >&2
  echo "Remote: cd ${REMOTE_VERSA_CONFIG_DIR} and validate ${REMOTE_XML_NAME} (needs sshpass, python3 on device)." >&2
}

case "${1:-}" in
  validate-remote|remote-validate)
    shift
    parse_ssh_cli_args "$@"
    validate_remote_app_activity_xml
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  format)
    shift
    run_format "${1:-app_activity_v1.xml}"
    ;;
  "")
    parse_ssh_cli_args
    validate_remote_app_activity_xml
    ;;
  *)
    if [[ -f "$1" && $# -eq 1 ]]; then
      run_format "$1"
    elif [[ $# -eq 3 ]]; then
      parse_ssh_cli_args "$@"
      validate_remote_app_activity_xml
    elif [[ $# -eq 2 ]]; then
      parse_ssh_cli_args "$@"
      validate_remote_app_activity_xml
    else
      echo "Unknown option or wrong number of arguments: $*" >&2
      usage
      exit 1
    fi
    ;;
esac
