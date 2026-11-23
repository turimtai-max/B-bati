#!/usr/bin/env python3
"""bati влогын жинау.
  python3 render.py --test 2.5 31.0   → test/frame_*.jpg (бір кадр, overlay-мен)
  python3 render.py                    → ready/bati/01_bati_sogym.mp4
"""
import os, sys, subprocess, functools, hashlib, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan import SHOTS, SUBS, THOUGHTS

P = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.dirname(os.path.dirname(P))
INBOX = os.path.join(HOME, 'inbox')
VOICE = os.path.join(INBOX, 'zvuk', 'voice.mov')
MUSIC = os.path.join(INBOX, 'music', 'bg.mp3')
FONTS = os.path.expanduser('~/maxkallaway-kit/fonts')
FDIR = os.path.join(HOME, 'fonts')
W, H, FPS = 1080, 1920, 30
OUT = os.path.join(P, 'out'); TEST = os.path.join(P, 'test')
os.makedirs(OUT, exist_ok=True); os.makedirs(TEST, exist_ok=True)
VIDEO_KBPS = 7200          # GitHub 100 MB шегіне сыяды, Instagram үшін жеткілікті

def dur(f):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]))
TOTAL = dur(VOICE)

# ---------- түс / сапа ----------
@functools.lru_cache(None)
def is_hlg(f):
    return 'arib-std-b67' in subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=color_transfer', '-of', 'csv=p=0', f]).decode()

def vf(f, gamma=1.0, w=W, h=H):
    tm = ('zscale=tin=arib-std-b67:min=bt2020nc:pin=bt2020:t=linear:npl=203,format=gbrpf32le,'
          'zscale=p=bt709,tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,') if is_hlg(f) else ''
    ex = f'eq=gamma={gamma:.3f},' if abs(gamma - 1) > 0.01 else ''
    return (tm + f'scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},fps={FPS},'
            + ex + 'hqdn3d=0.8:0.8:2.5:2.5,eq=contrast=1.05:saturation=1.10,'
            'unsharp=5:5:0.75:5:5:0,setsar=1,format=yuv420p')

TARGET_Y = 128   # орташа жарықтық (0–255)
def exposure(f, a, d):
    """Кадр тым ашық болса — gamma-мен басады (тек ашығын, қараңғысын қозғамайды)."""
    out = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{d:.3f}', '-i', f,
        '-vf', vf(f, 1.0, 270, 480) + ',signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-',
        '-f', 'null', '-'], capture_output=True, text=True).stdout
    ys = [float(l.split('=')[1]) for l in out.splitlines() if 'YAVG' in l]
    y = sum(ys) / len(ys) if ys else TARGET_Y
    if y <= TARGET_Y + 10: return 1.0, y
    g = np.log(y / 255) / np.log((TARGET_Y + 6) / 255)
    return float(max(0.72, min(1.0, g))), y

# ---------- субтитр ----------
SAFE_L, SAFE_R = 96, 984
@functools.lru_cache(None)
def sfont(name, size, wg=None):
    path = os.path.join(FONTS, name) if name.startswith('Montserrat') else os.path.join(FDIR, name)
    f = ImageFont.truetype(path, size)
    if wg: f.set_variation_by_axes([wg])
    return f

def parse(text):
    out = []
    for i, part in enumerate(text.split('*')):
        for w in part.split():
            out.append((w, i % 2 == 1))
    return out

SANS, SANS_SIZE, TRACK = 'Montserrat-SemiBold.ttf', 44, 0.10    # кіші, бас әріп, кең аралық
SERIF, SERIF_SIZE, SERIF_W = 'PlayfairDisplay-Italic.ttf', 92, 600  # кілт сөз — үлкен курсив

def tok_metrics(w, key, k):
    if key:
        f = sfont(SERIF, int(SERIF_SIZE * k), SERIF_W)
        return f, f.getlength(w)
    f = sfont(SANS, int(SANS_SIZE * k)); tr = SANS_SIZE * k * TRACK
    return f, sum(f.getlength(c) for c in w.upper()) + tr * (len(w) - 1)

def layout(words, k):
    toks = [(w, b) + tok_metrics(w, b, k) for w, b in words]
    sp = lambda a, b: (26 if (a[1] or b[1]) else 18) * k
    def width(line): return sum(t[3] for t in line) + sum(sp(line[i], line[i + 1]) for i in range(len(line) - 1))
    if width(toks) <= SAFE_R - SAFE_L: return [toks], sp, width
    best = None
    for i in range(1, len(toks)):          # екі жолға ең тең бөлу
        a, b = toks[:i], toks[i:]
        m = max(width(a), width(b))
        if best is None or m < best[0]: best = (m, [a, b])
    return best[1], sp, width

@functools.lru_cache(512)
def draw_sub(text):
    words = parse(text)
    if not any(b for _, b in words):
        words = [(w, False) for w, _ in words]
    k = 1.0
    while True:
        lines, sp, width = layout(words, k)
        if max(width(l) for l in lines) <= SAFE_R - SAFE_L or k < 0.6: break
        k -= 0.05
    has_key = any(b for _, b in words)
    lh = (SERIF_SIZE if has_key else SANS_SIZE * 1.6) * k * 1.12
    img = Image.new('RGBA', (W, 400), (0, 0, 0, 0))
    base0 = 200 - lh * (len(lines) - 1) / 2 + (SERIF_SIZE * 0.32 * k if has_key else SANS_SIZE * 0.36 * k)
    def paint(d, dx, dy, fill, stroke=0):
        for li, line in enumerate(lines):
            x = (W - width(line)) / 2 + dx; y = base0 + li * lh + dy
            for j, (w, b, f, wd) in enumerate(line):
                if b:
                    d.text((x, y), w, font=f, fill=fill, anchor='ls', stroke_width=stroke, stroke_fill=fill)
                else:
                    xx, tr = x, SANS_SIZE * k * TRACK
                    for c in w.upper():
                        d.text((xx, y), c, font=f, fill=fill, anchor='ls', stroke_width=stroke, stroke_fill=fill)
                        xx += f.getlength(c) + tr
                x += wd + (sp(line[j], line[j + 1]) if j + 1 < len(line) else 0)
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0)); paint(ImageDraw.Draw(sh), 0, 3, (0, 0, 0, 255), 3)
    sh = Image.alpha_composite(Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)),
                                                     sh.filter(ImageFilter.GaussianBlur(8))), sh.filter(ImageFilter.GaussianBlur(2)))
    sh.putalpha(sh.getchannel('A').point(lambda v: int(v * 0.85)))
    img = Image.alpha_composite(img, sh)
    paint(ImageDraw.Draw(img), 0, 0, (255, 255, 255, 255))
    return img

FADE_FR = 5   # ≈0,17 с: жайлап пайда болу + 14 px көтерілу
def sub_at(t):
    for i, (s, txt) in enumerate(SUBS):
        s0 = s + 0.05
        e = SUBS[i + 1][0] + 0.05 if i + 1 < len(SUBS) else TOTAL
        e = min(e, s0 + 2.6)
        if s0 <= t < e: return txt, t - s0
    return None, 0

SUB_Y = 360
def overlay(t):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    txt, dt = sub_at(t)
    if txt:
        step = min(FADE_FR, int(dt * FPS))
        si = draw_sub(txt)
        if step < FADE_FR:
            k = (step + 1) / (FADE_FR + 1); k = 1 - (1 - k) ** 2
            si = si.copy(); si.putalpha(si.getchannel('A').point(lambda v: int(v * k)))
            img.alpha_composite(si, (0, int(SUB_Y - 200 + 14 * (1 - k))))
        else:
            img.alpha_composite(si, (0, SUB_Y - 200))
    return img

# ---------- переход дыбысы (синтез) ----------
SR = 48000
def whoosh(seed, length=0.75, peak=0.42):
    rng = np.random.default_rng(seed)
    n = int(SR * length); t = np.arange(n) / SR
    noise = rng.standard_normal((2, n))
    # жиілігі жоғарылап-төмендейтін сүзгі (sweep)
    fc = 300 + 5200 * np.exp(-((t - peak) / 0.16) ** 2)
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.zeros_like(noise); lo = np.zeros(2)
    for i in range(n):
        lo = a[i] * lo + (1 - a[i]) * noise[:, i]; y[:, i] = lo
    y = y - 0.6 * np.concatenate([np.zeros((2, 1)), y[:, :-1]], axis=1)  # аздап жоғары жиілік
    env = np.where(t < peak, (t / peak) ** 2.2, np.exp(-(t - peak) / 0.13))
    pan = 0.5 + 0.35 * np.tanh((t - peak) / 0.12) * (1 if seed % 2 else -1)
    y[0] *= env * np.sqrt(1 - pan); y[1] *= env * np.sqrt(pan)
    return y / np.abs(y).max()

def sfx_track(path):
    n = int(SR * TOTAL) + SR
    tr = np.zeros((2, n))
    variants = [whoosh(s) for s in range(3)]
    for i, t in enumerate(THOUGHTS):
        w = variants[i % 3]; st = int((t - 0.42) * SR)   # ең қатты сәті — кадр ауысқан жерде
        st = max(0, st); tr[:, st:st + w.shape[1]] += w[:, :n - st]
    tr = (tr / max(1e-9, np.abs(tr).max()) * 0.9 * 32767).astype('<i2')
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR); wf.writeframes(tr.T.tobytes())
    return path

# ---------- кадрларды кесу ----------
def segments():
    for i, (t0, f, src_in) in enumerate(SHOTS):
        t1 = SHOTS[i + 1][0] if i + 1 < len(SHOTS) else TOTAL
        yield i, os.path.join(INBOX, f), src_in, t1 - t0

def cut(seg):
    i, f, a, d = seg
    sig = hashlib.md5(f'{f}|{a}|{d}|v2'.encode()).hexdigest()[:8]
    out = os.path.join(OUT, f'seg{i:02d}_{sig}.mp4')
    if os.path.exists(out): return out
    g, y = exposure(f, a, d)
    n = round(d * FPS)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{a:.3f}', '-i', f, '-vf', vf(f, g), '-frames:v', str(n), '-an',
                    '-c:v', 'libx264', '-preset', 'slow', '-crf', '10', '-pix_fmt', 'yuv420p', out + '.tmp.mp4'], check=True)
    os.replace(out + '.tmp.mp4', out)
    print(f'seg{i:02d} Y={y:.0f} gamma={g:.2f}', flush=True)
    return out

def main():
    if '--test' in sys.argv:
        for t in map(float, sys.argv[sys.argv.index('--test') + 1:]):
            i = max(k for k, s in enumerate(SHOTS) if s[0] <= t)
            f = os.path.join(INBOX, SHOTS[i][1]); a = SHOTS[i][2] + (t - SHOTS[i][0])
            nxt = SHOTS[i + 1][0] if i + 1 < len(SHOTS) else TOTAL
            g, _ = exposure(f, SHOTS[i][2], nxt - SHOTS[i][0])
            raw = os.path.join(TEST, 'raw.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{a:.3f}', '-i', f, '-vf', vf(f, g), '-frames:v', '1', raw], check=True)
            fr = Image.open(raw).convert('RGBA'); fr.alpha_composite(overlay(t))
            fr.convert('RGB').save(os.path.join(TEST, f'frame_{t:05.1f}.jpg'), quality=92)
            print('test', t, 'gamma', round(g, 2))
        return
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as ex: files = list(ex.map(cut, list(segments())))
    lst = os.path.join(OUT, 'concat.txt')
    open(lst, 'w').write(''.join(f"file '{x}'\n" for x in files))
    base = os.path.join(OUT, 'base.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', base], check=True)
    sfx = sfx_track(os.path.join(OUT, 'sfx.wav'))
    nfr = round(TOTAL * FPS)
    # 1) субтитр + дыбыс → аралық (жоғары сапа)
    mid = os.path.join(OUT, 'mid.mkv')
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-i', base,
        '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
        '-i', VOICE, '-i', MUSIC, '-i', sfx,
        '-filter_complex', '[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v];'
            '[2:a]highpass=f=70,acompressor=threshold=-20dB:ratio=2.5:attack=10:release=200,loudnorm=I=-15:TP=-2:LRA=9,'
            'aresample=48000,asplit=2[vo][sc];'
            f'[3:a]atrim=0:{TOTAL:.3f},asetpts=PTS-STARTPTS,aresample=48000,loudnorm=I=-27:TP=-6,'
            f'afade=t=in:d=0.6,afade=t=out:st={TOTAL-2.5:.3f}:d=2.5[mu];'
            '[mu][sc]sidechaincompress=threshold=0.03:ratio=3:attack=30:release=450[duck];'
            f'[4:a]atrim=0:{TOTAL:.3f},highpass=f=120,volume=0.22[fx];'
            '[vo][duck][fx]amix=inputs=3:normalize=0:duration=first,alimiter=limit=0.89[a]',
        '-map', '[v]', '-map', '[a]', '-frames:v', str(nfr), '-t', f'{TOTAL:.3f}',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '8', '-pix_fmt', 'yuv420p',
        '-c:a', 'pcm_s16le', mid], stdin=subprocess.PIPE)
    last_key, last = None, None
    for n in range(nfr):
        t = n / FPS
        txt, dt = sub_at(t)
        key = (txt, min(FADE_FR, int(dt * FPS)) if txt else 0)
        if key != last_key: last = overlay(t).tobytes(); last_key = key
        p.stdin.write(last)
    p.stdin.close()
    if p.wait() != 0: raise SystemExit('overlay өтуі сәтсіз')
    # 2) екі өтпелі кодтау — Instagram үшін тұрақты жоғары сапа
    ready = os.path.join(HOME, 'ready', 'bati'); os.makedirs(ready, exist_ok=True)
    final = os.path.join(ready, '01_bati_sogym.mp4'); tmp = final + '.tmp.mp4'
    common = ['-c:v', 'libx264', '-preset', 'slower', '-tune', 'film', '-b:v', f'{VIDEO_KBPS}k',
              '-maxrate', f'{int(VIDEO_KBPS*1.6)}k', '-bufsize', f'{VIDEO_KBPS*3}k', '-profile:v', 'high', '-level', '4.1',
              '-g', '60', '-bf', '2', '-pix_fmt', 'yuv420p', '-r', str(FPS),
              '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
              '-passlogfile', os.path.join(OUT, 'x264pass')]
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', mid] + common + ['-pass', '1', '-an', '-f', 'null', '-'], check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', mid] + common + ['-pass', '2',
                    '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-movflags', '+faststart', tmp], check=True)
    os.replace(tmp, final)
    print('дайын:', final, round(os.path.getsize(final) / 2**20, 1), 'MB')

if __name__ == '__main__':
    main()
