# ad_assemble.py — сборка рекламного ролика по секундам шот-листа (рекламная ветка, шаг I).
#
# У клипа монтаж ведёт сетка такта (clip-editor). У рекламы сетки нет: порядок и длины планов
# лежат в шот-листе, поле `sec`. Скрипт берёт clips/<src>.mp4 по порядку, подрезает каждый до
# своей длины, склеивает ЖЁСТКИМИ склейками (эффектов-переходов нет — cinema/06) и проверяет
# результат: длительность против суммы `sec`, разрешение, частоту кадров.
#
#   python ad_assemble.py --project <папка> [--audio music.mp3] [--size ШxВ] [--fps 30]
#                         [--out имя]
#
# Размер ролика, если --size не задан: render из project.json (его туда ставит формат паспорта),
# иначе формат паспорта (aspect), иначе 3:4 — 1080x1440. Админ 10.10.2026: «по карточкам … лучше
# три на четыре, … высокие нам точно не нужны». Клип другой пропорции вписывается с обрезкой по
# центру (cover), и скрипт предупреждает, сколько кадра при этом теряется: у товара может уйти край.
#
# Чего скрипт не делает намеренно:
#   - не растягивает короткий исходник: если клипа не хватает на `sec`, это ошибка. Растяжка
#     (zoompan, замедление) множит кадры и ломает длительность — R21;
#   - не накладывает текст, логотип и субтитры: они зависят от площадки, а правила площадок
#     в плагин не вшиты (shared/ads/03-craft.md, «Вертикаль: пять зон кадра»);
#   - не читает аудио с трека: музыка, если нужна, подаётся одним файлом.
#
# Поле `in` у плана (секунды) — с какого места исходного клипа начинать, по умолчанию 0.
#
# Выход: 0 — собрано и сходится; 2 — не собрано или брак. Файл: output/<имя>.mp4.
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib
from gate_assembly import probe, fps_note

DURATION_TOL = 0.25   # секунд: кадров мало, а концы планов округляются до кадра
CROP_WARN = 0.03      # доля кадра, теряемая при вписывании с обрезкой; меньше — на глаз незаметно


def default_size(pdir):
    """Размер ролика без --size: render из project.json, иначе формат паспорта, иначе умолчание
    рекламы. Так сборка не расходится с тем, в каком формате генерировались кадры."""
    try:
        r = lib.read_json(lib.find_project_json(pdir)).get("render") or {}
        w, h = int(r.get("width")), int(r.get("height"))
        if w > 0 and h > 0:
            return w, h
    except (SystemExit, Exception):
        pass
    try:
        passport = lib.read_json(Path(pdir) / "clip-memory" / "product" / "product.json")
    except Exception:
        passport = {}
    return lib.ad_aspect(passport)[1] or lib.AD_ASPECTS[lib.AD_ASPECT_DEFAULT]


def crop_note(sid, name, res, w, h):
    """Предупреждение, если клип другой пропорции: фильтр вписывает кадр с обрезкой по центру, и
    у товара может уйти край. Строка или None."""
    if not res or not res[0] or not res[1]:
        return None
    src, tar = res[0] / res[1], w / h
    lost = 1 - min(src / tar, tar / src)
    if lost <= CROP_WARN:
        return None
    side = "высоты" if src < tar else "ширины"
    return (f"{sid}: клип {name} {res[0]}x{res[1]} вписывается в {w}x{h} с обрезкой по центру — "
            f"теряется {round(lost * 100)}% {side}; проверь, что товар не задет")


def count_frames(ffmpeg, path):
    """Сколько кадров реально в видеопотоке. Длительность контейнера для этого не годится:
    240 кадров при 30 к/с контейнер mp4 после x264 может записать как 7,97 с."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-map", "0:v:0", "-c", "copy",
                        "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    found = re.findall(r"frame=\s*(\d+)", (r.stderr or "").replace("\r", "\n"))
    return int(found[-1]) if found else None


def plan(pdir):
    """Список планов для сборки: (id, путь к клипу, in, sec). Бросает SystemExit при беде."""
    sl_path = Path(pdir) / "clip-memory" / "script" / "shotlist.json"
    if not sl_path.exists():
        lib.fail(f"нет {sl_path}: собирать нечего")
    sl = lib.read_json(sl_path)
    if sl.get("form") != "ad":
        lib.fail(f"form «{sl.get('form')}»: рекламную сборку ведут только шот-листы form=ad "
                 f"(клип собирает clip-editor по сетке такта)")
    shots = [s for s in (sl.get("shots") or []) if s.get("enabled", True)]
    if not shots:
        lib.fail("в шот-листе нет планов")
    out = []
    for s in shots:
        sid = s.get("id") or "?"
        sec = s.get("sec")
        if not isinstance(sec, (int, float)) or isinstance(sec, bool) or sec <= 0:
            lib.fail(f"{sid}: sec «{sec}» — длина плана в секундах, положительное число")
        src = (s.get("src") or sid).strip()
        out.append((sid, Path(pdir) / "clips" / f"{src}.mp4", float(s.get("in") or 0), float(sec)))
    return sl, out


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--audio", default=None, help="музыка или звук одним файлом; без него ролик немой")
    ap.add_argument("--size", default=None,
                    help="ШxВ итогового ролика; без него — render из project.json, иначе формат паспорта (3:4)")
    ap.add_argument("--fps", type=float, default=30.0, help="частота кадров; 24 или 30 (cinema/08)")
    ap.add_argument("--out", default=None, help="имя файла без расширения; по умолчанию <проект>-<формат>")
    args = ap.parse_args()

    cfg = lib.load_config()
    ffmpeg = cfg["ffmpeg"]
    pdir = Path(lib.project_dir(args.project))
    sl, shots = plan(pdir)
    if args.size:
        try:
            w, h = (int(x) for x in args.size.lower().split("x"))
        except Exception:
            lib.fail(f"--size «{args.size}»: нужно ШxВ, например 1080x1440")
    else:
        w, h = default_size(pdir)

    # Исходники на месте и хватает длины — до того, как запускать ffmpeg.
    missing, crop_notes = [], []
    for sid, clip, start, sec in shots:
        if not clip.exists():
            missing.append(f"{sid}: нет клипа {clip.name}")
            continue
        dur, res, _ = probe(ffmpeg, clip)
        if dur is None:
            missing.append(f"{sid}: {clip.name} не читается")
        elif dur + 0.05 < start + sec:
            missing.append(f"{sid}: клип {clip.name} длится {dur:.2f} с, а плану нужны {start:g}+{sec:g} с — "
                           f"не хватает материала; растягивать нельзя (R21), нужен более длинный клип")
        else:
            note = crop_note(sid, clip.name, res, w, h)
            if note:
                crop_notes.append(note)
    if missing:
        for m in missing:
            print("[-] " + m, file=sys.stderr)
        lib.fail("сборка невозможна: исходники не сходятся с шот-листом.")
    for note in crop_notes:
        print("[~] " + note, file=sys.stderr)

    total = sum(sec for _, _, _, sec in shots)
    fmt = sl.get("format") or "ad"
    name = args.out or f"{pdir.name}-{fmt}"
    dest = pdir / "output" / f"{name}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for _, clip, start, sec in shots:
        cmd += ["-ss", f"{start:g}", "-t", f"{sec:g}", "-i", str(clip)]
    audio_idx = None
    if args.audio:
        if not Path(args.audio).exists():
            lib.fail(f"аудио не найдено: {args.audio}")
        audio_idx = len(shots)
        cmd += ["-i", str(args.audio)]
    # scale=cover + crop, а не по одной стороне (R21); fps приводит все планы к одной частоте,
    # иначе concat между источниками разной частоты даёт рывок.
    #
    # Число кадров каждого плана задано ТОЧНО: round(sec × fps). Первая версия резала только
    # по времени (-t) и на сухом прогоне 10.10.2026 теряла по кадру на каждом стыке: 4 плана
    # дали 7,83 с вместо 8 и 30,13 fps вместо 30 — фильтр fps округляет конец сегмента вниз.
    # На 7 планах дрейф ушёл бы за допуск и дал ложный брак. tpad подстраховывает последний
    # кадр клоном, trim отрезает ровно положенное.
    parts = []
    for i, (_, _, _, sec) in enumerate(shots):
        n = max(1, round(sec * args.fps))
        parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                     f"fps={args.fps:g},tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame={n},"
                     f"setsar=1,setpts=PTS-STARTPTS[v{i}]")
    chain = "".join(f"[v{i}]" for i in range(len(shots)))
    parts.append(f"{chain}concat=n={len(shots)}:v=1:a=0[v]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]"]
    if audio_idx is not None:
        cmd += ["-map", f"{audio_idx}:a", "-c:a", "aac", "-t", f"{total:g}"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(dest)]

    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not dest.exists():
        print(r.stderr.strip()[-600:], file=sys.stderr)
        lib.fail("ffmpeg не собрал ролик.")

    vdur, vres, vfps = probe(ffmpeg, dest)
    frames = count_frames(ffmpeg, dest)
    want = sum(max(1, round(sec * args.fps)) for _, _, _, sec in shots)
    print(f"── РЕКЛАМНАЯ СБОРКА · {dest.name} " + "─" * 14)
    print(f"  планов : {len(shots)} · сумма sec {total:g}")
    print(f"  ролик  : {vdur:.2f} с · {vres[0]}x{vres[1]} · {vfps:g} к/с"
          if vdur and vres and vfps else f"  ролик  : {vdur} с")
    print(f"  кадров : {frames} (ждали {want})")
    errors = []
    if vdur is None or abs(vdur - total) > DURATION_TOL:
        errors.append(f"длительность {vdur} с против суммы планов {total:g} с (допуск {DURATION_TOL} с)")
    # Кадры считаются точно: потеря кадра на стыке (первая версия сборки теряла по одному) на
    # длительности почти не видна, а на частоте и ритме — видна.
    if frames is None or abs(frames - want) > 1:
        errors.append(f"кадров {frames} вместо {want}: на стыках планов теряются или множатся кадры")
    if vres and (vres[0] != w or vres[1] != h):
        errors.append(f"разрешение {vres[0]}x{vres[1]}, ожидалось {w}x{h}")
    warn = fps_note(vfps, cfg.get("assembly_fps_ok", [24, 25, 30]))
    if warn:
        print("[~] " + warn, file=sys.stderr)
    if errors:
        for e in errors:
            print("[-] " + e, file=sys.stderr)
        lib.fail("сборка бракована.")
    lib.ok(f"ролик собран: {dest}. Посмотреть целиком и без звука — тест «выключи звук» (cinema/08).")


if __name__ == "__main__":
    main()
