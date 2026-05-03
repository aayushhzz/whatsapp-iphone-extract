#!/usr/bin/env bash
# Step 1: Create an iPhone backup via USB using libimobiledevice.
# Usage: ./backup_iphone.sh [OUTPUT_DIR]
set -euo pipefail

OUTPUT_DIR="${1:-./iphone_backup}"

echo "=========================================="
echo " iPhone USB Backup Tool"
echo "=========================================="

# --- Check dependencies ---
if ! command -v idevice_id &>/dev/null; then
    echo ""
    echo "[!] libimobiledevice is not installed."
    echo ""
    echo "Install it with:"
    echo "  macOS:  brew install libimobiledevice"
    echo "  Linux:  sudo apt install libimobiledevice-utils"
    echo ""
    exit 1
fi

# --- Detect device ---
echo ""
echo "[1/3] Detecting iPhone..."
UDID=$(idevice_id -l 2>/dev/null | head -1)
if [ -z "$UDID" ]; then
    echo "[!] No iPhone detected via USB."
    echo ""
    echo "Make sure:"
    echo "  1. iPhone is connected via USB cable"
    echo "  2. iPhone is unlocked"
    echo "  3. You tapped 'Trust' on the iPhone when prompted"
    echo ""
    echo "Then try: idevicepair pair"
    exit 1
fi

DEVICE_NAME=$(ideviceinfo -k DeviceName 2>/dev/null || echo "Unknown")
IOS_VERSION=$(ideviceinfo -k ProductVersion 2>/dev/null || echo "Unknown")
echo "  Found: $DEVICE_NAME (iOS $IOS_VERSION)"
echo "  UDID:  $UDID"

# --- Pair if needed ---
echo ""
echo "[2/3] Ensuring device is paired..."
if ! idevicepair validate &>/dev/null; then
    echo "  Pairing... (tap 'Trust' on your iPhone if prompted)"
    idevicepair pair
fi
echo "  Paired."

# --- Backup ---
echo ""
echo "[3/3] Starting backup to: $OUTPUT_DIR"
echo "  This may take 10-60 minutes depending on device size."
echo "  Keep your iPhone connected and unlocked."
echo ""
mkdir -p "$OUTPUT_DIR"
idevicebackup2 backup --full "$OUTPUT_DIR"

echo ""
echo "=========================================="
echo " Backup complete!"
echo "=========================================="
BACKUP_SIZE=$(du -sh "$OUTPUT_DIR" 2>/dev/null | cut -f1)
echo "  Location: $OUTPUT_DIR"
echo "  Size:     $BACKUP_SIZE"
echo ""
echo "Next step: extract WhatsApp data with:"
echo "  python3 extract_whatsapp.py --backup \"$OUTPUT_DIR\" --output ./whatsapp_output"
