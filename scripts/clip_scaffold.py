# clip_scaffold.py — новый клип = новая папка со своими запусками (R32).
#
# Зачем: пока проект жил один, пути были вшиты в скрипты моста, панель занимала
# один порт, а реестр скачанного лежал в общей папке. Второй клип на таком
# устройстве либо перетирает первый, либо стартует с пустым реестром (R14).
# Скрипт разводит проекты по папкам и выдаёт каждому свои .bat со своим портом.
#
#   python clip_scaffold.py --name "Рубка связи" [--track "E:\...\track.mp3"] [--root <папка>]
#
# Создаёт <root>/<slug>/ с деревом памяти, project.<slug>.json из шаблона,
# START.bat (студийная панель) и ПРИЁМКА.bat (панель приёмки) с личными портами.
# Существующую папку не трогает: повторный запуск дописывает недостающее.
import argparse
import io
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib
import lang_policy

DIRS = ["clip-memory/research", "clip-memory/song", "clip-memory/script", "clip-memory/canon",
        "clip-memory/fragments", "clip-memory/reports", "clip-memory/doctor",
        "clips", "frames", "anchors", "prompts", "output"]   # output/final.mp4 — как в PIPELINE.md

# Рекламный проект (--kind ad): та же машина, но без трека. Вместо песни — паспорт товара и его фото.
# Папки research/song нет: ресёрча темы и разбора трека у рекламы нет (shared/ads/00-README.md).
DIRS_AD = ["clip-memory/product/photos", "clip-memory/script", "clip-memory/canon",
           "clip-memory/fragments", "clip-memory/reports", "clip-memory/doctor",
           "clips", "frames", "anchors", "prompts", "output"]

# Порт ловится в любом виде, в каком он может стоять в .bat соседнего проекта.
# Пул ОБЩИЙ для приёмки и студии: раздельные пулы уже дали приёмке новичка
# порт студийной панели старого проекта — и панель молча открыла бы чужой клип.
PORT_RE = re.compile(r"REVIEW_PORT=(\d+)|CLIP_STUDIO_PORT=(\d+)|--port\s+(\d+)|localhost:(\d+)")
PORT_BASE = 7801          # 7777 и 7788 заняты первым проектом студии

def taken_ports(root):
    """Занятые порты соседних проектов: читаем их .bat, а не гадаем."""
    used = {7777, 7788}
    for bat in Path(root).glob("*/*.bat"):
        try:
            txt = io.open(bat, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for m in PORT_RE.finditer(txt):
            for g in m.groups():
                if g:
                    used.add(int(g))
    return used

def free_ports(root, n):
    """n свободных портов подряд из одного пула — чтобы панели не сталкивались."""
    used = taken_ports(root)
    out, p = [], PORT_BASE
    while len(out) < n:
        if p not in used:
            out.append(p)
            used.add(p)
        p += 1
    return out

# Путь к установленному плагину .bat выясняет В МОМЕНТ ЗАПУСКА, а не при создании
# проекта. Причина (18.09.2026, девять проектов разом): папка кэша названа номером
# версии, в .bat вшивался путь к .../clipmaker/0.7.0/scripts/clip_studio.py, после
# обновления плагина эта папка удаляется — и студийная панель не стартует.
#
# Почему installed_plugins.json, а не перебор папок кэша: перебор — догадка.
# По алфавиту 0.7.10 встаёт раньше 0.7.9 — на этом ошибается обходной цикл
# `for /d`, который стоял в <проект>. По числам самая новая папка кэша не
# обязательно установленная: старые версии остаются лежать (03.10.2026 в кэше
# 0.7.4 и 0.8.0–0.8.8 при установленной 0.8.8), и после отката максимум соврёт.
# installed_plugins.json переписывает сам Claude Code при каждом plugin update и
# держит ровно один installPath — догадываться не о чем. Python тут не новая
# зависимость: им же запускается сама панель.
#
# Имя маркетплейса не вшито: ключ сверяется по префиксу "clipmaker@".
# Внутри .bat только ASCII, в коде Python только одинарные кавычки (R22).
PLUGIN_RESOLVER = (
    'set "CM="\r\n'
    'for /f "usebackq delims=" %%P in (`python -c "'
    "import json,os;"
    "c=[v[0]['installPath'] for k,v in json.load(open("
    "os.path.expanduser('~/.claude/plugins/installed_plugins.json'),"
    "encoding='utf-8-sig'))['plugins'].items() "
    "if k.startswith('clipmaker@') and v];"
    "print(c[0] if c else '')"
    '" 2^>nul`) do set "CM=%%P"\r\n'
    'if not defined CM goto no_plugin\r\n'
    'if not exist "%CM%\\scripts\\clip_studio.py" goto no_plugin\r\n')

# Метка no_plugin ставится В КОНЕЦ .bat, после exit: иначе cmd провалится в неё
# и после нормальной работы панели покажет сообщение об ошибке.
PLUGIN_MISSING = (
    ':no_plugin\r\n'
    'echo.\r\n'
    'echo   ClipMaker not found: either the plugin is not installed\r\n'
    'echo   or python is not on PATH.\r\n'
    'echo   Fix: claude plugin update clipmaker@aurora-nexus-local\r\n'
    'echo.\r\n'
    'pause\r\n'
    'exit /b 1\r\n')

def write_if_absent(path, text):
    p = Path(path)
    if p.exists():
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    # R22: в .bat только латиница — cmd читает файл в OEM-кодировке,
    # кириллица внутри ломает разбор команд. Русский печатает Python после chcp.
    # newline="" для .bat: текст уже несёт \r\n, трансляция добавляла второй CR —
    # во всех .bat, выданных до 03.10.2026, лежит \r\r\n.
    with io.open(p, "w", encoding="utf-8", newline="" if p.suffix == ".bat" else "\n") as f:
        f.write(text)
    return True

LYRIC_TAGS = ("lyrics", "unsyncedlyrics", "uslt", "text")


def pull_lyrics(track, pdir, cfg):
    """R33: авторский текст сначала ищется В ТРЕКЕ, а не у человека и не у whisper.

    Suno кладёт полный текст в тег `lyrics-eng` и метит комментарий «made with suno
    studio». На прогоне «Alpha» текст лежал в mp3 с первого дня,
    музыкант прогнал faster-whisper, тегов не открыл — и whisper переврал несущую
    строку припева на противоположную по смыслу. 44 отправки ушли в брак.
    """
    out = pdir / "clip-memory" / "song" / "lyrics-author.md"
    if out.exists():
        return
    ff = cfg.get("ffmpeg", "ffmpeg")
    try:
        # R22: ffmpeg печатает теги в UTF-8, а Windows-локаль декодирует в cp1252 —
        # умляуты превращаются в «TÃ¼r». Кодировку задаём явно, не полагаясь на систему.
        p = subprocess.run([ff, "-nostdin", "-i", str(track)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except Exception:
        return
    lines, key, src_tag = [], None, None
    for raw in (p.stdout + p.stderr).splitlines():
        if not raw.startswith("    "):
            continue
        head, sep, val = raw.partition(":")
        name = head.strip().lower()
        if sep and name and not name.startswith("lyrics") and name != "":
            # новый тег — текст закончился
            if key and name not in ("",):
                key = None
        if sep and any(name.startswith(t) for t in LYRIC_TAGS):
            key, src_tag = name, head.strip()
            lines.append(val.strip())
        elif key and head.strip() == "":
            lines.append(val.strip())
    text = "\n".join(lines).strip()
    if len(text) < 80:            # тега нет или он пустой — не выдумываем
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"# Авторский текст · вынут из тега `{src_tag}` трека\n\n"
        f"Источник: метаданные `song.mp3` (R33). Это авторитетный источник СЛОВ.\n"
        f"Тайминги берутся из `words.json` — там машина не ошибается, ошибается в словах.\n"
        f"Расхождения текста и транскрипции разрешаются в пользу этого файла.\n\n"
        f"---\n\n{text}\n", encoding="utf-8")
    print(f"  текст   : вынут из тега {src_tag} → clip-memory/song/lyrics-author.md")


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="название клипа или товара по-русски")
    ap.add_argument("--slug", default=None, help="имя папки латиницей; по умолчанию транслит имени")
    ap.add_argument("--track", default=None, help="путь к mp3; будет скопирован в song.mp3 (только для клипа)")
    ap.add_argument("--root", default=None, help="где заводить; по умолчанию new_project_root")
    ap.add_argument("--kind", choices=("clip", "ad"), default="clip",
                    help="clip — музыкальный клип (по умолчанию); ad — рекламный ролик или карточка товара")
    ap.add_argument("--aspect", choices=sorted(lib.AD_ASPECTS), default=None,
                    help=f"формат кадра рекламы; по умолчанию {lib.AD_ASPECT_DEFAULT} (карточки WB и Ozon, "
                         f"решение Админа 10.10.2026), 9:16 — только для ленты. Клипу не нужен: он всегда 9:16")
    ap.add_argument("--platform", default=None,
                    help="для чего делаем ролик — профиль из config/platforms.json (suno-hook, instagram-reels, "
                         "tiktok, youtube-shorts, youtube-long, vk-clips, ads-ozon-wb, generic-vertical); от него "
                         "зависят субтитры и безопасная зона. По умолчанию: клип — generic-vertical, "
                         "--hook — suno-hook, реклама — ads-ozon-wb")
    ap.add_argument("--hook", action="store_true",
                    help="это Suno-hook (ролик под фрагмент песни): платформа по умолчанию suno-hook, "
                         "субтитры запрещены")
    args = ap.parse_args()
    ad = args.kind == "ad"
    if args.hook and ad:
        lib.fail("--hook — для клипа под песню; у рекламы Suno-hook не бывает.")
    platform = args.platform
    if platform:
        _prof, err = lib.platform_check(platform)
        if err:
            lib.fail(err)
    else:
        platform = lib.load_platforms().get("default_for", {}).get("ad" if ad else ("hook" if args.hook else "clip"))
        _prof, err = lib.platform_check(platform)  # опечатка в config/platforms.json не должна доехать до проекта
        if err:
            lib.fail(err)
    explicit_platform = bool(args.platform or args.hook)
    if args.aspect and not ad:
        lib.fail("--aspect нужен только рекламному проекту (--kind ad): клип всегда 9:16.")
    if ad and args.track:
        lib.fail("--track нужен только клипу: у рекламного ролика нет трека. Музыку, если она нужна, "
                 "подают при сборке (ad_assemble.py --audio).")

    cfg = lib.load_config()
    root = Path(args.root or cfg.get("new_project_root") or ".")
    if not root.exists():
        lib.fail(f"нет папки проектов: {root}")

    slug = args.slug or lang_policy.slug(args.name)
    pdir = root / slug
    fresh = not pdir.exists()
    for d in (DIRS_AD if ad else DIRS):
        (pdir / d).mkdir(parents=True, exist_ok=True)

    plugin = lib.plugin_root()
    # Паспорт товара — из шаблона, имя подставлено. Существующий не перетирается.
    asp_name, asp_dims = None, None
    if ad:
        passport = pdir / "clip-memory" / "product" / "product.json"
        if not passport.exists():
            tpl = lib.read_json(plugin / "shared" / "ads" / "product-template.json")
            tpl["name"] = args.name
            tpl["aspect"] = args.aspect or tpl.get("aspect") or lib.AD_ASPECT_DEFAULT
            lib.write_json(passport, tpl)
        passport_data = lib.read_json(passport)
        asp_name, asp_dims = lib.ad_aspect(passport_data)
        if asp_dims is None:
            lib.fail(f"в паспорте aspect «{asp_name}» — допустимо {sorted(lib.AD_ASPECTS)}. Поправь паспорт.")
        if args.aspect and args.aspect != asp_name:
            lib.fail(f"паспорт уже есть, и формат в нём «{asp_name}», а запрошен «{args.aspect}». Паспорт "
                     f"не перетирается: поменяй aspect в нём и запусти gate_product.py --apply-aspect.")
    # project.json из шаблона, имя проекта подставлено
    pj = pdir / f"project.{slug}.json"
    if not pj.exists():
        tpl = lib.read_json(plugin / "shared" / "project-template.json")
        tpl["project"] = slug
        tpl["platform"] = platform
        lib.write_json(pj, tpl)
        if ad:
            # Шаблон — клиповый, 9:16. Реклама берёт формат из паспорта (умолчание 3:4).
            lib.apply_ad_aspect(pdir, passport_data, project_json=pj)

    elif explicit_platform:
        # Проект уже есть: платформу меняет только явный ключ. Без ключа поле не трогается (нет поля — старое поведение).
        d = lib.read_json(pj)
        if d.get("platform") != platform:
            d["platform"] = platform
            lib.write_json(pj, d)

    if args.track:
        src = Path(args.track)
        if not src.exists():
            lib.fail(f"трек не найден: {src}")
        dst = pdir / "song.mp3"
        if not dst.exists():
            shutil.copy2(src, dst)
        pull_lyrics(dst, pdir, cfg)

    review_port, studio_port = free_ports(root, 2)
    bridge = cfg.get("grok_bridge", "")
    panel_dir = str(Path(cfg.get("review_panel_bat", "")).parent) or bridge

    write_if_absent(pdir / "ПРИЁМКА.bat",
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        f"title Review {slug}\r\n"
        f"set \"CLIP_PROJECT={pdir}\"\r\n"
        f"set \"REVIEW_MEDIA={str(pdir).replace(chr(92), '/')}/clips\"\r\n"
        f"set \"REVIEW_PORT={review_port}\"\r\n"
        f"cd /d \"{panel_dir}\"\r\n"
        f"start \"\" http://localhost:{review_port}\r\n"
        "node review-server.js\r\n")

    # START.bat означает то же, что и в первом проекте студии: открыть Claude Code
    # на этой папке. Менять привычный смысл кнопки ради новой функции нельзя.
    write_if_absent(pdir / "START.bat",
        "@echo off\r\n"
        "rem ClipMaker: start the studio on this project.\r\n"
        "rem ASCII only - cmd reads .bat in the OEM codepage (R22).\r\n"
        "chcp 65001 >nul\r\n"
        f"title ClipMaker {slug}\r\n"
        "cd /d \"%~dp0\"\r\n"
        "echo.\r\n"
        "echo   ClipMaker\r\n"
        "echo   ---------------------------------------------\r\n"
        "echo    1  start development  (" + ("product to pitch" if ad else "research to pitch") + ", free)\r\n"
        "echo    2  continue           (resume where it stopped)\r\n"
        "echo    3  just open Claude Code here\r\n"
        "echo.\r\n"
        f"set \"CMD=/clipmaker:{'ad-new' if ad else 'clip-new'}\"\r\n"
        "set /p PICK=  choice [1]: \r\n"
        f"if \"%PICK%\"==\"2\" set \"CMD=/clipmaker:{'ad-continue' if ad else 'clip-continue'}\"\r\n"
        "if \"%PICK%\"==\"3\" set \"CMD=\"\r\n"
        "echo.\r\n"
        "if \"%CMD%\"==\"\" (claude) else (claude \"%CMD%\")\r\n")

    write_if_absent(pdir / "STUDIO.bat",
        "@echo off\r\n"
        "rem ClipMaker: studio panel for this project.\r\n"
        "rem ASCII only - cmd reads .bat in the OEM codepage (R22).\r\n"
        "chcp 65001 >nul\r\n"
        f"title Studio {slug}\r\n"
        f"set \"CLIP_PROJECT={pdir}\"\r\n"
        f"set \"CLIP_STUDIO_PORT={studio_port}\"\r\n"
        + PLUGIN_RESOLVER +
        "python \"%CM%\\scripts\\clip_studio.py\" "
        "--project \"%CLIP_PROJECT%\" --port %CLIP_STUDIO_PORT% --open\r\n"
        "exit /b %ERRORLEVEL%\r\n"
        + PLUGIN_MISSING)

    write_if_absent(pdir / "SHOOT.bat",
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        f"title Shoot {slug}\r\n"
        f"set \"CLIP_PROJECT={pdir}\"\r\n"
        f"cd /d \"{bridge}\"\r\n"
        f"node clips.js --project \"{str(pdir).replace(chr(92), '/')}\" %*\r\n")

    if ad:
        head = (f"# Проект рекламного ролика · {args.name}\n\n"
                f"Ведётся плагином **ClipMaker**, рекламная ветка. Начало сессии — `/clipmaker:ad-new`,\n"
                f"продолжение прерванного прогона — `/clipmaker:ad-continue`.\n\n")
        entry = (f"## Вход\n\n"
                 f"- `clip-memory/product/product.json` — паспорт товара: что обязано совпасть с оригиналом,\n"
                 f"  чего нельзя обещать, площадки, оффер. Заполнить до старта.\n"
                 f"- Фото товара: `clip-memory/product/photos/`. Без реальных фото якорь не собирается —\n"
                 f"  дорисовывать товару то, чего у него нет, нельзя.\n\n")
    else:
        head = (f"# Проект клипа · {args.name}\n\n"
                f"Ведётся плагином **ClipMaker**. Начало сессии — `/clipmaker:clip-new`,\n"
                f"продолжение прерванного прогона — `/clipmaker:clip-continue`.\n\n")
        entry = (f"## Вход\n\n"
                 f"- `clip-memory/00-brief.md` — тема, трек, референсы. Заполнить до старта.\n"
                 f"- Трек: `song.mp3` в этой папке.\n\n")
    own_fmt = ""
    if ad:
        own_fmt = (f"- формат кадра: **{asp_name}** ({asp_dims[0]}x{asp_dims[1]}) — поле `aspect` паспорта "
                   f"(по умолчанию 3:4, карточки WB и Ozon); project.json приведён к нему;\n")
    write_if_absent(pdir / "CLAUDE.md",
        head +
        f"## Своё у этого проекта (R32)\n\n"
        f"- папка: `{pdir}` — весь материал клипа только здесь;\n"
        f"{own_fmt}"
        f"- открыть проект: `START.bat` — меню Claude Code на этой папке;\n"
        f"- панель приёмки: `ПРИЁМКА.bat`, порт **{review_port}**;\n"
        f"- студийная панель: `STUDIO.bat`, порт **{studio_port}**;\n"
        f"- съёмка: `SHOOT.bat` — тот же `clips.js` моста, но с `--project` на эту папку;\n"
        f"- реестр скачанного: `clips/seen-srcs.json` — свой, непустой с самого начала (R14).\n\n"
        + entry +
        f"## Что важно помнить\n\n"
        f"**Остановка на питче.** Разработка бесплатна; после неё Директор собирает\n"
        f"`clip-memory/reports/pitch.md`. Без явного «да» деньги не тратятся.\n\n"
        f"**Правила живут в коде.** Гейт упал — чинить ДАННЫЕ, а не скрипт.\n\n"
        f"**Два языка (R25).** Промпты, идентификаторы, имена файлов — латиницей.\n"
        f"Тритмент, досье, `note` кадра, отчёты — по-русски.\n")

    if ad:
        write_if_absent(pdir / "clip-memory" / "00-brief.md",
            f"# Бриф · {args.name}\n\n"
            f"## Что рекламируем\n\n(товар одной фразой; всё остальное — в `product/product.json`)\n\n"
            f"## Формат\n\n"
            f"`card` — витринный показ для карточки маркетплейса, 3–15 с, товар в центре.\n"
            f"`ad` — рекламный ролик со слоганом и драматургией, 5–30 с.\n\n"
            f"## Формат кадра\n\n"
            f"{asp_name} ({asp_dims[0]}x{asp_dims[1]}). Умолчание 3:4 — карточки WB и Ozon (Админ 10.10.2026); "
            f"квадрат 1:1 тоже годится; 9:16 — только если ролик идёт в ленту. Решает поле `aspect` паспорта.\n\n"
            f"## Где будет жить ролик\n\nПлатформа: `{platform}` (project.json → platform; профили — config/platforms.json). "
            f"От неё зависят субтитры и безопасная зона. Сменить: clip_scaffold.py --name ... --platform <имя>.\n\n"
            f"## Референсы\n\n(ссылки на ролики, которые нравятся, или «придумать самим»)\n\n"
            f"## Границы\n\n(чего в ролике быть не должно; чего нельзя обещать про товар)\n")
    else:
        write_if_absent(pdir / "clip-memory" / "00-brief.md",
            f"# Бриф · {args.name}\n\n"
            f"## Тема\n\n(одной фразой: о чём клип)\n\n"
            f"## Трек\n\n`song.mp3`\n\n"
            f"## Текст песни\n\n"
            f"(АВТОРСКИЙ текст — сюда или в `clip-memory/song/lyrics-author.md`.\n"
            f"Спросить у автора ДО сценария, а не после. Машинная транскрипция —\n"
            f"источник таймингов, но НЕ слов: на прогоне «Alpha»\n"
            f"whisper переврал несущую строку припева на противоположную по смыслу\n"
            f"(«du musst mal gut angehen» вместо «du musst — na gut, dann geh»),\n"
            f"и клип был построен не на той эмоции — 44 отправки в брак.\n"
            f"Авторского текста нет — так и написать «нет, работаем по words.json»,\n"
            f"тогда сценарист не опирается на сомнительные строки.)\n\n"
            f"## Для чего делаем\n\nПлатформа: `{platform}` (project.json → platform; профили — "
            f"config/platforms.json). От неё зависят субтитры: для Suno-hook букв в кадре нет, для Инстаграма, "
            f"TikTok и прочего они включаются. Сменить: clip_scaffold.py --name ... --platform <имя>.\n\n"
            f"## Референсы\n\n(ссылки или «придумать самим»)\n\n"
            f"## Границы\n\n(чего в клипе быть не должно)\n")

    print(f"── ПРОЕКТ · {slug} " + ("· реклама " if ad else "") + "─" * 22)
    print(f"  папка   : {pdir}" + ("  (создана)" if fresh else "  (дополнена)"))
    print(f"  платформа: {platform} · субтитры: {lib.SUBTITLE_TEXT[_prof['subtitles']]}")
    target = asp_name if ad else "9:16"
    if _prof["aspect"] != target:
        print(f"  [~] профиль {platform} ждёт кадр {_prof['aspect']}, а проект {target} (ориентир, сверить с площадкой)")
    print(f"  открыть : START.bat  (меню Claude Code на этой папке)")
    print(f"  приёмка : порт {review_port} · ПРИЁМКА.bat")
    print(f"  студия  : порт {studio_port} · STUDIO.bat")
    print(f"  съёмка  : SHOOT.bat → clips.js --project")
    if ad:
        print(f"  паспорт : clip-memory/product/product.json  ← заполнить; фото товара — в product/photos/")
        print(f"  формат  : {asp_name} ({asp_dims[0]}x{asp_dims[1]}) — project.json приведён к паспорту")
        lib.ok(f"рекламный проект заведён отдельной папкой со своими портами (R32). "
               f"Дальше — /clipmaker:ad-new (он проведёт по паспорту товара).")
    else:
        if not args.track:
            print("  [~] трек не задан: положить song.mp3 в папку проекта")
        lib.ok(f"проект заведён отдельной папкой со своими портами (R32). "
               f"Дальше — заполнить clip-memory/00-brief.md и /clipmaker:clip-new.")

if __name__ == "__main__":
    main()
