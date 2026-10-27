# prop_fx.py — мелкий реквизит накладывается в монтаже, а не генерируется (R37).
#
# Зачем: «Charlie», 27–28.09.2026. Grok не держит размер монеты: из макро-старта она выходит
# «шайбой», в общем плане лежит на столе блином, броска с пальца не рисует. Админ: «на столе лежит огромная
# монета… нет вообще никакого восприятия с этой монетой. Я уже сколько пытался…». Решение, принятое им
# после демо: кадры и ролики делаются без монеты, а настоящий квотер из двух чистых текстур (лицо и оборот)
# накладывается здесь — со своим размером, траекторией и вращением, где стороны сменяют друг друга.
#
#   python prop_fx.py --plate frames/LT_base.png --front heads.png --back tails.png --out o.mp4 \
#       --mode toss --start 520,1300 --land 540,1300 --t0 0.6 --t1 2.2 --peak 620 --dur 4
#   python prop_fx.py --plate clips/B_coin_hang.mp4 ... --mode hang --pos 505,1010
#   python prop_fx.py --plate ... --mode fall --pos 505,1010 --land 505,1300 --t0 0.2 --t1 1.0
#
# Координаты — в пикселях основы (картинки или первого кадра ролика). Размер — диаметр в пикселях.
import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib
from PIL import Image, ImageDraw, ImageFilter


def pt(s):
    x, y = s.split(",")
    return float(x), float(y)


def tinted(face, w, h, tint):
    im = face.resize((max(2, int(w)), max(2, int(h))), Image.LANCZOS)
    r, g, b, a = im.split()
    r = r.point(lambda v: int(v * tint[0]))
    g = g.point(lambda v: int(v * tint[1]))
    b = b.point(lambda v: int(v * tint[2]))
    return Image.merge("RGBA", (r, g, b, a))


def state(a, t):
    """(x, y, theta, lying, shadow_y) в момент t. theta — угол переворота вокруг горизонтальной оси."""
    if a.mode == "hang":
        x, y = a.pos
        # висит ровно, лицом к камере; едва заметно дышит и медленно поворачивается — чтобы было видно, что
        # это предмет в воздухе, а не наклейка
        return x, y + math.sin(t * 2.1) * a.bob, math.sin(t * 0.9) * 0.35, False, a.shadow_y
    start = a.start if a.mode == "toss" else a.pos
    land = a.land or start
    if t < a.t0:
        return start[0], start[1], 0.0, a.mode == "toss", land[1]
    if t > a.t1:
        dt = t - a.t1
        y = land[1] - abs(math.sin(dt * 14)) * 10 * math.exp(-dt * 6)    # маленький отскок и успокоение
        return land[0], y, 0.0, True, land[1]
    u = (t - a.t0) / (a.t1 - a.t0)
    x = start[0] + (land[0] - start[0]) * u
    if a.mode == "toss":
        y = start[1] + (land[1] - start[1]) * u - 4 * a.peak * u * (1 - u)
    else:                                                                # fall: из точки вниз с ускорением
        y = start[1] + (land[1] - start[1]) * u * u
    # целое число оборотов к приземлению: ложится той стороной, что задана (--land-side)
    turns = max(1, round(a.rev * (a.t1 - a.t0)))
    theta = 2 * math.pi * turns * u + (math.pi if a.land_side == "back" else 0.0)
    return x, y, theta, False, land[1]


def size_at(a, t):
    """Диаметр в момент t. Рампа нужна «Flip It», S59: на отъезде монета уходит из кадра во всю ширину в точку."""
    if a.size_to is None:
        return a.size
    u = min(1.0, max(0.0, (t - a.t0) / max(1e-6, a.t1 - a.t0)))
    return a.size + (a.size_to - a.size) * u


def render_frame(bg, a, t, faces):
    x, y, th, lying, shadow_y = state(a, t)
    size = size_at(a, t)
    fr = bg.copy()
    if shadow_y is not None:
        h = max(0.0, shadow_y - y)
        sw = size * (1.0 + h / 900)
        op = int(150 * max(0.12, 1 - h / 700))
        sh = Image.new("RGBA", fr.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse((x - sw / 2 + 6, shadow_y + 6 - sw * 0.17,
                                    x + sw / 2 + 6, shadow_y + 6 + sw * 0.17), fill=(0, 0, 0, op))
        fr = Image.alpha_composite(fr, sh.filter(ImageFilter.GaussianBlur(4)))
    c = math.cos(th)
    face = faces[0] if c >= 0 else faces[1]
    sy = max(abs(c), 0.06) * (a.lying_ratio if lying else 1.0)
    ci = tinted(face, size, size * sy, a.tint)
    fr.alpha_composite(ci, (int(x - ci.width / 2), int(y - ci.height / 2)))
    return fr


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--plate", required=True, help="картинка или ролик-основа")
    ap.add_argument("--front", required=True)
    ap.add_argument("--back", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["toss", "hang", "fall"], required=True)
    ap.add_argument("--start", type=pt, help="toss: откуда (кончик пальца или стол)")
    ap.add_argument("--pos", type=pt, help="hang/fall: где висит")
    ap.add_argument("--land", type=pt, default=None, help="куда падает")
    ap.add_argument("--shadow-y", type=float, default=None, help="hang: высота стола для тени")
    ap.add_argument("--land-side", choices=["front", "back"], default="front")
    ap.add_argument("--t0", type=float, default=0.5)
    ap.add_argument("--t1", type=float, default=2.0)
    ap.add_argument("--peak", type=float, default=600)
    ap.add_argument("--rev", type=float, default=5.0, help="оборотов в секунду в полёте")
    ap.add_argument("--bob", type=float, default=4.0)
    ap.add_argument("--size", type=float, default=34, help="диаметр в пикселях основы")
    ap.add_argument("--size-to", type=float, default=None,
                    help="диаметр к концу отрезка --t0..--t1: монета растёт или уходит вдаль на отъезде камеры")
    ap.add_argument("--lying-ratio", type=float, default=0.34, help="сплющивание лежащей монеты перспективой")
    ap.add_argument("--tint", default="1.0,0.86,0.66", help="тёплый свет лампы по умолчанию")
    ap.add_argument("--dur", type=float, default=None, help="для картинки-основы")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--sub", type=int, default=6, help="подкадры на кадр: естественный смаз")
    a = ap.parse_args()
    a.tint = tuple(float(v) for v in a.tint.split(","))
    if a.mode == "toss" and not a.start:
        lib.fail("toss требует --start")
    if a.mode in ("hang", "fall") and not a.pos:
        lib.fail(f"{a.mode} требует --pos")

    ff = lib.load_config()["ffmpeg"]
    faces = (Image.open(a.front).convert("RGBA"), Image.open(a.back).convert("RGBA"))
    tmp = Path(tempfile.mkdtemp(prefix="prop_fx_"))
    try:
        plate = Path(a.plate)
        if plate.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            if not a.dur:
                lib.fail("для картинки-основы нужен --dur")
            base = Image.open(plate).convert("RGBA")
            plates = [base] * int(a.dur * a.fps)
            audio = None
        else:
            # R21: кадры ролика — через ffmpeg, фиксированный fps, без второго потока-обложки
            subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(plate), "-map", "0:v:0",
                            "-vf", f"fps={a.fps}", str(tmp / "p_%05d.png")], check=True)
            plates = [Image.open(p).convert("RGBA") for p in sorted(tmp.glob("p_*.png"))]
            audio = plate
        for i, bg in enumerate(plates):
            acc = None
            for s in range(a.sub):
                fr = render_frame(bg, a, (i + s / a.sub) / a.fps, faces)
                acc = fr if acc is None else Image.blend(acc, fr, 1 / (s + 1))
            acc.convert("RGB").save(tmp / f"o_{i:05d}.png")
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(a.fps), "-i", str(tmp / "o_%05d.png")]
        if audio:
            cmd += ["-i", str(audio), "-map", "0:v", "-map", "1:a?", "-c:a", "copy"]
        cmd += ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", a.out]
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lib.ok(f"реквизит наложен: {a.mode}, {len(plates)} кадров → {a.out}")


if __name__ == "__main__":
    main()
