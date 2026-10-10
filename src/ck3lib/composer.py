"""Conservative CK3 activity clone POC. Standard-library only; not a full CK3 parser."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

ID = re.compile(r"^[a-z][a-z0-9_]*$")
SAFE_MOD_ID = re.compile(r"^cklib_activity_[a-z0-9_]+$")

class CompositionError(ValueError):
    pass

@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


def tokenize(source: str) -> list[Token]:
    """Keep offsets; ignore comments and quoted strings as symbol matches."""
    tokens = []
    i = 0
    while i < len(source):
        c = source[i]
        if c.isspace() or c == '\ufeff':
            i += 1
        elif c == '#':
            n = source.find('\n', i)
            i = len(source) if n == -1 else n + 1
        elif c == '"':
            start = i
            i += 1
            while i < len(source):
                if source[i] == '\\':
                    i += 2
                elif source[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            else:
                raise CompositionError("Unterminated quoted string")
            tokens.append(Token(source[start:i], start, i))
        elif c in '{}=':
            tokens.append(Token(c, i, i + 1))
            i += 1
        else:
            start = i
            while i < len(source) and not source[i].isspace() and source[i] not in '{}=#"':
                i += 1
            if start == i:
                raise CompositionError(f"Unsupported character at {i}: {source[i]!r}")
            tokens.append(Token(source[start:i], start, i))
    return tokens


def matching_braces(ts: list[Token]) -> dict[int, int]:
    stack, ends = [], {}
    for i, t in enumerate(ts):
        if t.text == '{':
            stack.append(i)
        elif t.text == '}':
            if not stack:
                raise CompositionError("Extra closing brace")
            begin = stack.pop()
            ends[begin] = i
    if stack:
        raise CompositionError("Unclosed brace")
    return ends


def assignments(ts: list[Token], ends: dict[int, int], start: int, stop: int):
    """Yield direct-child key/value tokens from a brace-delimited scope."""
    i = start
    while i < stop:
        if i + 2 >= stop or ts[i + 1].text != '=':
            raise CompositionError(f"Unrecognized direct-child syntax near {ts[i].text!r}")
        key = ts[i]
        val_idx = i + 2
        val = ts[val_idx]
        if val.text == '{':
            if val_idx not in ends:
                raise CompositionError("Missing closing brace")
            yield key, val, val_idx, ends[val_idx]
            i = ends[val_idx] + 1
        else:
            yield key, val, None, None
            i = val_idx + 1


def resolve_path(ts, ends, root_open, root_end, parts):
    start, end = root_open + 1, root_end
    for pos, part in enumerate(parts):
        matches = [item for item in assignments(ts, ends, start, end) if item[0].text == part]
        if len(matches) != 1:
            raise CompositionError(f"Expected one field at {'.'.join(parts[:pos+1])}, found {len(matches)}")
        key, val, op, close = matches[0]
        if pos < len(parts) - 1:
            if op is None:
                raise CompositionError(f"Expected block at {part}")
            start, end = op + 1, close
        else:
            if op is not None:
                raise CompositionError(f"Cannot override a block: {part}")
            return val
    raise AssertionError("Empty path")


def confined_path(root: Path, rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute() or not p.parts or any(x in ('..', '.') for x in p.parts) or '\\' in rel:
        raise CompositionError(f"Unsafe relative path: {rel}")
    base = root.resolve()
    path = (base / p).resolve()
    if not path.is_relative_to(base):
        raise CompositionError(f"Path escapes root: {rel}")
    return path


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def valid_atom(v) -> str:
    s = str(v)
    if isinstance(v, bool) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', s):
        raise CompositionError(f"Not a safe CK3 scalar: {v!r}")
    return s


def apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    ordered = sorted(edits, reverse=True)
    for i, (a, b, value) in enumerate(ordered):
        if i and b > ordered[i - 1][0]:
            raise CompositionError("Overlapping edits")
        text = text[:a] + value + text[b:]
    return text


def compose(recipe: dict, vanilla_root: Path, output_root: Path) -> dict:
    if recipe.get('schema_version') != 1 or recipe.get('kind') != 'activity_clone':
        raise CompositionError("Requires schema_version=1, kind=activity_clone")
    source_id = recipe['source_id']
    target_id = recipe['target_id']
    if not ID.fullmatch(source_id) or not SAFE_MOD_ID.fullmatch(target_id) or source_id == target_id:
        raise CompositionError("Unsafe or unchanged activity identifiers")
    src_rel = recipe['source_path']
    if not src_rel.startswith('common/activities/activity_types/') or not src_rel.endswith('.txt'):
        raise CompositionError('Source must be in common/activities/activity_types/*.txt')
    original = confined_path(vanilla_root, src_rel)
    if not original.is_file():
        raise CompositionError(f"Missing source: {original}")
    raw = original.read_bytes()
    expected = recipe.get('source_git_blob_sha')
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{40}', expected):
        raise CompositionError('A pinned source_git_blob_sha is required')
    actual = git_blob_sha(raw)
    if actual != expected:
        raise CompositionError(f"Vanilla source hash mismatch: expected {expected}, got {actual}")
    text = raw.decode('utf-8-sig')
    ts = tokenize(text)
    ends = matching_braces(ts)
    roots = list(assignments(ts, ends, 0, len(ts)))
    if len(roots) != 1 or roots[0][0].text != source_id or roots[0][2] is None:
        raise CompositionError('Expected exactly one activity root with the declared source_id')
    root_key, _, root_open, root_end = roots[0]
    edits = [(root_key.start, root_key.end, target_id)]
    for token in ts[root_open + 1:root_end]:
        if token.text == source_id:
            edits.append((token.start, token.end, target_id))
    overrides = recipe.get('overrides', {})
    if not isinstance(overrides, dict):
        raise CompositionError('overrides must be an object')
    for key, val in overrides.items():
        # Allow only explicitly reviewed scalar parameters, never arbitrary text replacement.
        if key not in ('cooldown.years', 'max_province_icons', 'sort_order'):
            raise CompositionError(f"Unsupported override field: {key}")
        token = resolve_path(ts, ends, root_open, root_end, key.split('.'))
        edits.append((token.start, token.end, valid_atom(val)))
    content = apply_edits(text, edits)
    # External references are deliberately not renamed or duplicated.
    external = sorted(set(re.findall(r'\b(?:trigger_event\s*=\s*(?:\{\s*id\s*=\s*)?|on_action\s*=\s*)([a-zA-Z0-9_.]+)', content)))
    mod_dir = output_root.resolve()
    if mod_dir == vanilla_root.resolve() or mod_dir.is_relative_to(vanilla_root.resolve()):
        raise CompositionError('Output must not be inside vanilla root')
    out_rel = f'common/activities/activity_types/{target_id}.txt'
    dest = confined_path(mod_dir, out_rel)
    if not recipe.get('allow_overwrite_generated', False):
        for protected in (dest, mod_dir / 'descriptor.mod', mod_dir / 'composition-report.json'):
            if protected.exists():
                raise CompositionError(f"Refusing to overwrite existing generated or mod file: {protected}")
    copies = []
    rewrites = []
    for asset in recipe.get('assets', []):
        if set(asset) != {'mode', 'source', 'target'} or asset['mode'] != 'clone':
            raise CompositionError('Asset must specify mode=clone, source, target')
        source, target = asset['source'], asset['target']
        if not source.startswith('gfx/') or not target.startswith('gfx/') or source == target:
            raise CompositionError('Assets must be distinct paths under gfx/')
        src = confined_path(vanilla_root, source)
        dst = confined_path(mod_dir, target)
        if not src.is_file():
            raise CompositionError(f'Missing asset: {src}')
        if dst.exists():
            raise CompositionError(f'Asset destination exists: {dst}')
        quoted = f'"{source}"'
        if quoted not in content:
            raise CompositionError(f'Asset source has no exact quoted reference in activity: {source}')
        rewrites.append((quoted, f'"{target}"'))
        copies.append((src, dst))
    for old, new in rewrites:
        content = content.replace(old, new)
    # Write only after completing all input checks.
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding='utf-8-sig')
    for src, dst in copies:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    report = {
        'source_version': recipe.get('source_version', 'unknown'),
        'source_path': src_rel, 'source_git_blob_sha': actual,
        'source_id': source_id, 'target_id': target_id,
        'overrides': overrides, 'generated_activity': out_rel,
        'copied_assets': [str(dst.relative_to(mod_dir)) for _, dst in copies],
        'external_references_sample': external,
        'status': 'STATIC_ONLY_NOT_GAME_VALIDATED',
        'warnings': [
            'Referenced vanilla events, scripted values, loc and GUI are NOT cloned or validated.',
            'The new activity may need explicit localization, event routing and GUI adapters.',
            'No load-order, DLC, behavior or CK3 runtime validation performed.'
        ]
    }
    (mod_dir / 'composition-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (mod_dir / 'descriptor.mod').write_text('name="CK3 Library Activity Prototype"\nversion="0.1.0"\nsupported_version="1.20.*"\n', encoding='utf-8')
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description='Safe CK3 activity prototype generator')
    p.add_argument('--recipe', type=Path, required=True)
    p.add_argument('--vanilla-root', type=Path, required=True, help='Game folder containing common/, gui/, gfx/')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    recipe = json.loads(a.recipe.read_text(encoding='utf-8-sig'))
    report = compose(recipe, a.vanilla_root, a.output)
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
