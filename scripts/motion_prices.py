# motion_prices.py — цена движения (картинка -> видео) в кредитах Kie из config/paths.json.
#
# Зачем отдельный модуль. До 29.10.2026 движение снималось бесплатным мостом Grok, и смета считала
# его в процентах недельной квоты, а деньги Kie за видео держала только вручную написанная смета.
# Когда мост кончился, цену секунды пришлось бы каждый раз вычислять в уме — а ограничение
# ресурса должно жить в коде (R08). Таблица одна: её читают предполёт (gate_preflight.py) и
# расчёт сметы (motion_cost.py), чтобы две цены одной модели не разошлись.
#
# Формат записи motion_prices[<модель>]:
#   {"per_sec": 4.5}                  — цена секунды, ролик = секунды × цена
#   {"per_clip": {"8": 30}}           — цена ролика по длительности в секундах (Veo, Omni)
#   status: замер | страница          — снято с нашего аккаунта или взято с прайса (R23)
#   source: откуда и когда
class NoPrice(Exception):
    """Модель в таблице есть, а этой длительности у неё нет."""


def usd_per_credit(cfg):
    return float(cfg.get("kie_usd_per_credit") or 0.005)


def usd(cfg, credits):
    return round(float(credits) * usd_per_credit(cfg), 2)


def takes_factor(cfg):
    return float(cfg.get("video_takes_factor") or 1.0)


def _dur_key(duration):
    d = float(duration)
    return str(int(d)) if d == int(d) else str(d)


def lookup(cfg, model, duration):
    """Цена ролика этой модели и длительности.

    Возвращает {"credits_per_clip", "credits_per_sec" (или None), "status", "source"};
    None — модели нет в таблице; NoPrice — модель есть, но такой длительности она не продаёт.
    """
    entry = (cfg.get("motion_prices") or {}).get(model)
    if not entry:
        return None
    if entry.get("per_sec") is not None:
        per_sec = float(entry["per_sec"])
        clip = round(per_sec * float(duration), 2)
    else:
        table = entry.get("per_clip") or {}
        key = _dur_key(duration)
        if key not in table:
            have = ", ".join(f"{k} с" for k in sorted(table, key=float))
            raise NoPrice(f"у модели {model} цена задана для длительностей {have}, а нужно {key} с: "
                          f"другая длительность — другая цена, сначала внеси её в motion_prices "
                          f"(config/paths.json) из прайса Kie или замера")
        clip = float(table[key])
        per_sec = None
    return {"credits_per_clip": clip, "credits_per_sec": per_sec,
            "status": entry.get("status", ""), "source": entry.get("source", "")}
