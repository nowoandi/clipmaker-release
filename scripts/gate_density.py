# gate_density.py — визуал обязан соответствовать энергии трека.
#
# Этот гейт написан по цене провала. Клип «Alpha» (11.08.2026):
# музыкальный аналитик сдал 129.44 BPM, дропы, хуки и карту энергии — материал под движение.
# Сценарист выбрал форму «концепт»: одна локация в разных состояниях света. Художник свёл мир
# к 4 якорям. Оператор запретил все быстрые движения камеры. Раскадровка собрала 27 генераций
# перестановкой тех же 4 объектов. Итог, дословный вердикт Админа: «всё ради четырёх кадров»,
# «одно и то же зациклилось», «выбирать было нечего», «лучше бы я всё руками делал».
#
# Ни один гейт этого не поймал: gate_script считает доли и длину, но не спрашивает,
# ХВАТАЕТ ЛИ РАЗЛИЧИМОГО МАТЕРИАЛА на такую музыку. Два документа — карта энергии
# и канон — лежали рядом и никем не сводились.
#
# Что проверяется:
#   1. различимые установки (якоря/локации) против темпа и числа разделов;
#   2. словарь движения камеры: есть ли вообще динамика при энергичном треке;
#   3. средняя длина плана против доли: не тянутся ли планы вопреки музыке;
#   4. однообразие: доля планов на самом частом якоре.
#
# Гейт стоит МЕЖДУ каноном и раскадровкой — там, где переделка ещё бесплатна. Без шот-листа
# он судит только установки и маркер не пишет; маркер — от прогона по шот-листу.
# Формат hook (grid.json → hook.start/end): норма считается на окно, а не на весь трек.
#
#   python gate_density.py --project <папка>
#
# Успех пишет маркер .gates/density-ok.json. Провал — exit 2.
#
# Осознанно принять разреженный визуал (медленная баллада, намеренная аскеза):
#   python gate_density.py --project <папка> --sparse-ok "<причина словами>"
# Причина уходит в маркер и в отчёт — молча обойти нельзя.
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

# Быстрые приёмы камеры: если их нет вовсе, картинка стоит.
#
# СЛОВАРЬ ОДИН НА ДВА ГЕЙТА — берётся из gate_script, который держит контракт шот-листа.
# До 15.08.2026 здесь стоял свой набор с `whip` и `pull_out_fast`, которых в контракте нет:
# раскадровка была обязана писать значение из ПЕРЕСЕЧЕНИЯ двух словарей, потому что
# `whip` и `pull_out_fast` роняли шот-лист на gate_script, а его собственные значения
# не считались динамикой здесь. Два словаря на один файл — это не защита, а работа руками.
import gate_script as _script

DYNAMIC_MOVES = {"push_in_fast", "tracking", "pan", "tilt", "handheld"} & _script.MOVES

# Порог «танцевального» темпа. Ниже — баллада, разреженность уместна.
DANCE_BPM = 110.0


def _sections(mem, project):
    """Разделы, BPM, длина и пульс того, что снимается, плюс окно hook (или None).

    У формата hook (clip_lib.hook_window) длина — окно, а разделы — только те, что в него
    попадают: норма полного клипа к 22-секундному фрагменту не применима.
    """
    grid = mem / "song" / "grid.json"
    if grid.exists():
        g = lib.read_json(grid)
        secs = g.get("sections") or []
        if secs:
            try:
                window = lib.hook_window(g)
            except ValueError as e:
                lib.fail(str(e))
            duration = float(g.get("duration") or 0)
            if window:
                duration = window["length"]
                secs = [s for s in secs if not _outside(s, window)]
            elif lib.hook_hint(g):
                print(f"  ! {lib.hook_hint(g)}", file=sys.stderr)
            return secs, float(g.get("bpm") or 0), duration, _pulse(g), window
    edit = (project.get("edit") or {}).get("sections") or []
    song = project.get("song") or {}
    return edit, float(song.get("bpm") or 0), float(song.get("duration") or 0), _pulse(song), None


def _outside(section, window):
    try:
        return float(section["end"]) <= window["start"] or float(section["start"]) >= window["end"]
    except (KeyError, TypeError, ValueError):
        return False


def _pulse(d):
    """Темп, который слышит зритель, — для нормы «танец или баллада».

    Монтажный BPM и пульс трека — разные числа. «Charlie» (26.09.2026):
    склейки ложатся на 90.9 BPM (снейр на 2 и 4), а поверхность бьёт джангл-восьмыми
    на 181.8. По монтажному числу гейт признал трек балладой — 7 планов в минуту
    и никакой быстрой камеры. Доля для длин планов остаётся монтажной.
    """
    return max(float(d.get("bpm") or 0), float(d.get("bpm_double") or 0))


def _setups(mem, project):
    """Различимые установки: якоря канона плюс якоря из брифа."""
    names = set((project.get("canon") or {}).get("refs", {}).keys())
    brief = mem / "canon" / "anchor-brief.json"
    if brief.exists():
        b = lib.read_json(brief)
        anchors = b.get("anchors") or b
        if isinstance(anchors, dict):
            names |= {k for k in anchors.keys() if not str(k).startswith("_")}
        elif isinstance(anchors, list):
            names |= {a.get("id") or a.get("name") for a in anchors if isinstance(a, dict)}
    return {n for n in names if n}


def _shots(mem):
    p = mem / "script" / "shotlist.json"
    if not p.exists():
        return []
    d = lib.read_json(p)
    return d.get("shots") or d.get("shotlist") or []


def required_shots(bpm, duration):
    """Сколько планов нужно минимум на такую длину и такой темп.

    Числа не выдуманы. Три независимых источника сходятся на 12–15 планах в минуту
    при средней длине плана 4–6 с:
      · Paul Trillo / Washed Out «The Hardest Part» (Sora): 700 генераций → 55 планов
        на 4:02 = 13.6 плана/мин, средний план 4.4 с;
      · практический гайд AI Video Bootcamp 2026: «3-минутное видео требует ≈45 планов»,
        план 4–6 с, за 8 с начинается сдвиг композиции = 15 планов/мин;
      · ISMIR 2021, разбор 548 официальных клипов (живых, доAI): средняя длина плана
        4.76 с = 12.6 плана/мин; 67% клипов синхронизированы на уровне бита.
    Для медленных треков берём нижнюю границу вдвое мягче.
    """
    if duration <= 0:
        return 0
    minutes = duration / 60.0
    per_min = 12.0 if bpm >= DANCE_BPM else 7.0
    return int(minutes * per_min)


# Технический потолок одной генерации: 6 с комфортно, 8 с предел — дальше заметен дрейф
# идентичности, света и композиции внутри самого ролика. Ограничение модели, не вкуса.
MAX_SHOT_SEC = 8.0
TARGET_SHOT_SEC = 6.0

# Сколько планов на одну установку — предел монотонности. Выведено из провала:
# 52 плана на 4 установки = 13 планов на объект, зритель видит одно и то же.
MAX_SHOTS_PER_SETUP = 10


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--sparse-ok", dest="sparse_ok", default=None,
                    help="осознанно принять разреженный визуал; нужна причина словами")
    a = ap.parse_args()

    pdir = lib.project_dir(a.project)
    mem = pdir / "clip-memory"
    project = lib.read_json(lib.find_project_json(pdir))

    sections, bpm, duration, pulse, window = _sections(mem, project)
    n_sections = len(sections)
    setups = _setups(mem, project)
    shots = _shots(mem)

    if bpm <= 0:
        lib.fail("нет BPM: сначала музыкальный аналитик (clip-memory/song/grid.json)")
    if not setups:
        lib.fail("нет якорей: сначала художник-постановщик (clip-memory/canon/anchor-brief.json)")

    problems = []
    warnings = []
    need = required_shots(pulse, duration)
    beat = 60.0 / bpm if bpm else 0
    span = (f"окно hook {window['start']:.2f}–{window['end']:.2f} с ({duration:.1f} с)"
            if window else f"трек {duration:.0f} с")

    # 0. До раскадровки (здесь гейт и стоит по пайплайну) судить можно только установки.
    # До 12.10.2026 без шот-листа не проверялось НИЧЕГО: все пункты ниже стоят под `if shots`,
    # и гейт выходил с кодом 0 и писал маркер, которого хватало хуку навсегда. Теперь без
    # шот-листа — проверка установок и никакого маркера: его пишет только прогон по шот-листу.
    if not shots:
        least = -(-need // MAX_SHOTS_PER_SETUP)
        pre = []
        if len(setups) < least:
            pre.append(f"{len(setups)} различимых установок на {span} при {pulse:.1f} BPM: нужно "
                       f"минимум {need} планов, а одна установка держит не больше "
                       f"{MAX_SHOTS_PER_SETUP} — значит установок нужно {least}")
        for p in pre:
            print(f"  · {p}", file=sys.stderr)
        if pre and not a.sparse_ok:
            print("\nГЕЙТ ПЛОТНОСТИ не пройден. Чинить КОНЦЕПЦИЮ — сценарий и канон.", file=sys.stderr)
            raise SystemExit(2)
        print(f"[~] шот-листа нет: проверены только установки ({len(setups)} на {span}). "
              f"Планы, камера и длины не проверены, маркер density-ok НЕ записан — "
              f"повторить гейт после раскадровки.", file=sys.stderr)
        return

    # 1. Плотность планов против длины и темпа (12–15 планов/мин, см. required_shots).
    if shots and len(shots) < need:
        got_per_min = len(shots) / (duration / 60.0) if duration else 0
        problems.append(
            f"планов {len(shots)} на {duration:.0f} с при {bpm:.1f} BPM "
            f"({got_per_min:.1f} в минуту) — норма 12–15 в минуту, нужно минимум {need}. "
            f"Планы длиннее нормы читаются как слайдшоу"
        )

    # 2. Монотонность: сколько планов приходится на одну установку.
    if shots and setups:
        per_setup = len(shots) / len(setups)
        if per_setup > MAX_SHOTS_PER_SETUP:
            problems.append(
                f"{len(shots)} планов на {len(setups)} различимых установок "
                f"({per_setup:.0f} планов на объект, предел {MAX_SHOTS_PER_SETUP}). "
                f"Зритель увидит одно и то же в разном свете. Чинить КОНЦЕПЦИЮ: "
                f"больше мест, объектов и событий, а не больше планов от тех же якорей"
            )

    # 2. Словарь движения камеры.
    moves = Counter()
    for s in shots:
        # Имя поля одно и то же, что в контракте шот-листа и в gate_script: `movement`.
        # Прежние `move` / `motion_type` убраны 15.08.2026: гейт читал их, контракт требовал
        # `movement`, и шот-лист, написанный строго по контракту, отдавал сюда ПУСТОЙ счётчик
        # и падал с текстом «нет ни одного быстрого приёма камеры» — что бы в нём ни стояло.
        # Раскадровке приходилось класть в каждый план два ключа с одним значением.
        m = (s.get("movement") or "").strip()
        if m:
            moves[m] += 1
    if shots and pulse >= DANCE_BPM:
        dynamic = sum(n for m, n in moves.items() if m in DYNAMIC_MOVES)
        if dynamic == 0:
            problems.append(
                f"при пульсе {pulse:.1f} BPM в шот-листе нет ни одного быстрого приёма камеры "
                f"(есть только {', '.join(sorted(moves)) or 'ничего'}). "
                f"Танцевальный трек с медленной камерой читается как чужая музыка"
            )

    # 3. Средняя и максимальная длина плана в СЕКУНДАХ (норма индустрии, не доли).
    total_beats = sum(int(s.get("beats") or 0) for s in shots)
    if shots and total_beats and beat:
        avg_sec = total_beats * beat / len(shots)
        if avg_sec > TARGET_SHOT_SEC:
            problems.append(
                f"средний план {avg_sec:.1f} с — норма 4–6 с "
                f"(ISMIR по 548 клипам: 4.76 с; практики: 4–6 с)"
            )
        longest = max((int(s.get("beats") or 0) * beat, s.get("id") or "?") for s in shots)
        if longest[0] > MAX_SHOT_SEC:
            warnings.append(
                f"план {longest[1]} длиной {longest[0]:.1f} с — за 8 с генерация плывёт "
                f"по свету и композиции; резать внутри или снимать двумя кусками"
            )

    # 4. Однообразие: перекос на один якорь.
    used = Counter()
    for s in shots:
        for r in (s.get("refs") or s.get("anchors") or []):
            used[r] += 1
    if used:
        top, cnt = used.most_common(1)[0]
        share = cnt / sum(used.values())
        if share > 0.5:
            warnings.append(
                f"якорь «{top}» держит {share*100:.0f}% планов — проверь, не будет ли монотонно"
            )

    fmt = {"shots": len(shots)}
    if window:
        fmt.update({"format": "hook", "window": [window["start"], window["end"]]})

    if problems and a.sparse_ok:
        print("ГЕЙТ ПЛОТНОСТИ пройден ОСОЗНАННЫМ РЕШЕНИЕМ. Претензии остаются в силе:",
              file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        print(f"  причина: {a.sparse_ok}", file=sys.stderr)
        lib.write_marker(pdir, "density-ok.json", {
            "gate": "density", "setups": len(setups), "need": need,
            "bpm": bpm, "sections": n_sections, "sparse_ok": a.sparse_ok, **fmt,
        })
        lib.ok(f"плотность принята под ответственность: {len(setups)} установок при {bpm:.1f} BPM")
        return

    if problems:
        print("ГЕЙТ ПЛОТНОСТИ не пройден. Раскадровка не начинается:", file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        for w in warnings:
            print(f"  ! {w}", file=sys.stderr)
        print("\nЭто дефект КОНЦЕПЦИИ, а не шот-листа. Чинить сценарий и канон —"
              "\nздесь переделка ещё бесплатна, после якорей она стоит кредитов."
              "\nЕсли разреженность намеренная: --sparse-ok \"причина\".", file=sys.stderr)
        raise SystemExit(2)

    for w in warnings:
        print(f"  ! {w}", file=sys.stderr)
    lib.write_marker(pdir, "density-ok.json", {
        "gate": "density", "setups": len(setups), "need": need,
        "bpm": bpm, "sections": n_sections, **fmt,
    })
    lib.ok(f"плотность сходится: {len(shots)} планов, {len(setups)} установок при {bpm:.1f} BPM, "
           f"{span}, {n_sections} разделов (нужно планов {need}).")


if __name__ == "__main__":
    main()
