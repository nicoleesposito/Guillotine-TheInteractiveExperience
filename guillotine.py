# ── IMPORTS ───────────────────────────────────────────────────────────────────

import os
import sys
import time
import logging
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # reads credentials from .env

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

CLOUDINARY_CLOUD_NAME  = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY     = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET  = os.getenv("CLOUDINARY_API_SECRET", "")

CLOUDINARY_FOLDER  = "guillotine"   # must match the folder set in cloudinary-config.js
POLL_INTERVAL_SEC  = 5              # how often to check for new uploads
PRINTER_KEYWORD    = "Phomemo"      # any part of the printer name in Windows
DELETE_AFTER_PRINT = True           # remove from Cloudinary after printing

import cloudinary
import cloudinary.api
import cloudinary.uploader
import requests
from PIL import Image
import win32print
import win32api

# ── LOGGING ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("guillotine")

# ── PRINTER DISCOVERY ─────────────────────────────────────────────────────────

def find_printer(keyword: str) -> str | None:
    """Return the exact Windows printer name matching `keyword`, or None."""
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = win32print.EnumPrinters(flags, None, 1)
    kw = keyword.lower()
    for p in printers:
        name = p[2]
        if kw in name.lower():
            return name
    log.warning(f"No printer matching '{keyword}' found. Installed printers:")
    for p in printers:
        log.warning(f"    {p[2]}")
    return None

# ── IMAGE PREPARATION ─────────────────────────────────────────────────────────

def prepare_image(src_path: str) -> str:
    """Convert image to a flat RGB BMP in a temp file. Returns the temp path."""
    img = Image.open(src_path)
    if img.mode in ("RGBA", "LA", "P"):
        if img.mode == "P":
            img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    tmp = tempfile.NamedTemporaryFile(suffix=".bmp", delete=False)
    tmp.close()
    img.save(tmp.name, "BMP")
    return tmp.name

# ── PRINT DISPATCH ────────────────────────────────────────────────────────────

def print_image(printer_name: str, src_path: str) -> bool:
    """Send image to printer via Windows ShellExecute. Returns True on success."""
    tmp_path = None
    try:
        tmp_path = prepare_image(src_path)
        log.info(f"Sending to printer '{printer_name}': {Path(src_path).name}")
        win32api.ShellExecute(
            0,
            "printto",
            tmp_path,
            f'"{printer_name}"',
            ".",
            0,
        )
        # Give the spooler time to read the BMP before we delete the temp file
        time.sleep(15)
        return True
    except Exception as exc:
        log.error(f"Print failed for '{src_path}': {exc}")
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

# ── CLOUDINARY POLLING ────────────────────────────────────────────────────────

def poll_and_print(printer_name: str, seen: set):
    """Check Cloudinary for new uploads and print any that haven't been seen."""
    try:
        result = cloudinary.api.resources(
            type="upload",
            prefix=f"{CLOUDINARY_FOLDER}/",
            max_results=100,
        )
    except Exception as exc:
        log.error(f"Cloudinary API error: {exc}")
        return

    for resource in result.get("resources", []):
        public_id = resource["public_id"]
        if public_id in seen:
            continue
        seen.add(public_id)

        url = resource["secure_url"]
        suffix = Path(resource.get("format", "jpg")).suffix or ".jpg"
        if not suffix.startswith("."):
            suffix = "." + suffix

        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.close()
        try:
            log.info(f"Downloading: {public_id}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            with open(tmp.name, "wb") as f:
                f.write(response.content)

            success = print_image(printer_name, tmp.name)
            if success and DELETE_AFTER_PRINT:
                cloudinary.uploader.destroy(public_id)
                log.info(f"Deleted from Cloudinary: {public_id}")
        except Exception as exc:
            log.error(f"Error processing {public_id}: {exc}")
        finally:
            if os.path.exists(tmp.name):
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
        log.error("Missing Cloudinary credentials. Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
    )

    printer_name = find_printer(PRINTER_KEYWORD)
    if not printer_name:
        log.error(
            f"Could not find a printer matching '{PRINTER_KEYWORD}'. "
            "Make sure the Phomemo app is open and the printer is connected."
        )
        sys.exit(1)

    log.info("=" * 60)
    log.info(f"Printer  : {printer_name}")
    log.info(f"Folder   : {CLOUDINARY_FOLDER}/")
    log.info(f"Polling  : every {POLL_INTERVAL_SEC}s")
    log.info("Press Ctrl+C to stop.")
    log.info("=" * 60)

    # Mark any images already in Cloudinary as seen so they don't print on startup
    seen: set = set()
    try:
        existing = cloudinary.api.resources(
            type="upload",
            prefix=f"{CLOUDINARY_FOLDER}/",
            max_results=500,
        )
        for r in existing.get("resources", []):
            seen.add(r["public_id"])
        if seen:
            log.info(f"Skipping {len(seen)} pre-existing image(s) already in Cloudinary.")
    except Exception as exc:
        log.warning(f"Could not pre-load existing images: {exc}")

    try:
        while True:
            poll_and_print(printer_name, seen)
            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
