#!/usr/bin/env python3
"""
Extract any app's data from an iPhone backup.

Usage:
    python3 extract_app.py --backup /path/to/backup --app "instagram" --output ./instagram_data
    python3 extract_app.py --backup /path/to/backup --app "IRCTC" --output ./irctc_tickets
    python3 extract_app.py --backup /path/to/backup --domain "CameraRollDomain" --output ./camera_roll
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


def find_backup_root(backup_arg: str) -> Path:
    p = Path(backup_arg)
    if not p.exists():
        sys.exit(f"Error: path does not exist: {p}")
    manifest = p / "Manifest.db"
    if manifest.exists():
        return p
    subdirs = [d for d in p.iterdir() if d.is_dir() and (d / "Manifest.db").exists()]
    if len(subdirs) == 1:
        return subdirs[0]
    if len(subdirs) > 1:
        return max(subdirs, key=lambda d: d.stat().st_mtime)
    sys.exit(f"Error: no Manifest.db found in {p}")


def resolve_file(backup_dir: Path, file_id: str) -> Path | None:
    p = backup_dir / file_id[:2] / file_id
    return p if p.exists() else None


def main():
    parser = argparse.ArgumentParser(
        description="Extract any app's data from an iPhone backup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract IRCTC tickets (PDFs)
  python3 extract_app.py -b ./backup -a irctc -o ./irctc_data

  # Extract Camera Roll
  python3 extract_app.py -b ./backup --domain CameraRollDomain -o ./photos

  # Extract Apple Notes
  python3 extract_app.py -b ./backup -a notes -o ./notes_data

  # Extract specific file types from Chrome
  python3 extract_app.py -b ./backup -a chrome -o ./chrome --ext .sqlite .pdf
        """,
    )
    parser.add_argument("--backup", "-b", required=True, help="Path to iPhone backup directory")
    parser.add_argument("--output", "-o", required=True, help="Output directory")
    parser.add_argument("--app", "-a", help="App name to search for (case-insensitive substring match)")
    parser.add_argument("--domain", "-d", help="Exact domain name (e.g., CameraRollDomain)")
    parser.add_argument("--ext", nargs="*", help="Only extract files with these extensions (e.g., .pdf .jpg)")
    args = parser.parse_args()

    if not args.app and not args.domain:
        sys.exit("Error: provide --app or --domain")

    backup_dir = find_backup_root(args.backup)
    manifest = backup_dir / "Manifest.db"
    output = Path(args.output)

    conn = sqlite3.connect(str(manifest))

    # Find matching domains
    if args.domain:
        domains = [args.domain]
    else:
        pattern = f"%{args.app}%"
        rows = conn.execute("SELECT DISTINCT domain FROM Files WHERE domain LIKE ?", (pattern,)).fetchall()
        domains = [r[0] for r in rows]

    if not domains:
        sys.exit(f"Error: no app found matching '{args.app or args.domain}'")

    print(f"{'=' * 70}")
    print(f"  iPhone Backup App Extractor")
    print(f"{'=' * 70}")
    print(f"  Matching domains:")
    for d in domains:
        count = conn.execute("SELECT COUNT(*) FROM Files WHERE domain=?", (d,)).fetchone()[0]
        print(f"    {d} ({count:,} files)")
    print()

    output.mkdir(parents=True, exist_ok=True)
    total_extracted = 0
    total_skipped = 0

    ext_filter = set(args.ext) if args.ext else None

    for domain in domains:
        rows = conn.execute(
            "SELECT fileID, relativePath FROM Files WHERE domain=? AND relativePath != ''",
            (domain,),
        ).fetchall()

        for file_id, rel_path in rows:
            if ext_filter:
                if not any(rel_path.lower().endswith(e.lower()) for e in ext_filter):
                    total_skipped += 1
                    continue

            src = resolve_file(backup_dir, file_id)
            if not src:
                continue

            dest = output / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)

            n = 1
            original_dest = dest
            while dest.exists():
                dest = original_dest.parent / f"{original_dest.stem}_{n}{original_dest.suffix}"
                n += 1

            shutil.copy2(src, dest)
            total_extracted += 1

        if total_extracted > 0 and total_extracted % 500 == 0:
            print(f"  Extracted {total_extracted:,} files...")

    conn.close()

    print(f"\n{'=' * 70}")
    print(f"  EXTRACTION COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Output:     {output}")
    print(f"  Extracted:  {total_extracted:,} files")
    if total_skipped:
        print(f"  Skipped:    {total_skipped:,} (filtered by extension)")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
