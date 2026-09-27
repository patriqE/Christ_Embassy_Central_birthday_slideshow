"""
google_sheet_loader.py
=======================
Pulls birthday celebrant data directly from the Google Sheet that collects
your Google Form responses, and downloads each person's uploaded photo from
Google Drive automatically.

ONE-TIME SETUP (see SETUP_GUIDE.md for click-by-click steps)
--------------------------------------------------------------
1. Create a Google Cloud project and enable:
     - Google Sheets API
     - Google Drive API
2. Create a Service Account, download its JSON key, save it as
   `service_account.json` in this folder.
3. Share your Google Sheet (the Form's response sheet) with the service
   account's email address (found inside the JSON file, field
   "client_email") - give it "Viewer" access.
4. Share the Google Drive folder where the Form saves uploaded photos with
   that same service account email - "Viewer" access.
   (Forms usually auto-create a folder named after the form, inside your
   Drive - look for a folder icon in the file-upload question in Form
   "Responses" settings, or just search Drive for the form's name.)

After that, this module "just works" - no browser login, no token refresh.
"""

import os
import re
import io
import unicodedata
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# --------------------------------------------------------------------------
# EDIT THIS to match your Google Form's actual column headers exactly
# (open the response sheet, look at row 1). Only the keys on the left matter
# to the code - change the values on the right to your real headers.
# --------------------------------------------------------------------------
COLUMN_MAP = {
    "name": "Full Name || Nom et prénom",
    "day": "Date of birth (Day of the month) || Date de naissance (jour du mois)",
    "month": "Month of birth || Mois de naissance",
    "cell_unit": "Cell Name || Nom de la cellule",
    "photo": "Upload your picture || Téléchargez votre photo",
}

DRIVE_ID_PATTERNS = [
    re.compile(r"/d/([a-zA-Z0-9_-]{10,})"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]{10,})"),
]


def normalize_header(s):
    """Normalize a header/text so accents, curly quotes, and stray whitespace
    don't cause false mismatches between COLUMN_MAP and the real sheet."""
    s = unicodedata.normalize("NFC", str(s or ""))
    s = s.replace("\u2019", "'").replace("\u2018", "'")  # curly quotes -> straight
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def get_credentials(credentials_path):
    return Credentials.from_service_account_file(credentials_path, scopes=SCOPES)


def extract_drive_file_ids(cell_value: str):
    """Form file-upload cells can contain one or more Drive links, comma
    or newline separated. Return every file ID found."""
    if not cell_value:
        return []
    ids = []
    for chunk in re.split(r"[,\n]", cell_value):
        chunk = chunk.strip()
        for pattern in DRIVE_ID_PATTERNS:
            m = pattern.search(chunk)
            if m:
                ids.append(m.group(1))
                break
    return ids


def download_drive_photo(drive_service, file_id, dest_folder: Path):
    meta = drive_service.files().get(fileId=file_id, fields="name,mimeType").execute()
    ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
    }.get(meta.get("mimeType", ""), ".jpg")
    dest_path = dest_folder / f"{file_id}{ext}"
    if dest_path.exists():
        return dest_path  # already cached from a previous run

    request = drive_service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    dest_path.write_bytes(buf.getvalue())
    return dest_path


FRENCH_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12,
}


def month_to_number(value: str) -> int:
    import calendar
    raw = str(value).strip()
    if not raw:
        raise ValueError("empty month value")
    # Bilingual cells like "July || Juillet" or "July / Juillet" - try each side
    parts = [p.strip() for p in re.split(r"\|\||/", raw)] if ("||" in raw or "/" in raw) else [raw]
    for part in parts:
        if part.isdigit():
            n = int(part)
            if 1 <= n <= 12:
                return n
        names = list(calendar.month_name)
        for i, name in enumerate(names):
            if name and name.lower().startswith(part.lower()):
                return i
        key = part.lower()
        if key in FRENCH_MONTHS:
            return FRENCH_MONTHS[key]
    raise ValueError(f"Could not parse month: {value!r}")


def load_celebrants_from_sheet(sheet_id, worksheet_name, credentials_path,
                                target_month=None, photos_dir=None, target_months=None):
    """
    Returns a list of dicts: {name, day, month, cell_unit, photo}
    matching the same shape birthday_slideshow.py expects from the CSV,
    but filtered to target_month(s) and with photo already downloaded locally.
    """
    selected_months = set(target_months or ([target_month] if target_month else []))
    photos_dir = Path(photos_dir)
    photos_dir.mkdir(parents=True, exist_ok=True)

    creds = get_credentials(credentials_path)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(sheet_id)
    ws = sheet.worksheet(worksheet_name) if worksheet_name else sheet.sheet1

    actual_headers = ws.row_values(1)
    header_lookup = {normalize_header(h): h for h in actual_headers}

    # Resolve each logical field to the real header text in the sheet.
    resolved = {}
    missing = []
    for field, expected in COLUMN_MAP.items():
        key = normalize_header(expected)
        if key in header_lookup:
            resolved[field] = header_lookup[key]
        else:
            missing.append((field, expected))

    if missing:
        print("\n*** COLUMN HEADER MISMATCH ***")
        print("These COLUMN_MAP entries in google_sheet_loader.py don't match any")
        print("column header actually found in the sheet:\n")
        for field, expected in missing:
            print(f"  - {field}: expected {expected!r}")
        print("\nActual column headers found in row 1 of the sheet:")
        for h in actual_headers:
            print(f"  - {h!r}")
        print("\nCopy the exact text from the list above into COLUMN_MAP for each "
              "mismatched field (spelling, spacing, and accents all have to match).\n")
        return []

    rows = ws.get_all_records()
    drive_service = build("drive", "v3", credentials=creds)

    people = []
    skip_reasons = []
    for row_num, row in enumerate(rows, start=2):  # row 1 is the header
        raw_name = row.get(resolved["name"], "")
        raw_day = row.get(resolved["day"], "")
        raw_month = row.get(resolved["month"], "")

        name = str(raw_name).strip()
        if not name:
            skip_reasons.append(f"Row {row_num}: blank name - skipped")
            continue
        try:
            day = int(str(raw_day).strip())
        except ValueError:
            skip_reasons.append(f"Row {row_num} ({name}): day value {raw_day!r} isn't a number - skipped")
            continue
        try:
            month = month_to_number(raw_month)
        except ValueError:
            skip_reasons.append(f"Row {row_num} ({name}): month value {raw_month!r} not recognized - skipped")
            continue

        if month not in selected_months:
            continue

        cell_unit = str(row.get(resolved["cell_unit"], "")).strip()

        photo_path = None
        photo_cell = row.get(resolved["photo"], "")
        file_ids = extract_drive_file_ids(photo_cell)
        if file_ids:
            try:
                photo_path = str(download_drive_photo(drive_service, file_ids[0], photos_dir))
            except Exception as e:
                print(f"  (could not download photo for {name}: {e})")

        people.append({
            "name": name,
            "day": day,
            "month": month,
            "cell_unit": cell_unit or None,
            "photo": photo_path,
        })

    if skip_reasons:
        print(f"\nSkipped {len(skip_reasons)} row(s):")
        for reason in skip_reasons:
            print(f"  - {reason}")

    people.sort(key=lambda p: (p["month"], p["day"]))
    return people