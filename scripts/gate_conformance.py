# gate_conformance.py — ролик обязан быть ТЕМ, что заказано (R14 → код, R31).
#
# Дыра, ради которой написан: приёмка (clip-guardian) смотрела КАЧЕСТВО картинки
# и не сверяла кадр со СЦЕНОЙ. В прогоне Alpha 33 ролика получили
# accept, а на монтажном столе выяснилось, что 23 из 27 источников содержат не ту
# сцену. Деньги уже потрачены, реверс-приём возвращения воды потерян.
#
# Проверяет две вещи:
#   A. МАШИНА — первый кадр clips/<src>.mp4 против входной картинки frames/<src>.png.
#      Съёмка идёт строго image-to-video (clips-bnb.js: attachImage(frames/<id>.png)),
#      значит первый кадр ролика обязан совпадать со своим кадром. Не совпал —
#      мост сохранил чужой файл (лента прошлых генераций, R14) или перепутал имена.
#      Отпечаток: 16x16 полутон → aHash 256 бит → расстояние Хэмминга. Без зависимостей,
#      только ffmpeg (ffprobe на машине нет, R22).
#   B. БУХГАЛТЕРИЯ — у каждого accept в clips/verdicts.json есть scene_ok: true
#      и непустой reason. Вердикт без причины не воспроизводится и не спорится.
#
# Плюс контактный лист: заказанный кадр | первый кадр ролика | середина, подпись —
# id сцены и что заказано. Человек на приёмке видит ПАРУ, а не один ролик.
#
#   python gate_conformance.py --project <папка> [--sheet] [--threshold 12] [--verdicts-optional]
#
# Успех пишет маркер .gates/conformance-ok.json. Провал — exit 2.
import argparse
import io
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

HASH_W = 16          # 16x16 = 256 бит отпечатка
NEAR = 12            # ≤ NEAR — тот же кадр (замер прогона: свои 1..4, чужие 22..129)
FAR_HINT = 25        # выше — точно другая картинка, ниже — смотреть глазами

def _run(cmd, binary=False):
    return subprocess.run(cmd, capture_output=True, text=not binary,
                          encoding=None if binary else "utf-8",
                          errors=None if binary else "replace")

def ahash(ffmpeg, path, seek=None):
    """Отпечаток кадра: 16x16 полутон, порог по среднему. None — кадр не прочитался."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if seek is not None:
        cmd += ["-ss", f"{seek:.3f}"]
    # -map 0:v:0 — тот же поток, что берёт мост (frame-hash.js): у роликов Grok
    # есть второй поток-обложка (R21), и без явного выбора числа могут разойтись.
    cmd += ["-i", str(path), "-map", "0:v:0", "-frames:v", "1",
            "-vf", f"scale={HASH_W}:{HASH_W}:force_original_aspect_ratio=disable,format=gray",
            "-f", "rawvideo", "-"]
    px = _run(cmd, binary=True).stdout
    n = HASH_W * HASH_W
    if not px or len(px) < n:
        return None
    px = list(px[:n])
    mean = sum(px) / n
    return [1 if v > mean else 0 for v in px]

def hamming(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)

def duration(ffmpeg, path):
    import re
    out = _run([ffmpeg, "-hide_banner", "-i", str(path)]).stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None

# ── контактный лист ───────────────────────────────────────────────────────────
FONT = "C:/Windows/Fonts/consola.ttf"

def _esc_path(p):
    """Путь внутри фильтра ffmpeg: двоеточие диска экранируется (грабля Windows, R22)."""
    return str(p).replace("\\", "/").replace(":", "\\:")

def frame_ratio(pdir):
    """Высота/ширина плитки листа — по render проекта: 16/9 у клипа, 4/3 у рекламы 3:4. Нет проекта —
    16/9, как было до рекламной ветки."""
    try:
        r = lib.read_json(lib.find_project_json(pdir)).get("render") or {}
        w, h = int(r.get("width")), int(r.get("height"))
        if w > 0 and h > 0:
            return h / w
    except (SystemExit, Exception):
        pass
    return 16 / 9

def make_pair(ffmpeg, out_jpg, frame_png, mp4, mid_t, caption, tile_w=280, ratio=16 / 9):
    """Строка листа: ЗАКАЗАНО | первый кадр | середина + подпись латиницей (R25)."""
    txt = out_jpg.with_suffix(".txt")
    with io.open(txt, "w", encoding="utf-8", newline="\n") as f:
        f.write(caption)
    band = 92
    inputs, labels = [], ["ORDERED frame", "SHOT t=0.0", f"SHOT t={mid_t:.1f}"]
    if frame_png and Path(frame_png).exists():
        inputs.append(["-i", str(frame_png)])
    else:
        inputs.append(None)
    inputs.append(["-ss", "0", "-i", str(mp4)])
    inputs.append(["-ss", f"{mid_t:.3f}", "-i", str(mp4)])

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    tile_h = int(tile_w * ratio) // 2 * 2   # плитка по формату проекта; кадр и ролик приходят разной высоты
    idx, chains, names = 0, [], []
    for i, inp in enumerate(inputs):
        if inp is None:
            continue
        cmd += inp
        # [N:v:0] обязателен: у роликов Grok есть второй поток-обложка (R21).
        chains.append(f"[{idx}:v:0]scale={tile_w}:{tile_h}:force_original_aspect_ratio=decrease,"
                      f"pad={tile_w}:{tile_h}:(ow-iw)/2:(oh-ih)/2:color=0x141210,"
                      f"drawtext=fontfile='{_esc_path(FONT)}':text='{labels[i]}':"
                      f"x=6:y=6:fontsize=15:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=4"
                      f"[t{idx}]")
        names.append(f"[t{idx}]")
        idx += 1
    fc = ";".join(chains) + ";" + "".join(names) + f"hstack=inputs={len(names)}[row];"
    fc += (f"[row]pad=iw:ih+{band}:0:0:color=0x141210,"
           f"drawtext=fontfile='{_esc_path(FONT)}':textfile='{_esc_path(txt)}':"
           f"x=10:y=h-{band}+10:fontsize=17:fontcolor=0xE8E0D6:line_spacing=6[out]")
    cmd += ["-filter_complex", fc, "-map", "[out]", "-frames:v", "1", "-q:v", "3", str(out_jpg)]
    r = _run(cmd)
    try:
        txt.unlink()
    except Exception:
        pass
    return r.returncode == 0 and out_jpg.exists()

def make_pages(ffmpeg, rows, out_dir, per_page=4):
    """Строки клеятся в страницы: столько, сколько влезает в один экран."""
    pages = []
    for p in range(0, len(rows), per_page):
        chunk = rows[p:p + per_page]
        page = out_dir / f"contact-sheet-{p // per_page + 1:02d}.jpg"
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        for r in chunk:
            cmd += ["-i", str(r)]
        if len(chunk) == 1:
            cmd += ["-frames:v", "1", "-q:v", "3", str(page)]
        else:
            fc = "".join(f"[{i}:v]" for i in range(len(chunk))) + f"vstack=inputs={len(chunk)}[o]"
            cmd += ["-filter_complex", fc, "-map", "[o]", "-frames:v", "1", "-q:v", "3", str(page)]
        if _run(cmd).returncode == 0 and page.exists():
            pages.append(page)
    return pages

# ── гейт ──────────────────────────────────────────────────────────────────────
def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--sheet", action="store_true", help="нарезать контактный лист заказано/снято")
    ap.add_argument("--threshold", type=int, default=None)
    ap.add_argument("--verdicts-optional", action="store_true",
                    help="только машинная сверка: вердикты ещё не проставлены")
    args = ap.parse_args()

    cfg = lib.load_config()
    ffmpeg = cfg["ffmpeg"]
    near = args.threshold if args.threshold is not None else cfg.get("conformance_max_dist", NEAR)

    pdir = lib.project_dir(args.project)
    mem = Path(pdir) / "clip-memory"
    sl_path = mem / "script" / "shotlist.json"
    if not sl_path.exists():
        lib.fail(f"нет {sl_path}: сверять ролик не с чем. Приёмка без шот-листа — это оценка картинки, а не приёмка.")
    sl = lib.read_json(sl_path)
    shots = [s for s in (sl.get("shots") or []) if s.get("enabled", True)]
    sources = sl.get("sources") or {}

    # src → какие кадры сцен на нём стоят
    order = []
    used = {}
    for s in shots:
        src = s.get("src") or s.get("id")
        if src not in used:
            used[src] = []
            order.append(src)
        used[src].append(s)

    clips_dir = Path(pdir) / "clips"
    frames_dir = Path(pdir) / "frames"
    review = clips_dir / "_review"
    ratio = frame_ratio(pdir)
    if args.sheet:
        review.mkdir(parents=True, exist_ok=True)

    # отпечатки всех заказанных кадров — для встречной сверки «а чей это ролик»
    fr_hash = {}
    for src in order:
        png = frames_dir / f"{src}.png"
        if png.exists():
            h = ahash(ffmpeg, png)
            if h:
                fr_hash[src] = h

    report, problems, warnings, rows = [], [], [], []
    print(f"── СВЕРКА СО СЦЕНОЙ · {len(order)} источников " + "─" * 14)

    for src in order:
        mp4 = clips_dir / f"{src}.mp4"
        shot_ids = ",".join(s.get("id", "?") for s in used[src])
        rec = {"src": src, "shots": [s.get("id") for s in used[src]]}
        if not mp4.exists():
            rec["status"] = "no_clip"
            report.append(rec)
            continue

        h0 = ahash(ffmpeg, mp4, 0)
        own = fr_hash.get(src)
        if h0 is None:
            problems.append(f"{src}: первый кадр не читается ffmpeg — ролик битый")
            rec["status"] = "unreadable"
            report.append(rec)
            continue

        if own is None:
            warnings.append(f"{src}: нет frames/{src}.png — машинная сверка невозможна, "
                            f"решает только глаз на контактном листе")
            rec["status"] = "no_reference"
        else:
            d = hamming(h0, own)
            rec["dist"] = d
            if d <= near:
                rec["status"] = "match"
            else:
                best, bd = min(((k, hamming(h0, v)) for k, v in fr_hash.items()), key=lambda x: x[1])
                rec["status"] = "mismatch"
                rec["best_match"] = best
                rec["best_dist"] = bd
                who = (f"это кадр «{best}» (дист {bd}) — мост сохранил ролик под чужим именем"
                       if bd <= near else
                       f"не совпал ни с одним кадром проекта (ближайший {best}, дист {bd}) — "
                       f"чужой ролик из ленты (R14)")
                problems.append(f"{src} [{shot_ids}]: первый кадр не совпал со своим "
                                f"frames/{src}.png (дист {d} > {near}); {who}")

        if args.sheet:
            dur = duration(ffmpeg, mp4) or 10.0
            desc = (sources.get(src) or {}).get("desc") or (used[src][0].get("content") or "")
            head = used[src][0]
            cap = (f"{src}   shots {shot_ids}   {head.get('size','?')} {head.get('angle','?')} "
                   f"{head.get('movement','?')}   water={head.get('water','-')}\n"
                   f"ORDERED: {desc[:110]}\n"
                   f"dist={rec.get('dist','-')} ({rec.get('status')})")
            out_jpg = review / f"{src}.pair.jpg"
            if make_pair(ffmpeg, out_jpg, frames_dir / f"{src}.png", mp4, dur / 2, cap, ratio=ratio):
                rows.append(out_jpg)
        report.append(rec)

    # ── половина Б: вердикты без причины ──────────────────────────────────────
    vpath = lib.verdicts_path(pdir)
    accepts = 0
    if not args.verdicts_optional:
        if not vpath.exists():
            problems.append(f"нет {vpath}: приёмка не проходила (R17 — вердикт ставится через панель)")
        else:
            try:
                verdicts = lib.read_json(vpath)
            except Exception as e:
                verdicts = []
                problems.append(f"{vpath} не читается: {e}")
            for v in verdicts:
                if v.get("verdict") != "accept":
                    continue
                accepts += 1
                name = v.get("clip", "?")
                if v.get("scene_ok") is not True:
                    problems.append(f"{name}: accept без сверки со сценой "
                                    f"(нет scene_ok: true) — приёмка оценила картинку, не кадр")
                if not (v.get("reason") or "").strip():
                    problems.append(f"{name}: accept без причины (пустой reason) — "
                                    f"вердикт без причины нельзя ни проверить, ни оспорить")

    if args.sheet and rows:
        pages = make_pages(ffmpeg, rows, review)
        for p in pages:
            print(f"  лист : {p}")
        print("  ↑ смотреть глазами: слева заказано, справа снято. Это и есть приёмка сцены.")

    lib.write_json(mem / "reports" / "conformance.json",
                   {"gate": "conformance", "near": near, "sources": report})

    ok_n = sum(1 for r in report if r.get("status") == "match")
    print(f"  сошлось: {ok_n} из {len(order)} · accept в вердиктах: {accepts}")
    for w in warnings:
        print("[~] " + w)

    if problems:
        print("\nГЕЙТ СВЕРКИ СО СЦЕНОЙ не пройден. Монтаж не начинается:", file=sys.stderr)
        for p in problems:
            print("  · " + p, file=sys.stderr)
        print("\nЧинить материал, не скрипт: пересъёмка точечно через новый предполёт (R09),\n"
              "или переименование, если ролик просто лёг под чужим именем.", file=sys.stderr)
        raise SystemExit(2)

    lib.write_marker(pdir, "conformance-ok.json",
                     {"gate": "conformance", "sources": len(order), "accepts": accepts})
    lib.ok(f"каждый ролик — та сцена, что заказана ({ok_n}/{len(order)}), "
           f"у каждого accept есть причина. Монтаж разрешён.")

if __name__ == "__main__":
    main()
