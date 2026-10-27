# suno_pack.py — упаковка готового ролика в Suno-hook: свой звук внутри, копия под загрузку.
#
# Зачем. Suno-hook берёт звук либо из видео («Video sound»), либо из песни («Song sound»), и
# начало фрагмента у готового hook'а не меняется (Админ, 12.10.2026). На <проект>
# звук трека вшивался руками, копия под загрузку пережималась руками: браузерный инструмент
# Chrome принимает файл до 10 МБ, а мастер весил 20 МБ. Здесь это одна команда с проверками —
# ролик, который Suno не примет или который разойдётся со звуком, не уходит дальше.
#
#   python suno_pack.py --project <клип> --master output/hook-v3.mp4 [--song-url URL]
#                       [--start 60.637 --end 83.049] [--fade-from 81.1] [--max-mb 9.5]
#
# Окно — grid.json → hook.start/hook.end (как у gate_script); --start/--end только перекрывают.
# Выход: 0 — готово; 2 — ролик не годится (stderr скажет чем).
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

lib.setup_io()

# Требования Suno к видео hook'а — с экрана загрузки suno.com/hooks/create, 13.10.2026:
# «9:16 portrait aspect ratio, duration between 10 seconds and 4 minutes, max file size 200 MB».
SUNO_MIN_SEC = 10.0
SUNO_MAX_SEC = 240.0
SUNO_MAX_MB = 200.0
ASPECT = 9 / 16
# Допуск пропорции: 704x1280 и 720x1264 у Grok — это 0,550 и 0,570 при 0,5625.
ASPECT_TOL = 0.03
# Ролик и окно трека обязаны совпасть: расхождение дальше одного кадра при 24 fps слышно.
LENGTH_TOL = 0.1
AUDIO_KBPS = 192

# Громкость итога (0.8.36). Цель -14 LUFS / -1 dBTP взята из сторонних обзоров (разбор 18.10.2026:
# video-use, OpenMontage) и в этом файле ТОЛЬКО предупреждение: трек уже сведён Suno, молча
# нормализовать чужой мастер нельзя. Числа сверить с площадкой (Suno их не публикует; не проверено).
LOUD_TARGET_LUFS = -14.0
LOUD_TOL_LU = 2.0
LOUD_MAX_TRUE_PEAK = -1.0
LOUD_NOTE = "ориентир из сторонних обзоров, сверить с площадкой; не нормализуется, только предупреждение"
try:
    # Числа живут в профиле платформы (config/platforms.json), чтобы не расходиться с ним; константы выше — запас.
    _loud = lib.load_platforms()["profiles"]["suno-hook"]["loudness"]
    LOUD_TARGET_LUFS = float(_loud["lufs"])
    LOUD_MAX_TRUE_PEAK = float(_loud["true_peak_dbtp"])
except Exception:
    pass


def probe(ffmpeg, path):
    """(длительность, ширина, высота) по выводу ffmpeg -i; ffprobe в поставке нет (R22)."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                       capture_output=True, encoding="utf-8", errors="replace")
    out = r.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if not m:
        lib.fail(f"не читается длительность {path}")
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    v = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    if not v:
        lib.fail(f"в {path} нет видеодорожки")
    return dur, int(v.group(1)), int(v.group(2))


def measure_loudness(ffmpeg, path):
    """Громкость звуковой дорожки файла по EBU R128: {integrated_lufs, true_peak_dbtp} или None.

    Берётся только блок Summary: до него ebur128 печатает строки каждые 100 мс с текущим I:.
    Тишина даёт -inf — это не число, поэтому вернётся None по соответствующему полю.
    """
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-vn",
                        "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, encoding="utf-8", errors="replace")
    return parse_ebur128(r.stderr or "")


def parse_ebur128(text):
    tail = text.rsplit("Summary:", 1)
    if len(tail) < 2:
        return None
    block = tail[1]
    i = re.search(r"Integrated loudness:\s*I:\s*(-?[\d.]+|-?inf)\s*LUFS", block)
    p = re.search(r"True peak:\s*Peak:\s*(-?[\d.]+|-?inf)\s*dBFS", block)

    def num(m):
        try:
            v = float(m.group(1)) if m else None
            return round(v, 1) if v is not None and v == v and abs(v) != float('inf') else None
        except ValueError:
            return None

    out = {"integrated_lufs": num(i), "true_peak_dbtp": num(p)}
    return out if any(v is not None for v in out.values()) else None


def loudness_warnings(m):
    """Предупреждения по замеру (не отказ). Пустой список — в ориентире."""
    if not m:
        return ["громкость не измерена: в файле нет звуковой дорожки или она беззвучна"]
    out = []
    i, tp = m.get("integrated_lufs"), m.get("true_peak_dbtp")
    if i is None:
        out.append("интегральная громкость не определена (тишина?)")
    elif abs(i - LOUD_TARGET_LUFS) > LOUD_TOL_LU:
        out.append(f"интегральная громкость {i} LUFS, ориентир {LOUD_TARGET_LUFS:.0f} ± {LOUD_TOL_LU:.0f}")
    if tp is not None and tp > LOUD_MAX_TRUE_PEAK:
        out.append(f"истинный пик {tp} dBTP выше {LOUD_MAX_TRUE_PEAK:.0f} dBTP — возможны искажения "
                   "при перекодировании площадкой")
    return out


def window(pdir, args):
    if args.start is not None and args.end is not None:
        return float(args.start), float(args.end)
    grid_path = pdir / "clip-memory" / "song" / "grid.json"
    if not grid_path.exists():
        lib.fail("нет clip-memory/song/grid.json и не заданы --start/--end: окно фрагмента неизвестно")
    try:
        w = lib.hook_window(lib.read_json(grid_path))
    except ValueError as e:
        lib.fail(str(e))
    if not w:
        lib.fail("в grid.json нет окна hook.start/hook.end — это полный клип, а не Suno-hook. "
                 "Окно считает музыковед: начало — пауза перед первым словом припева")
    return w["start"], w["end"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--master", required=True, help="смонтированный ролик 9:16 под окно")
    ap.add_argument("--track", help="трек; по умолчанию song.mp3 проекта")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--fade-from", type=float,
                    help="секунда ТРЕКА, с которой звук затухает к концу окна; не раньше конца последнего слова")
    ap.add_argument("--song-url", default="", help="ссылка на песню в Suno — версия, к которой крепится hook")
    ap.add_argument("--max-mb", type=float, default=9.5,
                    help="потолок копии под загрузку: инструмент Chrome берёт до 10 МБ")
    ap.add_argument("--out-dir", help="по умолчанию output/ проекта")
    ap.add_argument("--force", action="store_true",
                    help="перезаписать паспорт уже опубликованного hook'а (новый hook той же песни)")
    ap.add_argument("--no-cuts-review", default=None, metavar="ПРИЧИНА",
                    help="упаковать без разбора склеек по правилу шести (cut_review.py); причина — в паспорт. "
                         "Законно только у ролика без склеек")
    args = ap.parse_args()

    pdir = lib.project_dir(args.project)
    # Платформа проекта (0.8.37): упаковка — только под Suno. Другая платформа в project.json — предупреждение,
    # а не отказ: решение «для чего» могли поменять, а упаковка — отдельный сознательный запуск.
    pname, _prof, perr = lib.project_platform(pdir)
    if perr:
        lib.fail(f"project.json → platform: {perr}")
    if pname and pname != "suno-hook":
        print(f"[~] в project.json платформа {pname}, а suno_pack упаковывает под Suno-hook: "
              "субтитры и титры здесь не вшиваются, для другой платформы упаковка не нужна")
    cfg = lib.load_config()
    ffmpeg = cfg.get("ffmpeg")
    if not ffmpeg or not Path(ffmpeg).exists():
        lib.fail("ffmpeg из config/paths.json не найден (R22)")

    master = Path(args.master)
    if not master.is_absolute():
        master = pdir / master
    if not master.exists():
        lib.fail(f"нет ролика {master}")
    track = Path(args.track) if args.track else pdir / "song.mp3"
    if not track.exists():
        lib.fail(f"нет трека {track}")

    start, end = window(pdir, args)
    length = end - start
    problems = []
    if length < SUNO_MIN_SEC:
        problems.append(f"окно {length:.2f} с короче {SUNO_MIN_SEC:.0f} с — Suno такой hook не примет")
    if length > SUNO_MAX_SEC:
        problems.append(f"окно {length:.2f} с длиннее {SUNO_MAX_SEC:.0f} с — предел Suno")

    dur, w, h = probe(ffmpeg, master)
    if abs(w / h - ASPECT) > ASPECT_TOL:
        problems.append(f"кадр {w}x{h} — не 9:16; Suno-hook только вертикальный")
    if abs(dur - length) > LENGTH_TOL:
        problems.append(f"ролик {dur:.2f} с, окно трека {length:.2f} с — звук разойдётся с картинкой; "
                        "монтаж обязан длиться ровно окно")
    tdur = _track_len(ffmpeg, track)
    if tdur and end > tdur + 0.05:
        problems.append(f"конец окна {end:.2f} с за концом трека {tdur:.2f} с")
    if args.fade_from is not None and not start < args.fade_from < end:
        problems.append(f"--fade-from {args.fade_from} вне окна {start}–{end}")
    if problems:
        lib.fail("ролик не годится для Suno:\n  · " + "\n  · ".join(problems))

    # Правило шести (0.8.35): склейки монтажа разобраны глазом (cut_review.py --check пишет маркер на
    # sha1 ЭТОГО файла). Монтаж, который никто не разбирал по эмоции, истории и ритму, в Suno не уходит.
    cuts_review = "skipped"
    if args.no_cuts_review:
        print(f"ПРЕДУПРЕЖДЕНИЕ (--no-cuts-review): склейки не разобраны — {args.no_cuts_review}")
        cuts_review = {"skipped": args.no_cuts_review}
    else:
        mk = lib.read_marker(pdir, "cuts-ok.json", 0)
        if not mk or mk.get("video_sha1") != lib.file_sha1(master):
            lib.fail("правило шести: склейки этого монтажа не разобраны. `cut_review.py --project … --video "
                     f"{master.name} --auto` → вердикты по шести критериям → `--check`. Ролик без склеек — "
                     "--no-cuts-review \"причина\".")
        cuts_review = {"cuts": mk.get("cuts"), "cuts_total": mk.get("cuts_total"),
                       "warnings": mk.get("warnings")}

    # Опубликованный hook — история, а не черновик: его паспорт (ссылка, подпись) не затирается.
    record_path = pdir / "publish" / "suno-hook.json"
    if record_path.exists() and not args.force:
        old = lib.read_json(record_path)
        if old.get("url"):
            lib.fail(f"hook уже опубликован ({old['url']}); новый — с --force, старый паспорт "
                     "переименовать в publish/suno-hook-<дата>.json")

    out_dir = Path(args.out_dir) if args.out_dir else pdir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = pdir.name
    full = out_dir / f"{slug}-suno.mp4"
    upload = out_dir / f"{slug}-suno-upload.mp4"

    # Звук — только трек, окно секунда в секунду. Звук модели (Grok пишет свой эмбиент) выбрасывается:
    # в Suno выбирается «Video sound», и это единственный звук ролика.
    af = f"atrim={start}:{end},asetpts=PTS-STARTPTS"
    if args.fade_from is not None:
        af += f",afade=t=out:st={args.fade_from - start:.3f}:d={end - args.fade_from:.3f}"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(master), "-i", str(track),
                    "-filter_complex", f"[1:a]{af}[a]", "-map", "0:v:0", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k",
                    "-t", f"{length:.3f}", "-movflags", "+faststart", str(full)], check=True)

    size_mb = full.stat().st_size / 1e6
    if size_mb > SUNO_MAX_MB:
        lib.fail(f"{full.name} {size_mb:.1f} МБ — больше предела Suno {SUNO_MAX_MB:.0f} МБ")

    # Замер итога — по готовой дорожке (после aac), а не по исходному треку: Suno ставит «Video sound»
    # на звук этого файла. Только предупреждение: мастер сведён автором в Suno, молча менять нельзя.
    loud = measure_loudness(ffmpeg, full)
    loud_warn = loudness_warnings(loud)
    if size_mb <= args.max_mb:
        upload = full
    else:
        # Битрейт под потолок с запасом 8 % на контейнер; картинку и звук не трогаем, только сжатие.
        kbps = int((args.max_mb * 8000 * 0.92) / length) - AUDIO_KBPS
        if kbps < 800:
            lib.fail(f"под {args.max_mb} МБ на {length:.1f} с выходит {kbps} кбит/с видео — "
                     "это уже мыло; загружать полный файл руками")
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(full),
                        "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k",
                        "-maxrate", f"{int(kbps * 1.2)}k", "-bufsize", f"{kbps * 2}k",
                        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
                        str(upload)], check=True)
        if upload.stat().st_size / 1e6 > args.max_mb:
            lib.fail(f"{upload.name} всё ещё больше {args.max_mb} МБ")

    udur, _, _ = probe(ffmpeg, upload)

    # Админ, 14.10.2026: «Первая картинка должна быть именно хоком … когда она на заставке стоит … когда
    # начало стоит плохо, это не работает как хок». После публикации у hook'а правятся только подпись,
    # комментарии и показ текста: кадр и видео не меняются (замерено 14.10.2026), а новый hook начинает
    # с нуля просмотров и лайков. Поэтому первый кадр смотрится ДО загрузки, и файл для этого кладётся рядом.
    first = out_dir / f"{slug}-first-frame.jpg"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(upload),
                    "-frames:v", "1", "-q:v", "2", str(first)], check=True)
    record = {
        "status": "ready",
        "song_url": args.song_url,
        "window": {"start": round(start, 3), "end": round(end, 3), "length": round(length, 3)},
        "suno_select_from_sec": round(start, 2),
        "audio_source": "video",
        "cuts_review": cuts_review,
        "loudness": {**(loud or {}), "target_lufs": LOUD_TARGET_LUFS,
                     "target_true_peak_dbtp": LOUD_MAX_TRUE_PEAK, "warnings": loud_warn,
                     "note": LOUD_NOTE},
        "fade_from": args.fade_from,
        "master": _rel(master, pdir),
        "file": _rel(full, pdir),
        "upload_file": _rel(upload, pdir),
        "upload_mb": round(upload.stat().st_size / 1e6, 2),
        "first_frame": _rel(first, pdir),
        "url": None,
        "caption": None,
    }
    lib.write_json(record_path, record)
    print(f"  окно трека        : {start:.2f}–{end:.2f} с ({length:.2f} с)")
    print(f"  ролик             : {w}x{h}, {dur:.2f} с → {full.name}")
    print(f"  под загрузку      : {upload.name}, {record['upload_mb']} МБ, {udur:.2f} с")
    if loud:
        print(f"  громкость итога   : {loud.get('integrated_lufs')} LUFS, истинный пик "
              f"{loud.get('true_peak_dbtp')} dBTP (ориентир {LOUD_TARGET_LUFS:.0f} LUFS / "
              f"{LOUD_MAX_TRUE_PEAK:.0f} dBTP — {LOUD_NOTE})")
    for w_ in loud_warn:
        print(f"  ПРЕДУПРЕЖДЕНИЕ (громкость): {w_}")
    print(f"  ПЕРВЫЙ КАДР       : {first.name} — открыть и посмотреть ДО загрузки: он же обложка, на нём "
          "должен стоять сам hook (герой, действие, сила), а не общий план или пустое место")
    print("  в Suno            : Audio Controls → Video sound (звук песни выключен)")
    lib.ok("ролик упакован для Suno; паспорт — publish/suno-hook.json (status: ready). "
           "Публикация — только после «да» Админа на подпись")
    return 0


def _rel(path, pdir):
    return (path.relative_to(pdir) if path.is_relative_to(pdir) else path).as_posix()


def _track_len(ffmpeg, track):
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(track)],
                       capture_output=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


if __name__ == "__main__":
    sys.exit(main())
