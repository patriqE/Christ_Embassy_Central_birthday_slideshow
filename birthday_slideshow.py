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


def load_celebrants(csv_path: str, target_month: int = None, target_months=None):
    selected_months = set(target_months or ([target_month] if target_month else []))
    people = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"].strip()
            day = int(row["day"].strip())
            month = month_to_number(row["month"])
            photo = (row.get("photo") or "").strip()
            cell_unit = (row.get("cell_unit") or "").strip()
            if month in selected_months:
                people.append({"name": name, "day": day, "month": month,
                                "photo": photo or None, "cell_unit": cell_unit or None})
    people.sort(key=lambda p: (p["month"], p["day"]))
    return people


def parse_months(month_value, months_value):
    """Parse either one month or a comma-separated month list."""
    if months_value:
        values = [part.strip() for part in months_value.split(",") if part.strip()]
    elif month_value:
        values = [month_value]
    else:
        values = [str(datetime.now().month)]
    if not values:
        raise ValueError("At least one month is required")
    result = []
    for value in values:
        number = month_to_number(value)
        if number not in result:
            result.append(number)
    return result


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


# --------------------------------------------------------------------------
# LIQUID GLASS SLIDE DESIGN
# --------------------------------------------------------------------------
def rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def glass_panel(base_rgba, box, radius=40, blur=35, tint=(255, 255, 255, 70), border=(255, 255, 255, 130)):
    """Cut a region out of base_rgba, blur it, tint it white, round its corners,
    add a soft border and a drop shadow - the frosted-glass card effect."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0

    # drop shadow first (blurred dark rounded rect, offset down)
    shadow = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle((x0, y0 + 18, x1, y1 + 18), radius=radius, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    base_rgba.alpha_composite(shadow)

    # blurred crop of what's behind the card = the "frosted" look
    crop = base_rgba.crop(box).convert("RGB").filter(ImageFilter.GaussianBlur(blur))
    crop = crop.convert("RGBA")
    tint_layer = Image.new("RGBA", crop.size, tint)
    frosted = Image.alpha_composite(crop, tint_layer)

    mask = rounded_mask((w, h), radius)
    base_rgba.paste(frosted, (x0, y0), mask)

    # border stroke
    draw = ImageDraw.Draw(base_rgba, "RGBA")
    draw.rounded_rectangle(box, radius=radius, outline=border, width=2)
    # top highlight sliver (light catching the top edge of the glass)
    draw.arc((x0 + 4, y0 + 2, x0 + 60, y0 + 60), start=180, end=270, fill=(255, 255, 255, 180), width=3)

    return base_rgba


def glow_text(base_rgba, xy, text, font, glow_color=(255, 220, 130, 140), radius=14):
    layer = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=font, fill=glow_color)
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    base_rgba.alpha_composite(layer)


def contain_fit(img, max_w, max_h):
    """Resize an image to fit fully WITHIN max_w x max_h, preserving aspect
    ratio and cropping nothing - the whole photo stays visible (head to toe)."""
    src_w, src_h = img.size
    scale = min(max_w / src_w, max_h / src_h)
    new_w, new_h = max(1, int(src_w * scale)), max(1, int(src_h * scale))
    return img.resize((new_w, new_h), Image.LANCZOS)


def open_oriented_photo(path):
    """Apply camera EXIF orientation before rendering a downloaded photo."""
    with Image.open(path) as source:
        orientation = source.getexif().get(274, 1)
        transpose_methods = {
            2: Image.Transpose.FLIP_LEFT_RIGHT,
            3: Image.Transpose.ROTATE_180,
            4: Image.Transpose.FLIP_TOP_BOTTOM,
            5: Image.Transpose.TRANSPOSE,
            6: Image.Transpose.ROTATE_270,
            7: Image.Transpose.TRANSVERSE,
            8: Image.Transpose.ROTATE_90,
        }
        if orientation in transpose_methods:
            return source.transpose(transpose_methods[orientation]).convert("RGB")
        return source.convert("RGB")


def make_slide(person, index, total, out_path):
    c1, c2 = BG_COLORS[index % len(BG_COLORS)]
    has_photo = bool(person["photo"] and os.path.exists(person["photo"]))

    if has_photo:
        photo = open_oriented_photo(person["photo"])
        # Preserve the complete photo. The blurred cover backdrop fills the
        # projector frame while the sharp photo is fitted inside it without cropping.
        backdrop = cover_crop(photo, WIDTH, HEIGHT).filter(ImageFilter.GaussianBlur(46))
        base = backdrop.convert("RGBA")
        base.alpha_composite(Image.new("RGBA", (WIDTH, HEIGHT), (8, 12, 20, 105)))
        fitted = contain_fit(photo, WIDTH - 150, HEIGHT - 170).convert("RGBA")
        fx = (WIDTH - fitted.width) // 2
        fy = 42 + max(0, (HEIGHT - 84 - fitted.height) // 2)
        photo_shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(photo_shadow).rectangle(
            (fx + 12, fy + 14, fx + fitted.width + 12, fy + fitted.height + 14),
            fill=(0, 0, 0, 115))
        base.alpha_composite(photo_shadow.filter(ImageFilter.GaussianBlur(22)))
        base.alpha_composite(fitted, (fx, fy))
        draw_photo = ImageDraw.Draw(base, "RGBA")
        draw_photo.rectangle((fx, fy, fx + fitted.width - 1, fy + fitted.height - 1),
                             outline=(255, 255, 255, 175), width=3)
    else:
        base = make_gradient((WIDTH, HEIGHT), c1, c2, vertical=True).convert("RGBA")
        draw0 = ImageDraw.Draw(base, "RGBA")
        initials = "".join(w[0].upper() for w in person["name"].split()[:2])
        big_font = ImageFont.truetype(FONT_BOLD, 520)
        bbox = draw0.textbbox((0, 0), initials, font=big_font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw0.text((WIDTH - tw - 80 - bbox[0], 70 - bbox[1]), initials, font=big_font,
                   fill=(255, 255, 255, 45))

    draw = ImageDraw.Draw(base, "RGBA")
    margin = 76

    # A dark lower gradient keeps projector text readable without covering the photo.
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    for y in range(HEIGHT // 2, HEIGHT):
        alpha = int(18 + 175 * ((y - HEIGHT // 2) / (HEIGHT // 2)))
        overlay_draw.line((0, y, WIDTH, y), fill=(12, 16, 24, alpha))
    base.alpha_composite(overlay)

    # Small gold accents make the layout feel celebratory without becoming busy.
    draw = ImageDraw.Draw(base, "RGBA")
    draw.ellipse((WIDTH - 150, 76, WIDTH - 128, 98), fill="#FFE08A")
    draw.ellipse((WIDTH - 112, 58, WIDTH - 98, 72), fill=(255, 255, 255, 190))
    draw.polygon([(WIDTH - 220, 138), (WIDTH - 212, 158), (WIDTH - 192, 166),
                  (WIDTH - 212, 174), (WIDTH - 220, 194), (WIDTH - 228, 174),
                  (WIDTH - 248, 166), (WIDTH - 228, 158)], fill=(255, 224, 138, 210))
    draw.ellipse((WIDTH - 286, 112, WIDTH - 274, 124), fill=(255, 255, 255, 170))
    draw.line((margin, HEIGHT - 80, margin + 150, HEIGHT - 80), fill="#FFE08A", width=5)

    banner_font = ImageFont.truetype(FONT_MEDIUM, 28)
    name_font, name_lines = fit_multiline(draw, person["name"], FONT_BOLD, WIDTH - margin * 2,
                                           start_size=78, min_size=42, max_lines=2)
    detail_font = ImageFont.truetype(FONT_REGULAR, 30)
    date_font = ImageFont.truetype(FONT_MEDIUM, 34)
    cursor_y = HEIGHT - 330

    month_text = f"{MONTH_NAMES[person['month']].upper()} BIRTHDAYS"
    draw.text((margin, cursor_y), month_text, font=banner_font, fill="#FFE08A")
    cursor_y += 48
    draw.text((margin, cursor_y), "HAPPY BIRTHDAY", font=banner_font, fill=(255, 255, 255, 205))
    cursor_y += 46
    for line in name_lines:
        glow_text(base, (margin, cursor_y), line, name_font, glow_color=(255, 255, 255, 70), radius=10)
        draw = ImageDraw.Draw(base, "RGBA")
        draw.text((margin, cursor_y), line, font=name_font, fill="white")
        bbox = draw.textbbox((0, 0), line, font=name_font)
        cursor_y += bbox[3] - bbox[1] + 4

    details = [f"{MONTH_NAMES[person['month']]} {person['day']}"]
    if person.get("cell_unit"):
        details.append(person["cell_unit"])
    draw.text((margin, cursor_y + 18), "  •  ".join(details), font=detail_font, fill=(255, 255, 255, 225))

    # A simple progress line is clearer from a distance than many small dots.
    progress_y = 66
    progress_x = WIDTH - margin - 260
    draw.rounded_rectangle((progress_x, progress_y, progress_x + 260, progress_y + 8), radius=4,
                           fill=(255, 255, 255, 90))
    progress_w = max(18, int(260 * (index + 1) / total))
    draw.rounded_rectangle((progress_x, progress_y, progress_x + progress_w, progress_y + 8), radius=4,
                           fill="#FFE08A")

    base.convert("RGB").save(out_path, quality=95)



# --------------------------------------------------------------------------
# NARRATION (TTS)
# --------------------------------------------------------------------------
def spoken_cell_name(cell_unit):
    """
    'Johnson' -> 'Johnson Cell'   (word "cell" not already present, so add it)
    'Johnson Cell' -> 'Johnson Cell'   (already there, don't double it up)
    'Cell Group 4 - Grace' -> 'Cell Group 4 - Grace'   (already there, anywhere in the phrase)
    """
    import re
    if re.search(r"\bcell\b", cell_unit, re.IGNORECASE):
        return cell_unit
    return f"{cell_unit} Cell"


def narration_text(person):
    date_part = f"born on {MONTH_NAMES[person['month']]} {person['day']}"
    if person.get("cell_unit"):
        cell_spoken = spoken_cell_name(person["cell_unit"])
        return f"Happy birthday to {person['name']}, from {cell_spoken}, {date_part}."
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
    motion_filter = (
        "zoompan=z='min(zoom+0.0012,1.06)':"
        "x='iw/2-(iw/zoom/2)+sin(on/120)*35':"
        "y='ih/2-(ih/zoom/2)+cos(on/150)*18':"
        "d=1:s=1920x1080:fps=30,"
        "drawbox=x='(iw+360)*mod(t,8)/8-360':y=0:w=180:h=ih:"
        "color=FFE08A@0.12:t=fill,"
        f"fade=t=in:st=0:d={FADE_SECONDS},"
        f"fade=t=out:st={duration - FADE_SECONDS}:d={FADE_SECONDS}"
    )
    subprocess.run([
        FFMPEG, "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-vf", motion_filter,
        "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac",
        "-b:a", "192k", "-ar", "44100", "-ac", "2", "-pix_fmt", "yuv420p",
        "-t", str(duration),
        "-shortest",
        str(out_path)
    ], check=True, capture_output=True)


def make_title_slide(month_label, total, out_path):
    base = make_gradient((WIDTH, HEIGHT), "#10243A", "#D28B42", vertical=False).convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    draw_confetti(draw, count=85, seed=total * 17)
    title_font = ImageFont.truetype(FONT_BOLD, 112)
    subtitle_font = ImageFont.truetype(FONT_MEDIUM, 42)
    title = f"{month_label.upper()} BIRTHDAYS"
    bbox = draw.textbbox((0, 0), title, font=title_font)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 360), title, font=title_font, fill="white")
    subtitle = f"Celebrating {total} special {'' if total == 1 else 'people'}"
    bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 510), subtitle, font=subtitle_font, fill="#FFE08A")
    draw.line((WIDTH // 2 - 120, 590, WIDTH // 2 + 120, 590), fill="#FFE08A", width=5)
    base.convert("RGB").save(out_path, quality=95)


def make_closing_slide(month_label, out_path):
    base = make_gradient((WIDTH, HEIGHT), "#D28B42", "#10243A", vertical=False).convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    draw_confetti(draw, count=85, seed=91)
    title_font = ImageFont.truetype(FONT_BOLD, 92)
    subtitle_font = ImageFont.truetype(FONT_MEDIUM, 40)
    title = "MAY YOUR YEAR BE FILLED WITH JOY"
    bbox = draw.textbbox((0, 0), title, font=title_font)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 365), title, font=title_font, fill="white")
    subtitle = f"Happy birthday, {month_label} celebrants"
    bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 505), subtitle, font=subtitle_font, fill="#FFE08A")
    base.convert("RGB").save(out_path, quality=95)


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
    parser.add_argument("--months", default=None,
                        help="Comma-separated months for one combined video, e.g. July,August,September")
    parser.add_argument("--out", default=None, help="Output MP4 filename")
    args = parser.parse_args()

    target_months = parse_months(args.month, args.months)
    month_label = (MONTH_NAMES[target_months[0]] if len(target_months) == 1 else
                   f"{MONTH_NAMES[target_months[0]]} - {MONTH_NAMES[target_months[-1]]}")

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
            target_months=target_months,
            photos_dir=photos_dir,
        )
    else:
        people = load_celebrants(args.csv, target_months=target_months)
    if not people:
        print(f"No celebrants found for {month_label}. Check your CSV file.")
        sys.exit(1)

    print(f"Building slideshow for {month_label} ({len(people)} celebrant(s))...")

    clip_paths = []
    title_slide = SLIDES_DIR / "title.png"
    title_audio = AUDIO_DIR / "title.mp3"
    title_clip = CLIPS_DIR / "title.mp4"
    make_title_slide(month_label, len(people), title_slide)
    synthesize_silence(title_audio, seconds=4)
    build_clip(title_slide, title_audio, title_clip)
    clip_paths.append(title_clip)

    for i, person in enumerate(people):
        print(f"[{i+1}/{len(people)}] {person['name']} - {month_label} {person['day']}")
        slide_path = SLIDES_DIR / f"slide_{i:03d}.png"
        audio_path = AUDIO_DIR / f"audio_{i:03d}.mp3"
        clip_path = CLIPS_DIR / f"clip_{i:03d}.mp4"

        make_slide(person, i, len(people), slide_path)
        make_narration(person, audio_path)
        build_clip(slide_path, audio_path, clip_path)
        clip_paths.append(clip_path)

    closing_slide = SLIDES_DIR / "closing.png"
    closing_audio = AUDIO_DIR / "closing.mp3"
    closing_clip = CLIPS_DIR / "closing.mp4"
    make_closing_slide(month_label, closing_slide)
    synthesize_silence(closing_audio, seconds=4)
    build_clip(closing_slide, closing_audio, closing_clip)
    clip_paths.append(closing_clip)

    out_name = args.out or f"birthday_slideshow_{month_label}.mp4"
    out_path = OUTPUT_DIR / out_name
    concat_clips(clip_paths, out_path)

    print(f"\nDone! Video saved to: {out_path}")
    return out_path


if __name__ == "__main__":
    main()