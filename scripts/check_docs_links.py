#!/usr/bin/env python3
"""Check local relative links in Markdown files, including links with anchors."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'(?<!!)\[[^\]]*\]\(([^)]+)\)')


def main():
    errors = []
    for markdown in ROOT.rglob('*.md'):
        if any(part in {'.git', 'node_modules', '.venv'} for part in markdown.parts):
            continue
        source = markdown.relative_to(ROOT)
        for target in LINK.findall(markdown.read_text(encoding='utf-8')):
            target = target.strip().split()[0].strip('<>')
            if not target or target.startswith(('http://', 'https://', 'mailto:', '#', 'tel:')):
                continue
            path = target.split('#', 1)[0].split('?', 1)[0]
            if not path:
                continue
            resolved = (markdown.parent / path).resolve()
            if not resolved.exists():
                errors.append(f'{source}: {target}')
    if errors:
        print('Broken relative Markdown links:')
        print('\n'.join(errors))
        return 1
    print('All relative Markdown links resolve.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
