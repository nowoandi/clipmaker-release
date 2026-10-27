# preset_build.py — промпт движения собирается из полей пресета, а не пишется руками (R34).
#
# Зачем: аннотация 26.09.2026 (пресет «Один непрерывный кадр» для Seedance) держит
# фиксированный текст шаблона дословно и меняет только переменные — и хранит поля,
# чтобы после правки одного поля промпт пересобирался целиком. У нас это закрывает
# две старые дыры: правку движения руками мимо рецепта (R12) и переписывание абзаца
# вместо одной переменной (R06). Запасной вариант (B — короче, C — без надписи)
# строится тем же пресетом ДО съёмки, чтобы брак приёмки чинился заменой, а не
# сочинением заново.
#
#   python preset_build.py --project <папка>                 # показать и сверить (exit 2 — расхождение)
#   python preset_build.py --project <папка> --write         # записать motion и fallback[*].motion
#   python preset_build.py --project <папка> --use-fallback S05:B   # снять сцену запасным вариантом
#   python preset_build.py --project <папка> --use-fallback S05:-   # вернуть основной
#
# Сцена под пресетом в project.json:
#   {"id": "S05", "preset": "oner", "vars": {...}, "fallback": {"B": {...}}, "motion": "<собрано>"}
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

PRESETS_DIR = lib.plugin_root() / "shared" / "presets"
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

def load_preset(name):
    p = PRESETS_DIR / f"{name}.json"
    if not p.exists():
        known = ", ".join(sorted(x.stem for x in PRESETS_DIR.glob("*.json")))
        raise ValueError(f"пресета '{name}' нет; есть: {known}")
    return lib.read_json(p)

def spell(text):
    """'Flip It' -> 'F-L-I-P / I-T'. Знаки препинания не раскладываются: модель пишет их
    сама, а буква, названная дефисом, — единственное, что держит написание (опыт eventkauf)."""
    words = [re.sub(r"[^0-9A-Za-z]", "", w) for w in text.split()]
    return " / ".join("-".join(w.upper()) for w in words if w)

def validate(preset, vars_):
    errors = []
    spec = preset.get("vars", {})
    for key in vars_:
        if key not in spec:
            errors.append(f"поле '{key}' пресету '{preset['id']}' неизвестно")
    for key, s in spec.items():
        v = vars_.get(key)
        if v is None or v == "" or v == []:
            if s.get("required"):
                errors.append(f"нет обязательного поля '{key}' ({s.get('help_ru', '')})")
            continue
        t = s.get("type")
        if t == "list":
            if not isinstance(v, list):
                errors.append(f"'{key}' должен быть списком")
                continue
            if len(v) < s.get("min", 0) or len(v) > s.get("max", 99):
                errors.append(f"'{key}': {len(v)} звеньев, допустимо {s.get('min')}–{s.get('max')}")
        elif t == "str" and not isinstance(v, str):
            # Главный случай — magic списком: «волшебный» момент один на план (аннотация, п. 5a).
            errors.append(f"'{key}' должен быть одной строкой, а не {type(v).__name__}")
        elif t == "bool" and not isinstance(v, bool):
            errors.append(f"'{key}' должен быть true/false")
    return errors

def _fmt(x):
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"

def build(preset, vars_, dur, rigid_clauses=()):
    spec = preset.get("vars", {})
    v = {k: s.get("default") for k, s in spec.items() if "default" in s}
    v.update({k: val for k, val in vars_.items() if val is not None})
    if isinstance(v.get("path"), list):
        v["path"] = ", then ".join(v["path"])
    if isinstance(v.get("text"), str):
        v["text_q"] = "“" + v["text"] + "”"
        v["spelled"] = spell(v["text"])
    # Первая стадия занимает долю split, только если вторая стадия включена полем split_if;
    # иначе весь план — одна стадия. Диапазон — бюджет события, а не точка склейки.
    two_stages = bool(v.get(preset.get("split_if", ""), False))
    t1 = round(dur * preset.get("split", 0.6)) if two_stages else dur
    v.update({"t0": "0", "t1": _fmt(t1), "t2": _fmt(dur)})

    out = []
    for part in preset["parts"]:
        if "if" in part and not v.get(part["if"]):
            continue
        if "if_not" in part and v.get(part["if_not"]):
            continue
        def sub(m):
            key = m.group(1)
            val = v.get(key[0].lower() + key[1:])
            if val is None:
                raise ValueError(f"в шаблоне '{{{key}}}', а поля нет")
            s = str(val)
            return s[0].upper() + s[1:] if key[0].isupper() else s
        out.append(PLACEHOLDER.sub(sub, part["text"]))
    # R35: жёсткость предмета — после шаблона, словами канона, без правки.
    out.extend(rigid_clauses)
    return " ".join(out)

def fallback_vars(preset, scene, name):
    """Поля запасного варианта: основные + явная замена из scene.fallback либо авто из пресета."""
    base = dict(scene.get("vars") or {})
    # Авто-замена пресета + явная замена сцены поверх неё. Собранный motion и why —
    # результат и пояснение, а не замена: иначе после --write авто-правило терялось бы.
    over = dict((preset.get("fallback_auto") or {}).get(name) or {})
    over.update({k: v for k, v in ((scene.get("fallback") or {}).get(name) or {}).items()
                 if k not in ("motion", "why") and not k.startswith("_")})
    over = {k: v for k, v in over.items() if not k.startswith("_")}
    if not over:
        raise ValueError(f"запасной '{name}' ничего не меняет — это копия основного")
    for k, val in over.items():
        if isinstance(val, str) and re.fullmatch(r":\d+", val) and isinstance(base.get(k), list):
            base[k] = base[k][:int(val[1:])]
        elif val is None:
            base.pop(k, None)
        else:
            base[k] = val
    return base

def fallback_names(preset, scene):
    names = list((preset.get("fallback_auto") or {}).keys())
    names += [k for k in (scene.get("fallback") or {}) if k not in names]
    return names

def rigid_for(scene, canon):
    rigid = canon.get("rigid") or {}
    return [rigid[r] for r in scene.get("refs", []) if r in rigid and rigid[r]]

def scene_dur(scene, project):
    return float(scene.get("dur") or (project.get("video") or {}).get("duration") or 10)

def expected(scene, project):
    """Что обязано лежать в motion и в fallback[*].motion. Бросает ValueError с причиной."""
    preset = load_preset(scene["preset"])
    canon = project.get("canon") or {}
    dur, rig = scene_dur(scene, project), rigid_for(scene, canon)
    errs = validate(preset, scene.get("vars") or {})
    if errs:
        raise ValueError("; ".join(errs))
    fbs = {}
    for name in fallback_names(preset, scene):
        fv = fallback_vars(preset, scene, name)
        e = validate(preset, fv)
        if e:
            raise ValueError(f"запасной {name}: " + "; ".join(e))
        fbs[name] = build(preset, fv, dur, rig)
    active = scene.get("fallback_active")
    if active:
        if active not in fbs:
            raise ValueError(f"fallback_active='{active}', а такого варианта нет")
        return fbs[active], fbs
    return build(preset, scene.get("vars") or {}, dur, rig), fbs

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--file", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--use-fallback", default=None, help="S05:B — снять запасным; S05:- — вернуть основной")
    args = ap.parse_args()

    pdir = lib.project_dir(args.project)
    pjson = lib.find_project_json(pdir, args.file)
    project = lib.read_json(pjson)
    scenes = project.get("scenes", [])

    if args.use_fallback:
        sid, _, name = args.use_fallback.partition(":")
        sc = next((s for s in scenes if s.get("id") == sid), None)
        if not sc or not sc.get("preset"):
            lib.fail(f"сцены {sid} с пресетом нет")
        if name in ("", "-"):
            sc.pop("fallback_active", None)
        else:
            sc["fallback_active"] = name
        args.write = True

    problems, changed, n = [], 0, 0
    for sc in scenes:
        if not sc.get("preset"):
            continue
        n += 1
        sid = sc.get("id", "?")
        try:
            motion, fbs = expected(sc, project)
        except ValueError as e:
            problems.append(f"{sid}: {e}")
            continue
        mark = f" [запасной {sc['fallback_active']}]" if sc.get("fallback_active") else ""
        print(f"── {sid} · {sc['preset']}{mark} · {len(motion)} симв.")
        print("   " + motion)
        stale = sc.get("motion") != motion or any(
            ((sc.get("fallback") or {}).get(k) or {}).get("motion") != t for k, t in fbs.items())
        if args.write:
            sc["motion"] = motion
            fb = sc.setdefault("fallback", {})
            for k, t in fbs.items():
                fb.setdefault(k, {})["motion"] = t
            changed += int(stale)
        elif stale:
            problems.append(f"{sid}: motion расходится со сборкой из vars — пересобрать --write, руками не править (R34)")

    if args.write and not problems:
        lib.write_json(pjson, project)
    for p in problems:
        print("[-] " + p, file=sys.stderr)
    if problems:
        lib.fail(f"пресеты: {len(problems)} проблем. Чинить vars в {pjson.name}.")
    what = f"записано {changed} сцен" if args.write else "совпадает со сборкой"
    lib.ok(f"пресеты: {n} сцен, {what}.")

if __name__ == "__main__":
    main()
