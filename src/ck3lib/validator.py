"""v0.8: read-only CK3 mod validation and attributed log triage.

This is static evidence, NEVER evidence of game execution. All findings are
conservative: engine/DLC/GUI dependencies remain explicitly unverified.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .composer import CompositionError, confined_path, tokenize, matching_braces, assignments

MAX_FILE_SIZE = 20_000_000
MAX_PACKAGE_BYTES = 60_000_000
MAX_LOG_SIZE = 5_000_000
MAX_DIAGNOSTICS = 200
LANG = re.compile(r"[a-z_]+\Z")
LOC_NAME = re.compile(r"localization/([a-z_]+)/([A-Za-z0-9_-]+)_l_\1\.yml\Z")
LOC_ENTRY = re.compile(r'^\s*([A-Za-z0-9_.-]+):\d*\s+"(?:[^"\\]|\\.)*"(?:\s*#.*)?$')
GFX_PATH = re.compile(r"gfx/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:dds|png|jpg|tga)\Z")
SAFE_TEXT = re.compile(r"(?:events/cklib_[a-z0-9_]+|common/(?:activities/activity_types|on_action|decisions)/cklib_[a-z0-9_]+)\.txt\Z")
SUPPORTED = re.compile(r"\d+\.\d+\.\*\Z")
VERSION = re.compile(r"\d+\.\d+\.\d+\Z")
EVENT_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.\d+\Z")
DESCRIPTOR = re.compile(r'^\s*([a-z_]+)\s*=\s*"([^"\n\r]*)"\s*(?:#.*)?$')
LOG_ERROR = re.compile(r"\b(?:error|exception|failed|not found|unknown)\b", re.IGNORECASE)
LOCALIZATION_REF = frozenset(("title", "desc", "name", "text", "tooltip", "description", "custom_tooltip"))


def _issue(issues: list, severity: str, code: str, path: str, detail: str) -> None:
    if len(issues) < MAX_DIAGNOSTICS:
        issues.append({"severity": severity, "code": code, "path": path, "detail": detail[:240]})


def _confined_root(value: Path, label: str) -> Path:
    if value.is_symlink():
        raise CompositionError(f"{label} symlink forbidden")
    p = value.resolve(strict=True)
    if not p.is_dir():
        raise CompositionError(f"{label} must be a directory")
    return p


def _relative_files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise CompositionError("Mod file or directory symlink forbidden")
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if (rel not in ("descriptor.mod", "cklib-package-report.json")
                and not SAFE_TEXT.fullmatch(rel)
                and not LOC_NAME.fullmatch(rel)
                and not GFX_PATH.fullmatch(rel)):
                raise CompositionError("Unexpected generated mod file: " + rel)
            size = p.stat().st_size
            total += size
            if size > MAX_FILE_SIZE or total > MAX_PACKAGE_BYTES:
                raise CompositionError("Generated mod size limit exceeded")
            files[rel] = p.read_bytes()
    return files


def _descriptor(raw: bytes, issues: list) -> dict:
    try:
        data = raw.decode("utf-8-sig")
    except UnicodeError:
        _issue(issues, "error", "DESCRIPTOR_ENCODING", "descriptor.mod", "Not UTF-8")
        return {}
    result = {}
    for line in data.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = DESCRIPTOR.fullmatch(line)
        if not m or m.group(1) not in ("name", "version", "supported_version"):
            _issue(issues, "error", "DESCRIPTOR_FIELD", "descriptor.mod", line)
            continue
        if m.group(1) in result:
            _issue(issues, "error", "DESCRIPTOR_DUPLICATE", "descriptor.mod", m.group(1))
        result[m.group(1)] = m.group(2)
    for field in ("name", "version", "supported_version"):
        if not result.get(field):
            _issue(issues, "error", "DESCRIPTOR_REQUIRED", "descriptor.mod", field)
    if result.get("version") and not VERSION.fullmatch(result["version"]):
        _issue(issues, "error", "DESCRIPTOR_VERSION", "descriptor.mod", result["version"])
    if result.get("supported_version") and not SUPPORTED.fullmatch(result["supported_version"]):
        _issue(issues, "error", "DESCRIPTOR_SUPPORTED_VERSION", "descriptor.mod", result["supported_version"])
    return result


def _localizations(files: dict[str, bytes], issues: list) -> dict[tuple[str, str], str]:
    loc = {}
    for path, raw in files.items():
        m = LOC_NAME.fullmatch(path)
        if not m:
            continue
        if not raw.startswith(b"\xef\xbb\xbf"):
            _issue(issues, "error", "LOC_BOM", path, "CK3 localization must have a UTF-8 BOM")
        try:
            lines = raw.decode("utf-8-sig").splitlines()
        except UnicodeError:
            _issue(issues, "error", "LOC_ENCODING", path, "Malformed UTF-8")
            continue
        if not lines or lines[0].strip() != "l_" + m.group(1) + ":":
            _issue(issues, "error", "LOC_HEADER", path, "Localization language header mismatch")
        for number, line in enumerate(lines[1:], 2):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            entry = LOC_ENTRY.fullmatch(line)
            if not entry:
                _issue(issues, "error", "LOC_FORMAT", path, "Line " + str(number))
                continue
            key = entry.group(1)
            scoped = (m.group(1), key)
            if scoped in loc:
                _issue(issues, "error", "LOC_DUPLICATE", path, key + " already defined in " + loc[scoped])
            loc[scoped] = path
    return loc


def _scripts(files: dict[str, bytes], loc: dict[tuple[str, str], str], vanilla: Path | None, issues: list) -> dict:
    event_ids, on_action_ids, references = set(), set(), []
    loc_keys = {key for _language, key in loc}
    parsed = {}
    for path, raw in files.items():
        if not SAFE_TEXT.fullmatch(path):
            continue
        try:
            ts = tokenize(raw.decode("utf-8-sig"))
            ends = matching_braces(ts)
            roots = list(assignments(ts, ends, 0, len(ts)))
        except (UnicodeError, ValueError, CompositionError) as exc:
            _issue(issues, "error", "SCRIPT_SYNTAX", path, str(exc))
            continue
        parsed[path] = (ts, roots)
        if path.startswith("events/"):
            namespaces = [row[1].text for row in roots if row[0].text == "namespace" and row[2] is None]
            if len(namespaces) != 1:
                _issue(issues, "error", "EVENT_NAMESPACE", path, "Exactly one namespace expected")
            for key, val, opening, _ in roots:
                if EVENT_ID.fullmatch(key.text) and opening is not None:
                    if key.text in event_ids:
                        _issue(issues, "error", "EVENT_DUPLICATE", path, key.text)
                    event_ids.add(key.text)
                    if namespaces and not key.text.startswith(namespaces[0] + "."):
                        _issue(issues, "error", "EVENT_NAMESPACE_MISMATCH", path, key.text)
        elif "/on_action/" in path:
            for key, _, op, _ in roots:
                if op is not None:
                    if key.text in on_action_ids:
                        _issue(issues, "error", "ON_ACTION_DUPLICATE", path, key.text)
                    on_action_ids.add(key.text)
    for path, (ts, _) in parsed.items():
        for i, t in enumerate(ts):
            if i >= 2 and ts[i-1].text == "=":
                field = ts[i-2].text
                value = t.text
                if value.startswith('"') and value.endswith('"'):
                    literal = value[1:-1]
                    if GFX_PATH.fullmatch(literal):
                        available = literal in files
                        if not available and vanilla is not None:
                            try:
                                candidate = confined_path(vanilla, literal)
                                available = candidate.is_file()
                            except CompositionError:
                                pass
                        if not available:
                            _issue(issues, "warning" if vanilla is None else "error", "GFX_UNRESOLVED", path, literal)
                elif field in LOCALIZATION_REF and value.startswith("cklib_") and value not in loc_keys:
                    _issue(issues, "warning", "LOC_UNRESOLVED", path, value)
                elif field in ("trigger_event", "id") and EVENT_ID.fullmatch(value) and (field == "trigger_event" or _in_event_trigger_context(ts, i)):
                    references.append((path, value))
                elif field == "on_action" and value.startswith("cklib_") and value not in on_action_ids:
                    _issue(issues, "error", "ON_ACTION_UNRESOLVED", path, value)
    for path, ev in references:
        if ev not in event_ids:
            _issue(issues, "error" if ev.startswith("cklib_") else "warning", "EVENT_EXTERNAL_REFERENCE", path, ev)
    return {"events_defined": sorted(event_ids), "on_actions_defined": sorted(on_action_ids),
            "event_calls_recognized": len(references)}


def _in_event_trigger_context(tokens, idx: int) -> bool:
    # Conservative 'id = ns.1' recognition only if a trigger_event occurred nearby.
    start = max(0, idx - 9)
    return any(t.text == "trigger_event" for t in tokens[start:idx])


def _package_report(files: dict[str, bytes], issues: list) -> None:
    raw = files.get("cklib-package-report.json")
    if raw is None:
        _issue(issues, "warning", "MANIFEST_MISSING", "", "No v0.7 package report")
        return
    try:
        report = json.loads(raw)
    except (ValueError, UnicodeError):
        _issue(issues, "error", "MANIFEST_INVALID", "cklib-package-report.json", "Malformed JSON")
        return
    if (not isinstance(report, dict) or report.get("status") != "PACKAGED_UNVALIDATED"
        or report.get("game_validated") is not False or report.get("changes_vanilla") is not False):
        _issue(issues, "error", "MANIFEST_STATUS", "cklib-package-report.json", "Unexpected status")
        return
    generated = report.get("generated_files")
    if not isinstance(generated, list) or not all(isinstance(f, str) for f in generated):
        _issue(issues, "error", "MANIFEST_FILES", "cklib-package-report.json", "Invalid files listing")
    elif set(generated) != set(files) - {"cklib-package-report.json"} or len(generated) != len(set(generated)):
        _issue(issues, "error", "MANIFEST_MISMATCH", "cklib-package-report.json", "Generated files differ from manifest")


def _log_triage(log_root: Path | None, names: set[str]) -> dict:
    if log_root is None:
        return {"logs_provided": False, "entries_seen": 0, "attributable_errors": [], "other_errors": 0}
    log_dir = _confined_root(log_root, "Log directory")
    attributed, other, entries = [], 0, 0
    for name in ("error.log", "game.log"):
        p = log_dir / name
        if p.is_symlink():
            raise CompositionError("Log symlink forbidden")
        if not p.exists():
            continue
        if not p.is_file() or p.stat().st_size > MAX_LOG_SIZE:
            raise CompositionError("Unsafe or oversized CK3 log")
        for n, line in enumerate(p.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
            if not LOG_ERROR.search(line):
                continue
            entries += 1
            # Evidence only when the log line directly names our namespace or file.
            if "cklib_" in line or any(path in line.replace("\\", "/") for path in names):
                if len(attributed) < 50:
                    attributed.append({"file": name, "line": n, "message": line[:300]})
            else:
                other += 1
    return {"logs_provided": True, "entries_seen": entries, "attributable_errors": attributed,
            "other_errors": other, "logs_not_proof_of_game_load": True}


def validate(mod_root: Path, vanilla_root: Path | None = None, log_root: Path | None = None) -> dict:
    """Read-only validation; returns JSON-serializable review report."""
    mod = _confined_root(mod_root, "Mod directory")
    vanilla = _confined_root(vanilla_root, "Vanilla directory") if vanilla_root is not None else None
    logs = _confined_root(log_root, "Log directory") if log_root is not None else None
    if vanilla and (mod == vanilla or mod.is_relative_to(vanilla) or vanilla.is_relative_to(mod)):
        raise CompositionError("Mod directory may not overlap vanilla")
    files = _relative_files(mod)
    issues = []
    if "descriptor.mod" not in files:
        _issue(issues, "error", "DESCRIPTOR_MISSING", "", "Missing descriptor.mod")
    else:
        _descriptor(files["descriptor.mod"], issues)
    _package_report(files, issues)
    loc = _localizations(files, issues)
    symbols = _scripts(files, loc, vanilla, issues)
    logs_report = _log_triage(logs, set(files))
    if logs_report["attributable_errors"]:
        _issue(issues, "error", "LOG_ATTRIBUTABLE_ERRORS", "error.log/game.log",
               str(len(logs_report["attributable_errors"])) + " log lines mention generated symbols/files")
    count = {key: sum(x["severity"] == key for x in issues) for key in ("error", "warning")}
    return {"version": 1,
            "status": "STATIC_FINDINGS_REVIEW_REQUIRED" if count["error"] else "STATIC_REVIEW_REQUIRED",
            "game_validated": False, "vanilla_modified": False,
            "summary": {"files": len(files), "localizations": len(loc), **symbols,
                        "errors": count["error"], "warnings": count["warning"]},
            "diagnostics": issues, "log_triage": logs_report,
            "limitations": ["Static lint only: does not launch CK3 or validate engine behavior.",
                            "GUI data bindings, DLC checks, dynamic references, and mod load order are not resolved.",
                            "Logs require game-version and session provenance before interpreting a real test."]}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Read-only CK3 generated mod linter and error-log triage")
    parser.add_argument("--mod-dir", type=Path, required=True)
    parser.add_argument("--vanilla-root", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--report-out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = validate(args.mod_dir, args.vanilla_root, args.log_dir)
    out = args.report_out.absolute()
    protected = [p.resolve(strict=True) for p in (args.mod_dir, args.vanilla_root, args.log_dir) if p is not None]
    if out.exists() or out.is_symlink() or not out.parent.is_dir() or out.parent.is_symlink():
        parser.error("Report must target a new file in an existing directory")
    dest_parent = out.parent.resolve(strict=True)
    if any(out.is_relative_to(p) or dest_parent.is_relative_to(p) for p in protected):
        parser.error("Report cannot be written inside mod, vanilla, or log directories")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary": report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
