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
PRINTER_KEYWORD    = "A28U"         # any part of the printer name in Windows
DELETE_AFTER_PRINT = True           # remove from Cloudinary after printing

import cloudinary
import cloudinary.api
import cloudinary.uploader
import requests
from PIL import Image
import win32print
import win32ui
import win32con
from PIL import ImageWin

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
    """Send image to printer via GDI. Returns True on success."""
    try:
        log.info(f"Sending to printer '{printer_name}': {Path(src_path).name}")
        img = Image.open(src_path)
        if img.mode != "RGB":
            if img.mode in ("RGBA", "LA", "P"):
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")

        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)

        pw = hdc.GetDeviceCaps(win32con.HORZRES)
        ph = hdc.GetDeviceCaps(win32con.VERTRES)

        iw, ih = img.size
        ratio = min(pw / iw, ph / ih)
        nw, nh = int(iw * ratio), int(ih * ratio)

        hdc.StartDoc(Path(src_path).name)
        hdc.StartPage()
        dib = ImageWin.Dib(img)
        dib.draw(hdc.GetHandleOutput(), (0, 0, nw, nh))
        hdc.EndPage()
        hdc.EndDoc()
        hdc.DeleteDC()
        return True
    except Exception as exc:
        log.error(f"Print failed for '{src_path}': {exc}")
        return False

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
            if success:
                seen.add(public_id)
                if DELETE_AFTER_PRINT:
                    cloudinary.uploader.destroy(public_id)
                    log.info(f"Deleted from Cloudinary: {public_id}")
            else:
                log.warning(f"Print failed for {public_id} — will retry next poll (check paper/printer)")
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

    seen: set = set()

    try:
        while True:
            poll_and_print(printer_name, seen)
            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
