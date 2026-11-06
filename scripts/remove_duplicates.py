#!/usr/bin/env python3
"""Find and optionally remove exact duplicate files.

The default mode is a dry run. Files are only removed when --delete is passed.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from collections import defaultdict
from pathlib import Path


DUPLICATE_SUFFIX = re.compile(r" \(\d+\)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find and remove exact duplicate files.")
    parser.add_argument("directory", type=Path, help="Directory to scan")
    parser.add_argument("--delete", action="store_true", help="Delete duplicates instead of only listing them")
    parser.add_argument(
        "--keep",
        choices=("first", "newest", "oldest"),
        default="oldest",
        help="Which copy to preserve (default: original name, then oldest)",
    )
    return parser.parse_args()


def iter_files(directory: Path) -> list[Path]:
    files = []
    for path in directory.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        files.append(path)
    return files


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def choose_keep(paths: list[Path], mode: str) -> Path:
    if mode == "newest":
        return max(paths, key=lambda path: (path.stat().st_mtime_ns, str(path)))
    if mode == "oldest":
        originals = [path for path in paths if not DUPLICATE_SUFFIX.search(path.stem)]
        if originals:
            paths = originals
        return min(paths, key=lambda path: (path.stat().st_mtime_ns, str(path)))
    return min(paths, key=lambda path: str(path))


def main() -> int:
    args = parse_args()
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        raise SystemExit(f"Not a directory: {directory}")

    by_size: defaultdict[int, list[Path]] = defaultdict(list)
    for path in iter_files(directory):
        try:
            by_size[path.stat().st_size].append(path)
        except OSError as error:
            print(f"SKIP {path}: {error}")

    duplicate_groups: list[tuple[str, list[Path]]] = []
    for candidates in by_size.values():
        if len(candidates) < 2:
            continue
        by_hash: defaultdict[str, list[Path]] = defaultdict(list)
        for path in candidates:
            try:
                by_hash[sha256(path)].append(path)
            except OSError as error:
                print(f"SKIP {path}: {error}")
        duplicate_groups.extend(
            (file_hash, paths) for file_hash, paths in by_hash.items() if len(paths) > 1
        )

    duplicates = 0
    reclaimed = 0
    for file_hash, paths in sorted(duplicate_groups, key=lambda item: str(item[1][0])):
        keep = choose_keep(paths, args.keep)
        print(f"\nHash {file_hash}")
        print(f"KEEP  {keep}")
        for duplicate in sorted(paths):
            if duplicate == keep:
                continue
            duplicates += 1
            size = duplicate.stat().st_size
            reclaimed += size
            if args.delete:
                try:
                    duplicate.unlink()
                    print(f"DELETE {duplicate}")
                except OSError as error:
                    print(f"ERROR {duplicate}: {error}")
            else:
                print(f"DUPLICATE {duplicate}")

    action = "deleted" if args.delete else "would be deleted"
    print(f"\nFound {duplicates} duplicate file(s); {action}; {reclaimed:,} bytes.")
    if not args.delete and duplicates:
        print("Run again with --delete to remove them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
