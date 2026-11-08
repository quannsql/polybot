"""Verify an extracted TWAP release with only Python's standard library."""
import hashlib
import json
from pathlib import Path


def main():
    root=Path(__file__).resolve().parent
    manifest=json.loads((root/'RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError(f'Missing/unsafe release path: {name}')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise RuntimeError(f'Release file changed: {name}')
    print(f"Verified {len(manifest['files'])} files; strategy={manifest['strategy']}; sdk={manifest['sdk']}")


if __name__=='__main__': main()
