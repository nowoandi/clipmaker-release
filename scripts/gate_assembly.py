# gate_assembly.py — не верить логу «ГОТОВО» (R18, ловит грабли R21).
#
# Проверяет собранный клип: длительность против трека (±1 с), разрешение,
# и режет контрольный лист из 20 кадров по всей длине — по нему видно,
# живёт картинка или один кадр стоит всю песню.
#
#   python gate_assembly.py --video final.mp4 --audio song.mp3 [--sheet] [--tolerance 1.0]
#
# Выход: 0 — сборка сходится; 2 — брак.
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")
RES_RE = re.compile(r"Video:.*?\s(\d{3,4})x(\d{3,4})")
# Строка потока: ..., 1245 kb/s, 25 fps, 25 tbr, ... «fps» — СРЕДНЯЯ частота (кадров / длительность
# контейнера), «tbr» — реальная частота потока. На mp4 после x264 они расходятся: 240 кадров на
# 30 tbr дают контейнер 7,97 с и «30.13 fps». Предупреждение по среднему значило бы ложную тревогу
# на нормальном файле — это поймал сухой прогон рекламной сборки 10.10.2026. Поэтому берётся tbr,
# а fps — только если tbr в строке нет.
TBR_RE = re.compile(r"Video:.*?,\s*(\d+(?:\.\d+)?)\s*tbr")
FPS_RE = re.compile(r"Video:.*?,\s*(\d+(?:\.\d+)?)\s*fps")

def probe(ffmpeg, path):
    """Длительность (с), разрешение и частота кадров через разбор stderr ffmpeg -i (ffprobe на машине нет)."""
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = out.stderr or ""
    m = DUR_RE.search(text)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    r = RES_RE.search(text)
    res = (int(r.group(1)), int(r.group(2))) if r else None
    f = TBR_RE.search(text) or FPS_RE.search(text)
    fps = float(f.group(1)) if f else None
    return dur, res, fps

def fps_note(fps, allowed):
    """Строка-предупреждение, если частота кадров вне набора; иначе None.

    Допуск 0,06 нужен, чтобы 23,976 считалось 24, а 29,97 — 30: так пишут кинокамеры и редакторы.
    """
    if fps is None or any(abs(fps - a) <= 0.06 for a in allowed):
        return None
    return (f"частота кадров {fps:g} вне {sorted(allowed)}. Во внешнем разборе работ "
            f"(08.09.2026) вывод в 50 fps назвали ошибкой: картинка перестаёт выглядеть киношной. "
            f"Это не брак сборки — если площадка требует другое, оставить; иначе экспортировать "
            f"в 24 или 30 (shared/ads/03-craft.md).")

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--tolerance", type=float, default=None)
    ap.add_argument("--sheet", action="store_true", help="нарезать контрольный лист 20 кадров")
    ap.add_argument("--expect", default="1080x1920", help="ожидаемое разрешение, ШxВ")
    args = ap.parse_args()

    cfg = lib.load_config()
    ffmpeg = cfg["ffmpeg"]
    tol = args.tolerance if args.tolerance is not None else cfg.get("assembly_tolerance_sec", 1.0)
    video, audio = Path(args.video), Path(args.audio)
    if not video.exists():
        lib.fail(f"видео не найдено: {video}")
    if not audio.exists():
        lib.fail(f"трек не найден: {audio}")

    vdur, vres, vfps = probe(ffmpeg, video)
    adur, _, _ = probe(ffmpeg, audio)
    if vdur is None or adur is None:
        lib.fail("не удалось прочитать длительность (ffmpeg -i).")

    print(f"── СБОРКА · {video.name} " + "─" * 20)
    shape = f" · {vres[0]}x{vres[1]}" if vres else ""
    rate = f" · {vfps:g} fps" if vfps else ""
    print(f"  видео : {vdur:8.2f} с{shape}{rate}")
    print(f"  трек  : {adur:8.2f} с · {audio.name}")
    diff = abs(vdur - adur)
    print(f"  дельта: {diff:8.2f} с (допуск {tol})")

    errors = []
    if diff > tol:
        errors.append(f"длительность разъехалась на {diff:.2f} с (R18: 3:52 вместо 3:09 — уже брак). "
                      f"Типовые причины — R21: zoompan множит кадры, timescale, concat -c copy.")
    exp = args.expect.lower().split("x")
    if vres and (vres[0] != int(exp[0]) or vres[1] != int(exp[1])):
        errors.append(f"разрешение {vres[0]}x{vres[1]}, ожидалось {args.expect} "
                      f"(R21: scale=cover, не по одной стороне).")

    # Частота кадров — предупреждение, не брак: на неё влияет площадка, а длительность и
    # разрешение ломают сборку всегда. Набор живёт в config/paths.json.
    warning = fps_note(vfps, cfg.get("assembly_fps_ok", [24, 25, 30]))

    if args.sheet or not errors:
        sheet = video.with_name(video.stem + ".sheet.png")
        n, cols, rows = 20, 5, 4
        step = max(vdur / n, 0.1)
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
               "-vf", f"fps=1/{step:.4f},scale=270:-2,tile={cols}x{rows}",
               "-frames:v", "1", str(sheet)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and sheet.exists():
            print(f"  лист  : {sheet}  ← смотреть глазами: картинка живёт или стоит (R18)")
        else:
            print(f"[~] лист не нарезался: {r.stderr.strip()[:200]}")

    if warning:
        print("[~] " + warning, file=sys.stderr)
    if errors:
        for e in errors:
            print("[-] " + e, file=sys.stderr)
        lib.fail("сборка бракована.")
    lib.ok(f"длительность и разрешение сходятся. Лист смотреть обязательно — это вторая половина R18."
           + (" Частота кадров — см. предупреждение выше." if warning else ""))

if __name__ == "__main__":
    main()
