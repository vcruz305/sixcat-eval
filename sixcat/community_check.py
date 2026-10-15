"""Validate public-result contributions as data with a trusted base validator."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .community import MAX_BYTES, START, END, SubmissionError, load_registry, read_json, require
from .community_export import validate_collection, replace_table


def tracked(root):
    try:
        done = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SubmissionError('Expected a git checkout for PR scope validation') from exc
    return set(done.stdout.decode('utf-8').split('\0')) - {''}


def entries(root):
    directory = root / 'community/results'
    if not directory.exists():
        return []
    require(not directory.is_symlink(), 'Results directory must not be a symlink')
    found = []
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(), 'Symlinks are not permitted in community results')
        if path.is_file():
            require(path.suffix == '.json' or path.name == '.gitkeep', 'Only JSON results belong in community/results')
            if path.suffix == '.json':
                found.append((path.relative_to(root).as_posix(), read_json(path)))
    require(len(found) <= 5000, 'Too many result files')
    return found


def outside_table(text):
    require(text.count(START) == text.count(END) == 1, 'Invalid managed table markers')
    before, rest = text.split(START)
    _, after = rest.split(END)
    return before, after


def check(root, *, base=None, author=None, render=False):
    root = root.resolve()
    # Never trust a submission's proposed registry. Base is a separately checked-out
    # trusted revision, not a ref or path taken from the submitted JSON.
    registry = load_registry((base / 'sixcat/community-compatibility.json') if base else None)
    pairs = entries(root)
    docs = validate_collection(pairs, registry)
    readme_path = root/'README.md'
    require(not readme_path.is_symlink(), 'README must not be a symlink')
    require(readme_path.stat().st_size <= MAX_BYTES, 'README size limit')
    readme = readme_path.read_text(encoding='utf-8')
    expected = replace_table(readme, docs)
    if base:
        base = base.resolve()
        base_files, head_files = tracked(base), tracked(root)
        changed = set()
        for name in base_files | head_files:
            a, b = base/name, root/name
            if name not in base_files or name not in head_files:
                changed.add(name)
            elif a.is_symlink() != b.is_symlink():
                changed.add(name)
            elif a.is_file() and b.is_file() and a.read_bytes() != b.read_bytes():
                changed.add(name)
        result_changes = {p for p in changed if p.startswith('community/results/')}
        if result_changes:
            require(len(result_changes) == 1, 'A result PR must add exactly one public JSON')
            path = next(iter(result_changes))
            require(path.endswith('.json') and path in head_files and path not in base_files,
                    'Existing result receipts are append-only; modifications/deletions are not result submissions')
            require(changed == {path, 'README.md'}, 'Result PRs may only add one JSON and its generated README row')
            require(outside_table((base/'README.md').read_text(encoding='utf-8')) == outside_table(readme),
                    'A result PR cannot change README content outside the managed table')
            added = dict(pairs)[path]
            if author:
                require(added['contributor'].casefold() == author.casefold(), 'Contributor must match the PR author')
    if render:
        require(base is None, 'Rendering is a local maintainer operation, not PR validation')
        readme_path.write_text(expected, encoding='utf-8')
    else:
        require(readme == expected, 'README table does not match JSON receipts; regenerate with sixcat community render')
    return {'status': 'valid', 'submissions': len(docs), 'executed_submitted_code': False,
            'validation': 'format and arithmetic consistency only; not model/weight attestation'}


def main(argv=None):
    p = argparse.ArgumentParser(prog='sixcat community', description=__doc__)
    p.add_argument('command', choices=['validate','render'])
    p.add_argument('--root', type=Path, default=Path('.'))
    p.add_argument('--base', type=Path)
    p.add_argument('--pr-author')
    args = p.parse_args(argv)
    try:
        print(json.dumps(check(args.root, base=args.base, author=args.pr_author, render=args.command == 'render')))
        return 0
    except (SubmissionError, OSError, ValueError, KeyError, TypeError) as exc:
        print('Community validation: ' + (str(exc) if isinstance(exc, SubmissionError) else 'Malformed result or repository'), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
