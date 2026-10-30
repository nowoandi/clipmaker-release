# motion_cost.py — смета движения (картинка -> видео) в кредитах Kie и долларах.
#
#   python motion_cost.py --model grok-imagine/image-to-video --duration 6 --scenes 29 [--takes 1.94] [--json]
#   python motion_cost.py --project <папка> [--takes 1.5] [--json]
#
# Зачем скрипт. budget.json пишет роль (clip-line-producer), и цену секунды она раньше вычисляла
# сама. 29.10.2026 выяснилось, что Grok в Kie подорожал с 18 до 27 кр. за ролик 6 с, а смета с
# одним дублем занижала расход почти вдвое (в октябре на сцену ушло 1,94 съёмки). Ограничение
# ресурса должно жить в коде (R08), поэтому цену берёт таблица config/paths.json → motion_prices,
# число дублей — video_takes_factor, и роль только вставляет напечатанное в смету.
#
# --json печатает блок для budget.json → motion; потолок (ceiling_credits) — расчёт с дублями,
# округлённый вверх. Цена с прайса, а не с замера, помечена: её обещание — гипотеза (R23).
#
# Выход: 0 — посчитано; 2 — нет цены (модели нет в таблице или у неё нет такой длительности).
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib
import motion_prices as mp


def estimate(cfg, model, duration, scenes, takes=None):
    price = mp.lookup(cfg, model, duration)
    if price is None:
        raise mp.NoPrice(f"модели {model} нет в motion_prices (config/paths.json): цену не посчитать. "
                         f"Внеси её из прайса Kie или замера, не из памяти.")
    takes = mp.takes_factor(cfg) if takes is None else float(takes)
    one = round(price["credits_per_clip"] * scenes, 2)
    with_takes = round(one * takes, 2)
    ceiling = int(math.ceil(with_takes))
    return {
        "model": model, "duration": duration, "scenes": scenes, "takes_factor": takes,
        "credits_per_clip": price["credits_per_clip"], "credits_per_sec": price["credits_per_sec"],
        "credits_one_take": one, "credits_with_takes": with_takes, "ceiling_credits": ceiling,
        "usd_one_take": mp.usd(cfg, one), "usd_with_takes": mp.usd(cfg, with_takes),
        "price_status": price["status"], "price_source": price["source"],
    }


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser(description="Смета движения в кредитах Kie и долларах")
    ap.add_argument("--project", default=None, help="папка проекта: модель, длительность и число сцен из project.json")
    ap.add_argument("--file", default=None, help="явный путь к project.json")
    ap.add_argument("--model", default=None)
    ap.add_argument("--duration", type=float, default=None, help="секунд на ролик (по умолчанию video.duration, иначе 6)")
    ap.add_argument("--scenes", type=int, default=None, help="сколько сцен снимаем")
    ap.add_argument("--takes", type=float, default=None, help="съёмок на сцену; по умолчанию video_takes_factor из конфига")
    ap.add_argument("--json", action="store_true", help="напечатать блок для budget.json → motion")
    args = ap.parse_args()

    cfg = lib.load_config()
    model, duration, scenes = args.model, args.duration, args.scenes
    if args.project or args.file:
        pdir = lib.project_dir(args.project)
        project = lib.read_json(lib.find_project_json(pdir, args.file))
        video = project.get("video") or {}
        model = model or video.get("model")
        duration = duration if duration is not None else (video.get("duration") or 6)
        if scenes is None:
            scenes = sum(1 for s in project.get("scenes", []) if s.get("enabled") is not False)
    if duration is None:
        duration = 6
    if not model or not scenes:
        lib.fail("нужны модель и число сцен: --model и --scenes или --project с video.model и сценами.")
    try:
        r = estimate(cfg, model, duration, scenes, args.takes)
    except mp.NoPrice as e:
        lib.fail(str(e))

    if args.json:
        block = {k: r[k] for k in ("model", "duration", "scenes", "takes_factor", "credits_per_clip",
                                   "credits_one_take", "ceiling_credits", "usd_one_take", "usd_with_takes",
                                   "price_status", "price_source")}
        if r["credits_per_sec"] is not None:
            block["credits_per_sec"] = r["credits_per_sec"]
        print(json.dumps(block, ensure_ascii=False, indent=2))
        return
    d = f"{duration:g}"
    print(f"── СМЕТА ДВИЖЕНИЯ · {model} · {d} с · {scenes} сцен " + "─" * 6)
    price_line = (f"{r['credits_per_sec']} кр./с" if r["credits_per_sec"] is not None
                  else f"прайс за ролик {d} с")
    print(f"  цена ролика         : {r['credits_per_clip']} кр. ({price_line}) · "
          f"${mp.usd(cfg, r['credits_per_clip'])}")
    print(f"  одна съёмка сцен    : {r['credits_one_take']} кр. · ${r['usd_one_take']}")
    print(f"  с дублями ×{r['takes_factor']:g}      : {r['credits_with_takes']} кр. · ${r['usd_with_takes']}  "
          f"→ потолок {r['ceiling_credits']} кр.")
    print(f"  цена                : {r['price_status'] or '—'}: {r['price_source']}")
    if r["price_status"] != "замер":
        print("  ВНИМАНИЕ: цена с прайса, нашим прогоном не проверена (R23): заявлено — проверяется пилотом.")
    print("─" * 46)


if __name__ == "__main__":
    main()
