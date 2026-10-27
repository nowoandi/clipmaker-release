# animatic.py — черновая сборка из СТАТИЧНЫХ КАДРОВ под музыку, до единой секунды видео.
#
# Зачем этот шаг существует. Клип «Alpha» (10–11.08.2026): кадры были
# готовы днём, съёмка видео заняла сутки, и только на готовых роликах стало видно, что
# смотреть нечего — четыре объекта в разном свете на танцевальном треке. Ту же правду
# показала бы сборка из тех же картинок под ту же музыку — за пять минут и ноль денег.
# Формулировка заказчика: «это можно было сразу посмотреть, а по нему уже соединять всё
# в видео — это должно было быть на порядок быстрее».
#
# Что делает: кладёт кадры на сетку такта по длинам планов из шот-листа, подставляет трек
# и рендерит mp4. Никаких генераций, только ffmpeg по локальным файлам.
#
#   python animatic.py --project <папка> [--out out/animatic.mp4] [--fps 30]
#
# Кадр берётся по shot["src"] из frames/<src>.png. Нет файла — план пропускается,
# его длительность отдаётся предыдущему, чтобы музыка не разъезжалась.
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib


def ffmpeg_path():
    cfg = lib.load_config() or {}
    p = cfg.get("ffmpeg")
    if p and Path(p).exists():
        return p
    return "ffmpeg"


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()

    pdir = lib.project_dir(a.project)
    mem = pdir / "clip-memory"
    project = lib.read_json(lib.find_project_json(pdir))

    song = project.get("song") or {}
    render = project.get("render") or {}
    W = int(render.get("width") or 1080)
    H = int(render.get("height") or 1920)

    grid_p = mem / "song" / "grid.json"
    beat = 0.0
    duration = float(song.get("duration") or 0)
    if grid_p.exists():
        g = lib.read_json(grid_p)
        beat = float(g.get("beat") or 0)
        duration = float(g.get("duration") or duration)
    if not beat:
        bpm = float(song.get("bpm") or 0)
        beat = 60.0 / bpm if bpm else 0
    if not beat:
        lib.fail("нет сетки такта: сначала музыкальный аналитик (clip-memory/song/grid.json)")

    sl = mem / "script" / "shotlist.json"
    if not sl.exists():
        lib.fail("нет шот-листа: clip-memory/script/shotlist.json")
    shots = lib.read_json(sl)
    shots = shots.get("shots") or shots.get("shotlist") or []
    if not shots:
        lib.fail("шот-лист пуст")

    frames = pdir / "frames"
    song_file = pdir / (song.get("file") or "song.mp3")
    if not song_file.exists():
        lib.fail(f"нет трека: {song_file}")

    items, missing, carry = [], [], 0.0
    for s in shots:
        src = s.get("src") or (s.get("anchors") or [None])[0]
        secs = float(s.get("beats") or 0) * beat + carry
        img = frames / f"{src}.png"
        if not img.exists():
            missing.append(src)
            carry = secs          # длительность отдаём следующему плану
            continue
        carry = 0.0
        items.append((img, secs))

    if not items:
        lib.fail("не найдено ни одного кадра в frames/")
    if carry and items:                      # хвост, если последние планы без картинки
        items[-1] = (items[-1][0], items[-1][1] + carry)

    out = Path(a.out) if a.out else (pdir / "out" / "animatic.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    lst = out.parent / "_animatic.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for img, secs in items:
            f.write(f"file '{img.as_posix()}'\n")
            f.write(f"duration {secs:.3f}\n")
        f.write(f"file '{items[-1][0].as_posix()}'\n")   # concat требует повтор последнего

    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},setsar=1,fps={a.fps}")
    cmd = [
        ffmpeg_path(), "-y",
        "-f", "concat", "-safe", "0", "-i", str(lst),
        "-i", str(song_file),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        lib.fail("ffmpeg не собрал аниматик")
    try:
        lst.unlink()
    except OSError:
        pass

    planned = sum(s for _, s in items)
    uniq = len({img.stem for img, _ in items})
    msg = (f"аниматик собран: {out}\n"
           f"  планов {len(items)}, различимых кадров {uniq}, "
           f"длина {planned:.1f} с при треке {duration:.1f} с")
    if missing:
        msg += f"\n  без картинки пропущено: {len(missing)} ({', '.join(sorted(set(missing))[:6])})"
    if uniq and len(items) / uniq > 3:
        msg += (f"\n  ! на каждый кадр приходится {len(items)/uniq:.1f} плана — "
                f"проверь, не будет ли монотонно (R26)")
    lib.ok(msg)


if __name__ == "__main__":
    main()
