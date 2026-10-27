# gate_ad_script.py — рекламный шот-лист сходится, промпты можно писать (рекламная ветка, шаг D).
#
# Это рекламный двойник gate_script.py. У клипа длину планов задаёт сетка такта, у рекламы
# сеткой служат секунды ролика: поле `sec` вместо `beats`, `duration_sec` вместо длины трека.
# Остальное — то же: словарь крупностей, якоря, полнота, источники для сверки (R31).
#
# Чего в клипе нет и здесь проверяется:
#   - товар виден, и у кадра с товаром есть якорь товара (R01: форму вещи держит картинка);
#   - для ad: акты (введение первым, развязка последней), товар в последнем кадре;
#   - для короткой формы «одинаковая крупность через один» — предупреждение. В клипе на 89 планов
#     оно срабатывало в 30% троек и было шумом (замер 10.10.2026, см. gate_script.py); на 3–7
#     кадрах это обычный сигнал вялой раскадровки.
#
# Что НЕ проверяется и почему: центр внимания соседних кадров. Поля `focus` в шот-листе нет,
# и пилот на Bravo (сверка с аниматиком) ещё не прогнан — shared/ads/02-plan.md.
#
#   python gate_ad_script.py --project <папка>
#
# Успех пишет script-ok.json и density-ok.json с kind=ad. Второй — потому что хук требует
# его на генерации якоря и кадров, а плотность визуала против энергии трека у рекламы считать
# нечем: трека нет. Маркер здесь значит лишь «структура ролика проверена», поэтому в нём
# kind=ad и пояснение; хук читает только факт и возраст маркера.
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib
from gate_script import SIZES, ANGLES, MOVES, known_anchors

ACTS = ("intro", "turn", "main", "outro")
SHOT_LIMITS = {"card": (2, 6), "ad": (3, 7)}
OUTRO_SOFT_MAX = 5.0       # наблюдение практиков короткой формы, не закон (cinema/08)
SUM_TOLERANCE = 0.5        # секунд: сумма планов против длительности ролика
DEFAULT_PRODUCT_ANCHOR = "product"
# Схема «звезда» Кулешова (cinema/06, п. 9): красные стрелки — Дальний с Крупным, Общий с Деталью.
# Предупреждение, не брак: у правила много исключений. Замер 10.10.2026 на 88 парах
# шот-листа Bravo: красных пар 8% — для клипа это шум, для рекламы из 3–7 планов сигнал.
RED_SIZE_PAIRS = {frozenset(("EWS", "CU")), frozenset(("WS", "ECU"))}


def check(pdir):
    """Вернуть (problems, warnings, info) для рекламного шот-листа проекта."""
    problems, warnings = [], []
    mem = Path(pdir) / "clip-memory"
    sl_path = mem / "script" / "shotlist.json"
    if not sl_path.exists():
        return [f"нет {sl_path}. Раскадровка не сделана — промпты писать не из чего."], [], {}
    sl = lib.read_json(sl_path)

    # Паспорт — источник правды о формате и длительности.
    product = {}
    pp = mem / "product" / "product.json"
    if pp.exists():
        try:
            product = lib.read_json(pp)
        except Exception:
            product = {}

    fmt = sl.get("format") or product.get("format")
    if sl.get("form") != "ad":
        problems.append(f"form: «{sl.get('form')}» — у рекламного шот-листа ровно «ad» "
                        f"(клипы проверяет gate_script.py)")
    if fmt not in SHOT_LIMITS:
        problems.append(f"format: «{fmt}» — допустимо {sorted(SHOT_LIMITS)}")
        fmt = None
    if product.get("format") and sl.get("format") and product["format"] != sl["format"]:
        problems.append(f"format в шот-листе «{sl['format']}» расходится с паспортом «{product['format']}» — "
                        f"паспорт главный, правится шот-лист")
    # Формат кадра: паспорт решает, project.json исполняет. Расхождение значит, что кадры уйдут
    # в генерацию не в том формате, а это деньги (решение Админа 10.10.2026: карточки — 3:4).
    if product:
        mismatch = lib.ad_frame_problems(pdir, product)
        if mismatch:
            problems.append("формат кадра расходится с project.json: " + "; ".join(mismatch) +
                            ". Привести: python gate_product.py --project <папка> --apply-aspect")
    dur = sl.get("duration_sec", product.get("duration_sec"))
    if not isinstance(dur, (int, float)) or isinstance(dur, bool) or dur <= 0:
        problems.append(f"duration_sec: «{dur}» — нужно положительное число секунд")
        dur = None
    if fmt == "ad" and not str(sl.get("change") or "").strip():
        problems.append("change: не сформулировано, что меняется от первого кадра к последнему — "
                        "рекламный ролик без перемены это витрина (для витрины есть format=card)")

    shots = [s for s in (sl.get("shots") or []) if s.get("enabled", True)]
    if fmt:
        lo, hi = SHOT_LIMITS[fmt]
        if not lo <= len(shots) <= hi:
            problems.append(f"shots: {len(shots)} — для {fmt} ожидается {lo}–{hi} планов "
                            f"(короткая форма; иначе это уже клип)")
    if not shots:
        return problems or ["shots: пусто"], warnings, {}

    anchors = known_anchors(pdir, mem)
    product_anchor = sl.get("product_anchor") or DEFAULT_PRODUCT_ANCHOR
    sources = sl.get("sources") or {}
    has_src = any((s.get("src") or "").strip() for s in shots)

    total = 0.0
    visible = 0
    for s in shots:
        sid = s.get("id") or "?"
        sec = s.get("sec")
        if not isinstance(sec, (int, float)) or isinstance(sec, bool) or sec <= 0:
            problems.append(f"{sid}: sec «{sec}» — длина плана в секундах, положительное число")
        else:
            total += sec
        for key, vocab in (("size", SIZES), ("angle", ANGLES), ("movement", MOVES)):
            if s.get(key) not in vocab:
                problems.append(f"{sid}: {key} «{s.get(key)}» вне словаря {sorted(vocab)}")

        refs = s.get("anchors")
        if refs is None:
            problems.append(f"{sid}: поле anchors отсутствует")
        elif not refs and not s.get("anchors_free"):
            problems.append(f"{sid}: якорей нет и нет явного anchors_free — что в кадре держит канон? (R01)")
        else:
            for a in refs or []:
                if a not in anchors:
                    problems.append(f"{sid}: якорь «{a}» не существует ни в canon.refs, ни в anchor-brief")

        if s.get("product_visible"):
            visible += 1
            if product_anchor not in (refs or []):
                problems.append(f"{sid}: товар в кадре, а якоря «{product_anchor}» в anchors нет — "
                                f"форму и цвет вещи держит картинка, не слова (R01)")

        for field, why in (("content", "нечего показывать"),
                           ("light", "свет якорь не держит, его пишут словами — R03"),
                           ("note", "кадр без назначения вырезается сейчас, а не на монтаже")):
            if not str(s.get(field) or "").strip():
                problems.append(f"{sid}: пустое поле {field} — {why}")

        if has_src:
            src = (s.get("src") or "").strip()
            if not src:
                problems.append(f"{sid}: нет src, а у других кадров он есть — сверка со сценой (R31) не соберётся")
            elif src not in sources:
                problems.append(f"{sid}: источник «{src}» не описан в sources (R31)")
            elif not str(sources[src].get("desc") or "").strip():
                problems.append(f"источник «{src}»: пустой desc — приёмке нечего сверять глазами (R31)")

    if dur and abs(total - dur) > SUM_TOLERANCE:
        problems.append(f"сумма sec даёт {total:g} с при duration_sec {dur:g} с "
                        f"(допуск ±{SUM_TOLERANCE} с)")

    # Товар в кадре.
    if not visible:
        problems.append("ни в одном кадре нет product_visible: true — это ролик не про товар")
    elif fmt == "card" and visible < 0.8 * len(shots):
        warnings.append(f"товар виден в {visible} из {len(shots)} кадров: карточка — витрина, "
                        f"в ней товар в каждом плане, кроме разве что общего вступления")
    if fmt == "ad" and not shots[-1].get("product_visible"):
        problems.append(f"{shots[-1].get('id')}: в последнем кадре ролика нет товара — "
                        f"развязка должна оставлять вещь в памяти")

    # Акты для рекламного ролика.
    if fmt == "ad":
        acts = [s.get("act") for s in shots]
        for s in shots:
            if s.get("act") not in ACTS:
                problems.append(f"{s.get('id')}: act «{s.get('act')}» — допустимо {list(ACTS)}")
        if all(a in ACTS for a in acts):
            if acts[0] != "intro":
                problems.append(f"{shots[0].get('id')}: первый кадр — не intro (заявочный план)")
            if acts[-1] != "outro":
                problems.append(f"{shots[-1].get('id')}: последний кадр — не outro (развязка)")
            if "turn" not in acts:
                warnings.append("нет кадра с act=turn: события, которое выталкивает из первого акта во "
                                "второй. Без крючка ролик остаётся описанием (cinema/08)")
            outro_sec = sum(s.get("sec") or 0 for s in shots if s.get("act") == "outro")
            if outro_sec > OUTRO_SOFT_MAX:
                warnings.append(f"развязка {outro_sec:g} с — дольше {OUTRO_SOFT_MAX:g} с; в короткой форме финал обычно сокращают "
                                f"до пяти секунд (cinema/08, не проверено нашим прогоном)")

    # Соседи.
    for i in range(1, len(shots)):
        a, b = shots[i - 1], shots[i]
        if a.get("size") == b.get("size") and a.get("movement") == b.get("movement"):
            problems.append(f"{b.get('id')}: у соседа {a.get('id')} те же крупность и движение — "
                            f"склейка не читается (правило смены крупности)")
    for i in range(2, len(shots)):
        a, m, b = shots[i - 2], shots[i - 1], shots[i]
        if a.get("size") == b.get("size") and m.get("size") != b.get("size"):
            warnings.append(f"{a.get('id')} → {m.get('id')} → {b.get('id')}: крупность {b.get('size')} "
                            f"повторяется через один (cinema/06, «Склейка в AI-роликах», п. 1)")

    for i in range(1, len(shots)):
        a, b = shots[i - 1], shots[i]
        if frozenset((a.get("size"), b.get("size"))) in RED_SIZE_PAIRS:
            warnings.append(f"{a.get('id')} → {b.get('id')}: {a.get('size')} и {b.get('size')} не клеятся по "
                            f"схеме «звезда» (cinema/06, п. 9) — нужен промежуточный план или подводка")

    info = {"shots": len(shots), "sec": round(total, 2), "format": fmt, "visible": visible}
    return problems, warnings, info


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    pdir = lib.project_dir(args.project)
    problems, warnings, info = check(pdir)
    for w in warnings:
        print(f"[~] {w}", file=sys.stderr)
    if problems:
        print("ГЕЙТ РЕКЛАМНОГО СЦЕНАРИЯ не пройден. Промпты не пишутся:", file=sys.stderr)
        for pr in problems:
            print(f"  · {pr}", file=sys.stderr)
        print("\nЧинить шот-лист (clip-memory/script/shotlist.json), не скрипт.", file=sys.stderr)
        raise SystemExit(2)
    lib.write_marker(pdir, "script-ok.json", {"gate": "ad_script", "kind": "ad", **info})
    lib.write_marker(pdir, "density-ok.json",
                     {"gate": "ad_script", "kind": "ad",
                      "note": "у рекламы нет трека; маркер значит «структура ролика проверена»", **info})
    lib.ok(f"рекламный шот-лист сходится: {info['shots']} планов, {info['sec']:g} с, "
           f"{info['format']}. Промптер может начинать.")


if __name__ == "__main__":
    main()
