#!/usr/bin/env python3
"""bati влогын жинау.
  python3 render.py --test 2.5 31.0   → test/frame_*.jpg (бір кадр, overlay-мен)
  python3 render.py                    → ready/bati/01_bati_sogym.mp4
"""
import os, sys, subprocess, json, functools
from PIL import Image, ImageDraw, ImageFont, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan import SHOTS, SUBS, HOOK, HOOK_END

P = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.dirname(os.path.dirname(P))
INBOX = os.path.join(HOME, 'inbox')
VOICE = os.path.join(INBOX, 'zvuk', 'voice.mov')
MUSIC = os.path.join(INBOX, 'music', 'bg.mp3')
FONTS = os.path.expanduser('~/maxkallaway-kit/fonts')
W, H, FPS = 1080, 1920, 30
OUT = os.path.join(P, 'out'); TEST = os.path.join(P, 'test')
os.makedirs(OUT, exist_ok=True); os.makedirs(TEST, exist_ok=True)

def dur(f):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]))
TOTAL = dur(VOICE)

@functools.lru_cache(None)
def is_hlg(f):
    return 'arib-std-b67' in subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=color_transfer', '-of', 'csv=p=0', f]).decode()

GRADE = 'hqdn3d=1.2:1.2:3:3,eq=contrast=1.05:saturation=1.12,unsharp=5:5:0.55:5:5:0'
def vf(f):
    tm = ('zscale=tin=arib-std-b67:min=bt2020nc:pin=bt2020:t=linear:npl=203,format=gbrpf32le,'
          'zscale=p=bt709,tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,') if is_hlg(f) else ''
    return (tm + f'scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},'
            f'fps={FPS},{GRADE},setsar=1,format=yuv420p')

# ---------- overlay (хук + субтитр) ----------
def font(name, size): return ImageFont.truetype(os.path.join(FONTS, f'Montserrat-{name}.ttf'), size)
SAFE_L, SAFE_R = 96, 984
RED = (0xE3, 0x06, 0x13, 255)

def parse(text):
    out, bold = [], False
    for i, part in enumerate(text.split('*')):
        for w in part.split():
            out.append((w, i % 2 == 1))
    return out

FDIR = os.path.join(HOME, 'fonts')
STYLES = {
    # (қарапайым сөз шрифті, салмақ), (кілт сөз шрифті, салмақ), кілт сөз өлшем коэф.
    'playfair':  (('Montserrat-Medium.ttf', None), ('PlayfairDisplay-Italic.ttf', 700), 1.22),
    'cormorant': (('Montserrat-Regular.ttf', None), ('CormorantGaramond-Italic.ttf', 650), 1.38),
    'lora':      (('Montserrat-Medium.ttf', None), ('Lora-Italic.ttf', 600), 1.2),
}
STYLE = os.environ.get('SUB_STYLE', 'playfair')

@functools.lru_cache(None)
def sfont(spec, size):
    name, wg = spec
    path = os.path.join(FONTS, name) if name.startswith('Montserrat') else os.path.join(FDIR, name)
    f = ImageFont.truetype(path, size)
    if wg: f.set_variation_by_axes([wg])
    return f

def draw_sub(text, scale=1.0):
    words = parse(text)
    reg, key, kmul = STYLES[STYLE]
    size = 64
    while True:
        fr, fb = sfont(reg, int(size * scale)), sfont(key, int(size * kmul * scale))
        sp = int(size * scale * 0.30)
        widths = [(fb if b else fr).getlength(w) for w, b in words]
        tw = sum(widths) + sp * (len(words) - 1)
        if tw <= (SAFE_R - SAFE_L) * scale or size <= 38: break
        size -= 2
    img = Image.new('RGBA', (W, 260), (0, 0, 0, 0))
    x = (W - tw) / 2; base = 150
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0)); ds = ImageDraw.Draw(sh)
    xx = x
    for (w, b), wd in zip(words, widths):
        ds.text((xx + 2, base + 4), w, font=fb if b else fr, fill=(0, 0, 0, 255), anchor='ls', stroke_width=3, stroke_fill=(0, 0, 0, 255))
        xx += wd + sp
    sh = Image.alpha_composite(Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)), sh.filter(ImageFilter.GaussianBlur(7))), sh.filter(ImageFilter.GaussianBlur(2)))
    img = Image.alpha_composite(img, sh); d = ImageDraw.Draw(img)
    xx = x
    for (w, b), wd in zip(words, widths):
        d.text((xx, base), w, font=fb if b else fr, fill=(255, 255, 255, 255), anchor='ls',
               stroke_width=1, stroke_fill=(0, 0, 0, 120))
        xx += wd + sp
    return img

def wrap(text, f, maxw):
    lines, cur = [], ''
    for w in text.split():
        t = (cur + ' ' + w).strip()
        if f.getlength(t) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = w
    return lines + [cur]

@functools.lru_cache(None)
def hook_img(scale=1.0):
    f = font('ExtraBold', int(80 * scale)); pad_x, pad_y, lh = int(34 * scale), int(22 * scale), int(96 * scale)
    lines = wrap(HOOK, f, (SAFE_R - SAFE_L - 2 * 34) * scale)
    bw = max(f.getlength(l) for l in lines) + 2 * pad_x; bh = lh * len(lines) + 2 * pad_y
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sh = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ds = ImageDraw.Draw(sh)
    x0 = (W - bw) / 2; y0 = 600 - bh / 2
    ds.rounded_rectangle((x0 + 4, y0 + 10, x0 + bw + 4, y0 + bh + 10), radius=int(18 * scale), fill=(0, 0, 0, 120))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=int(18 * scale), fill=RED)
    for i, l in enumerate(lines):
        d.text((W / 2, y0 + pad_y + lh * i + lh / 2), l, font=f, fill='white', anchor='mm')
    return img

POP = 0.16
def sub_at(t):
    for i, (s, txt) in enumerate(SUBS):
        s0 = s + 0.05
        e = SUBS[i + 1][0] + 0.05 if i + 1 < len(SUBS) else TOTAL
        e = min(e, s0 + 2.6)
        if s0 <= t < e: return txt, t - s0
    return None, 0

@functools.lru_cache(512)
def sub_img(txt, step):
    k = min(1.0, step / 4)  # 4 қадам ≈ 0.13 с
    return draw_sub(txt, 0.86 + 0.14 * k)

def overlay(t):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    if t < HOOK_END:
        k = min(1.0, t / POP)
        hi = hook_img(round(0.9 + 0.1 * k, 2))
        img = Image.alpha_composite(img, hi)
    txt, dt = sub_at(t)
    if txt:
        si = sub_img(txt, min(4, int(dt * FPS)))
        img.alpha_composite(si, (0, 335 - 150))
    return img

# ---------- кадрларды кесу ----------
def segments():
    segs = []
    for i, (t0, f, src_in) in enumerate(SHOTS):
        t1 = SHOTS[i + 1][0] if i + 1 < len(SHOTS) else TOTAL
        segs.append((i, os.path.join(INBOX, f), src_in, t1 - t0))
    return segs

def cut(seg):
    i, f, a, d = seg
    out = os.path.join(OUT, f'seg{i:02d}.mp4')
    if os.path.exists(out): return out
    n = round(d * FPS)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{a:.3f}', '-i', f, '-vf', vf(f), '-frames:v', str(n), '-an',
                    '-c:v', 'libx264', '-preset', 'slow', '-crf', '12', '-pix_fmt', 'yuv420p', out], check=True)
    return out

def main():
    if '--test' in sys.argv:
        for t in map(float, sys.argv[sys.argv.index('--test') + 1:]):
            i = max(k for k, s in enumerate(SHOTS) if s[0] <= t)
            f = os.path.join(INBOX, SHOTS[i][1]); a = SHOTS[i][2] + (t - SHOTS[i][0])
            raw = os.path.join(TEST, 'raw.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{a:.3f}', '-i', f, '-vf', vf(f), '-frames:v', '1', raw], check=True)
            fr = Image.open(raw).convert('RGBA'); fr.alpha_composite(overlay(t))
            fr.convert('RGB').save(os.path.join(TEST, f'frame_{t:05.1f}.jpg'), quality=90)
            print('test', t)
        return
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as ex: files = list(ex.map(cut, segments()))
    lst = os.path.join(OUT, 'concat.txt')
    open(lst, 'w').write(''.join(f"file '{x}'\n" for x in files))
    base = os.path.join(OUT, 'base.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', base], check=True)
    ready = os.path.join(HOME, 'ready', 'bati'); os.makedirs(ready, exist_ok=True)
    final = os.path.join(ready, '01_bati_sogym.mp4')
    nfr = round(TOTAL * FPS)
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-i', base,
        '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
        '-i', VOICE, '-i', MUSIC,
        '-filter_complex', '[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v];'
                           '[2:a]highpass=f=70,acompressor=threshold=-20dB:ratio=2.5:attack=10:release=200,loudnorm=I=-15:TP=-2:LRA=9,'
                           'aresample=48000,asplit=2[vo][sc];'
                           f'[3:a]atrim=0:{TOTAL:.3f},asetpts=PTS-STARTPTS,aresample=48000,loudnorm=I=-27:TP=-6,'
                           f'afade=t=in:d=0.6,afade=t=out:st={TOTAL-2.5:.3f}:d=2.5[mu];'
                           '[mu][sc]sidechaincompress=threshold=0.03:ratio=3:attack=30:release=450[duck];'
                           '[vo][duck]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.89[a]',
        '-map', '[v]', '-map', '[a]', '-frames:v', str(nfr), '-t', f'{TOTAL:.3f}',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-maxrate', '9M', '-bufsize', '18M', '-profile:v', 'high',
        '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
        '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-movflags', '+faststart', final], stdin=subprocess.PIPE)
    last_key, last = None, None
    for n in range(nfr):
        t = n / FPS
        txt, dt = sub_at(t)
        key = (txt, min(4, int(dt * FPS)) if txt else 0, round(min(1.0, t / POP), 2) if t < HOOK_END else -1)
        if key != last_key: last = overlay(t).tobytes(); last_key = key
        p.stdin.write(last)
    p.stdin.close(); p.wait()
    print('дайын:', final)

if __name__ == '__main__':
    main()
