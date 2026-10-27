# gate_lang.py — латиница там, где работает машина; кириллица там, где читает человек (R25).
#
# Проверяет ровно те места, где кириллица уже ломала работу:
#   · имена файлов и папок проекта — файловая система, node и ffmpeg спотыкаются;
#   · промпты, канон, негатив, silence — уходят в модель;
#   · идентификаторы и значения словарей — сверяются машинно;
#   · .bat и .cmd — cmd читает их в OEM-кодировке и ломает разбор команд (R22).
#
# Тритмент, досье, экспликацию, note кадра и отчёты НЕ трогает: там русский язык уместен
# и нужен, это и есть описание процесса для Админа.
#
#   python gate_lang.py --project <папка> [--plugin]
#
# Провал — exit 2 со списком мест и объяснением, почему именно там нельзя.
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib
import lang_policy as LP

# Папки, куда человек пишет по-русски: их имена и содержимое не проверяем.
HUMAN_DIRS = {"clip-memory"}
HUMAN_SUFFIX = {".md", ".txt", ".csv", ".log"}

# Кнопки в корне проекта: их имя читает Проводник, а не node и не ffmpeg — по этому пути
# ничего не вызывается, поэтому кириллица в ИМЕНИ безопасна и нужна (человек ищет кнопку
# глазами). Опасность R22 — кириллица ВНУТРИ .bat, её проверяет check_plugin_scripts.
# Без этого исключения гейт ронял каждый новый проект на файле, который создаёт сам
# скаффолд по R32: правило запрещало то, что другое правило предписывает.
HUMAN_LAUNCHERS = {"ПРИЁМКА.bat"}

def check_names(pdir, problems):
    """Имена файлов и папок. Кириллица в пути = сломанный вызов node/ffmpeg (R22)."""
    root = Path(pdir)
    if LP.has_cyr(root.name):
        problems.append(f"имя папки проекта «{root.name}»: кириллица в пути ломает вызовы node и ffmpeg")
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] in HUMAN_DIRS:
            continue
        if p.name.startswith("."):
            continue
        if p.name in HUMAN_LAUNCHERS and p.parent == root:
            continue
        if LP.has_cyr(p.name):
            problems.append(f"{rel}: кириллица в имени файла — переименовать латиницей")

def check_project_json(pdir, problems):
    try:
        pjson = lib.find_project_json(pdir)
    except SystemExit:
        return
    data = lib.read_json(pjson)
    canon = data.get("canon") or {}
    for field, why in (("style", "хвост промпта"), ("style_short", "хвост промпта"),
                       ("neg", "негатив уходит в генератор"), ("neg_short", "негатив уходит в генератор"),
                       ("must", "дописывается в каждый промпт (R03)"),
                       ("must_short", "дописывается в каждый промпт (R03)"),
                       ("ref_rule", "правило референса уходит в промпт"),
                       ("ref_rule_short", "правило референса уходит в промпт"),
                       ("silence", "сверяется со словами промпта (R02)"),
                       ("rigid", "фраза жёсткости дописывается в движение (R35)"),
                       ("style_mods", "модификаторы стиля уходят в промпт (R36)")):
        if field in canon:
            LP.check_value(f"canon.{field}", canon[field], problems, why)
    for name in (canon.get("refs") or {}):
        if LP.has_cyr(name):
            problems.append(f"canon.refs[{name}]: имя якоря подставляется в запрос — латиницей")
    for sc in (data.get("scenes") or []):
        sid = sc.get("id", "?")
        LP.check_value(f"scenes[{sid}].scene", sc.get("scene"), problems, "промпт кадра уходит в генератор")
        LP.check_value(f"scenes[{sid}].motion", sc.get("motion"), problems, "промпт движения уходит в генератор")
        LP.check_value(f"scenes[{sid}].vars", sc.get("vars"), problems, "поля пресета собираются в промпт (R34)")
        LP.check_value(f"scenes[{sid}].fallback", sc.get("fallback"), problems, "запасной вариант уходит в генератор (R34)")
        if LP.has_cyr(sid):
            problems.append(f"scenes[{sid}].id: идентификатор становится именем файла — латиницей")

def check_shotlist(pdir, problems):
    p = Path(pdir) / "clip-memory" / "script" / "shotlist.json"
    if not p.exists():
        return
    try:
        sl = lib.read_json(p)
    except Exception:
        return
    for sh in (sl.get("shots") or []):
        sid = sh.get("id", "?")
        for field, why in (("id", "идентификатор становится именем файла"),
                           ("section", "имя раздела сверяется с сеткой такта"),
                           ("size", "значение словаря"), ("angle", "значение словаря"),
                           ("movement", "значение словаря"),
                           ("content", "содержание кадра уходит в промпт"),
                           ("light", "описание света уходит в промпт")):
            LP.check_value(f"shots[{sid}].{field}", sh.get(field), problems, why)
        LP.check_value(f"shots[{sid}].anchors", sh.get("anchors"), problems,
                       "имя якоря подставляется в запрос")

def check_anchor_brief(pdir, problems):
    p = Path(pdir) / "clip-memory" / "canon" / "anchor-brief.json"
    if not p.exists():
        return
    try:
        data = lib.read_json(p)
    except Exception:
        return
    for a in (data.get("anchors") or []):
        name = a.get("name", "?")
        LP.check_value(f"anchors[{name}].name", a.get("name"), problems,
                       "имя якоря становится ключом канона")
        LP.check_value(f"anchors[{name}].prompt", a.get("prompt"), problems,
                       "промпт якоря уходит в генератор")

def check_plugin_scripts(problems):
    """.bat и .cmd плагина: cmd читает их в OEM, кириллица внутри ломает разбор команд (R22)."""
    root = lib.plugin_root()
    for p in list(root.glob("*.bat")) + list(root.glob("*.cmd")) + list(root.glob("scripts/*.bat")):
        try:
            raw = p.read_bytes()
        except Exception:
            continue
        try:
            raw.decode("ascii")
        except UnicodeDecodeError:
            problems.append(f"{p.name}: не-ASCII внутри .bat — cmd прочитает файл в OEM и сломает разбор команд")

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser(description="Проверка языковой политики (R25)")
    ap.add_argument("--project", default=None)
    ap.add_argument("--plugin", action="store_true", help="проверить только файлы плагина")
    args = ap.parse_args()

    problems = []
    if args.plugin:
        check_plugin_scripts(problems)
    else:
        pdir = lib.project_dir(args.project)
        if not Path(pdir).exists():
            lib.fail(f"папка проекта не найдена: {pdir}")
        check_names(pdir, problems)
        check_project_json(pdir, problems)
        check_shotlist(pdir, problems)
        check_anchor_brief(pdir, problems)
        check_plugin_scripts(problems)

    if problems:
        print("ГЕЙТ ЯЗЫКА (R25) не пройден:", file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        print("\nКириллица нужна в описаниях для человека — тритмент, досье, note, отчёты.", file=sys.stderr)
        print("В машинном слое — латиница: имена файлов, идентификаторы, промпты, канон.", file=sys.stderr)
        raise SystemExit(2)
    lib.ok("язык на месте: машинный слой латиницей, описания по-русски.")

if __name__ == "__main__":
    main()
