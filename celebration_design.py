"""Editorial birthday cards: full photographs, generous type, joyful details."""
import math
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

SIZE = (1920, 1080)
CREAM = '#FFF5E5'
INK = '#382338'
CORAL = '#ED705B'
GOLD = '#E9B958'
PALETTES = [(INK, CORAL), ('#183F3A', '#D5B75E'), ('#343B66', '#D58DB1')]
ROOT = Path(__file__).parent


def font(size, serif=False, bold=False):
    windows = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    candidates = ([ROOT / 'fonts/Display.ttf', windows / 'georgia.ttf',
                   Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf')] if serif else
                  [windows / ('arialbd.ttf' if bold else 'arial.ttf'),
                   ROOT / 'fonts' / ('Roboto-Bold.ttf' if bold else 'Roboto-Regular.ttf')])
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def text(draw, xy, value, size, fill=INK, serif=False, bold=False):
    draw.text(xy, value, font=font(size, serif, bold), fill=fill, anchor='lt')


def fitted(draw, value, width, height, size=110, serif=True):
    """Fit both long words and multi-line names inside a fixed text region."""
    for point in range(size, 11, -2):
        face = font(point, serif)
        lines, line = [], ''
        for word in value.split():
            if draw.textlength(word, font=face) > width:
                break
            trial = (line + ' ' + word).strip()
            if draw.textlength(trial, font=face) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        else:
            lines.append(line)
            if len(lines) * point * 1.18 <= height:
                return face, lines, int(point * 1.18)
    raise ValueError('Text is too long for the slide: ' + value)


def block(draw, xy, value, width, height, size, fill=INK, serif=True):
    face, lines, step = fitted(draw, value, width, height, size, serif)
    for i, line in enumerate(lines):
        draw.text((xy[0], xy[1] + i * step), line, font=face, fill=fill, anchor='lt')


def star(draw, x, y, radius, color, points=4):
    vertices = []
    for i in range(points * 2):
        angle = i * math.pi / points - math.pi / 2
        r = radius if i % 2 == 0 else radius * .3
        vertices.append((x + math.cos(angle) * r, y + math.sin(angle) * r))
    draw.polygon(vertices, fill=color)


def decorations(draw, seed, accent):
    rng = random.Random(seed)
    # Keep celebration marks in the margins, clear of names and faces.
    for _ in range(34):
        x = rng.randint(30, 1890)
        y = rng.choice([rng.randint(112, 165), rng.randint(1000, 1050)])
        color = rng.choice([accent, GOLD, '#BEA5B4'])
        if rng.random() < .5:
            draw.line((x, y, x + 8, y + 15), fill=color, width=5)
        else:
            draw.ellipse((x, y, x + 7, y + 7), fill=color)


def canvas(index=0):
    dark, accent = PALETTES[index % len(PALETTES)]
    base = Image.new('RGB', SIZE, CREAM)
    draw = ImageDraw.Draw(base)
    text(draw, (86, 55), 'CHRIST EMBASSY', 25, dark, bold=True)
    text(draw, (395, 56), '/  PARIS CENTRAL', 24, dark)
    draw.line((86, 102, 1834, 102), fill='#DCCFC3', width=2)
    decorations(draw, 41 + index, accent)
    return base, draw, dark, accent


def make_slide(person, index, total, out_path):
    import calendar
    base, draw, dark, accent = canvas(index)
    text(draw, (1610, 56), f'CELEBRANT {index + 1:02d} / {total:02d}', 22, dark)
    text(draw, (106, 215), 'TODAY, WE CELEBRATE YOU', 25, dark, bold=True)
    text(draw, (99, 279), 'Happy', 123, dark, serif=True)
    text(draw, (99, 407), 'birthday!', 143, dark, serif=True)
    draw.arc((105, 553, 645, 600), 184, 350, fill=accent, width=7)
    block(draw, (108, 625), person['name'], 850, 205, 84, dark)
    if person.get('cell_unit'):
        block(draw, (110, 852), person['cell_unit'], 810, 75, 32, dark, False)
    text(draw, (110, 949), 'LOVED. CELEBRATED. BLESSED.', 23, dark, bold=True)

    # A dedicated portrait stage keeps the complete image separate from all text.
    draw.rounded_rectangle((1034, 207, 1818, 963), 30, fill='#E7D8CC')
    draw.rounded_rectangle((1016, 190, 1800, 944), 30, fill=dark)
    photo_path = person.get('photo')
    if photo_path and Path(photo_path).exists():
        with Image.open(photo_path) as source:
            photo = ImageOps.exif_transpose(source).convert('RGB')
        photo.thumbnail((724, 638), Image.Resampling.LANCZOS)
        base.paste(photo, (1046 + (724 - photo.width) // 2, 220 + (638 - photo.height) // 2))
    else:
        draw.ellipse((1175, 301, 1641, 767), fill=accent)
        initials = ''.join(part[0] for part in person['name'].split()[:2]).upper()
        face = font(155, serif=True)
        draw.text((1408, 532), initials, font=face, fill=dark, anchor='mm')
        star(draw, 1680, 310, 43, GOLD)
        star(draw, 1150, 734, 27, CREAM)
    date = f"{calendar.month_name[person['month']].upper()} {person['day']:02d}"
    text(draw, (1053, 888), date, 29, CREAM, bold=True)
    text(draw, (1530, 890), 'YOUR DAY TO SHINE', 20, CREAM)
    star(draw, 1786, 208, 66, accent, 12)
    star(draw, 978, 862, 48, GOLD)
    base.save(out_path)


def make_title_slide(month_label, total, out_path):
    base, draw, dark, accent = canvas()
    text(draw, (1560, 56), 'THE BIRTHDAY EDIT', 23, dark)
    text(draw, (110, 220), 'A LITTLE CONFETTI. A LOT OF LOVE.', 26, dark, bold=True)
    text(draw, (98, 306), 'Life is a gift.', 161, dark, serif=True)
    text(draw, (98, 492), "Let's celebrate.", 151, dark, serif=True)
    draw.line((112, 711, 235, 711), fill=accent, width=8)
    block(draw, (111, 758), month_label, 1260, 115, 83, dark)
    text(draw, (114, 922), f"{total} BEAUTIFUL {'LIFE' if total == 1 else 'LIVES'}. ONE CHURCH FAMILY.", 28, dark, bold=True)
    # Sculptural orbit and starburst give the opener a celebratory focal point.
    draw.ellipse((1490, 245, 2055, 810), fill=dark)
    draw.arc((1420, 199, 2110, 857), 70, 290, fill=accent, width=9)
    star(draw, 1668, 518, 175, GOLD, 12)
    star(draw, 1442, 282, 45, accent)
    star(draw, 1510, 851, 58, accent)
    base.save(out_path)


def make_closing_slide(month_label, out_path):
    base = Image.new('RGB', SIZE, INK)
    draw = ImageDraw.Draw(base)
    decorations(draw, 91, CORAL)
    text(draw, (88, 56), 'CHRIST EMBASSY  /  PARIS CENTRAL', 25, CREAM)
    text(draw, (110, 240), 'ANOTHER YEAR. MORE REASONS TO GIVE THANKS.', 26, GOLD, bold=True)
    text(draw, (100, 335), 'More joy.', 160, CREAM, serif=True)
    text(draw, (100, 518), 'More grace.', 160, CREAM, serif=True)
    text(draw, (110, 764), 'May your new year overflow with both.', 43, CREAM)
    block(draw, (112, 915), f'With love, to our {month_label} celebrants', 1610, 65, 32, GOLD, False)
    star(draw, 1550, 475, 195, CORAL, 12)
    star(draw, 1550, 475, 115, GOLD, 4)
    star(draw, 1740, 738, 48, CREAM)
    base.save(out_path)
