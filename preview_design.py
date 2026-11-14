"""Render an offline design sample. Dates below are illustrative, not records."""
from pathlib import Path
from PIL import Image, ImageDraw
from celebration_design import make_slide, make_title_slide, make_closing_slide

ROOT = Path(__file__).parent
DEST = ROOT / 'output' / 'design_preview'


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', action='store_true', help='Also encode a silent MP4 preview')
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    people = [
        dict(name='Annabelle Tatchoum', month=7, day=12, cell_unit='Birthday design preview',
             photo=str(ROOT.parent / 'Annabelle Tatchoum.jpeg')),
        dict(name='Lilian', month=8, day=24, cell_unit=None,
             photo=str(ROOT.parent / 'Lilian.jpeg')),
        dict(name='Our wonderful celebrant', month=9, day=8, cell_unit='Your church family', photo=None),
    ]
    paths = [DEST / '00_opening.png']
    make_title_slide('July - September', len(people), paths[0])
    for i, person in enumerate(people):
        path = DEST / f'{i + 1:02d}_celebrant.png'
        make_slide(person, i, len(people), path)
        paths.append(path)
    paths.append(DEST / '04_closing.png')
    make_closing_slide('July - September', paths[-1])
    sheet = Image.new('RGB', (1440, 1215), '#E5D9CD')
    for i, path in enumerate(paths):
        with Image.open(path) as slide:
            sheet.paste(slide.resize((720, 405)), ((i % 2) * 720, (i // 2) * 405))
    ImageDraw.Draw(sheet).text((760, 1000), 'DESIGN PREVIEW / Illustrative dates', fill='#382338')
    sheet.save(DEST / 'contact_sheet.jpg')
    if args.video:
        from birthday_slideshow import synthesize_silence, build_clip, concat_clips
        audio = DEST / 'silence.mp3'
        synthesize_silence(audio, seconds=3)
        clips = []
        for i, path in enumerate(paths):
            clip = DEST / f'preview_{i:02d}.mp4'
            build_clip(path, audio, clip, opening=(i == 0))
            clips.append(clip)
        concat_clips(clips, DEST / 'birthday_design_preview.mp4')
    print(DEST)


if __name__ == '__main__':
    main()
