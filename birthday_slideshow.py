#!/usr/bin/env python3
"""
Monthly Birthday Slideshow Generator
=====================================
Reads a list of celebrants from a CSV file (or a Google Sheet), filters
everyone whose birthday falls in a given month, generates a designed slide +
spoken narration for each person, and stitches everything into a single
downloadable MP4 video.

Usage
-----
    python birthday_slideshow.py --csv celebrants.csv --month July
    python birthday_slideshow.py --sheet-id YOUR_SHEET_ID     # uses current month

Requirements
------------
    pip install pillow gTTS pyttsx3 requests gspread google-auth google-api-python-client
    (ffmpeg must be installed - either on your PATH, or at C:\\ffmpeg\\bin on Windows)

Voice narration priority:
    1. gTTS   (needs internet, natural-sounding Google voices)
    2. pyttsx3 (fully offline, uses your OS's built-in voices)
    3. silent slide (last resort, so the video still gets built)
"""

import argparse
import csv
import os
import shutil
import requests
import subprocess
import sys
import calendar
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter


# --------------------------------------------------------------------------
# FFMPEG / FFPROBE AUTO-DETECTION
# --------------------------------------------------------------------------
def find_tool(name):
    """
    Locate an ffmpeg-family executable. Checks PATH first (works on every
    OS if ffmpeg was installed properly), then falls back to a couple of
    common Windows install locations. Raises a clear error if it truly
    can't be found anywhere, instead of a cryptic WinError/FileNotFoundError.
    """
    exe_name = f"{name}.exe" if sys.platform == "win32" else name
    found = shutil.which(name) or shutil.which(exe_name)
    if found:
        return found
    if sys.platform == "win32":
        candidates = [
            rf"C:\ffmpeg\bin\{exe_name}",
            rf"C:\Program Files\ffmpeg\bin\{exe_name}",
            rf"C:\ProgramData\chocolatey\bin\{exe_name}",
        ]
        for c in candidates:
            if Path(c).exists():
                return c
    raise FileNotFoundError(
        f"\nCould not find '{name}'. ffmpeg needs to be installed and either:\n"
        f"  1. Added to your system PATH (recommended - see GETTING_STARTED.md), or\n"
        rf"  2. Installed at C:\ffmpeg\bin\ (Windows)" "\n"
        f"Run `{name} -version` in a NEW terminal window to check if it's already "
        f"on PATH (you may need to restart your terminal/IDE after installing)."
    )


FFMPEG = find_tool("ffmpeg")
FFPROBE = find_tool("ffprobe")


def setup_fonts():
    """Download Roboto fonts if they don't exist in the fonts folder."""
    fonts_dir = Path(__file__).parent / "fonts"
    fonts_dir.mkdir(exist_ok=True)

    fonts_needed = {
        "Roboto-Regular.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Regular.ttf",
        "Roboto-Bold.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Bold.ttf",
        "Roboto-Medium.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Medium.ttf",
    }

    for font_name, url in fonts_needed.items():
        font_path = fonts_dir / font_name
        if not font_path.exists():
            print(f"  Downloading {font_name}...")
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                font_path.write_bytes(response.content)
                print(f"  Downloaded {font_name}")
            except Exception as e:
                print(f"  Failed to download {font_name}: {e}")
                fallback = find_system_font()
                if fallback:
                    shutil.copy(fallback, font_path)
                    print(f"  Using system font: {fallback}")


def find_system_font():
    """Find a reasonable system font to use as fallback."""
    if sys.platform == "win32":
        windows_fonts = os.environ.get("WINDIR", "C:\\Windows") + "\\Fonts"
        possible = [
            windows_fonts + "\\arial.ttf",
            windows_fonts + "\\segoeui.ttf",
            windows_fonts + "\\tahoma.ttf"
        ]
    elif sys.platform == "darwin":
        possible = ["/System/Library/Fonts/Helvetica.ttc"]
    else:
        possible = ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]

    for path in possible:
        if Path(path).exists():
            return path
    return None


# Call font setup when module loads
setup_fonts()

# --------------------------------------------------------------------------
# CONFIG - tweak these to change the look & feel
# --------------------------------------------------------------------------
WIDTH, HEIGHT = 1920, 1080
SLIDE_SECONDS_PADDING = 1.0          # extra seconds after narration finishes
FADE_SECONDS = 0.6                   # crossfade-in length per slide
BG_COLORS = [("#FF6B6B", "#FFD93D"), ("#6BCB77", "#4D96FF"),
             ("#F783AC", "#9775FA"), ("#FFA94D", "#FF6B9D")]  # gradient pairs, cycled
# Use local fonts folder instead of system paths
FONTS_DIR = Path(__file__).parent / "fonts"
FONT_BOLD = str(FONTS_DIR / "Roboto-Bold.ttf")
FONT_REGULAR = str(FONTS_DIR / "Roboto-Regular.ttf")
FONT_MEDIUM = str(FONTS_DIR / "Roboto-Medium.ttf")

WORKDIR = Path(__file__).parent
SLIDES_DIR = WORKDIR / "_build" / "slides"
AUDIO_DIR = WORKDIR / "_build" / "audio"
CLIPS_DIR = WORKDIR / "_build" / "clips"
OUTPUT_DIR = WORKDIR / "output"

MONTH_NAMES = list(calendar.month_name)  # index 1-12


# --------------------------------------------------------------------------
# DATA LOADING
# --------------------------------------------------------------------------
def month_to_number(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        n = int(value)
        if 1 <= n <= 12:
            return n
        raise ValueError(f"Invalid month number: {value}")
    for i, name in enumerate(MONTH_NAMES):
        if name and name.lower().startswith(value.lower()):
            return i
    raise ValueError(f"Could not parse month: {value}")


def load_celebrants(csv_path: str, target_month: int):
    people = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"].strip()
            day = int(row["day"].strip())
            month = month_to_number(row["month"])
            photo = (row.get("photo") or "").strip()
            cell_unit = (row.get("cell_unit") or "").strip()
            if month == target_month:
                people.append({"name": name, "day": day, "month": month,
                                "photo": photo or None, "cell_unit": cell_unit or None})
    people.sort(key=lambda p: p["day"])
    return people


# --------------------------------------------------------------------------
# SLIDE IMAGE GENERATION (Pillow)
# --------------------------------------------------------------------------
def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def make_gradient(size, color1, color2, vertical=True):
    c1, c2 = hex_to_rgb(color1), hex_to_rgb(color2)
    base = Image.new("RGB", size)
    top = Image.new("RGB", size, c2)
    mask = Image.new("L", size)
    mask_data = []
    w, h = size
    length = h if vertical else w
    for y in range(h):
        for x in range(w):
            pos = y if vertical else x
            mask_data.append(int(255 * (pos / length)))
    mask.putdata(mask_data)
    base.paste(Image.new("RGB", size, c1), (0, 0))
    base.paste(top, (0, 0), mask)
    return base


def circular_photo(path, diameter):
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    img = img.resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter, diameter), fill=255)
    out = Image.new("RGBA", (diameter, diameter))
    out.paste(img, (0, 0), mask)
    return out


def initials_avatar(name, diameter, color):
    img = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, diameter, diameter), fill=hex_to_rgb(color) + (255,))
    initials = "".join(w[0].upper() for w in name.split()[:2])
    font = ImageFont.truetype(FONT_BOLD, diameter // 2)
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((diameter - tw) / 2 - bbox[0], (diameter - th) / 2 - bbox[1]),
               initials, font=font, fill="white")
    return img


def cover_crop(img, target_w, target_h):
    """Crop+resize an image to exactly fill target_w x target_h (like CSS object-fit: cover)."""
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h
    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        x0 = (src_w - new_w) // 2
        box = (x0, 0, x0 + new_w, src_h)
    else:
        new_h = int(src_w / target_ratio)
        y0 = (src_h - new_h) // 2
        box = (0, y0, src_w, y0 + new_h)
    return img.crop(box).resize((target_w, target_h), Image.LANCZOS)


def big_photo_panel(path, target_w, target_h):
    img = Image.open(path).convert("RGB")
    return cover_crop(img, target_w, target_h)


def big_initials_panel(name, target_w, target_h, color1, color2):
    """Large color block with big initials, used when no photo is available."""
    img = make_gradient((target_w, target_h), color1, color2, vertical=False).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    initials = "".join(w[0].upper() for w in name.split()[:2])
    size = int(min(target_w, target_h) * 0.55)
    font = ImageFont.truetype(FONT_BOLD, size)
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((target_w - tw) / 2 - bbox[0], (target_h - th) / 2 - bbox[1]),
               initials, font=font, fill=(255, 255, 255, 235))
    return img.convert("RGB")


def wrap_lines(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_multiline(draw, text, font_path, max_width, start_size, min_size=34, max_lines=3):
    size = start_size
    while size > min_size:
        font = ImageFont.truetype(font_path, size)
        lines = wrap_lines(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 4
    font = ImageFont.truetype(font_path, min_size)
    return font, wrap_lines(draw, text, font, max_width)


def draw_confetti(draw, count=60, seed=None, x_range=None):
    import random
    rnd = random.Random(seed)
    colors = ["#FFFFFF", "#FFE066", "#FF6B6B", "#4D96FF", "#6BCB77"]
    x_lo, x_hi = x_range if x_range else (0, WIDTH)
    for _ in range(count):
        x, y = rnd.randint(x_lo, x_hi), rnd.randint(0, HEIGHT)
        r = rnd.randint(4, 10)
        c = rnd.choice(colors)
        shape = rnd.choice(["circle", "rect"])
        if shape == "circle":
            draw.ellipse((x, y, x + r, y + r), fill=c)
        else:
            draw.rectangle((x, y, x + r, y + r * 2), fill=c)


def wrap_text_to_fit(draw, text, font_path, max_width, start_size, min_size=40):
    size = start_size
    while size > min_size:
        font = ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 4
    return ImageFont.truetype(font_path, min_size)


PHOTO_FRACTION = 0.62  # how much of the frame width the photo takes up


def make_slide(person, index, total, out_path):
    c1, c2 = BG_COLORS[index % len(BG_COLORS)]

    photo_w = int(WIDTH * PHOTO_FRACTION)
    panel_w = WIDTH - photo_w

    img = Image.new("RGB", (WIDTH, HEIGHT))

    if person["photo"] and os.path.exists(person["photo"]):
        photo_img = big_photo_panel(person["photo"], photo_w, HEIGHT)
    else:
        photo_img = big_initials_panel(person["name"], photo_w, HEIGHT, c1, c2)
    img.paste(photo_img, (0, 0))

    panel_img = make_gradient((panel_w, HEIGHT), c1, c2, vertical=True)
    img.paste(panel_img, (photo_w, 0))

    img = img.convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    draw_confetti(draw, count=40, seed=index, x_range=(photo_w, WIDTH))

    draw.rectangle((photo_w - 6, 0, photo_w, HEIGHT), fill=(255, 255, 255, 200))

    panel_margin = 70
    text_x = photo_w + panel_margin
    text_max_w = panel_w - panel_margin * 2

    banner_font = ImageFont.truetype(FONT_BOLD, 46)
    name_font, name_lines = fit_multiline(draw, person["name"], FONT_BOLD, text_max_w,
                                           start_size=88, min_size=40, max_lines=3)
    cell_font = ImageFont.truetype(FONT_REGULAR, 34)
    date_font = ImageFont.truetype(FONT_MEDIUM, 50)

    def line_h(font, text="Ag"):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]

    banner_h = line_h(banner_font)
    name_line_h = line_h(name_font)
    cell_h = line_h(cell_font) if person.get("cell_unit") else 0
    date_h = line_h(date_font)

    gap_banner_name = 40
    gap_name_lines = 12
    gap_name_cell = 26
    gap_cell_date = 34

    total_h = banner_h + gap_banner_name
    total_h += name_line_h * len(name_lines) + gap_name_lines * (len(name_lines) - 1)
    if person.get("cell_unit"):
        total_h += gap_name_cell + cell_h
    total_h += gap_cell_date + date_h

    cursor_y = (HEIGHT - total_h) / 2

    def draw_left(text, font, fill):
        nonlocal cursor_y
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text((text_x, cursor_y - bbox[1]), text, font=font, fill=fill)
        cursor_y += (bbox[3] - bbox[1])

    draw_left("HAPPY BIRTHDAY!", banner_font, "white")
    cursor_y += gap_banner_name

    for i, line in enumerate(name_lines):
        draw_left(line, name_font, "white")
        cursor_y += gap_name_lines if i < len(name_lines) - 1 else 0

    if person.get("cell_unit"):
        cursor_y += gap_name_cell
        draw_left(person["cell_unit"], cell_font, (255, 255, 255, 220))

    cursor_y += gap_cell_date
    date_text = f"{MONTH_NAMES[person['month']]} {person['day']}"
    draw_left(date_text, date_font, "#FFE066")

    page_font = ImageFont.truetype(FONT_REGULAR, 30)
    page_text = f"{index + 1} / {total}"
    bbox = draw.textbbox((0, 0), page_text, font=page_font)
    pw = bbox[2] - bbox[0]
    draw.text((WIDTH - panel_margin - pw, HEIGHT - 60), page_text, font=page_font,
               fill=(255, 255, 255, 180))

    img.convert("RGB").save(out_path, quality=95)


# --------------------------------------------------------------------------
# NARRATION (TTS)
# --------------------------------------------------------------------------
def narration_text(person):
    date_part = f"born on {MONTH_NAMES[person['month']]} {person['day']}"
    if person.get("cell_unit"):
        return f"Happy birthday to {person['name']}, from {person['cell_unit']}, {date_part}."
    return f"Happy birthday to {person['name']}, {date_part}."


def synthesize_gtts(text, out_path):
    from gtts import gTTS
    gTTS(text=text, lang="en").save(str(out_path))
    return True


def synthesize_pyttsx3(text, out_path):
    import pyttsx3
    engine = pyttsx3.init()
    engine.save_to_file(text, str(out_path))
    engine.runAndWait()
    return True


def synthesize_silence(out_path, seconds=3):
    subprocess.run([
        FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", str(seconds), str(out_path)
    ], check=True, capture_output=True)
    return True


def make_narration(person, out_path_mp3):
    text = narration_text(person)
    try:
        synthesize_gtts(text, out_path_mp3)
        print(f"  [voice: gTTS] {person['name']}")
        return
    except Exception:
        pass
    try:
        wav_path = out_path_mp3.with_suffix(".wav")
        synthesize_pyttsx3(text, wav_path)
        subprocess.run([FFMPEG, "-y", "-i", str(wav_path), str(out_path_mp3)],
                        check=True, capture_output=True)
        print(f"  [voice: pyttsx3 offline] {person['name']}")
        return
    except Exception:
        pass
    print(f"  [voice: SILENT fallback - no TTS engine available] {person['name']}")
    synthesize_silence(out_path_mp3, seconds=3)


# --------------------------------------------------------------------------
# VIDEO ASSEMBLY (ffmpeg)
# --------------------------------------------------------------------------
def get_audio_duration(path):
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def build_clip(image_path, audio_path, out_path):
    duration = get_audio_duration(audio_path) + SLIDE_SECONDS_PADDING
    subprocess.run([
        FFMPEG, "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-vf", f"fade=t=in:st=0:d={FADE_SECONDS},fade=t=out:st={duration - FADE_SECONDS}:d={FADE_SECONDS}",
        "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac",
        "-b:a", "192k", "-pix_fmt", "yuv420p",
        "-t", str(duration),
        "-shortest",
        str(out_path)
    ], check=True, capture_output=True)


def concat_clips(clip_paths, out_path):
    list_file = out_path.parent / "concat_list.txt"
    with open(list_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p.resolve()}'\n")
    subprocess.run([
        FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(out_path)
    ], check=True, capture_output=True)


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Build a monthly birthday slideshow video.")
    parser.add_argument("--csv", default="celebrants.csv", help="Path to celebrants CSV file")
    parser.add_argument("--sheet-id", default=None,
                         help="Google Sheet ID to pull data from instead of a CSV "
                              "(the long ID in the sheet's URL)")
    parser.add_argument("--worksheet", default=None,
                         help="Worksheet/tab name in the Google Sheet (default: first tab)")
    parser.add_argument("--credentials", default="service_account.json",
                         help="Path to the Google service-account JSON key (only needed with --sheet-id)")
    parser.add_argument("--month", default=None, help="Month name or number (default: current month)")
    parser.add_argument("--out", default=None, help="Output MP4 filename")
    args = parser.parse_args()

    target_month = month_to_number(args.month) if args.month else datetime.now().month
    month_label = MONTH_NAMES[target_month]

    for d in (SLIDES_DIR, AUDIO_DIR, CLIPS_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    if args.sheet_id:
        from google_sheet_loader import load_celebrants_from_sheet
        photos_dir = WORKDIR / "_build" / "photos"
        print(f"Pulling responses from Google Sheet {args.sheet_id} ...")
        people = load_celebrants_from_sheet(
            sheet_id=args.sheet_id,
            worksheet_name=args.worksheet,
            credentials_path=args.credentials,
            target_month=target_month,
            photos_dir=photos_dir,
        )
    else:
        people = load_celebrants(args.csv, target_month)
    if not people:
        print(f"No celebrants found for {month_label}. Check your CSV file.")
        sys.exit(1)

    print(f"Building slideshow for {month_label} ({len(people)} celebrant(s))...")

    clip_paths = []
    for i, person in enumerate(people):
        print(f"[{i+1}/{len(people)}] {person['name']} - {month_label} {person['day']}")
        slide_path = SLIDES_DIR / f"slide_{i:03d}.png"
        audio_path = AUDIO_DIR / f"audio_{i:03d}.mp3"
        clip_path = CLIPS_DIR / f"clip_{i:03d}.mp4"

        make_slide(person, i, len(people), slide_path)
        make_narration(person, audio_path)
        build_clip(slide_path, audio_path, clip_path)
        clip_paths.append(clip_path)

    out_name = args.out or f"birthday_slideshow_{month_label}.mp4"
    out_path = OUTPUT_DIR / out_name
    concat_clips(clip_paths, out_path)

    print(f"\nDone! Video saved to: {out_path}")
    return out_path


if __name__ == "__main__":
    main()