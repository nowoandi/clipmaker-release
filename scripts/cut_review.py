# cut_review.py — правило шести (Уолтер Марч) по каждой склейке готового монтажа.
#
# Зачем. Админ, 14.10.2026: «есть критерии, шесть критериев монтажа … какой-то очень известный монтажёр
# написал, изучи их, и нам тоже нужно их интегрировать». Правило шести у нас было записано
# (shared/cinema/06) и стояло только у приёмщика роликов. Монтаж же до сих пор проверялся на длину и
# лист кадров (gate_assembly) — склейки не разбирал никто. Здесь правило превращено в разбор каждой
# склейки: сначала измеряется то, что измеряется (ритм, перескок взгляда, скачок яркости), потом
# глаз выносит вердикт по шести критериям, и скрипт проверяет порядок приоритета.
#
#   python cut_review.py --project <клип> --video <монтаж.mp4> [--cuts 4.6,9.2 | --auto]
#                        [--window-start 60.637] [--top 12]           → шаблон разбора + лист кадров
#   python cut_review.py --project <клип> --video <монтаж.mp4> --check                → проверка разбора
#
# Шесть критериев в порядке приоритета (вес Марча — ориентир, а не закон):
#   emotion 51 · story 23 · rhythm 10 · eye_trace 7 · plane 5 · space 4
# Жертвовать можно только снизу вверх: если выше стоящий критерий принесён в жертву, ВСЕ нижние
# тоже обязаны быть принесены в жертву (иначе пожертвовали большим ради меньшего). У каждого
# принесённого в жертву — причина словами.
#
# Сказано честно: измеряются только три сигнала из шести (ритм по сетке и словам, перескок взгляда
# по яркому центру кадра, скачок яркости). Эмоцию, историю, плоскость и пространство оценивает глаз.
# Выход: 0 — шаблон записан / разбор верен; 2 — разбор неполон или нарушен порядок.
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

lib.setup_io()

# (ключ, русское имя, вес Марча %, вопрос к склейке)
CRITERIA = [
    ("emotion", "эмоция", 51, "склейка сохраняет или усиливает то, что зритель должен чувствовать в этой строке?"),
    ("story", "история", 23, "склейка даёт новую информацию, двигает рассказ?"),
    ("rhythm", "ритм", 10, "склейка стоит там, где её ждёт музыка: на доле, в паузе между словами?"),
    ("eye_trace", "взгляд", 7, "куда смотрел глаз до склейки и куда он попадает после — искать главное не надо?"),
    ("plane", "плоскость", 5, "положение главного по экрану и направление движения держатся (не перескочили ось)?"),
    ("space", "пространство", 4, "понятно, где кто находится, свет и предметы на месте?"),
]
KEYS = [c[0] for c in CRITERIA]

# Пороги подсказок. Это сигналы для глаза, а не вердикты: решает человек.
BEAT_FRACTION_OFF = 0.20       # склейка дальше 20% доли от ближайшей доли — «мимо доли»
EYE_JUMP_PCT = 35.0            # яркий центр прыгнул больше чем на 35% диагонали кадра
LUMA_JUMP = 25.0               # средняя яркость сменилась больше чем на 25 из 255
SIDE_FLIP_PCT = 12.0           # центр перешёл через середину кадра с заметным зазором


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe_like(ffmpeg, video):
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video)], capture_output=True,
                       encoding="utf-8", errors="replace")
    out = r.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    f = re.search(r"(\d+(?:\.\d+)?) fps", out)
    return dur, float(f.group(1)) if f else 24.0


def detect_cuts(ffmpeg, video, thr=0.35):
    """Склейки по смене сцены ffmpeg (select='gt(scene,thr)'); подходит для жёстких склеек клипа."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video), "-vf", f"select='gt(scene,{thr})',showinfo",
                        "-an", "-f", "null", "-"], capture_output=True, encoding="utf-8", errors="replace")
    return [round(float(x), 3) for x in re.findall(r"pts_time:([0-9.]+)", r.stderr or "")]


def grab(ffmpeg, video, t, out_png, size="108x192"):
    t = max(0.0, t)
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video),
                    "-frames:v", "1", "-s", size, str(out_png)], check=True)


def frame_stats(png):
    """Яркий центр кадра (центроид верхних 6% по яркости), средняя яркость. numpy/PIL — как в соседних скриптах."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(png).convert("L"), dtype=np.float32)
    h, w = a.shape
    thr = np.percentile(a, 94)
    ys, xs = np.nonzero(a >= thr)
    if len(xs) == 0:
        return {"cx": 50.0, "cy": 50.0, "luma": float(a.mean())}
    return {"cx": float(xs.mean()) / w * 100, "cy": float(ys.mean()) / h * 100, "luma": float(a.mean())}


def rhythm_info(cut_track, beats, words):
    """Расстояние до ближайшей доли и положение относительно слов (внутри слова — слабая склейка)."""
    info = {}
    if beats:
        nb = min(beats, key=lambda b: abs(b - cut_track))
        i = beats.index(nb)
        gap = (beats[i + 1] - nb) if i + 1 < len(beats) else (nb - beats[i - 1] if i else 0.57)
        info.update(nearest_beat=round(nb, 3), beat_offset_s=round(cut_track - nb, 3),
                    beat_offset_fraction=round(abs(cut_track - nb) / gap, 2) if gap else None)
    if words:
        inside = [w for w in words if w["start"] + 0.05 < cut_track < w["end"] - 0.05]
        info["inside_word"] = inside[0]["word"] if inside else None
        # шаг от конца ближайшего слова: склейка в паузе — хорошо
        prev = [w for w in words if w["end"] <= cut_track]
        nxt = [w for w in words if w["start"] >= cut_track]
        if prev and nxt:
            info["pause_s"] = round(max(0.0, nxt[0]["start"] - prev[-1]["end"]), 2)
    return info


def measure(ffmpeg, video, cuts, fps, window_start, beats, words, sheet_dir):
    import numpy as np
    from PIL import Image
    res = []
    rows = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for i, t in enumerate(cuts, 1):
            one = 1.0 / fps
            before, after = max(0.0, t - one), t + one
            pb, pa = td / f"b{i}.png", td / f"a{i}.png"
            grab(ffmpeg, video, before, pb)
            grab(ffmpeg, video, after, pa)
            sb, sa = frame_stats(pb), frame_stats(pa)
            diag = (100 ** 2 + 100 ** 2) ** 0.5
            jump = ((sa["cx"] - sb["cx"]) ** 2 + (sa["cy"] - sb["cy"]) ** 2) ** 0.5 / diag * 100
            flip = (sb["cx"] - 50) * (sa["cx"] - 50) < 0 and abs(sb["cx"] - 50) > SIDE_FLIP_PCT / 2 \
                and abs(sa["cx"] - 50) > SIDE_FLIP_PCT / 2
            hints = []
            r = rhythm_info(window_start + t, beats, words) if (beats or words) else {}
            if r.get("beat_offset_fraction") is not None and r["beat_offset_fraction"] > BEAT_FRACTION_OFF:
                hints.append(f"ритм: склейка в {r['beat_offset_s']:+.2f} с от ближайшей доли ({int(r['beat_offset_fraction'] * 100)}% доли)")
            if r.get("inside_word"):
                hints.append(f"ритм: склейка внутри слова «{r['inside_word']}»")
            if jump > EYE_JUMP_PCT:
                hints.append(f"взгляд: яркий центр кадра прыгнул на {jump:.0f}% диагонали")
            if flip:
                hints.append("плоскость: яркий центр перешёл с одной стороны кадра на другую")
            dl = sa["luma"] - sb["luma"]
            if abs(dl) > LUMA_JUMP:
                hints.append(f"взгляд/пространство: яркость {'выросла' if dl > 0 else 'упала'} на {abs(dl):.0f} из 255")
            # листовой ряд: -0.5, -0.25, до, после, +0.25, +0.5
            strip = []
            for dt in (-0.5, -0.25, -one, one, 0.25, 0.5):
                p = td / f"s{i}_{dt:+.2f}.png"
                grab(ffmpeg, video, max(0.0, t + dt), p, size="144x256")
                strip.append(Image.open(p).convert("RGB"))
            row = Image.new("RGB", (144 * 6 + 5 * 4, 256), (0, 0, 0))
            for k, im in enumerate(strip):
                row.paste(im, (k * 148, 0))
            rows.append(row)
            res.append({
                "n": i, "t": round(t, 3), "track_time": round(window_start + t, 3),
                "rhythm": r,
                "eye": {"before": {"cx": round(sb["cx"], 1), "cy": round(sb["cy"], 1)},
                        "after": {"cx": round(sa["cx"], 1), "cy": round(sa["cy"], 1)},
                        "jump_pct_diag": round(jump, 1), "side_flip": bool(flip)},
                "luma": {"before": round(sb["luma"], 1), "after": round(sa["luma"], 1)},
                "hints": hints,
                "risk": len(hints),
            })
        if rows and sheet_dir:
            Path(sheet_dir).mkdir(parents=True, exist_ok=True)
            sheet = Image.new("RGB", (rows[0].width, rows[0].height * len(rows) + 4 * (len(rows) - 1)), (20, 20, 20))
            for k, rw in enumerate(rows):
                sheet.paste(rw, (0, k * (rw.height + 4)))
            sheet.save(Path(sheet_dir) / "cuts-sheet.jpg", quality=88)
    return res


def template(pdir, video, cuts_measured, window_start, top):
    chosen = cuts_measured
    if top and len(cuts_measured) > top:
        chosen = sorted(cuts_measured, key=lambda c: (-c["risk"], c["n"]))[:top]
        chosen.sort(key=lambda c: c["n"])
    cuts = []
    for c in chosen:
        c = dict(c)
        c["criteria"] = {k: {"state": None, "note": ""} for k in KEYS}   # kept | sacrificed
        cuts.append(c)
    return {
        "reviewer": "clip-editor / clip-guardian",
        "video": str(video), "video_sha1": sha1(video), "window_start": window_start,
        "note_ru": "state у каждого критерия: kept | sacrificed; sacrificed — только с note. Жертвовать — снизу вверх: "
                   "если принесён в жертву критерий выше, все ниже тоже. Порядок: " + " > ".join(k for k in KEYS),
        "cuts_total": len(cuts_measured), "cuts_in_review": len(cuts),
        "cuts": cuts,
    }


def check(pdir, video):
    path = Path(pdir) / "clip-memory" / "reports" / "cuts-review.json"
    if not path.exists():
        lib.fail(f"нет разбора склеек {path}: сначала `cut_review.py --video …` (шаблон), потом глаз.")
    data = lib.read_json(path)
    problems, warns = [], []
    if data.get("video_sha1") != sha1(video):
        problems.append("разбор относится к другому файлу монтажа — монтаж пересобран, разбор заново")
    cuts = data.get("cuts") or []
    if not cuts:
        problems.append("в разборе нет склеек")
    for c in cuts:
        n = c.get("n")
        cr = c.get("criteria") or {}
        miss = [k for k in KEYS if (cr.get(k) or {}).get("state") not in ("kept", "sacrificed")]
        if miss:
            problems.append(f"склейка {n}: нет вердикта по {', '.join(miss)} (kept | sacrificed)")
            continue
        sac = [k for k in KEYS if cr[k]["state"] == "sacrificed"]
        for k in sac:
            if not str(cr[k].get("note") or "").strip():
                problems.append(f"склейка {n}: {k} принесён в жертву без причины")
        # порядок: если принесён критерий k, все ниже тоже обязаны быть принесены
        for k in sac:
            idx = KEYS.index(k)
            kept_lower = [x for x in KEYS[idx + 1:] if cr[x]["state"] == "kept"]
            if kept_lower:
                problems.append(f"склейка {n}: принесён в жертву {k}, а нижние сохранены ({', '.join(kept_lower)}) — "
                                "пожертвовали большим ради меньшего; жертвуют снизу вверх")
        # метрика против вердикта — предупреждение
        for h in c.get("hints") or []:
            if h.startswith("ритм") and cr["rhythm"]["state"] == "kept":
                warns.append(f"склейка {n}: замер говорит «{h}», а ритм отмечен kept — проверь по листу")
            if h.startswith("взгляд:") and cr["eye_trace"]["state"] == "kept":
                warns.append(f"склейка {n}: замер говорит «{h}», а взгляд отмечен kept — проверь по листу")
    for w in warns:
        print("[~] " + w)
    if problems:
        lib.fail("разбор склеек не принят:\n  · " + "\n  · ".join(problems))
    lib.write_marker(pdir, "cuts-ok.json", {"video_sha1": data["video_sha1"], "cuts": len(cuts),
                                            "cuts_total": data.get("cuts_total"), "warnings": len(warns)})
    lib.ok(f"склейки разобраны: {len(cuts)} из {data.get('cuts_total')}, порядок приоритета соблюдён, "
           f"предупреждений замера {len(warns)}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--video", required=True)
    ap.add_argument("--cuts", help="секунды склеек в монтаже через запятую")
    ap.add_argument("--auto", action="store_true", help="найти склейки по смене сцены")
    ap.add_argument("--thr", type=float, default=0.35,
                    help="порог смены сцены для --auto; мягкие склейки между похожими кадрами — 0.15–0.25")
    ap.add_argument("--window-start", type=float, help="секунда ТРЕКА, с которой начинается монтаж; "
                    "по умолчанию grid.json → hook.start, иначе 0")
    ap.add_argument("--top", type=int, default=0, help="в разбор взять N самых рискованных склеек (для длинных клипов)")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    pdir = lib.project_dir(args.project)
    video = Path(args.video)
    if not video.is_absolute():
        video = pdir / video
    if not video.exists():
        lib.fail(f"нет файла {video}")
    if args.check:
        return check(pdir, video)

    cfg = lib.load_config()
    ffmpeg = cfg.get("ffmpeg")
    if not ffmpeg or not Path(ffmpeg).exists():
        lib.fail("ffmpeg из config/paths.json не найден (R22)")
    dur, fps = ffprobe_like(ffmpeg, video)
    if args.cuts:
        cuts = [float(x) for x in args.cuts.split(",") if x.strip()]
    elif args.auto:
        cuts = detect_cuts(ffmpeg, video, args.thr)
    else:
        lib.fail("укажи склейки: --cuts 4.6,9.2 или --auto")
    cuts = [c for c in cuts if 0.2 < c < dur - 0.2]
    if not cuts:
        lib.fail("склеек не найдено (внутри ролика, не у самых краёв)")

    beats, words, ws = [], [], args.window_start
    grid_path = pdir / "clip-memory" / "song" / "grid.json"
    if grid_path.exists():
        grid = lib.read_json(grid_path)
        beats = grid.get("beats") or []
        if ws is None:
            try:
                w = lib.hook_window(grid)
                ws = w["start"] if w else 0.0
            except ValueError:
                ws = 0.0
    words_path = pdir / "clip-memory" / "song" / "words.json"
    if words_path.exists():
        wj = lib.read_json(words_path)
        words = [{"word": x["word"], "start": float(x["start"]), "end": float(x["end"])}
                 for x in (wj.get("words") if isinstance(wj, dict) else wj) or []
                 if x.get("start") is not None and x.get("end") is not None]
    ws = ws or 0.0

    measured = measure(ffmpeg, video, cuts, fps, ws, beats, words, pdir / "output" / "cuts")
    tpl = template(pdir, video, measured, ws, args.top)
    out = pdir / "clip-memory" / "reports" / "cuts-review.json"
    if out.exists():
        old = lib.read_json(out)
        if old.get("video_sha1") == tpl["video_sha1"] and any(
                (c.get("criteria") or {}).get("emotion", {}).get("state") for c in old.get("cuts") or []):
            lib.fail(f"{out} уже заполнен для этого файла монтажа; перезапись затёрла бы разбор. "
                     "Переименуй его, если нужно начать заново.")
    lib.write_json(out, tpl)

    print(f"  монтаж             : {video.name}, {dur:.2f} с, {fps:g} к/с; склеек {len(measured)}, в разборе {len(tpl['cuts'])}")
    print(f"  окно трека         : с {ws:.2f} с (сетка долей: {len(beats)}, слов: {len(words)})")
    for c in measured:
        mark = "  !" if c["hints"] else "   "
        print(f"{mark} склейка {c['n']:>2} · {c['t']:>6.2f} с · доля {c['rhythm'].get('beat_offset_s', '—'):>6}"
              f" · взгляд {c['eye']['jump_pct_diag']:>4.0f}% · яркость {c['luma']['before']:.0f}→{c['luma']['after']:.0f}")
        for h in c["hints"]:
            print(f"        · {h}")
    print(f"  лист кадров        : {pdir / 'output' / 'cuts' / 'cuts-sheet.jpg'} (−0,5 −0,25 до | после +0,25 +0,5 с)")
    lib.ok(f"шаблон разбора записан: {out}. Заполнить глазом по листу и пройти `--check`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
