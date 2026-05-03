#!/usr/bin/env python3
"""
List all apps and their data in an iPhone backup.

Usage:
    python3 list_backup_apps.py --backup /path/to/backup
    python3 list_backup_apps.py --backup /path/to/backup --json
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

APP_NAMES = {
    "net.whatsapp.WhatsApp": "WhatsApp",
    "com.google.chrome.ios": "Chrome",
    "com.amazon.aiv.AIVApp": "Prime Video",
    "com.google.keyboard": "Gboard",
    "com.google.GoogleMobile": "Google",
    "com.microsoft.skype.teams": "Microsoft Teams",
    "com.ubercab.UberClient": "Uber",
    "com.apple.PosterBoard": "Lock Screen",
    "com.netflix.Netflix": "Netflix",
    "com.amazon.AmazonIN": "Amazon",
    "com.google.ios.youtube": "YouTube",
    "com.chess.iphone": "Chess.com",
    "com.apple.notes": "Apple Notes",
    "com.superkalam": "SuperKalam",
    "com.phonepe.PhonePeApp": "PhonePe",
    "com.BhartiMobile.myairtel": "Airtel",
    "com.supercell.scroll": "Supercell",
    "bundl.swiggy": "Swiggy",
    "olacabs.OlaCabs": "Ola",
    "com.nextbillion.groww": "Groww",
    "com.tinyspeck.chatlyio": "Slack",
    "com.burbn.instagram": "Instagram",
    "com.one97.paytm": "Paytm",
    "com.Faasos": "EatSure/Faasos",
    "BookMyShow.com": "BookMyShow",
    "com.openai.chat": "ChatGPT",
    "in.startv.hotstar": "Hotstar",
    "com.reddit.Reddit": "Reddit",
    "com.myntra.Myntra": "Myntra",
    "com.brave.ios.browser": "Brave Browser",
    "bike.rapido.customer": "Rapido",
    "com.ge.capital.sbiapp.SBI": "SBI",
    "cris.org.in.prs.ima": "IRCTC",
    "com.dominosin.olo": "Dominos",
    "com.pnbios1128": "PNB",
    "com.coinswitch.kuber": "CoinSwitch",
    "com.toyopagroup.picaboo": "Snapchat",
    "com.zomato.zomato": "Zomato",
    "com.Iphone.MMT": "MakeMyTrip",
    "com.linkedin.LinkedIn": "LinkedIn",
    "com.apple.mobilesafari": "Safari",
    "com.dream11.sportsguru": "Dream11",
    "com.google.Maps": "Google Maps",
    "com.spotify.client": "Spotify",
    "com.google.Gmail": "Gmail",
    "com.negd.digilocker": "DigiLocker",
    "com.google.photos": "Google Photos",
    "com.google.Classroom": "Google Classroom",
    "org.cris.aikyam": "IRCTC (Aikyam)",
    "com.flipkart.flipkart": "Flipkart",
    "com.appflipkart.flipkart": "Flipkart",
    "com.truesoftware.TrueCallerOther": "Truecaller",
}

SYSTEM_DOMAIN_NAMES = {
    "CameraRollDomain": "Camera Roll (Photos & Videos)",
    "HomeDomain": "System Settings (WiFi, Contacts, SMS, Calendar, Call History)",
    "MediaDomain": "Media (Ringtones, iTunes content)",
    "RootDomain": "Root System Files",
    "HealthDomain": "Apple Health Data",
    "KeychainDomain": "Keychain (Saved Passwords)",
    "WirelessDomain": "WiFi & Bluetooth Settings",
    "DatabaseDomain": "System Databases",
    "KeyboardDomain": "Keyboard Settings & Dictionaries",
    "TonesDomain": "Custom Ringtones",
    "HomeKitDomain": "HomeKit Devices",
}


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


def get_readable_name(domain: str) -> str:
    if domain in SYSTEM_DOMAIN_NAMES:
        return SYSTEM_DOMAIN_NAMES[domain]
    bundle_id = domain
    for prefix in ("AppDomainGroup-group.", "AppDomainPlugin-", "AppDomain-"):
        if bundle_id.startswith(prefix):
            bundle_id = bundle_id[len(prefix):]
            break
    for prefix in ("SysContainerDomain-", "SysSharedContainerDomain-systemgroup."):
        if bundle_id.startswith(prefix):
            return f"System: {bundle_id[len(prefix):]}"
    return APP_NAMES.get(bundle_id, bundle_id)


def main():
    parser = argparse.ArgumentParser(description="List all apps and data in an iPhone backup.")
    parser.add_argument("--backup", "-b", required=True, help="Path to iPhone backup directory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    backup_dir = find_backup_root(args.backup)
    manifest = backup_dir / "Manifest.db"

    conn = sqlite3.connect(str(manifest))
    rows = conn.execute("""
        SELECT
            domain,
            COUNT(*) as total,
            SUM(CASE WHEN relativePath LIKE '%.sqlite%' OR relativePath LIKE '%.db' THEN 1 ELSE 0 END),
            SUM(CASE WHEN relativePath LIKE '%.jpg' OR relativePath LIKE '%.jpeg' OR relativePath LIKE '%.heic'
                      OR relativePath LIKE '%.png' OR relativePath LIKE '%.webp' OR relativePath LIKE '%.gif' THEN 1 ELSE 0 END),
            SUM(CASE WHEN relativePath LIKE '%.mp4' OR relativePath LIKE '%.mov' OR relativePath LIKE '%.m4v' THEN 1 ELSE 0 END),
            SUM(CASE WHEN relativePath LIKE '%.mp3' OR relativePath LIKE '%.m4a' OR relativePath LIKE '%.opus'
                      OR relativePath LIKE '%.aac' OR relativePath LIKE '%.caf' THEN 1 ELSE 0 END),
            SUM(CASE WHEN relativePath LIKE '%.pdf' THEN 1 ELSE 0 END)
        FROM Files GROUP BY domain ORDER BY total DESC
    """).fetchall()
    conn.close()

    total_files = sum(r[1] for r in rows)

    if args.json:
        data = []
        for domain, total, dbs, imgs, vids, audio, pdfs in rows:
            data.append({
                "domain": domain,
                "name": get_readable_name(domain),
                "files": total,
                "databases": dbs,
                "images": imgs,
                "videos": vids,
                "audio": audio,
                "pdfs": pdfs,
            })
        print(json.dumps({"total_files": total_files, "domains": len(rows), "apps": data}, indent=2))
        return

    print(f"\n{'=' * 90}")
    print(f"  iPhone Backup: {backup_dir}")
    print(f"  Total files: {total_files:,} across {len(rows)} app domains")
    print(f"{'=' * 90}\n")
    print(f"  {'App':<40} {'Files':>8}  {'DBs':>5}  {'Imgs':>7}  {'Vids':>6}  {'Audio':>6}  {'PDFs':>5}")
    print(f"  {'-' * 40} {'-' * 8}  {'-' * 5}  {'-' * 7}  {'-' * 6}  {'-' * 6}  {'-' * 5}")

    for domain, total, dbs, imgs, vids, audio, pdfs in rows:
        if total < 5:
            continue
        name = get_readable_name(domain)
        if len(name) > 39:
            name = name[:36] + "..."
        print(f"  {name:<40} {total:>8,}  {dbs:>5}  {imgs:>7,}  {vids:>6,}  {audio:>6,}  {pdfs:>5}")

    print(f"\n{'=' * 90}")


if __name__ == "__main__":
    main()
