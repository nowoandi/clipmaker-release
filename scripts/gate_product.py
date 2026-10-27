# gate_product.py — паспорт товара принят, можно придумывать ролик (рекламная ветка, шаг A).
#
# Зачем. В клипе героя придумывает студия, а канон решает её воля. В рекламе героем служит
# реальная вещь, и ошибка стоит иначе: героиня с чуть другим лицом — плохой клип, сумка с
# чуть другой пряжкой — товар, которого покупатель не получит. Поэтому до сценария и якоря
# должно быть записано, ЧТО обязано совпасть с оригиналом и ЧЕГО нельзя обещать, и должны
# лежать реальные фото. Без этого приёмке нечем судить, а якорю не из чего собираться.
#
# Что проверяется (контракт — shared/ads/product-template.json):
#   1. паспорт есть и читается;
#   2. format — card или ad; name заполнено;
#   3. фото: минимум одно, все существуют и это картинки; меньше трёх — предупреждение;
#   4. must_match: минимум одна строка; меньше трёх — предупреждение;
#   5. platforms: непусто, имена из списка;
#   6. длительность: число; длиннее предела формата — предупреждение;
#   7. для ad: слоган и крючок обязательны;
#   8. aspect — формат кадра (3:4 по умолчанию, 1:1, 9:16) и согласие с project.json: паспорт решает,
#      project.json исполняет, расхождение значит, что кадры уйдут в генерацию не в том формате.
#
#   python gate_product.py --project <папка> [--apply-aspect]
#
# --apply-aspect приводит project.json к формату паспорта (только image/video.aspect_ratio и render).
#
# Успех пишет маркер .gates/product-ok.json. Провал — exit 2.
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

FORMATS = {"card", "ad"}
PLATFORMS = {"wb", "ozon", "instagram", "tiktok", "youtube", "other"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
# Предел длины — ориентир, не закон: источники для него — внешний разбор и ТЗ Админа
# 10.10.2026 («короткие вставки»). Превышение — предупреждение.
SOFT_MAX_SEC = {"card": 15, "ad": 30}


def check(pdir):
    """Вернуть (problems, warnings) для паспорта в папке проекта."""
    problems, warnings = [], []
    path = Path(pdir) / "clip-memory" / "product" / "product.json"
    if not path.exists():
        return [f"нет {path}. Паспорт товара не заведён — ролик придумывать не из чего."], []
    try:
        p = lib.read_json(path)
    except Exception as e:
        return [f"{path.name} не читается: {e}"], []
    if not isinstance(p, dict):
        return [f"{path.name}: ожидался объект"], []

    fmt = p.get("format")
    if fmt not in FORMATS:
        problems.append(f"format: «{fmt}» — допустимо {sorted(FORMATS)}")
    if not str(p.get("name") or "").strip():
        problems.append("name: не заполнено — что именно рекламируем")

    photos = p.get("photos") or []
    if not isinstance(photos, list) or not photos:
        problems.append("photos: нет ни одного фото товара — якорь собирать не из чего, "
                        "а рисовать товару то, чего у него нет, нельзя")
    else:
        for rel in photos:
            f = Path(pdir) / str(rel)
            if f.suffix.lower() not in IMAGE_EXT:
                problems.append(f"photos: «{rel}» — не картинка ({', '.join(sorted(IMAGE_EXT))})")
            elif not f.exists():
                problems.append(f"photos: файла нет — {rel}")
        if len(photos) < 3:
            warnings.append(f"фото {len(photos)} из желательных 3+: лист-якорь с несколькими ракурсами "
                            f"и крупными деталями из одного фото не собрать (cinema/05, «Якорь-ЛИСТ»)")

    must = [str(x).strip() for x in (p.get("must_match") or []) if str(x).strip()]
    if not must:
        problems.append("must_match: пусто — приёмке нечего сверять с оригиналом (цвет, фурнитура, "
                        "логотип, пропорции). Это главное поле паспорта")
    elif len(must) < 3:
        warnings.append(f"must_match: {len(must)} строк; 3 и больше надёжнее — иначе совпадение "
                        f"проверяется по одному признаку")

    if not [x for x in (p.get("must_not_claim") or []) if str(x).strip()]:
        warnings.append("must_not_claim пусто: обещания и сравнения не проверялись. Допустимо, "
                        "но это сознательное «нечего запрещать», а не забытое поле")

    plats = p.get("platforms") or []
    if not plats:
        problems.append("platforms: не указано, где ролик будет жить — формат, длина и запреты у площадок разные")
    else:
        bad = [x for x in plats if x not in PLATFORMS]
        if bad:
            problems.append(f"platforms: {bad} вне списка {sorted(PLATFORMS)}")

    # Формат кадра. Админ 10.10.2026: «по карточкам … лучше три на четыре, это более универсальный
    # формат … высокие нам точно не нужны» — умолчание 3:4; 9:16 только по явному решению.
    aspect, dims = lib.ad_aspect(p)
    if dims is None:
        problems.append(f"aspect: «{aspect}» — допустимо {sorted(lib.AD_ASPECTS)}; по умолчанию "
                        f"{lib.AD_ASPECT_DEFAULT} (карточки WB и Ozon), 9:16 — только для ленты")
    else:
        if not p.get("aspect"):
            warnings.append(f"aspect не записан в паспорте: берётся {lib.AD_ASPECT_DEFAULT} (решение Админа "
                            f"10.10.2026). Впиши явно — тогда видно, что выбор сделан")
        mismatch = lib.ad_frame_problems(pdir, p)
        if mismatch:
            problems.append("формат кадра расходится с project.json: " + "; ".join(mismatch) +
                            ". Кадры сгенерировались бы не в том формате. "
                            "Привести: python gate_product.py --project <папка> --apply-aspect")

    dur = p.get("duration_sec")
    if not isinstance(dur, (int, float)) or isinstance(dur, bool) or dur <= 0:
        problems.append(f"duration_sec: «{dur}» — нужно положительное число секунд")
    elif fmt in SOFT_MAX_SEC and dur > SOFT_MAX_SEC[fmt]:
        warnings.append(f"duration_sec {dur:g} с длиннее ориентира {SOFT_MAX_SEC[fmt]} с для формата {fmt}: "
                        f"это короткая вставка, а не ролик на минуту")

    if fmt == "ad":
        offer = p.get("offer") or {}
        for key, why in (("slogan", "слоган — то, ради чего ролик существует"),
                         ("hook", "крючок — что происходит в первые секунды ролика")):
            if not str(offer.get(key) or "").strip():
                problems.append(f"offer.{key}: пусто — для рекламного ролика обязателен ({why})")
    return problems, warnings


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--apply-aspect", action="store_true",
                    help="привести project.json к формату кадра из паспорта (image/video.aspect_ratio, render)")
    args = ap.parse_args()

    pdir = lib.project_dir(args.project)
    if args.apply_aspect:
        pp = Path(pdir) / "clip-memory" / "product" / "product.json"
        if not pp.exists():
            lib.fail(f"нет {pp}: формат брать неоткуда")
        try:
            changed = lib.apply_ad_aspect(pdir, lib.read_json(pp))
        except ValueError as e:
            lib.fail(f"aspect в паспорте: {e}")
        print("project.json приведён к паспорту: " + ("; ".join(changed) if changed else "уже сходилось"))
    problems, warnings = check(pdir)
    for w in warnings:
        print(f"[~] {w}", file=sys.stderr)
    if problems:
        print("ГЕЙТ ТОВАРА не пройден. Ролик не придумывается:", file=sys.stderr)
        for pr in problems:
            print(f"  · {pr}", file=sys.stderr)
        print("\nЧинить паспорт (clip-memory/product/product.json), не скрипт.", file=sys.stderr)
        raise SystemExit(2)
    p = lib.read_json(Path(pdir) / "clip-memory" / "product" / "product.json")
    lib.write_marker(pdir, "product-ok.json",
                     {"gate": "product", "format": p.get("format"), "photos": len(p.get("photos") or []),
                      "aspect": lib.ad_aspect(p)[0]})
    lib.ok(f"паспорт товара принят: {p.get('name')} · {p.get('format')} · {lib.ad_aspect(p)[0]} · "
           f"{len(p.get('photos') or [])} фото. Можно придумывать ролик.")


if __name__ == "__main__":
    main()
