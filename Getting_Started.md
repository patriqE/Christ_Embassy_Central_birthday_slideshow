# Getting Started: Birthday Slideshow Python Project

No web framework needed here (not Django, not FastAPI, not Flask, not Jupyter) —
this is just a script you run yourself once a month from a folder on your
computer. Below is every step, from a totally empty computer to a working
`python birthday_slideshow.py --sheet-id ...` command.

---

## PART 1 - Install the basics (one-time, ~15 min)

### 1. Install Python
Check if you already have it:
```bash
python3 --version
```
If that shows `Python 3.9` or higher, skip to step 2. Otherwise:
- **Windows**: download from https://python.org/downloads — during install,
  tick the box **"Add python.exe to PATH"** before clicking Install.
- **Mac**: download from https://python.org/downloads, or if you have
  Homebrew: `brew install python`
- **Linux**: `sudo apt install python3 python3-pip python3-venv`

### 2. Install ffmpeg
This is the video engine the script uses. Check first:
```bash
ffmpeg -version
```
If not found:
- **Windows**: download from https://www.gyan.dev/ffmpeg/builds/ (get the
  "release essentials" zip), unzip it somewhere like `C:\ffmpeg`, then add
  `C:\ffmpeg\bin` to your System PATH (search "Edit environment variables"
  in the Start menu).
- **Mac**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

Confirm both work before moving on:
```bash
python3 --version
ffmpeg -version
```

---

## PART 2 - Create the project folder

Pick a spot for this, e.g. your Documents folder, then:

```bash
mkdir birthday-slideshow
cd birthday-slideshow
```

### Create a virtual environment
This keeps this project's packages separate from everything else on your
computer — standard practice, avoids version conflicts later.

```bash
python3 -m venv venv
```

Activate it (you'll need to do this **every time** you open a new terminal
to work on this project):

- **Mac/Linux**: `source venv/bin/activate`
- **Windows (PowerShell)**: `venv\Scripts\Activate.ps1`
- **Windows (cmd.exe)**: `venv\Scripts\activate.bat`

You'll know it worked because your terminal prompt will now start with
`(venv)`.

---

## PART 3 - Add the project files

Download these files (from our conversation above) into this
`birthday-slideshow` folder:

- `birthday_slideshow.py` — the main script
- `google_sheet_loader.py` — pulls data from your Google Sheet
- `SETUP_GUIDE.md` — the Google Cloud setup steps (Part 4 below)

Your folder should now look like:
```
birthday-slideshow/
├── venv/
├── birthday_slideshow.py
├── google_sheet_loader.py
└── SETUP_GUIDE.md
```

### Install the Python packages
With your venv still activated:
```bash
pip install pillow gTTS pyttsx3 gspread google-auth google-api-python-client
```

---

## PART 4 - Connect it to your Google Form

Follow `SETUP_GUIDE.md` now, start to finish. In short, you will:
1. Create a free Google Cloud project
2. Enable the Sheets API and Drive API
3. Create a "service account" and download its JSON key → save it into
   this same `birthday-slideshow` folder as `service_account.json`
4. Share your response Sheet, and the Drive photo folder, with that
   service account's email address (Viewer access)
5. Open `google_sheet_loader.py` and edit `COLUMN_MAP` near the top so the
   five values match your Sheet's actual header row exactly (Name, Day,
   Month, Cell Unit, Photo column headers)
6. Copy your Sheet ID from its URL

Come back here once that's done.

---

## PART 5 - Run it

Get your Sheet ID from the sheet's URL:
```
https://docs.google.com/spreadsheets/d/1AbCDefGhIJKLmnop.../edit
                                        ^^^^^^^^^^^^^^^^^^ this part
```

Then, with your venv activated, from inside the `birthday-slideshow` folder:

```bash
python3 birthday_slideshow.py --sheet-id 1AbCDefGhIJKLmnop...
```

It will:
1. Pull every response from the live Sheet
2. Figure out the current month automatically
3. Keep only the people born that month, skip incomplete rows
4. Sort them 1st → 31st
5. Download each person's photo from Drive
6. Generate a slide + spoken narration for each person
7. Stitch it all into one video at `output/birthday_slideshow_<Month>.mp4`

To build a different month instead of the current one:
```bash
python3 birthday_slideshow.py --sheet-id 1AbCDefGhIJKLmnop... --month August
```

---

## Every month after this (the only thing you'll actually repeat)

```bash
cd birthday-slideshow
source venv/bin/activate          # Windows: venv\Scripts\Activate.ps1
python3 birthday_slideshow.py --sheet-id 1AbCDefGhIJKLmnop...
```

Then grab the finished `.mp4` from the `output/` folder and play it Sunday.

---

## If something goes wrong

- **`command not found: python3`** → Python isn't installed or isn't on
  PATH. Re-check Part 1, step 1.
- **`ModuleNotFoundError: No module named 'gspread'`** (or similar) → your
  venv isn't activated, or the `pip install` step didn't run. Re-check
  Part 2/3.
- **`PERMISSION_DENIED` from Google** → you forgot to share the Sheet or
  Drive folder with the service account email (Part 4, step 4).
- **Video looks wrong / person missing** → check that person's row in the
  Sheet — a blank Day, Month, or Name will cause that row to be skipped
  (the script prints a warning telling you how many rows were skipped).