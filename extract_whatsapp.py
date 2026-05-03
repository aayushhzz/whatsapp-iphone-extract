#!/usr/bin/env python3
"""
Extract WhatsApp chats and media from an unencrypted iPhone backup.

Usage:
    python3 extract_whatsapp.py --backup /path/to/backup --output ./whatsapp_output
    python3 extract_whatsapp.py --backup /path/to/backup --output ./out --embed-exif
    python3 extract_whatsapp.py --backup /path/to/backup --output ./out --chat "John"
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

IOS_EPOCH_OFFSET = 978307200
WA_DOMAINS = [
    "AppDomainGroup-group.net.whatsapp.WhatsApp.shared",
    "AppDomain-net.whatsapp.WhatsApp",
]
EXIF_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tiff", ".mp4", ".mov", ".m4v", ".3gp"}


def find_backup_root(backup_arg: str) -> Path:
    """Resolve the backup directory, auto-detecting the UDID subfolder."""
    p = Path(backup_arg)
    if not p.exists():
        sys.exit(f"Error: backup path does not exist: {p}")

    manifest = p / "Manifest.db"
    if manifest.exists():
        return p

    subdirs = [d for d in p.iterdir() if d.is_dir() and (d / "Manifest.db").exists()]
    if len(subdirs) == 1:
        return subdirs[0]
    if len(subdirs) > 1:
        newest = max(subdirs, key=lambda d: d.stat().st_mtime)
        print(f"  Multiple backups found, using newest: {newest.name}")
        return newest

    sys.exit(f"Error: no Manifest.db found in {p} (is this an iPhone backup?)")


def build_media_index(manifest: Path, domain: str) -> dict:
    """Map WhatsApp media relative paths to backup file IDs."""
    conn = sqlite3.connect(str(manifest))
    rows = conn.execute(
        "SELECT fileID, relativePath FROM Files WHERE domain=? AND relativePath LIKE 'Message/Media/%.%'",
        (domain,),
    ).fetchall()
    conn.close()
    index = {}
    for file_id, rel_path in rows:
        wa_path = rel_path.replace("Message/Media/", "Media/", 1)
        index[wa_path] = file_id
    return index


def resolve_file(backup_dir: Path, file_id: str) -> Path | None:
    """Resolve a SHA-1 file ID to the actual file in the backup."""
    p = backup_dir / file_id[:2] / file_id
    return p if p.exists() else None


def find_whatsapp_db(backup_dir: Path, manifest: Path) -> tuple[Path | None, str]:
    """Locate the WhatsApp ChatStorage.sqlite and return (path, domain)."""
    conn = sqlite3.connect(str(manifest))
    for domain in WA_DOMAINS:
        for rel_path in ["ChatStorage.sqlite", "Documents/ChatStorage.sqlite"]:
            row = conn.execute(
                "SELECT fileID FROM Files WHERE domain=? AND relativePath=?",
                (domain, rel_path),
            ).fetchone()
            if row:
                src = resolve_file(backup_dir, row[0])
                if src:
                    conn.close()
                    return src, domain
    conn.close()
    return None, ""


def detect_schema(cur: sqlite3.Cursor) -> dict:
    """Auto-detect WhatsApp DB schema (column/table names vary across iOS versions)."""
    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    chat_table = next((t for t in ("ZWACHATSESSION", "ZWACHATS") if t in tables), None)
    if not chat_table:
        sys.exit("Error: no WhatsApp chat table found in database")

    chat_cols = {r[1] for r in cur.execute(f"PRAGMA table_info({chat_table})").fetchall()}
    msg_cols = {r[1] for r in cur.execute("PRAGMA table_info(ZWAMESSAGE)").fetchall()}
    has_media_table = "ZWAMEDIAITEM" in tables
    media_cols = {r[1] for r in cur.execute("PRAGMA table_info(ZWAMEDIAITEM)").fetchall()} if has_media_table else set()

    def pick(candidates, available):
        return next((c for c in candidates if c in available), None)

    return {
        "chat_table": chat_table,
        "chat_name": pick(("ZPARTNERNAME", "ZCONTACTJID", "ZJID"), chat_cols) or "Z_PK",
        "msg_chat_fk": pick(("ZCHATSESSION", "ZCHATID"), msg_cols),
        "msg_sender": pick(("ZFROMJID", "ZSENDERJID"), msg_cols),
        "msg_text": pick(("ZTEXT", "ZCONTENT", "ZMESSAGE"), msg_cols),
        "msg_ts": pick(("ZMESSAGEDATE", "ZSENTDATE", "ZCREATIONDATE"), msg_cols),
        "has_media_join": "ZMEDIAITEM" in msg_cols and has_media_table and "ZMEDIALOCALPATH" in media_cols,
    }


def safe_filename(name: str) -> str:
    """Convert a chat name to a safe filesystem name."""
    safe = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
    return safe or "unnamed"


def format_timestamp(ts) -> str:
    if ts is None:
        return "?"
    try:
        return datetime.fromtimestamp(ts + IOS_EPOCH_OFFSET).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def embed_exif(db_path: Path, media_root: Path):
    """Write EXIF dates and GPS into extracted media files using exiftool."""
    if not shutil.which("exiftool"):
        print("\n  [!] exiftool not found — skipping EXIF embedding.")
        print("      Install: brew install exiftool  (macOS) or sudo apt install libimage-exiftool-perl  (Linux)")
        return

    print("\n[EXIF] Embedding metadata into media files...")

    file_index = {}
    for f in media_root.rglob("*"):
        if f.is_file():
            file_index[f.name] = f

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("""
        SELECT mi.ZMEDIALOCALPATH, m.ZMESSAGEDATE, mi.ZLATITUDE, mi.ZLONGITUDE
        FROM ZWAMESSAGE m
        JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
        WHERE mi.ZMEDIALOCALPATH IS NOT NULL
    """).fetchall()
    conn.close()

    date_count, gps_count, fs_count = 0, 0, 0

    for mpath, msg_ts, lat, lon in rows:
        filename = Path(mpath).name
        ext = Path(mpath).suffix.lower()
        filepath = file_index.get(filename)
        if not filepath:
            continue

        # Set filesystem modification date
        if msg_ts:
            try:
                unix_ts = msg_ts + IOS_EPOCH_OFFSET
                os.utime(filepath, (unix_ts, unix_ts))
                fs_count += 1
            except Exception:
                pass

        if ext not in EXIF_EXTENSIONS:
            continue

        args = ["exiftool", "-overwrite_original", "-ignoreMinorErrors", "-quiet"]

        if msg_ts:
            try:
                dt = datetime.fromtimestamp(msg_ts + IOS_EPOCH_OFFSET)
                date_str = dt.strftime("%Y:%m:%d %H:%M:%S")
                args.extend([f"-DateTimeOriginal={date_str}", f"-CreateDate={date_str}", f"-ModifyDate={date_str}"])
                if ext in (".mp4", ".mov", ".m4v", ".3gp"):
                    args.extend([f"-MediaCreateDate={date_str}", f"-MediaModifyDate={date_str}"])
                date_count += 1
            except Exception:
                pass

        if lat and lon and -90 <= lat <= 90 and -180 <= lon <= 180:
            lat_ref = "N" if lat >= 0 else "S"
            lon_ref = "E" if lon >= 0 else "W"
            args.extend([
                f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={lat_ref}",
                f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={lon_ref}",
            ])
            gps_count += 1

        if len(args) > 4:
            args.append(str(filepath))
            try:
                subprocess.run(args, capture_output=True, timeout=30)
            except Exception:
                pass

    print(f"  Dates written:   {date_count:,}")
    print(f"  GPS written:     {gps_count:,}")
    print(f"  FS dates set:    {fs_count:,}")


def extract(args):
    backup_dir = find_backup_root(args.backup)
    manifest = backup_dir / "Manifest.db"
    output = Path(args.output)
    chats_dir = output / "chats"
    media_dir = output / "media"
    db_dir = output / "database"

    print("=" * 70)
    print("  WhatsApp iPhone Backup Extractor")
    print("=" * 70)
    print(f"  Backup:  {backup_dir}")
    print(f"  Output:  {output}")
    print()

    # --- Find WhatsApp DB ---
    print("[1/4] Locating WhatsApp database...")
    db_src, wa_domain = find_whatsapp_db(backup_dir, manifest)
    if not db_src:
        sys.exit("Error: WhatsApp database not found in backup.\n"
                 "Make sure WhatsApp is installed on the iPhone and the backup is complete.")

    for d in (chats_dir, media_dir, db_dir):
        d.mkdir(parents=True, exist_ok=True)

    db_out = db_dir / "ChatStorage.sqlite"
    shutil.copy2(db_src, db_out)
    print(f"  Found: {db_out.stat().st_size / 1024 / 1024:.1f} MB (domain: {wa_domain})")

    # --- Build media index ---
    print("\n[2/4] Indexing media files...")
    media_index = build_media_index(manifest, wa_domain)
    print(f"  {len(media_index):,} media files available in backup")

    # --- Read chats ---
    print("\n[3/4] Reading chats...")
    conn = sqlite3.connect(str(db_out))
    cur = conn.cursor()
    schema = detect_schema(cur)

    chats = cur.execute(
        f"SELECT Z_PK, {schema['chat_name']} FROM {schema['chat_table']} ORDER BY Z_PK"
    ).fetchall()

    # Filter chats if --chat is specified
    if args.chat:
        pattern = args.chat.lower()
        chats = [(cid, cn) for cid, cn in chats if cn and pattern in cn.lower()]
        print(f"  Filtered to {len(chats)} chats matching '{args.chat}'")
    else:
        print(f"  {len(chats)} chats found")

    # --- Export ---
    print(f"\n[4/4] Exporting...")
    stats = {"total_chats": len(chats), "total_messages": 0, "media_copied": 0, "media_missing": 0, "chats": []}

    for idx, (chat_id, chat_name) in enumerate(chats, 1):
        chat_name = chat_name or f"Unknown_{chat_id}"
        safe = safe_filename(chat_name)

        if schema["has_media_join"]:
            q = f"""
                SELECT m.{schema['msg_sender']}, m.{schema['msg_text']}, m.{schema['msg_ts']}, mi.ZMEDIALOCALPATH
                FROM ZWAMESSAGE m LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
                WHERE m.{schema['msg_chat_fk']} = ? ORDER BY m.{schema['msg_ts']} ASC
            """
        else:
            q = f"""
                SELECT {schema['msg_sender']}, {schema['msg_text']}, {schema['msg_ts']}, NULL
                FROM ZWAMESSAGE WHERE {schema['msg_chat_fk']}=? ORDER BY {schema['msg_ts']} ASC
            """

        msgs = cur.execute(q, (chat_id,)).fetchall()
        stats["total_messages"] += len(msgs)

        chat_media_dir = media_dir / safe
        chat_file = chats_dir / f"{safe}.txt"
        mc, mm = 0, 0

        with open(chat_file, "w", encoding="utf-8") as f:
            f.write(f"{'=' * 70}\n")
            f.write(f"WhatsApp Chat: {chat_name}\n")
            f.write(f"Messages: {len(msgs)}\n")
            f.write(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'=' * 70}\n\n")

            for sender, text, ts, mpath in msgs:
                ts_str = format_timestamp(ts)
                who = sender or "me"

                if text:
                    f.write(f"[{ts_str}] {who}: {text}\n")

                if mpath:
                    file_id = media_index.get(mpath)
                    src = resolve_file(backup_dir, file_id) if file_id else None
                    if src:
                        if not chat_media_dir.exists():
                            chat_media_dir.mkdir(parents=True, exist_ok=True)
                        dest_name = Path(mpath).name
                        dest = chat_media_dir / dest_name
                        n = 1
                        while dest.exists():
                            dest = chat_media_dir / f"{Path(dest_name).stem}_{n}{Path(dest_name).suffix}"
                            n += 1
                        shutil.copy2(src, dest)
                        f.write(f"[{ts_str}] {who}: [Media: {dest.name}]\n")
                        mc += 1
                    else:
                        f.write(f"[{ts_str}] {who}: [Media missing: {Path(mpath).name}]\n")
                        mm += 1

        stats["media_copied"] += mc
        stats["media_missing"] += mm
        stats["chats"].append({"name": str(chat_name), "messages": len(msgs), "media_copied": mc, "media_missing": mm})

        if idx % 50 == 0 or idx == len(chats):
            print(f"  [{idx}/{len(chats)}] {stats['media_copied']:,} media copied, {stats['media_missing']:,} missing")

    conn.close()

    # --- EXIF ---
    if args.embed_exif:
        embed_exif(db_out, media_dir)

    # --- Report ---
    with open(output / "report.json", "w") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    # --- Summary ---
    print(f"\n{'=' * 70}")
    print("  EXTRACTION COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Output:        {output}")
    print(f"  Chats:         {stats['total_chats']:,}")
    print(f"  Messages:      {stats['total_messages']:,}")
    print(f"  Media copied:  {stats['media_copied']:,}")
    print(f"  Media missing: {stats['media_missing']:,}")
    if stats["chats"]:
        print(f"\n  Top 10 chats:")
        for i, c in enumerate(sorted(stats["chats"], key=lambda x: x["messages"], reverse=True)[:10], 1):
            print(f"    {i:2d}. {c['name']}: {c['messages']:,} msgs, {c['media_copied']:,} media")
    print(f"{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract WhatsApp chats and media from an iPhone backup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract everything
  python3 extract_whatsapp.py --backup ./iphone_backup --output ./whatsapp_out

  # Extract with EXIF metadata (dates/GPS) embedded into media
  python3 extract_whatsapp.py --backup ./iphone_backup --output ./whatsapp_out --embed-exif

  # Extract only chats matching a name
  python3 extract_whatsapp.py --backup ./iphone_backup --output ./whatsapp_out --chat "John"
        """,
    )
    parser.add_argument("--backup", "-b", required=True, help="Path to iPhone backup directory")
    parser.add_argument("--output", "-o", required=True, help="Output directory for extracted data")
    parser.add_argument("--embed-exif", action="store_true", help="Embed date/GPS EXIF tags into media (requires exiftool)")
    parser.add_argument("--chat", "-c", help="Only extract chats matching this name (case-insensitive substring)")
    args = parser.parse_args()

    extract(args)


if __name__ == "__main__":
    main()
