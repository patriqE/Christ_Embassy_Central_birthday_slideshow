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
import math
import random
import re
import wave
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
APPLAUSE_SECONDS = 4.0               # applause and cheers after each celebrant
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
OPENING_BACKGROUND = WORKDIR / "assets" / "branding" / "opening_background.jpg"
APPLAUSE_ASSET = WORKDIR / "assets" / "audio" / "AI_Cheers and Applause 2 Sound Effects.mp3"

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
            cell_unit = normalize_cell_name(row.get("cell_unit"))
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


from celebration_design import make_slide, make_title_slide, make_closing_slide


# --------------------------------------------------------------------------
# NARRATION (TTS)
# --------------------------------------------------------------------------
def normalize_cell_name(cell_unit):
    """Ensure the displayed cell name ends with a consistently capitalized Cell."""
    cell_name = str(cell_unit or "").strip()
    if not cell_name:
        return ""
    if re.search(r"\bcell\s*$", cell_name, re.IGNORECASE):
        return re.sub(r"\bcell\s*$", "Cell", cell_name, flags=re.IGNORECASE)
    return f"{cell_name} Cell"


def spoken_cell_name(cell_unit):
    return normalize_cell_name(cell_unit)


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


def make_applause(out_path_mp3, seconds=APPLAUSE_SECONDS):
    """Create a lively applause-and-cheer bed without requiring a bundled audio file."""
    if APPLAUSE_ASSET.exists():
        fade_out_start = max(0.0, seconds - 0.35)
        subprocess.run([
            FFMPEG, "-y", "-i", str(APPLAUSE_ASSET), "-t", str(seconds),
            "-af", f"afade=t=in:st=0:d=0.08,afade=t=out:st={fade_out_start}:d=0.35,"
                   "loudnorm=I=-16:TP=-1.5:LRA=7,alimiter=limit=0.95",
            str(out_path_mp3)
        ], check=True, capture_output=True)
        print(f"  [celebration audio: {APPLAUSE_ASSET.name}]")
        return

    sample_rate = 44100
    total_samples = int(sample_rate * seconds)
    rng = random.Random(42)
    left = [0.0] * total_samples
    right = [0.0] * total_samples

    # Many independent clap transients sound fuller than one repeating noise burst.
    for _ in range(18):
        clap_count = rng.randint(5, 8)
        for _ in range(clap_count):
            start = rng.randint(0, total_samples - int(sample_rate * 0.1))
            length = rng.randint(int(sample_rate * 0.035), int(sample_rate * 0.085))
            pan = rng.uniform(0.25, 0.75)
            for index in range(length):
                position = start + index
                attack = min(1.0, index / (sample_rate * 0.004))
                envelope = attack * math.exp(-7.0 * index / length)
                snap = rng.uniform(-1.0, 1.0) * envelope * 0.42
                resonance = math.sin(index * rng.uniform(0.035, 0.055)) * envelope * 0.07
                left[position] += (snap + resonance) * (1.0 - pan)
                right[position] += (snap + resonance) * pan

    # A rising, textured vocal bed gives the applause the feeling of joyful cheering.
    for index in range(total_samples):
        time = index / sample_rate
        swell = 0.58 + 0.42 * math.sin(math.pi * min(1.0, time / seconds))
        voice = (
            math.sin(2 * math.pi * 235 * time + math.sin(time * 5.5) * 0.8) * 0.055 +
            math.sin(2 * math.pi * 317 * time + math.sin(time * 4.1) * 0.6) * 0.04 +
            rng.uniform(-1.0, 1.0) * 0.075
        ) * swell
        left[index] += voice * 0.82
        right[index] += voice

    pcm = bytearray()
    peak = max(1.0, max(max(abs(value) for value in left), max(abs(value) for value in right)))
    for left_sample, right_sample in zip(left, right):
        left_value = int(max(-1.0, min(1.0, left_sample / peak * 1.65)) * 32767)
        right_value = int(max(-1.0, min(1.0, right_sample / peak * 1.65)) * 32767)
        pcm.extend(left_value.to_bytes(2, byteorder="little", signed=True))
        pcm.extend(right_value.to_bytes(2, byteorder="little", signed=True))

    wav_path = out_path_mp3.with_suffix(".wav")
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    subprocess.run([FFMPEG, "-y", "-i", str(wav_path), "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=7,aecho=0.7:0.8:75:0.22,"
                    "volume=2.5,alimiter=limit=0.95",
                    str(out_path_mp3)], check=True, capture_output=True)
    wav_path.unlink(missing_ok=True)


def append_audio(first_path, second_path, out_path):
    """Join narration and applause while keeping one continuous audio track."""
    subprocess.run([
        FFMPEG, "-y", "-i", str(first_path), "-i", str(second_path),
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
        "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "192k", str(out_path)
    ], check=True, capture_output=True)


# --------------------------------------------------------------------------
# VIDEO ASSEMBLY (ffmpeg)
# --------------------------------------------------------------------------
def get_audio_duration(path):
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def build_clip(image_path, audio_path, out_path, opening=False):
    duration = get_audio_duration(audio_path) + SLIDE_SECONDS_PADDING
    # Preserve the composition and photo edges; only opening cards gently zoom.
    motion_filter = (
        "zoompan=z='min(1+on*0.00012,1.018)':"
        "x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=30,"
        if opening else "fps=30,"
    ) + (
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
        "-af", "apad",
        "-movflags", "+faststart",
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
    parser.add_argument("--credentials", default=str(WORKDIR / "service_account.json"),
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
    for person in people:
        person["cell_unit"] = normalize_cell_name(person.get("cell_unit"))
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
    build_clip(title_slide, title_audio, title_clip, opening=True)
    clip_paths.append(title_clip)

    applause_path = AUDIO_DIR / "applause.mp3"
    make_applause(applause_path)

    for i, person in enumerate(people):
        print(f"[{i+1}/{len(people)}] {person['name']} - {month_label} {person['day']}")
        slide_path = SLIDES_DIR / f"slide_{i:03d}.png"
        audio_path = AUDIO_DIR / f"audio_{i:03d}.mp3"
        full_audio_path = AUDIO_DIR / f"audio_{i:03d}_with_applause.mp3"
        clip_path = CLIPS_DIR / f"clip_{i:03d}.mp4"

        make_slide(person, i, len(people), slide_path)
        make_narration(person, audio_path)
        append_audio(audio_path, applause_path, full_audio_path)
        build_clip(slide_path, full_audio_path, clip_path)
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