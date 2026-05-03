# WhatsApp iPhone Backup Extractor

Extract **all WhatsApp chats, media (photos, videos, voice notes, PDFs), and metadata** from an iPhone backup to your Mac or Linux machine. No jailbreak required.

Also includes tools to **list all apps** in a backup, **extract any app's data**, and **embed EXIF metadata** (dates, GPS) into extracted media files.

## What You Get

```
whatsapp_output/
├── chats/                    # Text files of every conversation
│   ├── John Doe.txt
│   ├── Family Group.txt
│   └── ...
├── media/                    # All photos, videos, voice notes, PDFs
│   ├── John Doe/
│   │   ├── a1b2c3d4.jpg
│   │   ├── e5f6g7h8.mp4
│   │   └── i9j0k1l2.opus
│   ├── Family Group/
│   │   └── ...
│   └── ...
├── database/
│   └── ChatStorage.sqlite    # Raw WhatsApp database for custom queries
└── report.json               # Extraction statistics
```

## Prerequisites

- **macOS** or **Linux** (macOS recommended for iPhone USB access)
- **Python 3.10+** (no pip packages needed)
- **iPhone connected via USB** (for creating the backup)
- **libimobiledevice** (for creating the backup from the command line)
- **exiftool** (optional, for embedding EXIF metadata)

### Install Dependencies

```bash
# macOS
brew install libimobiledevice
brew install exiftool          # optional, for EXIF embedding

# Linux (Ubuntu/Debian)
sudo apt install libimobiledevice-utils
sudo apt install libimage-exiftool-perl  # optional
```

## Quick Start

### Step 1: Create an iPhone Backup

Connect your iPhone via USB, unlock it, and tap "Trust" when prompted.

```bash
./backup_iphone.sh ./my_backup
```

Or use Finder: click your iPhone in the sidebar > "Back Up Now".

> **Important:** Use an **unencrypted** backup. The scripts read the backup's `Manifest.db` to locate files, which requires it to be unencrypted.

### Step 2: Extract WhatsApp Data

```bash
# Extract all chats and media
python3 extract_whatsapp.py --backup ./my_backup --output ./whatsapp_out

# Extract with EXIF dates/GPS embedded into media files
python3 extract_whatsapp.py --backup ./my_backup --output ./whatsapp_out --embed-exif

# Extract only chats matching a name
python3 extract_whatsapp.py --backup ./my_backup --output ./whatsapp_out --chat "Mom"
```

### Step 3 (Optional): List All Apps in Backup

```bash
python3 list_backup_apps.py --backup ./my_backup

# Output as JSON
python3 list_backup_apps.py --backup ./my_backup --json
```

### Step 4 (Optional): Extract Any App's Data

```bash
# Extract IRCTC train tickets
python3 extract_app.py --backup ./my_backup --app irctc --output ./irctc_data

# Extract Camera Roll (all photos/videos)
python3 extract_app.py --backup ./my_backup --domain CameraRollDomain --output ./photos

# Extract Apple Notes
python3 extract_app.py --backup ./my_backup --app notes --output ./notes_data

# Extract only PDFs from Chrome
python3 extract_app.py --backup ./my_backup --app chrome --output ./chrome_pdfs --ext .pdf
```

## How It Works

1. **iPhone backups** store all app data as SHA-1-hashed files in a flat directory structure.
2. A `Manifest.db` SQLite database maps each file to its original app domain and path.
3. WhatsApp stores messages in `ChatStorage.sqlite` and media in `Message/Media/`.
4. The scripts read `Manifest.db` to find WhatsApp files, extract the chat database, join messages with media paths, and copy the actual media files to organized output folders.
5. Optionally, `exiftool` is used to write the WhatsApp message timestamp and GPS coordinates back into the image/video EXIF data.

## EXIF Metadata

WhatsApp **strips EXIF data** (camera info, GPS, date taken) from images for privacy. When you use `--embed-exif`, the script recovers what it can:

- **Date/Time**: The WhatsApp message timestamp is written as `DateTimeOriginal`, `CreateDate`, and `ModifyDate` EXIF tags.
- **GPS**: If the WhatsApp database has valid GPS coordinates for a media item, they are written as EXIF GPS tags.
- **File dates**: The filesystem modification date of every media file is set to the message timestamp, so files sort correctly in Finder/Explorer.

## Existing Backup

If you already have an iPhone backup (from Finder, iTunes, or `idevicebackup2`), skip Step 1 and point `--backup` directly at it:

```bash
# Default macOS Finder backup location
python3 extract_whatsapp.py \
  --backup ~/Library/Application\ Support/MobileSync/Backup/ \
  --output ./whatsapp_out \
  --embed-exif
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `No iPhone detected` | Unlock iPhone, tap "Trust This Computer", try `idevicepair pair` |
| `Manifest.db not found` | Make sure you're pointing at the backup directory (contains `Manifest.db` or a UDID subfolder) |
| `WhatsApp database not found` | WhatsApp may not be installed, or the backup is incomplete. Re-run the backup. |
| `Permission denied` | On macOS, grant Full Disk Access to Terminal: System Settings > Privacy > Full Disk Access |
| `exiftool not found` | Install it: `brew install exiftool` (macOS) or `sudo apt install libimage-exiftool-perl` (Linux) |
| Encrypted backup | These scripts require an unencrypted backup. Re-create it without the "Encrypt local backup" checkbox. |

## Supported WhatsApp Versions

The scripts auto-detect the database schema and handle differences across iOS/WhatsApp versions:
- Chat table: `ZWACHATSESSION` or `ZWACHATS`
- Message columns: `ZTEXT`/`ZCONTENT`, `ZFROMJID`/`ZSENDERJID`, `ZMESSAGEDATE`/`ZSENTDATE`
- Media join: `ZWAMEDIAITEM` with `ZMEDIALOCALPATH`
- Both modern (`AppDomainGroup-group.net.whatsapp.WhatsApp.shared`) and legacy (`AppDomain-net.whatsapp.WhatsApp`) domains

## License

MIT License. Use freely.
