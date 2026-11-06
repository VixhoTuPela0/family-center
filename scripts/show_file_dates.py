#!/usr/bin/env python3
"""Show filesystem dates for files."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


def format_timestamp(value: float | None) -> str:
    if value is None:
        return "No disponible"
    return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def show_file(path: Path) -> None:
    try:
        stat = path.stat()
    except OSError as error:
        print(f"{path}: ERROR: {error}", file=sys.stderr)
        return

    print(f"\nArchivo: {path}")
    print(f"Tamaño: {stat.st_size:,} bytes")
    print(f"Modificación (mtime): {format_timestamp(stat.st_mtime)}")
    print(f"Cambio de metadata/permisos (ctime): {format_timestamp(stat.st_ctime)}")
    birthtime = getattr(stat, "st_birthtime", None)
    if birthtime is None:
        birthtime = getattr(stat, "st_birthtime_ns", None)
        if birthtime is not None:
            birthtime /= 1_000_000_000
    print(f"Creación (birthtime): {format_timestamp(birthtime)}")
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Muestra las fechas del sistema de archivos."
    )
    parser.add_argument("path", type=Path, help="Archivo o directorio")
    args = parser.parse_args()
    path = args.path.expanduser().resolve()
    if path.is_file():
        show_file(path)
        return 0
    if path.is_dir():
        files = sorted(item for item in path.rglob("*") if item.is_file())
        if not files:
            print("No se encontraron archivos.")
            return 0
        for item in files:
            show_file(item)
        return 0
    parser.error(f"No existe o no es un archivo/directorio: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
