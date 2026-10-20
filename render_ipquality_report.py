# Copyright (C) 2026 sunzh815. AGPL-3.0. Modified 2026-10-20.
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse
import json
import os
import re
import unicodedata
from urllib.parse import urlsplit
from PIL import Image, ImageDraw, ImageFont
from full_report_sections import build_full_report

parser = argparse.ArgumentParser(description='Render this run of IPQuality as a color PNG report.')
parser.add_argument('--input', type=Path, required=True, help='ANSI report captured from this run')
parser.add_argument('--json', type=Path, required=True, help='JSON result from the same run')
parser.add_argument('--output', type=Path, required=True, help='PNG output path')
parser.add_argument('--proxy', default='http://127.0.0.1:7890')
parser.add_argument('--open', action='store_true', help='Open the finished image')
args = parser.parse_args()
data = json.loads(args.json.read_text(encoding='utf-8-sig'))
tested_ip = data.get('Head', {}).get('IP')
raw = args.input.read_bytes().decode('utf-8')
raw = raw.replace('\r\r\n', '\n').replace('\r\n', '\n').replace('\r', '')
plain_raw = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', raw)
if not tested_ip or tested_ip not in plain_raw:
    parser.error('The ANSI report and JSON result must contain the same tested IP.')
args.output.parent.mkdir(parents=True, exist_ok=True)
proxy = urlsplit(args.proxy)
proxy_label = f'{proxy.hostname}:{proxy.port}' if proxy.port else str(proxy.hostname)
version = data.get('Head', {}).get('Version', 'unknown')
stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M UTC+8')
lines = build_full_report(data, raw, stamp, proxy_label, version)
complete_ansi = '\n'.join(lines) + '\n'
args.output.with_suffix('.ansi').write_text(complete_ansi, encoding='utf-8')
args.output.with_suffix('.txt').write_text(re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', complete_ansi), encoding='utf-8-sig')
details_path = args.output.with_suffix('.details.txt')
if not details_path.exists():
    details_path.write_text('扩展检测未完成或未运行；以下保留可获得的数据。\n\n' + json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8-sig')

SCALE = 2
CW, LH, PAD = 13 * SCALE, 29 * SCALE, 14 * SCALE
FONTS = Path(os.environ.get('IPQ_FONT_DIR', 'C:/Windows/Fonts'))
font_cache = {}

def font(cjk, bold, italic):
    key = (cjk, bold, italic)
    if key not in font_cache:
        if cjk:
            name = 'simhei.ttf'
        else:
            name = 'consolaz.ttf' if bold and italic else 'consolab.ttf' if bold else 'consolai.ttf' if italic else 'consola.ttf'
        path = FONTS / name
        if not path.is_file():
            path = Path(__file__).resolve().parent / 'fonts/NotoSansMonoCJKsc-Regular.otf'
        font_cache[key] = ImageFont.truetype(str(path), 24 * SCALE)
    return font_cache[key]

normal = ['#000000', '#c00000', '#00cc00', '#b1a900', '#315bdb', '#a265c1', '#00bcbc', '#bfbfbf']
bright = ['#666666', '#ff5a5a', '#55ff55', '#ffff55', '#668cff', '#ff66ff', '#55ffff', '#ffffff']
def terminal_width(text):
    text = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', text)
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)

columns = max(72, *(terminal_width(line) for line in lines))
image = Image.new('RGB', (columns * CW + 2 * PAD, len(lines) * LH + 2 * PAD), '#000000')
draw = ImageDraw.Draw(image)
state = {'fg': normal[7], 'bg': normal[0], 'bold': False, 'italic': False, 'underline': False}
ansi = re.compile(r'\x1b\[([0-9;]*)m')

def sgr(sequence):
    codes = [int(v or '0') for v in sequence.split(';')]
    for n in codes:
        if n == 0:
            state.update(fg=normal[7], bg=normal[0], bold=False, italic=False, underline=False)
        elif n == 1: state['bold'] = True
        elif n == 22: state['bold'] = False
        elif n == 3: state['italic'] = True
        elif n == 23: state['italic'] = False
        elif n == 4: state['underline'] = True
        elif n == 24: state['underline'] = False
        elif 30 <= n <= 37: state['fg'] = normal[n - 30]
        elif 40 <= n <= 47: state['bg'] = normal[n - 40]
        elif 90 <= n <= 97: state['fg'] = bright[n - 90]
        elif 100 <= n <= 107: state['bg'] = bright[n - 100]
        elif n == 39: state['fg'] = normal[7]
        elif n == 49: state['bg'] = normal[0]

for row, line in enumerate(lines):
    x, y, i = PAD, PAD + row * LH, 0
    while i < len(line):
        match = ansi.match(line, i)
        if match:
            sgr(match.group(1)); i = match.end(); continue
        c = line[i]; i += 1
        wide = unicodedata.east_asian_width(c) in ('W', 'F')
        cells = 0 if unicodedata.combining(c) else 2 if wide else 1
        width = cells * CW
        if width:
            draw.rectangle((x, y, x + width - 1, y + LH - 1), fill=state['bg'])
        face = font(wide, state['bold'], state['italic'])
        measured = draw.textlength(c, font=face)
        dx = max(0, (width - measured) / 2)
        draw.text((x + dx, y + 2 * SCALE), c, font=face, fill=state['fg'], stroke_width=0)
        if state['underline']:
            draw.line((x, y + LH - 3 * SCALE, x + width, y + LH - 3 * SCALE), fill=state['fg'], width=SCALE)
        x += width
    if x > image.width - PAD + CW:
        raise RuntimeError(f'Line {row+1} exceeds the report width')

image.save(args.output)
print(f'PNG report saved: {args.output.resolve()}')
if args.open:
    try:
        os.startfile(str(args.output.resolve()))
    except OSError as error:
        print(f'The image was saved but could not be opened: {error}')
