# gate_slideshow.py — риск «слайдшоу» в шот-листе: ПРЕДУПРЕЖДЕНИЕ, не блок.
#
# Зачем. gate_density считает плотность планов и однообразие якорей, но не спрашивает, стоит ли кадр:
# камера в статике, одна и та же крупность три раза подряд, один источник растянут на пол-ролика —
# зритель видит набор картинок, а не кино. Идея метрики взята из разбора OpenMontage (18.10.2026,
# `_research/video-tools-2026-10-18/04-openmontage.md`: у них «слайдшоу-риск» судит рендер); код и
# оси здесь свои, под наш шот-лист.
#
# Оговорка. Статичная камера — законный выбор: `shared/cinema/10-physics-in-motion.md` советует
# locked-off, когда двигается сам предмет. Шот-лист не видит, двигается ли предмет, поэтому гейт
# только предупреждает, а пороги ниже — ориентир, не наш замер (R23).
#
#   python gate_slideshow.py --project <папка> [--shotlist путь]
#
# Читает clip-memory/script/shotlist.json (клип, hook и реклама), считает длины планов по долям
# (grid.json) или по секундам (`sec`), пишет clip-memory/reports/slideshow-risk.json. Выход всегда 0,
# если шот-лист читается; 2 — только когда читать нечего.
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

# Ориентиры (не измерены нами). Доля статики по времени — выше этого уже подозрительно.
STATIC_SHARE_WARN = 0.7
# Подряд идущие планы со статичной камерой, секунды суммарно. Длинная неподвижность — слайд.
STATIC_RUN_SEC = 12.0
# Столько одинаковых крупностей подряд — повтор, глаз не получает новой информации.
SIZE_RUN = 3
# Одна крупность занимает больше этой доли планов (при не менее MIN_FOR_MIX планах).
SIZE_DOMINANCE = 0.6
MIN_FOR_MIX = 5
# Один источник (одна генерация) под столькими планами — это одна картинка, нарезанная на куски.
SRC_REUSE = 3
# Дольше этого один план читается как стоп-кадр (потолок генерации см. gate_density.MAX_SHOT_SEC).
LONG_SHOT_SEC = 8.0

VERDICTS = [(3, "высокий"), (1, "средний"), (0, "низкий")]


def shot_seconds(shot, beat):
    """Длина плана в секундах: `sec` (реклама) или `beats` × доля (клип); иначе None."""
    if shot.get("sec") is not None:
        try:
            return float(shot["sec"])
        except (TypeError, ValueError):
            return None
    if shot.get("beats") and beat:
        try:
            return float(shot["beats"]) * float(beat)
        except (TypeError, ValueError):
            return None
    return None


def analyze(shots, beat=None):
    """Разбор списка планов → {risk, verdict, flags[], metrics{}}. Чистая функция, без файлов."""
    shots = [s for s in shots if s.get("enabled", True)]
    n = len(shots)
    out = {"shots": n, "flags": [], "metrics": {}}
    if not n:
        out.update(risk=0, verdict="нечего судить")
        return out
    secs = [shot_seconds(s, beat) for s in shots]
    timed = all(x is not None for x in secs)
    weights = secs if timed else [1.0] * n
    total = sum(weights) or 1.0
    moves = [(s.get("movement") or "").strip() for s in shots]
    sizes = [(s.get("size") or "").strip() for s in shots]

    static_share = sum(w for w, m in zip(weights, moves) if m == "static") / total
    out["metrics"]["static_share"] = round(static_share, 2)
    out["metrics"]["timed"] = timed
    risk = 0

    def flag(code, text, points=1):
        nonlocal risk
        risk += points
        out["flags"].append({"code": code, "text": text, "points": points})

    if n >= 3 and static_share > STATIC_SHARE_WARN:
        flag("static_share", f"{static_share * 100:.0f}% времени камера неподвижна "
             f"(ориентир не выше {STATIC_SHARE_WARN * 100:.0f}%) — если предмет в кадре тоже стоит, "
             "это слайд; если он движется, статика законна (cinema/10)")

    run = best = 0.0
    run_ids, best_ids = [], []
    for w, m, s in zip(weights, moves, shots):
        if m == "static":
            run += w
            run_ids.append(s.get("id") or "?")
            if run > best:
                best, best_ids = run, list(run_ids)
        else:
            run, run_ids = 0.0, []
    out["metrics"]["longest_static_run"] = round(best, 1)
    if timed and best > STATIC_RUN_SEC:
        flag("static_run", f"{best:.1f} с подряд без движения камеры ({best_ids[0]}–{best_ids[-1]}), "
             f"ориентир не больше {STATIC_RUN_SEC:.0f} с")

    streak, cur = 1, 1
    for a, b in zip(sizes, sizes[1:]):
        cur = cur + 1 if a and a == b else 1
        streak = max(streak, cur)
    out["metrics"]["size_run"] = streak
    if streak >= SIZE_RUN:
        flag("size_run", f"одна крупность {streak} планов подряд (ориентир не больше {SIZE_RUN - 1})")

    cnt = Counter(x for x in sizes if x)
    if cnt and n >= MIN_FOR_MIX:
        top, k = cnt.most_common(1)[0]
        out["metrics"]["size_top_share"] = round(k / n, 2)
        if k / n > SIZE_DOMINANCE:
            flag("size_dominance", f"крупность {top} занимает {k / n * 100:.0f}% планов "
                 f"(ориентир не больше {SIZE_DOMINANCE * 100:.0f}%)")

    srcs = Counter(s.get("src") for s in shots if s.get("src"))
    if srcs:
        src, k = srcs.most_common(1)[0]
        out["metrics"]["src_max_shots"] = k
        if k > SRC_REUSE:
            flag("src_reuse", f"источник {src} лежит под {k} планами (ориентир не больше {SRC_REUSE}): "
                 "одна генерация, нарезанная на куски, читается как слайд")

    if timed:
        long_ids = [s.get("id") or "?" for s, x in zip(shots, secs) if x > LONG_SHOT_SEC]
        out["metrics"]["avg_shot_sec"] = round(sum(secs) / n, 2)
        if long_ids:
            flag("long_shot", f"планы длиннее {LONG_SHOT_SEC:.0f} с: {', '.join(long_ids)} — "
                 "за такое время без события кадр застывает", 1)
    else:
        out["metrics"]["note"] = "длины планов неизвестны (нет grid.json / sec) — доли считаны по числу планов"

    verdict = next(name for limit, name in VERDICTS if risk >= limit)
    out.update(risk=risk, verdict=verdict)
    return out


def load_beat(pdir):
    grid = Path(pdir) / "clip-memory" / "song" / "grid.json"
    if grid.exists():
        try:
            return float(lib.read_json(grid).get("beat") or 0) or None
        except Exception:
            return None
    return None


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--shotlist", help="по умолчанию clip-memory/script/shotlist.json")
    a = ap.parse_args()
    pdir = lib.project_dir(a.project)
    path = Path(a.shotlist) if a.shotlist else pdir / "clip-memory" / "script" / "shotlist.json"
    if not path.exists():
        lib.fail(f"нет шот-листа {path}: судить слайдшоу-риск нечего")
    data = lib.read_json(path)
    shots = data.get("shots") or data.get("shotlist") or []
    res = analyze(shots, load_beat(pdir))
    lib.write_json(pdir / "clip-memory" / "reports" / "slideshow-risk.json", res)
    print(f"  слайдшоу-риск: {res['verdict']} ({res['risk']}), планов {res['shots']}; "
          f"доля статики {res['metrics'].get('static_share')}")
    for f in res["flags"]:
        print(f"  [~] {f['text']}", file=sys.stderr)
    if res["flags"]:
        print("  Это предупреждение, не блок: правит раскадровка (больше смены крупности, движения, "
              "источников) или Админ принимает осознанно.", file=sys.stderr)
    lib.ok("слайдшоу-риск посчитан; отчёт — clip-memory/reports/slideshow-risk.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
