# gate_research.py — сценарист не начинает, пока нет фактуры и сетки такта.
#
# Правило, которое этот гейт исполняет: клип не придумывается из воздуха.
# Сначала тема изучена (досье, жанр, факт-банк), трек измерен (сетка долей и разделы),
# и только потом пишется сценарий. Иначе сценарий сочиняет факты, а монтаж не сходится
# с музыкой — и то и другое всплывает после того, как за генерацию заплачено.
#
#   python gate_research.py --project <папка>
#
# Успех пишет маркер .gates/research-ok.json. Провал — exit 2.
import argparse
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

# Заглушки: текст, который выглядит как работа, но работой не является.
STUB_RE = re.compile(
    r"\bTODO\b|\bFIXME\b|lorem ipsum|placeholder|заглушк|в разработке|"
    r"уточнить позже|доработать позже|нужно исследовать|будет позже|дописать",
    re.IGNORECASE,
)

# Минимальный объём: файл короче — это оглавление, а не результат.
MIN_CHARS = {
    "dossier.md": 800,
    "genre-map.md": 500,
    "references.md": 400,
    "fact-bank.md": 200,
}

def read_text(p):
    with io.open(str(p), "r", encoding="utf-8-sig") as f:
        return f.read()

def check_research(mem, problems):
    rdir = mem / "research"
    for name, min_len in MIN_CHARS.items():
        p = rdir / name
        if not p.exists():
            problems.append(f"нет файла research/{name} — ресёрч не сделан")
            continue
        text = read_text(p)
        body = re.sub(r"^\s*#.*$", "", text, flags=re.MULTILINE).strip()
        if len(body) < min_len:
            problems.append(
                f"research/{name}: {len(body)} значимых символов при минимуме {min_len} — "
                f"это набросок, а не фактура"
            )
        for m in STUB_RE.finditer(text):
            problems.append(f"research/{name}: заглушка «{m.group(0)}» — незавершённое выдаётся за готовое")
            break

def check_grid(mem, problems):
    p = mem / "song" / "grid.json"
    if not p.exists():
        problems.append("нет song/grid.json — трек не измерен, монтаж будет не по такту (R20)")
        return
    try:
        grid = lib.read_json(p)
    except Exception as e:
        problems.append(f"song/grid.json не читается: {e}")
        return

    duration = float(grid.get("duration") or 0)
    bpm = float(grid.get("bpm") or 0)
    beat = float(grid.get("beat") or 0)
    sections = grid.get("sections") or []

    if duration <= 0:
        problems.append("grid.json: duration не задан")
    if bpm <= 0:
        problems.append("grid.json: bpm не задан — заявленному BPM верить нельзя, он измеряется")
    if beat <= 0:
        problems.append("grid.json: beat не задан (beat = 60 / bpm)")
    elif bpm > 0 and abs(beat - 60.0 / bpm) > 0.01:
        problems.append(f"grid.json: beat {beat} не сходится с bpm {bpm} (ожидалось {60.0 / bpm:.4f})")
    if "first_beat" not in grid:
        problems.append("grid.json: нет first_beat — без фазы сетка уедет на весь клип")
    if not sections:
        problems.append("grid.json: разделы не размечены — сценаристу не на что класть арку")
        return

    # Разделы должны покрывать трек без дыр и нахлёстов: по ним строится вся драматургия.
    prev_end = None
    for i, s in enumerate(sections):
        name = s.get("name") or f"#{i}"
        start, end = s.get("start"), s.get("end")
        if start is None or end is None:
            problems.append(f"grid.json: раздел {name} без start/end")
            continue
        if end <= start:
            problems.append(f"grid.json: раздел {name}: end <= start")
        if prev_end is not None and abs(float(start) - prev_end) > 0.5:
            gap = float(start) - prev_end
            kind = "дыра" if gap > 0 else "нахлёст"
            problems.append(f"grid.json: {kind} {abs(gap):.2f} с перед разделом {name}")
        prev_end = float(end)
    if duration > 0 and prev_end is not None and abs(duration - prev_end) > 1.0:
        problems.append(
            f"grid.json: разделы кончаются на {prev_end:.2f} с при длительности {duration:.2f} с"
        )

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    pdir = lib.project_dir(args.project)
    mem = Path(pdir) / "clip-memory"
    if not mem.exists():
        lib.fail(f"нет папки clip-memory в {pdir}. Память проекта не создана (shared/memory-protocol.md).")

    problems = []
    check_research(mem, problems)
    check_grid(mem, problems)

    if problems:
        print("ГЕЙТ РЕСЁРЧА не пройден. Сценарист не запускается:", file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        print("\nЧинить ДАННЫЕ (ресёрч и разбор трека), не скрипт.", file=sys.stderr)
        raise SystemExit(2)

    lib.write_marker(pdir, "research-ok.json", {"gate": "research"})
    lib.ok("ресёрч и сетка такта на месте — сценарист может начинать.")

if __name__ == "__main__":
    main()
