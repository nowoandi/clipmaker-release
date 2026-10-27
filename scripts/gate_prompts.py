# gate_prompts.py — проверка промптов ДО трат (R02, R05, R07 + якоря R01).
#
# Считает длину собираемого промпта каждой сцены (полный и короткий канон),
# ловит слова из canon.silence в текстах сцен, мусорные теги из стоп-листа
# и битые ссылки на якоря. При успехе пишет маркер .gates/prompts-ok.json —
# его требует hook_guard.py для запуска генерации кадров без --dry.
#
#   python gate_prompts.py --project <папка> [--file project.json]
#
# Выход: 0 — можно генерить; 2 — стоп (список проблем в stderr).
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib
import preset_build

# R07: заклинания эпохи SD — в GPT Image читаются буквально.
STOP_TAGS = [
    "8k", "4k", "uhd", "masterpiece", "best quality", "high quality",
    "highly detailed", "hyperdetailed", "ultra detailed", "intricate details",
    "trending on artstation", "artstation", "octane render", "unreal engine",
    "award winning",
]
WEIGHT_RE = re.compile(r"\(\s*[^()]{1,60}:\s*\d+(\.\d+)?\s*\)|\(\([^()]+\)\)")

def canon_for(scene, canon):
    """Канон в том режиме, в котором сцена реально уедет в модель (R27).

    До 15.08.2026 гейт мерил длину ТОЛЬКО верхним уровнем канона, то есть режимом без
    человека, а роль кадров перед партией подменяла must/must_short/neg/neg_short
    значениями из canon._canon_modes[scene.canon_mode]. Замер прогона «Bleib noch ein
    bisschen» (заход 2): расхождение до 104 знаков, 19 сцен над пределом по счёту гейта
    против 45 из 45 по фактическим режимам, худшая 980 при пределе 900. Зелёный гейт
    не означал готовности — он означал, что померили не то.
    """
    mode = scene.get("canon_mode")
    modes = canon.get("_canon_modes") or {}
    m = modes.get(mode) if mode else None
    if not isinstance(m, dict):
        return canon
    merged = dict(canon)
    for f in ("must", "must_short", "neg", "neg_short"):
        if f in m:
            merged[f] = m[f]
    return merged

def build_prompt(scene, canon, short):
    c = canon_for(scene, canon)
    parts = [scene.get("scene", "")]
    if scene.get("refs"):
        parts.append(c.get("ref_rule_short" if short else "ref_rule", ""))
    must = c.get("must_short" if short else "must", "")
    if isinstance(must, list):
        must = " ".join(must)
    parts.append(must)
    parts.append(c.get("style_short" if short else "style", ""))
    parts.append(c.get("neg_short" if short else "neg", ""))
    return " ".join(p for p in parts if p)

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--file", default=None)
    args = ap.parse_args()

    cfg = lib.load_config()
    pdir = lib.project_dir(args.project)
    pjson = lib.find_project_json(pdir, args.file)
    project = lib.read_json(pjson)
    canon = project.get("canon", {})
    scenes = [s for s in project.get("scenes", []) if s.get("enabled", True)]
    warn_at = cfg.get("kie_prompt_warn", 600)
    max_at = cfg.get("kie_prompt_max", 900)

    errors, warnings = [], []

    # R01: все refs сцен существуют в canon.refs и якоря залиты (URL не пустой).
    #
    # СЧИТАЕТСЯ ПО ИМЕНАМ ЯКОРЕЙ, А НЕ ПО ССЫЛКАМ СЦЕН, и печатается отдельным блоком.
    # Причина — замер прогона «Alpha» (заход 2): гейт стоит на шаге G,
    # а canon.refs заполняется на шаге I, поэтому до съёмки якорей он КРАСНЫЙ ВСЕГДА и
    # законно. Три раза подряд (33, 58 и 92 «проблемы») это была одна и та же строка,
    # размноженная по числу ссылок, и три раза роль строила копию проекта в песочнице
    # с заглушками URL — только затем, чтобы узнать, есть ли к промптам ещё претензии.
    # Красный, который всегда красный, перестаёт быть сигналом; ритуал с песочницей стоил
    # больше, чем ловил. Блокировка при этом НЕ ослаблена: маркер по-прежнему не пишется,
    # hook_guard по-прежнему не пускает генерацию.
    refs = canon.get("refs", {})
    waiting, empty_url, scenes_waiting = set(), set(), set()
    for sc in scenes:
        for r in sc.get("refs", []):
            if r not in refs:
                waiting.add(r)
                scenes_waiting.add(sc.get("id", "?"))
            elif not str(refs.get(r, "")).strip():
                empty_url.add(r)
                scenes_waiting.add(sc.get("id", "?"))

    # Место: три плана и красота (0.8.30, clip_lib.place_set_problems). Ошибка держит маркер —
    # без него hook_guard не пустит ни якоря, ни кадры: голое место ловится до первой генерации.
    brief_path = Path(pdir) / "clip-memory" / "canon" / "anchor-brief.json"
    if brief_path.exists():
        try:
            e_set, w_set = lib.place_set_problems(lib.read_json(brief_path))
            errors += e_set
            warnings += w_set
        except Exception as e:
            errors.append(f"anchor-brief.json не читается ({type(e).__name__}: {e})")

    # R05: короткие варианты канона обязаны существовать.
    for f in ("ref_rule_short", "must_short", "style_short", "neg_short"):
        if f not in canon:
            warnings.append(f"в каноне нет '{f}' — на длинных сценах Kie зависнет (R05)")

    silence = [w.lower() for w in canon.get("silence", [])]
    rigid_texts = [t for t in (canon.get("rigid") or {}).values() if t]

    # R36: стиль — не больше трёх модификаторов и словами. Правило «2–3, иначе модель
    # путается в стилях» — из поста @neitronoff (аннотация 26.09.2026); слеш-синтаксис
    # не взят: пост про картинки ChatGPT, в видео не проверен (R23).
    mods = canon.get("style_mods") or []
    if len(mods) > 3:
        errors.append(f"canon.style_mods: {len(mods)} модификаторов, не больше 3 — лишние спорят "
                      f"друг с другом и с пресетом (R36)")
    for m in mods:
        if str(m).strip().startswith("/"):
            errors.append(f"canon.style_mods: '{m}' слеш-кодом — писать словами «как снято» (R36)")
        # style_mods — перечень, а в модель уезжает style/style_short. В 0.8.0 гейт считал
        # список, который ни один генератор не читает: поймал оператор клипа «Flip It»
        # 26.09.2026. Теперь перечень обязан совпадать с тем, что реально уходит в промпт.
        for f in ("style", "style_short"):
            if str(m).lower() not in str(canon.get(f, "")).lower():
                errors.append(f"canon.style_mods: '{m}' нет в canon.{f} — в модель уезжает "
                              f"style, а не перечень; слово дословно в оба поля (R36)")

    # R34: движение пресетной сцены = сборка из полей; запасной вариант готов до съёмки.
    # R35: у сцены с якорем из canon.rigid фраза жёсткости стоит в движении.
    for sc in scenes:
        sid = sc.get("id", "?")
        if sc.get("preset"):
            try:
                want, fbs = preset_build.expected(sc, project)
            except ValueError as e:
                errors.append(f"{sid}: пресет '{sc['preset']}': {e} (R34)")
                continue
            if sc.get("motion") != want:
                errors.append(f"{sid}: motion не совпадает со сборкой пресета — править vars и "
                              f"пересобрать preset_build.py --write, текст руками не трогать (R34)")
            if not fbs:
                errors.append(f"{sid}: у пресетной сцены нет запасного варианта (R34)")
            for k, t in fbs.items():
                if ((sc.get("fallback") or {}).get(k) or {}).get("motion") != t:
                    errors.append(f"{sid}: запасной {k} не собран — preset_build.py --write (R34)")
        else:
            for t in preset_build.rigid_for(sc, canon):
                if t not in sc.get("motion", ""):
                    errors.append(f"{sid}: в движении нет фразы жёсткости из canon.rigid — "
                                  f"предмет поплывёт (R35)")

    print(f"── ПРОМПТЫ · {project.get('project', pjson.name)} · сцен {len(scenes)} " + "─" * 10)
    over_full = 0
    for sc in scenes:
        sid = sc.get("id", "?")
        full = build_prompt(sc, canon, short=False)
        short = build_prompt(sc, canon, short=True)
        # Фраза жёсткости (R35) называет предмет по имени намеренно: её пишет постановщик один
        # раз в канон, и с якорем она не спорит — якорь держит вид, она держит физику (R03).
        motion = sc.get("motion", "")
        for t in rigid_texts:
            motion = motion.replace(t, " ")
        text_fields = (sc.get("scene", "") + " " + motion).lower()

        flag = ""
        if len(short) > max_at:
            errors.append(f"{sid}: даже КОРОТКИЙ промпт {len(short)} симв. > {max_at} — "
                          f"резать сцену до сути (R05)")
            flag = " ← СТОП"
        elif len(full) > max_at:
            over_full += 1
            flag = " ← только короткий канон"
        elif len(short) > warn_at:
            flag = " ~ длинновато"
        print(f"  {sid}: полный {len(full):5d} · короткий {len(short):5d}{flag}")

        for w in silence:
            if w and w in text_fields:
                errors.append(f"{sid}: слово '{w}' из canon.silence в тексте сцены — "
                              f"эту вещь держит якорь, про неё молчим (R02)")
        low = full.lower()
        for tag in STOP_TAGS:
            if tag in low:
                errors.append(f"{sid}: мусорный тег '{tag}' (R07)")
        if WEIGHT_RE.search(full):
            errors.append(f"{sid}: веса в скобках — механика SD, в GPT Image читаются буквально (R07)")

    print("─" * 46)
    if over_full:
        print(f"[i] {over_full} сцен длиннее {max_at} полным каноном — генерить С КОРОТКИМ.")
    for w in warnings:
        print("[~] " + w)

    # ТЕКСТЫ ПРОМПТОВ И ЯКОРЯ — ДВА РАЗНЫХ ВОПРОСА, И ОТВЕТ НА КАЖДЫЙ ПЕЧАТАЕТСЯ ОТДЕЛЬНО.
    # Промпт-инженеру нужен ответ «к моим текстам претензии есть?», и он не должен для этого
    # собирать копию проекта в песочнице.
    if errors:
        for e in errors:
            print("[-] " + e, file=sys.stderr)
        print(f"[=] ТЕКСТЫ СЦЕН: {len(errors)} претензий: длина (R05), silence (R02), "
              f"стоп-теги (R07), пресеты и жёсткость (R34–R36).", file=sys.stderr)
    else:
        print("[=] ТЕКСТЫ СЦЕН: претензий НЕТ — длина (R05), silence (R02), стоп-теги (R07), "
              "веса, пресеты и жёсткость (R34–R36) чисты по всем сценам.", file=sys.stderr)

    if waiting or empty_url:
        if waiting:
            print(f"[·] ЯКОРЕЙ ЖДЁМ: {len(waiting)} имён на {len(scenes_waiting)} сцен — "
                  f"{', '.join(sorted(waiting))}. Это НЕ дефект данных: canon.refs "
                  f"заполняется на шаге I (clip-anchors → upload), а гейт стоит на шаге G.",
                  file=sys.stderr)
        if empty_url:
            print(f"[·] ЯКОРЬ ОБЪЯВЛЕН, URL ПУСТОЙ: {', '.join(sorted(empty_url))} — "
                  f"имя завёл художник-постановщик, заливает шаг I (upload). Это тоже не "
                  f"дефект: пустой ключ стал бы ложью только если по нему снять кадры, "
                  f"а их держит хук (R01).", file=sys.stderr)

    if errors:
        lib.fail(f"тексты сцен не готовы: {len(errors)} претензий. "
                 f"Чинить в {pjson.name}, не в скрипте (R12).")

    # Ожидание якорей — НЕ красный вердикт, а место в конвейере: шаг I ещё не прошёл.
    # Маркер пишется, а имена незалитых якорей едут В НЁМ: по нему hook_guard пускает
    # съёмку ЯКОРЕЙ и держит кадры сцен, пока список не опустеет.
    #
    # До 03.10.2026 вердикт был общим — и шаг I запирал сам себя: хук требовал
    # prompts-ok на t2i.js, а prompts-ok не мог появиться до upload якорей. Якоря
    # нельзя было снять, пока не залиты якоря. В клипе Bravo из этого вышел
    # обход: 18.09 якорь сняли через anchor.js, которого хук не видел, — мимо сметы
    # («якоря: 0 кр») и мимо R05 (промпты 807–838 знаков).
    pending = sorted(waiting | empty_url)
    lib.write_marker(pdir, "prompts-ok.json",
                     {"scenes": len(scenes), "project": str(pjson), "refs_pending": pending})
    if pending:
        lib.ok(f"тексты сцен чисты: {len(scenes)} сцен. ЯКОРЕЙ ЖДЁМ {len(pending)} "
               f"({', '.join(pending)}) — шаг I (clip-anchors) открыт, кадры сцен хук держит "
               f"до upload. Промпт якоря вычитать глазами: гейта на него нет.")
    else:
        lib.ok(f"промпты готовы: {len(scenes)} сцен. Перед пакетом всё равно прогони --dry "
               f"и вычитай глазами.")

if __name__ == "__main__":
    main()
