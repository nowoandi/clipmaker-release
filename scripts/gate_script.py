# gate_script.py — промпты не пишутся, пока шот-лист не сходится с музыкой и каноном.
#
# Этот гейт существует потому, что промпт, написанный без шот-листа, невозможно проверить:
# он не привязан ни к длине плана, ни к якорю, ни к назначению кадра. Ошибка тут стоит ноль,
# а через шаг — кредиты Kie и квоту Grok.
#
# Что проверяется (контракт — shared/shotlist-contract.md):
#   1. поля клипа: форма, отношение к тексту, что меняется;
#   2. словарь: крупность, ракурс, движение — только из списков;
#   3. разделы существуют в song/grid.json;
#   4. сумма долей сходится с длиной трека (±1 такт); у формата hook — с длиной окна
#      grid.json → hook.start/end, и каждый раздел кадра пересекается с окном;
#   5. якоря существуют (canon.refs или anchor-brief);
#   6. соседние кадры различаются (классика монтажа, shared/cinema/06-classic-rules.md);
#   7. полнота: content, light, note;
#   8. развитие: второй припев не повторяет первый (R06);
#   9. герой за четыре поля СТНЦ (script/hero.json) у narrative и hybrid — только предупреждение;
#  10. регистр реальности: reality real | heightened | fantasy; не real — только с названным miracle.
#
# «Одинаковая крупность через один» НЕ проверяется намеренно. Замер 10.10.2026 на шот-листе
# Bravo (89 планов): по крупности 30% троек, по трём параметрам сразу — 17%. Для клипа это
# норма чередования, предупреждение читали бы как шум. Это правило годится для
# коротких форм (3–5 планов) — оно ляжет в рекламный гейт (shared/ads/02-plan.md).
#
#   python gate_script.py --project <папка>
#
# Успех пишет маркер .gates/script-ok.json. Провал — exit 2.
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

SIZES = {"EWS", "WS", "MS", "MCU", "CU", "ECU"}
ANGLES = {"eye", "low", "high", "bird", "dutch"}
MOVES = {"static", "push_in_slow", "push_in_fast", "pull_out", "tracking", "pan", "tilt", "handheld"}
FORMS = {"concept", "narrative", "performance", "hybrid"}
RELATIONS = {"illustrate", "counterpoint", "independent"}
# Регистр реальности (0.8.29, shared/cinema/12-reality-register.md). Админ, 13.10.2026: «если мы хотим
# сделать в другом видео абсолютно нереальное что-то, то у нас не должно быть сразу ограничений … из
# другой оперы». Физика из cinema/10 — закон для real; heightened и fantasy объявляют своё допущение
# в miracle, и приёмка сверяет физику с ним, а не с жизнью. «Чудо одно и названо, остальное по физике».
REALITY = {"real", "heightened", "fantasy"}

# Герой за четыре слова — мнемоника «станция»: сокровище,
# тайна, недостаток, цель. Проверяется только у форм, где есть история. Как предупреждение,
# а не стоп: нарративный клип Bravo прошёл этот гейт 18.09.2026 без героя, и новое
# требование не должно задним числом ломать пройденный проект.
HERO_FIELDS = ("treasure", "secret", "flaw", "goal")
HERO_FORMS = {"narrative", "hybrid"}

def known_anchors(pdir, mem):
    """Имена якорей: уже загруженные (canon.refs) плюс запланированные (anchor-brief)."""
    names = set()
    try:
        pjson = lib.find_project_json(pdir)
        project = lib.read_json(pjson)
        names |= set((project.get("canon") or {}).get("refs", {}).keys())
    except SystemExit:
        pass
    except Exception:
        pass
    brief = mem / "canon" / "anchor-brief.json"
    if brief.exists():
        try:
            for a in (lib.read_json(brief).get("anchors") or []):
                if a.get("name"):
                    names.add(a["name"])
        except Exception:
            pass
    return names

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    pdir = lib.project_dir(args.project)
    mem = Path(pdir) / "clip-memory"
    sl_path = mem / "script" / "shotlist.json"
    grid_path = mem / "song" / "grid.json"

    if not sl_path.exists():
        lib.fail(f"нет {sl_path}. Раскадровка не сделана — промпты писать не из чего.")
    if not grid_path.exists():
        lib.fail(f"нет {grid_path}. Без сетки такта длину планов проверить нечем (R20).")

    sl = lib.read_json(sl_path)
    grid = lib.read_json(grid_path)
    anchors = known_anchors(pdir, mem)
    problems = []
    warnings = []   # печатаются, но маркер script-ok не отнимают

    # 1. Поля клипа целиком.
    if sl.get("form") not in FORMS:
        problems.append(f"form: «{sl.get('form')}» — допустимо {sorted(FORMS)}")
    if sl.get("lyric_relation") not in RELATIONS:
        problems.append(f"lyric_relation: «{sl.get('lyric_relation')}» — допустимо {sorted(RELATIONS)}")
    if not (sl.get("change") or "").strip():
        problems.append("change: не сформулировано, что меняется от первого кадра к последнему — клип без изменения это заставка")

    # 1а. Регистр реальности: не задан — реальный, с предупреждением (старые шот-листы его не знают).
    reality = sl.get("reality")
    if reality is None:
        warnings.append("reality не задан — клип считается реальным (real): физика по "
                        "shared/cinema/10. Сказка или поэтичное допущение — reality и miracle "
                        "(shared/cinema/12-reality-register.md)")
    elif reality not in REALITY:
        problems.append(f"reality: «{reality}» — допустимо {sorted(REALITY)}")
    elif reality != "real" and not (sl.get("miracle") or "").strip():
        problems.append(f"reality {reality} без miracle: допущение не названо — приёмке не с чем сверять "
                        "физику. Чудо одно и названо, остальное по физике")
    for s in (sl.get("shots") or []):
        r = s.get("reality")
        if r is None:
            continue
        if r not in REALITY:
            problems.append(f"{s.get('id') or '?'}: reality «{r}» — допустимо {sorted(REALITY)}")
        elif r != "real" and not ((s.get("miracle") or sl.get("miracle") or "").strip()):
            problems.append(f"{s.get('id') or '?'}: reality {r} без miracle у кадра и у клипа")

    # 1б. Герой у форм с историей (предупреждение, см. HERO_FIELDS).
    if sl.get("form") in HERO_FORMS:
        warnings += hero_warnings(mem / "script" / "hero.json")

    shots = [s for s in (sl.get("shots") or []) if s.get("enabled", True)]
    if not shots:
        problems.append("shots: пусто")
        _report(problems, warnings)

    # Источники: либо у всех кадров, либо ни у кого. На разъехавшихся именах
    # слепнет сверка ролика со сценой (R31) — приёмке нечего класть рядом с роликом.
    sources = sl.get("sources") or {}
    has_src = any((s.get("src") or "").strip() for s in shots)

    section_names = {s.get("name") for s in (grid.get("sections") or [])}
    beat = float(grid.get("beat") or 0)
    duration = float(grid.get("duration") or 0)

    # Формат hook: шот-лист покрывает окно, а не трек (clip_lib.hook_window).
    try:
        window = lib.hook_window(grid)
    except ValueError as e:
        problems.append(str(e))
        window = None
    if window:
        duration = window["length"]
    elif lib.hook_hint(grid):
        warnings.append(lib.hook_hint(grid))
    outside = _sections_outside(grid, window) if window else set()

    total_beats = 0
    prev = None
    chorus_seen = {}

    for s in shots:
        sid = s.get("id") or "?"

        # 2. Словарь: значения только из списков, иначе оператор и промптер поймут по-разному.
        if s.get("size") not in SIZES:
            problems.append(f"{sid}: size «{s.get('size')}» вне словаря {sorted(SIZES)}")
        if s.get("angle") not in ANGLES:
            problems.append(f"{sid}: angle «{s.get('angle')}» вне словаря {sorted(ANGLES)}")
        if s.get("movement") not in MOVES:
            problems.append(f"{sid}: movement «{s.get('movement')}» вне словаря {sorted(MOVES)}")

        # 3. Раздел существует.
        sec = s.get("section")
        if sec not in section_names:
            problems.append(f"{sid}: раздел «{sec}» отсутствует в song/grid.json")
        elif sec in outside:
            problems.append(f"{sid}: раздел «{sec}» не пересекается с окном hook "
                            f"{window['start']:.2f}–{window['end']:.2f} с — в ролик он не попадёт")

        # 4. Длина в долях.
        beats = s.get("beats")
        if not isinstance(beats, int) or beats < 1:
            problems.append(f"{sid}: beats должно быть целым ≥ 1, сейчас «{beats}» (длина задаётся в долях, не в секундах — R20)")
        else:
            total_beats += beats

        # 5. Якоря.
        refs = s.get("anchors")
        if refs is None:
            problems.append(f"{sid}: поле anchors отсутствует")
        elif not refs and not s.get("anchors_free"):
            problems.append(f"{sid}: якорей нет и нет явного anchors_free — что в этом кадре держит канон? (R01)")
        else:
            for a in refs or []:
                if a not in anchors:
                    problems.append(f"{sid}: якорь «{a}» не существует ни в canon.refs, ни в anchor-brief")

        # 7. Полнота.
        for field, why in (("content", "нечего показывать"),
                           ("light", "свет якорь не держит, его пишут словами — R03"),
                           ("note", "кадр без назначения вырезается сейчас, а не на монтаже")):
            if not (s.get(field) or "").strip():
                problems.append(f"{sid}: пустое поле {field} — {why}")

        # 8. Источник кадра — вход сверки со сценой (R31).
        if has_src:
            src = (s.get("src") or "").strip()
            if not src:
                problems.append(f"{sid}: нет src, а у других кадров он есть — "
                                f"сверка ролика со сценой (R31) не соберётся")
            elif src not in sources:
                problems.append(f"{sid}: источник «{src}» не описан в sources — "
                                f"на контактном листе приёмки будет пустая подпись (R31)")
            elif not (sources[src].get("desc") or "").strip():
                problems.append(f"источник «{src}»: пустой desc — приёмке нечего сверять глазами (R31)")

        # 6. Соседи различаются: одинаковая крупность и то же движение подряд читается как брак склейки.
        if prev is not None:
            if s.get("size") == prev.get("size") and s.get("movement") == prev.get("movement"):
                problems.append(
                    f"{sid}: у соседа {prev.get('id')} те же крупность и движение — "
                    f"склейка не читается (правило смены крупности)"
                )
        prev = s

        # 8. Развитие припевов.
        if isinstance(sec, str) and ("chorus" in sec.lower() or "припев" in sec.lower()):
            fingerprint = (s.get("size"), s.get("angle"), s.get("movement"), (s.get("content") or "").strip())
            chorus_seen.setdefault(sec, []).append((sid, fingerprint))

    # Второй припев обязан отличаться от первого хотя бы одним кадром.
    groups = sorted(chorus_seen.items())
    if len(groups) >= 2:
        first = [fp for _, fp in groups[0][1]]
        for name, items in groups[1:]:
            later = [fp for _, fp in items]
            if later and later == first[:len(later)]:
                problems.append(
                    f"раздел {name} повторяет {groups[0][0]} кадр в кадр — "
                    f"структура песни не будет читаться в картинке (R06)"
                )

    # 4. Сходимость с треком.
    if beat > 0 and duration > 0 and total_beats:
        planned = total_beats * beat
        delta = planned - duration
        bar = beat * 4
        if abs(delta) > bar:
            what = (f"окне hook {window['start']:.2f}–{window['end']:.2f} с ({duration:.1f} с)"
                    if window else f"длине трека {duration:.1f} с")
            problems.append(
                f"сумма долей даёт {planned:.1f} с при {what} "
                f"(расхождение {delta:+.1f} с, допуск ±{bar:.1f} с = один такт)"
            )

    extra = {"format": "hook", "window": [window["start"], window["end"]]} if window else {}
    _report(problems, warnings, pdir, len(shots), total_beats, extra)

def _sections_outside(grid, window):
    """Имена разделов, целиком лежащих вне окна hook. Раздел без секунд не судим."""
    out = set()
    for s in grid.get("sections") or []:
        try:
            start, end = float(s["start"]), float(s["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= window["start"] or start >= window["end"]:
            out.add(s.get("name"))
    return out

def hero_warnings(path):
    """Предупреждения о герое: файл script/hero.json и четыре заполненных поля.

    Возвращает список строк; пусто — герой записан целиком. Читаемость важнее строгости:
    битый JSON — тоже предупреждение, а не падение гейта.
    """
    if not path.exists():
        return [f"нет {path.name} в clip-memory/script/: у героя нет записанных сокровища, тайны, "
                f"недостатка и цели (мнемоника СТНЦ). "
                f"Не стоп — но без них герой остаётся нарисованным, а не придуманным."]
    try:
        hero = lib.read_json(path)
    except Exception as e:
        return [f"{path.name} не читается ({e}); поля героя не проверены"]
    if not isinstance(hero, dict):
        return [f"{path.name}: ожидался объект с полями {list(HERO_FIELDS)}"]
    missing = [f for f in HERO_FIELDS if not str(hero.get(f) or "").strip()]
    if missing:
        return [f"{path.name}: не заполнено {', '.join(missing)} — герой не записывается в четыре строки "
                f"(СТНЦ), значит он ещё не придуман"]
    return []

def _report(problems, warnings=None, pdir=None, n_shots=0, total_beats=0, extra=None):
    for w in (warnings or []):
        print(f"[~] {w}", file=sys.stderr)
    if problems:
        print("ГЕЙТ СЦЕНАРИЯ не пройден. Промпты не пишутся:", file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        print("\nЧинить шот-лист (clip-memory/script/shotlist.json), не скрипт.", file=sys.stderr)
        raise SystemExit(2)
    lib.write_marker(pdir, "script-ok.json",
                     {"gate": "script", "shots": n_shots, "beats": total_beats, **(extra or {})})
    span = " в окне hook" if extra else ""
    lib.ok(f"шот-лист сходится{span}: {n_shots} кадров, {total_beats} долей. Промптер может начинать.")

if __name__ == "__main__":
    main()
