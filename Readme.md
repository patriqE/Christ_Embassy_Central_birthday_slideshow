# Birthday Slideshow Generator

Generates a monthly birthday slideshow video — one slide per celebrant with
their photo, name, cell group, and birth date, narrated with spoken audio —
pulled automatically from a Google Form's response sheet.

Built for a church's monthly "last Sunday of the month" birthday
celebration, but works for any group that collects birthdays through a
Google Form.

## What it does

1. Pulls every response from a linked Google Sheet (Google Form output)
2. Filters down to whoever was born in the current month (or any month you specify)
3. Sorts them in ascending order by day (1st → 31st)
4. Downloads each person's uploaded photo directly from Google Drive
5. Generates a projector-friendly full-screen slide per person — complete photo,
   name, cell group, birth date, and a celebratory lower third
6. Generates spoken narration per person — _"Happy birthday to [Name], from [Cell Group], born on [Month] [Day]"_
7. Adds an opening title, closing blessing, fades, and gentle cinematic motion
8. Stitches everything into a single downloadable `.mp4` video with transitions

## Visual design

The default design pairs warm cream with plum, forest, and indigo portrait
frames, oversized serif headlines, coral/gold starbursts, and edge confetti.
Photos remain fully visible in a dedicated area, separate from names and cell
groups. Missing photos receive a coordinated initials card. Opening and closing
cards share the same visual language. Celebrant cards stay steady for readability;
the opener has a subtle zoom, and all cards fade in and out.

Render an offline sample using local photos (the sample dates are illustrative):

```bash
python preview_design.py
python preview_design.py --video
```

Preview images, a contact sheet, and the optional silent MP4 are written to
`output/design_preview/`. The normal CSV/Sheets workflow uses this same design
with narration and applause. Edit `celebration_design.py` to adjust palettes,
layout, or fonts. It uses Georgia/Arial on Windows with local/system fallbacks;
provide `fonts/Display.ttf` to supply your own display face.

## Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/download.html) installed and on your PATH
- A Google Cloud service account with access to Sheets API + Drive API
  (see `SETUP_GUIDE.md` — one-time setup, ~15 minutes)

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/birthday-slideshow.git
cd birthday-slideshow
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\Activate.ps1
pip install pillow gTTS pyttsx3 requests gspread google-auth google-api-python-client
```

Full step-by-step walkthrough (including the Google Cloud setup) is in
[`GETTING_STARTED.md`](GETTING_STARTED.md).

## Usage

Build the slideshow for the current month:

```bash
python birthday_slideshow.py --sheet-id YOUR_GOOGLE_SHEET_ID
```

Build a specific month instead:

```bash
python birthday_slideshow.py --sheet-id YOUR_GOOGLE_SHEET_ID --month August
```

Build several months into one video:

```bash
python birthday_slideshow.py --sheet-id YOUR_GOOGLE_SHEET_ID --months July,August,September --out birthday_slideshow_July_to_September.mp4
```

Use a local CSV instead of a live Google Sheet:

```bash
python birthday_slideshow.py --csv celebrants.csv --month July
```

The finished video is saved to `output/birthday_slideshow_<Month>.mp4`, or to the
filename supplied with `--out`.

## Configuration

Open `google_sheet_loader.py` and edit `COLUMN_MAP` near the top so it
matches your form's actual column headers exactly:

```python
COLUMN_MAP = {
    "name": "Full Name",
    "day": "Date of birth (Day of the month)",
    "month": "Month of birth",
    "cell_unit": "Cell Name",
    "photo": "Upload your picture",
}
```

Other tunables live in `birthday_slideshow.py`:

- `PALETTES` in `celebration_design.py` — portrait and accent colors
- `SLIDE_SECONDS_PADDING` / `FADE_SECONDS` — pacing and transition timing
- The opening card gently zooms; portrait cards remain steady. Background
  music can be added later as a separate audio layer.

## Voice narration

Tries each of these in order, so it always produces a working video even
without internet:

1. **gTTS** — natural Google voices, requires internet
2. **pyttsx3** — fully offline, uses your OS's built-in voice
3. Silent slide — last-resort fallback

## Project structure

```
birthday-slideshow/
├── birthday_slideshow.py     # main script - builds slides, narration, video
├── google_sheet_loader.py    # pulls data + photos from the Google Sheet/Drive
├── celebrants.csv            # sample data for --csv mode #if you want to use a CSV file
├── SETUP_GUIDE.md            # one-time Google Cloud / service account setup
├── GETTING_STARTED.md        # full from-scratch walkthrough
├── service_account.json      # your Google credentials (NOT committed - see below)
├── fonts/                    # auto-downloaded on first run
├── _build/                   # intermediate slides/audio/clips (gitignored)
└── output/                   # finished videos (gitignored)
```

## Security note

`service_account.json` contains a private credential and is excluded via
`.gitignore` — never commit it. If you fork or clone this repo, you'll need
to create your own service account key by following `SETUP_GUIDE.md`.

## Troubleshooting

See the "If something goes wrong" section at the bottom of
`GETTING_STARTED.md` for the most common issues (permission errors, missing
ffmpeg, mismatched column headers, skipped rows).
