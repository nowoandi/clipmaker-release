# hook_guard.py — PreToolUse-хук: съёмка и генерация не запускаются без гейта.
#
# Это исполнительный механизм правила R08: «правило в памяти не работает,
# работает код, который не даёт запуститься». Хук вызывается Claude Code
# ПЕРЕД каждым Bash/PowerShell и читает JSON вызова со stdin. Если команда —
# съёмочная или генерационная, а свежего маркера гейта нет, хук блокирует
# вызов (exit 2). Модель обойти это не может независимо от состояния контекста.
#
# Маркеры (пишутся гейтами, живут preflight_ttl_min минут):
#   <project>/.gates/preflight-ok.json  ← gate_preflight.py  (видео)
#       Поле provider: bridge — мост Grok (у маркеров до 0.8.26 поля нет, это тоже
#       мост), api — Kie. Маркер одного провайдера другой не пускает.
#   <project>/.gates/prompts-ok.json    ← gate_prompts.py    (кадры без --dry; якоря)
#       У кадров сцен сверх маркера — пустой refs_pending в нём. У якорей нет:
#       якоря этот список и опустошают (шаг I конвейера).
#
# Папка проекта: cd/--project в команде, $CLIP_PROJECT, cwd и его родители, путь
# в команде (finde_projekt). Не наш вызов — молча exit 0; наш, но проект не найден —
# стоп (с 0.8.25).
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

# clips.js — общий съёмочный скрипт (R32); clips-<что-то>.js — старые копии под проект.
# Узкий список имён однажды уже пропустил съёмку мимо предполёта: clips-bnb.js
# не совпадал ни с одним шаблоном, и весь клип снялся без гейта R08.
# \b после расширения отделяет скрипт от файла данных: clips.js — не clips.json.
#
# agent-*.js — режим Agent в Grok Imagine (появился 18.09.2026): одна отправка
# снимает связку из трёх планов и стоит ≈7% недельной квоты вместо 1,8% у
# обычной — самая дорогая отправка, какая у нас есть (замеры в <проект>,
# clip-memory/reports/grok-agent-price.md). Проба agent-test.js 18.09 сожгла эти
# 7% мимо предполёта: ни одно имя из списка выше ей не подошло. Шаблон, а не
# точное имя agent-shot.js, — по той же причине, по которой узкий список однажды
# пропустил clips-bnb.js: копия под новый проект и следующая проба не должны
# выпадать из правила. Своей проверки маркера у agent-shot.js с 03.10.2026 нет,
# её сняли: хук гасит маркер ДО запуска скрипта, и две проверки на одном маркере
# выключали друг друга (скрипт падал бы на «нет маркера предполёта»).
VIDEO_RE = re.compile(r"clips(-\w+)?\.js\b|chain-link\.js\b|video\.js\b|agent-\w+\.js\b", re.IGNORECASE)
# video.js из pipeline-v3 ходит и в мост, и в Kie: --provider в команде, иначе
# video.provider проекта, иначе api (video.js:41). Остальные из VIDEO_RE — только мост.
# Различать надо, потому что маркеры считаны по разному счёту: квота моста против
# кредитов Kie. 12.10.2026 маркер моста было не получить вовсе (квота кончилась), и
# видео через Kie пошло под --force-estimate — а предполёт денег Kie не считал.
KIE_VIDEO_RE = re.compile(r"(?<![\w-])video\.js\b", re.IGNORECASE)
BRIDGE_VIDEO_RE = re.compile(r"clips(-\w+)?\.js\b|chain-link\.js\b|agent-\w+\.js\b", re.IGNORECASE)
ARG_TAIL = r"""["']?(?:=|\s*,\s*|\s+)["']?([^"'\s;&|)}]+(?:\s*,\s*[^"'\s;&|)}]+)*)"""
PROVIDER_ARG_RE = re.compile(r"--provider" + ARG_TAIL)
ONLY_ARG_RE = re.compile(r"--only" + ARG_TAIL)
BLOCK_ARG_RE = re.compile(r"--block" + ARG_TAIL)
PROJECT_FILE_RE = re.compile(r"""[^\s"';&|)}]*project[\w.-]*\.json""", re.IGNORECASE)
# Якорь (шаг I) и кадр сцены (шаг J) — два разных расхода, и спрашивать с них надо
# разное. До 03.10.2026 они стояли в одном FRAMES_RE и ждали одного маркера
# prompts-ok, а тот до шага I не появляется по определению: его пишет гейт промптов,
# который проверяет, что canon.refs залиты, — а заливает их как раз шаг I. Шаг
# якорей запирал сам себя, и в Bravo из этого вышел обход: 18.09 якорь сняли
# через anchor.js, которого в списке не было вовсе.
#
# Теперь оба ждут prompts-ok, но кадрам сцен вдобавок нужен пустой refs_pending.
# anchor*.js — в списке: это генератор Kie, и ровно им ушли деньги мимо гейтов.
ANCHOR_RE = re.compile(r"t2i\.js\b|i2i2?\.js\b|anchor(-\w+)?\.js\b", re.IGNORECASE)
# frames-<проект>.js: по R32 каждый проект копирует свой генератор «по образцу
# frames-sk.js» (clip-frames SKILL), а узкий список имён однажды уже пропустил целый
# клип — см. clips-bnb.js выше. Та же дыра, тот же способ её закрыть.
FRAMES_RE = re.compile(r"frames(-\w+)?\.js\b", re.IGNORECASE)
ASSEMBLY_RE = re.compile(r"edit-\w+\.py\b|assemble\w*\.py\b", re.IGNORECASE)
# Любое имя, из-за которого хук вообще вмешивается. Нужно там, где решается, можно ли
# считать звено безобидным: `cat > notes.md` безобиден, `cat clips.js > notes.md` — нет,
# это копия, и node исполнит её под любым расширением.
SKRIPT_NAME_RE = re.compile("|".join(
    r.pattern for r in (VIDEO_RE, FRAMES_RE, ANCHOR_RE, ASSEMBLY_RE)), re.IGNORECASE)
# Черновик (аниматик) — сборка из кадров и проб ДО съёмки, её смотрит Админ (PIPELINE ★ «аниматик»).
# Сверка роликов со сценой (R31) к нему неприменима: роликов почти нет. До 28.09.2026 черновик проходил
# только потому, что имя draft_v1_build.py не совпало с ASSEMBLY_RE, — монтажёр «Flip It» сказал об этом
# прямо, и это был обход по имени, а не правило. Теперь черновик узнаётся явно и свободен, но если он
# пишет файл final*.mp4 — это уже монтаж, и сверка обязательна.
DRAFT_RE = re.compile(r"(?:draft|animatic)\w*\.py\b", re.IGNORECASE)
FINAL_RE = re.compile(r"\bfinal\w*\.mp4\b", re.IGNORECASE)
DRY_RE = re.compile(r"--dry\b")
PROBE_RE = re.compile(r"model-check|mc-video|probe|--help|-version", re.IGNORECASE)

# Имя скрипта в команде — ещё не запуск. 18.09.2026 в сессии Bravo хук
# остановил два чтения: PowerShell перебирал frames.json, clips.json и
# clips\clip-jobs.json моста (в «clips.json» шаблон видел «clips.js»), потом
# Get-Content читал assemble.py. Оба раза — сообщение про предполёт и сверку,
# хотя ничего не снималось и не монтировалось. И второе, молчаливое: при свежем
# маркере предполёта такое чтение сжигало маркер (ветка is_video ниже), и
# следующая настоящая партия вставала без понятной причины.
#
# Поэтому нужен запуск. Сам .js или .py не исполняется — его запускает
# интерпретатор, и интерпретатор ищется во ВСЕЙ команде, а не только прямо
# перед именем. Роль съёмки запускает партию так (R22):
#   Start-Process -FilePath "node" -ArgumentList "clips-bnb.js","--block","1" ...
# Между node и именем стоит -ArgumentList, в многострочной команде имя бывает на
# другой строке, а в цикле — в переменной. Правило «имя сразу после node»
# пропустило бы ровно этот запуск — та же дыра, через которую однажды уже
# снялся целый клип без предполёта. Цена широкого правила: python, который
# ЧИТАЕТ assemble.py, по-прежнему остановлен. Это неудобство; дыра стоила бы денег.
INTERP_RE = re.compile(
    r"(?<![^\s\"'`&(;|{\\/])"  # слово начинается после пробела, кавычки, & ( ; | { или пути
    r"(?:node|nodejs|python(?:\d+(?:\.\d+)?)?|pythonw|py)(?:\.exe)?"
    r"(?=[\s\"'`);|&}]|$)",    # и кончается: .py в «assemble.py» интерпретатором не считается
    re.IGNORECASE)
# Запуск без интерпретатора: .\assemble.py (ассоциация файла), ./clips.js (shebang),
# & "путь\clips.js". Имя скрипта — первое слово одной из команд строки. Строка в
# кавычках первым словом без & PowerShell лишь печатает ("=== clips.js ===").
PART_RE = re.compile(r"&&|\|\||[;|\n]")
FIRST_WORD_RE = re.compile(r"\s*(?:&\s*(\"[^\"]*\"?|'[^']*'?|\S+)|([^\s\"'`]+))")

# Широкое правило сложило в «запуск» два чтения. 26.09.2026, сессия Bleib noch
# ein bisschen: `python -c "…читает ledger.jsonl…"; …; grep -rn … budget.js
# clips.js …` и цикл, который подавал хуку строки 'grep -n foo … clips.js …'.
# Интерпретатор стоял в одной команде строки, имя — аргументом grep в другой.
#
# Сузить правило до «интерпретатор рядом с именем» нельзя: это дыра, описанная
# выше (Start-Process, переменная, другая строка). Поэтому правило прежнее, а до
# него из команды вычёркивается звено, которое ничего не запускает, — команда из
# READERS. Вычёркивается только доказуемо мёртвое; в сомнении звено остаётся и
# решает по-старому:
#   - дальше по конвейеру не читатель: Get-Content clips.js | node — это запуск;
#   - в звене подстановка или скобки: внутри $( ) может сидеть node;
#   - вывод уходит в файл: cat clips.js > shoot.js сделает копию для запуска;
#   - кавычки не сошлись: разбор не удался.
# Строки в кавычках у прочих команд (цикл по командам, bash -c '…') разбираются
# как команды — если в звене нет интерпретатора: node "…" исполняет свою строку.
#
# Список узкий намеренно. rg (--pre), sort (--compress-program), find (-exec),
# xargs, awk (system), sed (e), git (bisect run) умеют запускать чужое. cp и
# Copy-Item не запускают, но копия под другим именем уйдёт в node той же строкой.
READERS = frozenset("""
    cat head tail wc grep egrep fgrep ls dir stat file diff cmp od xxd md5sum
    sha256sum echo printf type findstr get-content gc select-string sls
    get-childitem gci get-item gi test-path get-filehash write-host write-output
""".split())
LEAD_WORDS = frozenset(("do", "then", "else", "elif"))
ENV_ASSIGN_RE = re.compile(r"[A-Za-z_]\w*=")
NULL_REDIR_RE = re.compile(r"[\d&]?>>?\s*(?:&\d|/dev/null\b|\$null\b|nul\b)", re.IGNORECASE)
# Запись в ДОКУМЕНТ — не копия скрипта. Правило «вывод уходит в файл» живое потому,
# что `cat clips.js > shoot.js` делает копию для ЗАПУСКА; .md, .txt, .rst, .adoc никто
# не запускает. 03.10.2026 на этом встала запись отчёта о самих гейтах: в тексте стояли
# слово python и имя clips-bnb.js, и хук увидел съёмку видео. Сам стоп был бы лишь
# неудобством, но ветка is_video сначала требует маркер предполёта, а потом его ГАСИТ —
# значит при свежем маркере такая запись проходила молча и уносила право на партию,
# а следующая настоящая отправка встала бы без понятной причины. Это вторая,
# «молчаливая» грабля из разбора 18.09.2026: тогда её закрыли только для чтений.
DOC_REDIR_RE = re.compile(r"[\d&]?>>?\s*[^\s\"'`;|&)]*\.(?:md|txt|rst|adoc)\b", re.IGNORECASE)
NESTED_RE = re.compile(r"[`(){}>]")
# Подстановка: bash исполняет $( ) и `…` в "…" и в теле heredoc без кавычек,
# PowerShell — $( ) в "…" и @"…"@.
SUBST_RE = re.compile(r"\$\(|`")

# Heredoc читался как команды. 26.09.2026, та же сессия: коммит плагина
#   git commit -q -F - <<'EOF'
#   …текст про clips.js, python и "(cat clips.js | node)"…
#   EOF
# остановлен сообщением R08 «съёмка видео без предполёта». _pipelines резал по
# переносам, и каждая строка сообщения стала звеном. Звено не из READERS — живое,
# «python» в тексте — интерпретатор, clips.js рядом — имя. Сообщение коммита
# сложилось в запуск.
#
# Теперь тело (<<WORD, <<'WORD', <<"WORD", <<-WORD) — не звенья, а данные того
# звена, где стоит <<. Решает команда, которая тело получает:
#   - читатель, и дальше по конвейеру только читатели, без записи в файл: тело
#     лишь печатается — мёртвое;
#   - git commit: тело — текст сообщения, git его не исполняет — мёртвое;
#   - всё прочее — живое, решает старое правило: python - <<'EOF' исполняет
#     тело, bash <<EOF тоже, cat <<'EOF' | node и cat > shoot.js <<'EOF' отдают
#     его на запуск. Разбирать такое тело построчно как команды не стали: для
#     python или node это код другого языка, и строка «cat = 'clips.js'» в нём
#     сошла бы за чтение.
# Ограничитель без кавычек: bash подставляет в теле $( ) и `…` — такое тело
# живое при любом получателе. Ограничитель не найден или форма незнакомая
# (сдвиг $((1<<2)), <<E"O"F) — разбор не удался, решает старое правило.
#
# В PowerShell то же самое — here-string @"…"@ и @'…'@: многострочная строка в
# кавычках. Строка одна в звене (@'…'@ | git commit -F -) PowerShell лишь
# выводит — в PowerShell такое звено читатель. В bash строка первым словом —
# имя команды: "./clips.js" её запускает, поэтому правило только для PowerShell.
#
# git в целом не читатель (git bisect run), читатель только git commit в простой
# форме: переменная перед git (GIT_EDITOR="node clips.js" git commit) и
# глобальные опции кроме -C (git -c core.editor=…) заставляют git запустить
# программу. Такой commit решается по-старому.
HEREDOC_RE = re.compile(
    r"<<(-?)[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|\\([\w.-]+)|([\w.-]+))(?=[\s;&|<>()]|$)")
HERESTRING_RE = re.compile(r"@([\"'])[ \t]*\r?\n")
LITERAL_RE = re.compile(r"@?([\"'])_*\1@?")


def _heredoc_end(text, pos, delim, tabs):
    """Начало и конец строки-ограничителя heredoc; None — её нет."""
    while True:
        end = text.find("\n", pos)
        if end < 0:
            end = len(text)
        line = text[pos:end]
        if (line.lstrip("\t") if tabs else line) == delim:
            return pos, end
        if end == len(text):
            return None
        pos = end + 1


def _pipelines(text, esc):
    """Конвейеры строки, звенья каждого: (начало, конец, строки в кавычках, тела heredoc).

    Разделители внутри кавычек не режут: `grep "a\\|b"` — одно звено. esc —
    знак экранирования диалекта (\\ в bash, ` в PowerShell); он же склеивает
    строку при переносе. Тело heredoc — (начало, конец вместе со строкой-
    ограничителем, мёртвое ли само по себе). None — кавычки не сошлись или
    heredoc не разобран.
    """
    pipelines, stages, quoted, docs, pending = [], [], [], [], []
    start = i = 0
    while i < len(text):
        c = text[i]
        if esc == "`" and c == "@":
            m = HERESTRING_RE.match(text, i)
            if m:
                q = m.group(1)
                # "@ с отступом тоже считается концом: если PowerShell с этим не
                # согласен, остаток тела разберётся как команды — строже, не мягче.
                end = re.compile("^[ \t]*" + q + "@", re.M).search(text, m.end())
                if not end:
                    return None
                qe = end.end() - 2
                quoted.append((i + 2, qe, q))
                i = qe + 2
                continue
        if esc == "\\" and text.startswith("<<", i):
            if text.startswith("<<<", i):  # here-string bash: слово на той же строке
                i += 3
                continue
            m = HEREDOC_RE.match(text, i)
            if not m:
                return None
            tabs, sq, dq, bs, bare = m.groups()
            # Тело читается после конца строки; до тех пор оно ничьё, а
            # принадлежит звену, где стоит <<, — его список docs. Подстановки
            # в теле bash раскрывает только при ограничителе без кавычек.
            pending.append((sq or dq or bs or bare, bool(tabs), bare is not None, docs))
            i = m.end()
            continue
        if c in "\"'":
            j = i + 1
            while j < len(text) and text[j] != c:
                j += 2 if c == '"' and text[j] == esc else 1
            if j >= len(text):
                return None
            quoted.append((i + 1, j, c))
            i = j + 1
            continue
        if c == esc:
            i += 2
            continue
        step, pipe = 0, False
        if text.startswith(("&&", "||"), i):
            step = 2
        elif c in ";\n":
            step = 1
        elif c == "|":
            step, pipe = 1, True
        # Одиночный & — фон в bash, но в 2>&1 это перенаправление, а в начале
        # звена — оператор вызова PowerShell: & "путь\clips.js".
        elif (c == "&" and text[i - 1:i] != ">" and text[i + 1:i + 2] != ">"
              and text[start:i].strip()):
            step = 1
        if step:
            stages.append((start, i, quoted, docs))
            quoted, docs = [], []
            if not pipe:
                pipelines.append(stages)
                stages = []
            start = i = i + step
            if c == "\n" and pending:
                # Тела идут подряд, в порядке операторов <<, с начала следующей строки.
                for delim, tabs, expands, owner in pending:
                    found = _heredoc_end(text, i, delim, tabs)
                    if found is None:
                        return None
                    ds, de = found
                    owner.append((i, de, not (expands and SUBST_RE.search(text[i:ds]))))
                    i = de + 1
                pending = []
                start = i = min(i, len(text))
            continue
        i += 1
    if pending:
        return None  # << в последней строке, тела нет
    stages.append((start, len(text), quoted, docs))
    pipelines.append(stages)
    return pipelines


def _name(word):
    """Имя команды без пути и .exe, строчными."""
    word = re.split(r"[\\/]", word)[-1].lower()
    return word[:-4] if word.endswith(".exe") else word


def _git_commit(words):
    """git commit без переменных перед ним и без глобальных опций, кроме -C."""
    if not words or _name(words[0]) != "git":
        return False
    i = 1
    while words[i:i + 1] == ["-C"]:
        i += 2
    return words[i:i + 1] == ["commit"]


def _only_reads(text, stage, esc):
    """Звено — чтение или печать без вложенной команды и без записи в файл."""
    s, e, quoted, docs = stage
    bare = list(text[s:e])
    for qs, qe, q in quoted:
        if q == '"' and SUBST_RE.search(text[qs:qe]):
            return False
        bare[qs - s:qe - s] = "_" * (qe - qs)
    bare = NULL_REDIR_RE.sub(" ", "".join(bare))
    # Запись в документ безобидна при двух условиях, и оба проверены прогоном:
    #   - тело heredoc не подставляется. При ограничителе без кавычек bash раскроет
    #     в теле $( ) и `…`, и `cat > notes.md <<MDEOF` с $(node clips.js) внутри —
    #     настоящий запуск. Инертность тела считает _pipelines, здесь её только читаем;
    #   - звено не копирует скрипт. `cat clips.js > notes.md` — копия, и node исполнит
    #     её под любым расширением. Имя ищем в СЫРОМ тексте звена: в bare строки в
    #     кавычках уже забиты, и "clips.js" стало бы невидимым.
    if all(inert for _, _, inert in docs) and not SKRIPT_NAME_RE.search(text[s:e]):
        bare = DOC_REDIR_RE.sub(" ", bare)
    if NESTED_RE.search(bare):
        return False
    words = bare.split()
    while words and words[0].lower() in LEAD_WORDS:
        words.pop(0)
    if _git_commit(words):
        return True
    if esc == "`" and len(words) == 1 and LITERAL_RE.fullmatch(words[0]):
        return True
    for word in words:
        if not ENV_ASSIGN_RE.match(word):
            return _name(word) in READERS
    return False


def _dead_spans(text, esc, depth=0):
    """Куски команды, которые заведомо ничего не запускают."""
    pipelines = _pipelines(text, esc) if depth < 4 else None
    if pipelines is None:
        return []
    spans = []
    for stages in pipelines:
        reads = [_only_reads(text, st, esc) for st in stages]
        for k, (s, e, quoted, docs) in enumerate(stages):
            if all(reads[k:]):
                spans.append((s, e))
                spans += [(bs, be) for bs, be, inert in docs if inert]
            elif not INTERP_RE.search(text[s:e]):
                for qs, qe, _ in quoted:
                    spans += [(qs + a, qs + b)
                              for a, b in _dead_spans(text[qs:qe], esc, depth + 1)]
    return spans


def runs_script(cmd, name_re, esc="\\"):
    """Команда запускает скрипт из name_re, а не только называет его."""
    if not name_re.search(cmd):
        return False
    # Переносы строк сохраняются: по ним ниже режет PART_RE.
    chars = list(cmd)
    for s, e in _dead_spans(cmd, esc):
        chars[s:e] = [ch if ch == "\n" else " " for ch in cmd[s:e]]
    cmd = "".join(chars)
    if not name_re.search(cmd):
        return False
    if INTERP_RE.search(cmd):
        return True
    for part in PART_RE.split(cmd):
        m = FIRST_WORD_RE.match(part)
        if m and name_re.search(m.group(1) or m.group(2)):
            return True
    return False


def vorheriger_verbraucher(pdir):
    """Строка «маркер забрала вот эта команда» — или пусто, если записки нет.

    Записку пишет сам хук, когда гасит маркер. Она нужна именно в сообщении
    блокировки: человек видит стоп «предполёта нет» ровно в тот момент, когда
    право на партию уже кто-то унёс, и без записки причина не находится никак.
    """
    try:
        data = lib.read_json(Path(pdir) / ".gates" / "preflight-used.json")
        when = datetime.fromtimestamp(int(data.get("at", 0))).strftime("%d.%m %H:%M")
        return (f"Предыдущий маркер израсходован {when} командой:\n"
                f"  {data.get('cmd', '?')}\n"
                "Если эта команда ничего не снимала — хук принял текст за съёмку, и это\n"
                "его дефект: сказать об этом, а не обходить гейт.\n")
    except Exception:
        return ""


def block(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def ist_clip_projekt(pdir):
    """Папка клипа или чужая папка?

    Три признака, любой достаточен — они покрывают проект на разных стадиях:
    project*.json есть с самого начала, clip-memory появляется вместе с
    исследованием и каноном, .gates — как только прошёл первый гейт.

    В сомнении отвечаем НЕТ: ложное «да» останавливает работу в чужом проекте
    сообщением про съёмку клипа, ложное «нет» лишь пропускает команду, которая
    в папке без признаков клипа всё равно ничего не снимет.
    """
    try:
        p = Path(pdir)
        if any(x for x in p.glob("project*.json") if "bak" not in x.name.lower()):
            return True
        return (p / "clip-memory").is_dir() or (p / ".gates").is_dir()
    except Exception:
        return False

# Папка проекта. До 0.8.25 она бралась из $CLIP_PROJECT или cwd сессии — и только.
# 12.10.2026, <проект>: роль якорей работала с cwd = C:\ClipMaker\projects
# (корень всех клипов, сам он не клип) и запускала платный генератор так:
#   Set-Location "…\<проект>"; node "…\_pipeline-v3\anchor.js" anchor-heroine-v1
# cwd в событии хука — тот, что был ДО Set-Location. Корень — не папка клипа, хук решил
# «чужой проект» и вышел с 0, гейты не смотрел вовсе. В тот раз маркеры лежали свежие
# (прошли за минуту до запуска), и 12 кредитов ушли законно, — но хук этого не знал:
# с пустыми гейтами было бы то же самое. Подпапка проекта (cwd = …\anchors) — та же дыра.
#
# Теперь папка ищется так, от сильного признака к слабому:
#   1. куда команда сама переходит: cd / Set-Location / pushd, и --project. Это место
#      запуска, оно точнее cwd сессии — в том числе когда cwd уже другой клип;
#   2. $CLIP_PROJECT;
#   3. cwd — и его родители: подпапка клипа принадлежит клипу;
#   4. любой абсолютный путь в команде, если он лежит внутри клипа.
# Папки инструментов (pipeline, grok_bridge) проектом не считаются, хотя в pipeline-v3
# лежат project.example.json и project.sandy.json и признак ist_clip_projekt на нём
# срабатывает: путь к anchor.js есть почти в каждой команде, и он сделал бы любой запуск
# «неоднозначным» или проверил бы гейты не той папки.
#
# Не нашлась — решает, наша ли это зона. Корень клипов, pipeline или мост в cwd или в
# команде — значит наша, и запуск стоит (fail closed): проверять гейты негде, а пропуск
# стоит кредитов. Иначе — чужой проект, граница 29.08.2026 (video.js в магазине) цела.
CD_RE = re.compile(
    r"(?:^|[;&|\n({])\s*(?:cd|chdir|pushd|set-location|sl|push-location)"
    r"(?:\s+-(?:literalpath|path))?\s+(\"[^\"]+\"|'[^']+'|[^\s;&|)}]+)",
    re.IGNORECASE)
PROJECT_ARG_RE = re.compile(r"--project(?:=|\s+)(\"[^\"]+\"|'[^']+'|[^\s;&|)}]+)")
ABS_PATH_RE = re.compile(r"\"([^\"]+)\"|'([^']+)'|((?:[A-Za-z]:|/[A-Za-z]/)[\\/][^\s\"';&|)}]*)")


def _pfad(text, basis):
    """Путь из команды: без кавычек, /d/… Git Bash → D:/…, относительный — от basis."""
    text = text.strip().strip("\"'")
    m = re.match(r"^/([A-Za-z])(/.*)?$", text)
    if m:
        text = m.group(1) + ":" + (m.group(2) or "/")
    p = Path(os.path.expandvars(text))
    if not p.is_absolute() and basis:
        p = Path(basis) / p
    return p


def _werkzeug_ordner(cfg):
    return [Path(cfg[k]) for k in ("pipeline", "grok_bridge") if cfg.get(k)]


def _innerhalb(p, ordner):
    try:
        p = p.resolve()
        return any(p == o.resolve() or o.resolve() in p.parents for o in ordner)
    except Exception:
        return False


def projekt_von(p, cfg):
    """Ближайший клип вверх от p (сам p или его родитель); None — p не внутри клипа."""
    werkzeug = _werkzeug_ordner(cfg)
    try:
        p = Path(p).resolve()
    except Exception:
        return None
    for kandidat in [p, *p.parents]:
        if _innerhalb(kandidat, werkzeug):
            continue
        if kandidat.is_dir() and ist_clip_projekt(kandidat):
            return str(kandidat)
    return None


def finde_projekt(cmd, cwd, cfg):
    """(папка проекта, причина отказа). Папка None и причина пуста — не наша зона."""
    def sammeln(treffer):
        gefunden = []
        for roh in treffer:
            pdir = projekt_von(_pfad(roh, cwd), cfg)
            if pdir and pdir not in gefunden:
                gefunden.append(pdir)
        return gefunden

    stark = sammeln([m.group(1) for m in CD_RE.finditer(cmd)]
                    + [m.group(1) for m in PROJECT_ARG_RE.finditer(cmd)])
    if len(stark) > 1:
        return None, "команда переходит в несколько проектов: " + ", ".join(stark)
    if stark:
        return stark[0], ""
    for basis in (os.environ.get("CLIP_PROJECT"), cwd):
        if basis:
            pdir = projekt_von(_pfad(basis, None), cfg)
            if pdir:
                return pdir, ""
    schwach = sammeln([next(g for g in m.groups() if g) for m in ABS_PATH_RE.finditer(cmd)])
    if len(schwach) > 1:
        return None, "в команде пути к нескольким проектам: " + ", ".join(schwach)
    if schwach:
        return schwach[0], ""

    # Наша ли зона. Пути из конфига сравниваются и с cwd, и с текстом команды.
    zone = [Path(r) for r in cfg.get("project_roots") or []] + _werkzeug_ordner(cfg)
    if cwd and _innerhalb(_pfad(cwd, None), zone):
        return None, f"cwd сессии — {cwd}, это не папка клипа"
    flach = cmd.replace("\\", "/").lower()
    for o in zone:
        if str(o).replace("\\", "/").lower().rstrip("/") in flach:
            return None, f"команда обращается к {o}, а папки клипа в ней нет"
    return None, ""


def _projekt_datei(cmd, pdir):
    """project*.json, который получит video.js: из команды, иначе единственный в папке."""
    for m in re.finditer(r'"([^"]*project[\w.-]*\.json)"|\'([^\']*project[\w.-]*\.json)\'', cmd,
                         re.IGNORECASE):
        p = _pfad(m.group(1) or m.group(2), pdir)
        if p.is_file():
            return p
    for m in PROJECT_FILE_RE.finditer(cmd):
        p = _pfad(m.group(0), pdir)
        if p.is_file():
            return p
    try:
        return lib.find_project_json(pdir)
    except SystemExit:
        return None


def _video_cfg(cmd, pdir):
    try:
        p = _projekt_datei(cmd, pdir)
        return (lib.read_json(p).get("video") or {}) if p else None
    except Exception:
        return None


def video_provider(cmd, pdir):
    """bridge | api | unknown — тем же порядком, что video.js:41."""
    if "--provider" in cmd:
        m = PROVIDER_ARG_RE.search(cmd)
        wert = m.group(1).lower() if m else ""
        return wert if wert in ("api", "bridge") else "unknown"
    video = _video_cfg(cmd, pdir)
    if video is None:
        return "unknown"
    return str(video.get("provider") or "api").lower()


def kie_marker_check(marker, cmd, pdir, ttl):
    """Партия Kie идёт только по маркеру Kie и только той выборкой, что посчитана.

    Маркер хранит сцены, длительность и модель, по которым предполёт считал деньги.
    Цена ролика — длительность × цена секунды, и в video.js длительность одна на запуск:
    поправь video.duration после предполёта с 6 на 10 — и та же партия стоит на 2/3
    дороже (смета 12.10.2026, СТОП-2). Поэтому всё это сверяется в момент запуска.
    """
    nachher = ("Что сделать:\n"
               "  python \"<plugin>/scripts/gate_preflight.py\" --project \"<папка>\" --provider api"
               " [--only S01,S02]\n"
               "  и в video.js — те же --provider api и --only.")
    if video_provider(cmd, pdir) == "unknown":
        block("ГЕЙТ CLIPMAKER (R08): не понял, через что пойдёт video.js — мост или Kie.\n"
              "Укажи провайдера явно словом: --provider api или --provider bridge.")
    if not marker:
        block("ГЕЙТ CLIPMAKER (R08): съёмка видео через Kie без предполёта заблокирована.\n"
              f"Свежего маркера .gates/preflight-ok.json нет в: {pdir}\n"
              + vorheriger_verbraucher(pdir) + nachher +
              f"\nМаркер живёт {ttl} мин и покрывает ОДНУ партию (R11).")
    if marker.get("provider") != "api":
        block("ГЕЙТ CLIPMAKER (R08): маркер предполёта посчитан для моста Grok, а партия идёт через Kie.\n"
              f"Папка: {pdir}\n"
              "Квота моста кредиты Kie не считает: потолок сметы и баланс этой партии не проверены.\n"
              + nachher)
    gezaehlt = marker.get("scenes") or []
    ids = None
    if "--only" in cmd:
        m = ONLY_ARG_RE.search(cmd)
        if not m:
            block("ГЕЙТ CLIPMAKER (R08): не разобрал --only в команде video.js — какие сцены пойдут "
                  "в Kie, неизвестно. Напиши --only S01,S02 одним словом.")
        ids = [x.strip() for x in m.group(1).split(",") if x.strip()]
    if ids is None and marker.get("only"):
        block("ГЕЙТ CLIPMAKER (R08): предполёт Kie считал партию " + ", ".join(gezaehlt) +
              ", а команда без --only — video.js возьмёт все включённые сцены.\n" + nachher)
    lishnie = [i for i in (ids or []) if i not in gezaehlt]
    if lishnie:
        block("ГЕЙТ CLIPMAKER (R08): в команде сцены, которых предполёт Kie не считал: "
              + ", ".join(lishnie) + f"\nПосчитаны: {', '.join(gezaehlt)}.\n" + nachher)
    if ids is None:
        m = BLOCK_ARG_RE.search(cmd)
        try:
            blok = int(m.group(1)) if m else 0
        except ValueError:
            blok = -1
        if blok != int(marker.get("block") or 0):
            block(f"ГЕЙТ CLIPMAKER (R08): предполёт Kie считал блок {marker.get('block') or 'все'}, "
                  f"а команда берёт другой.\n" + nachher)
    video = _video_cfg(cmd, pdir)
    if video is None:
        block(f"ГЕЙТ CLIPMAKER (R08): не прочитал project*.json в {pdir} — цену партии Kie не сверить.")
    if (video.get("duration") or 6) != marker.get("duration") or video.get("model") != marker.get("model"):
        block("ГЕЙТ CLIPMAKER (R08): после предполёта Kie в project.json сменились длительность или модель.\n"
              f"Посчитано: {marker.get('model')}, {marker.get('duration')} с. "
              f"Сейчас: {video.get('model')}, {video.get('duration') or 6} с.\n"
              "Цена ролика уже другая: новый предполёт.\n" + nachher)


def main():
    lib.setup_io()
    try:
        # R22: BOM-грабля — PowerShell дописывает BOM, JSON молча не читается.
        # Та же ошибка однажды отключила бюджетный гейт в budget.js.
        raw = sys.stdin.buffer.read().decode("utf-8-sig")
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)  # нечитаемый вход — не наша зона, не мешаем

    tool = payload.get("tool_name", "")
    if tool not in ("Bash", "PowerShell"):
        sys.exit(0)
    ti = payload.get("tool_input", {}) or {}
    cmd = ti.get("command", "") or ""
    if not cmd or PROBE_RE.search(cmd):
        sys.exit(0)

    # В PowerShell \ — часть пути ("D:\Projects\"), а экранирует обратный апостроф.
    esc = "`" if tool == "PowerShell" else "\\"
    is_video = runs_script(cmd, VIDEO_RE, esc)
    is_frames = runs_script(cmd, FRAMES_RE, esc) and not DRY_RE.search(cmd)
    # Освобождения по --dry у якорей НЕТ, и это не упущение. У генератора кадров --dry
    # настоящий: он печатает промпты и ничего не тратит. t2i.js читает argv позиционно
    # (файл, id, папка, модель) — для него --dry станет именем папки, и генерация
    # пойдёт за деньги. anchor.js примет --dry за фильтр вариантов. Освободить якоря
    # по этому слову значило бы отдать обход тому, кто его просто допишет.
    is_anchor = runs_script(cmd, ANCHOR_RE, esc)
    is_assembly = runs_script(cmd, ASSEMBLY_RE, esc)
    if runs_script(cmd, DRAFT_RE, esc) and FINAL_RE.search(cmd):
        is_assembly = True   # черновик, который пишет final, — уже монтаж (R31)
    if not (is_video or is_frames or is_anchor or is_assembly):
        sys.exit(0)

    try:
        cfg = lib.load_config()
    except Exception:
        sys.exit(0)  # конфиг сломан — хук не должен парализовать всю машину
    ttl = cfg.get("preflight_ttl_min", 30)

    pdir, grund = finde_projekt(cmd, payload.get("cwd") or os.getcwd(), cfg)
    if grund:
        block(
            "ГЕЙТ CLIPMAKER: запуск без папки проекта заблокирован.\n"
            f"Хук не понял, какой это клип: {grund}.\n"
            "Без папки проекта гейты (density-ok, script-ok, prompts-ok, preflight-ok)\n"
            "проверять негде. До 0.8.25 хук в этом случае молча пропускал запуск:\n"
            "12.10.2026 якоря <проект> ушли в Kie мимо проверки гейтов.\n"
            "Что сделать — перейти в папку клипа в той же команде:\n"
            "  Set-Location \"<папка клипа>\"; node \"<pipeline>\\anchor.js\" <рецепт>\n"
            "  (bash: cd \"<папка клипа>\" && node …), у скриптов с --project — --project \"<папка>\".\n"
            "Обходить переименованием или копией скрипта нельзя."
        )
    if not pdir:
        sys.exit(0)

    # Граница действия хука. Он висит на КАЖДОМ вызове Bash и PowerShell во всех
    # проектах сразу — так работают хуки плагина: включён плагин, значит хук
    # стоит везде, а не только там, где снимают клип.
    #
    # ПОВОД (Админ 29.08.2026): «Хук в клипмейкере, почему он там вообще
    # появился, что он постоянно исполняется, это, конечно, вообще нонсенс».
    # Найден при разборе чужого проекта: в магазине на Next.js при каждой
    # команде запускался этот файл.
    #
    # До сих пор решали только регулярки по тексту команды, и это опасно узкая
    # опора. VIDEO_RE ловит `video.js` — имя самой распространённой библиотеки
    # видеоплеера в вебе; ASSEMBLY_RE ловит `assemble*.py`. В чужом проекте с
    # такими именами хук СОРВАЛ БЫ работу, объясняя это правилом R08 про
    # предполёт съёмки — сообщением, из которого человек в том проекте не понял
    # бы ровно ничего.
    #
    # Поэтому: похоже на съёмку — ещё не повод. Нужно, чтобы папка была папкой
    # клипа (finde_projekt выше, по трём признакам ist_clip_projekt); проверка стоит
    # ПОСЛЕ регулярок, чтобы в обычной работе диск не трогать вовсе.

    if is_video:
        marker = lib.read_marker(pdir, "preflight-ok.json", ttl)
        is_kie = runs_script(cmd, KIE_VIDEO_RE, esc) and video_provider(cmd, pdir) != "bridge"
        if is_kie and runs_script(cmd, BRIDGE_VIDEO_RE, esc):
            block(
                "ГЕЙТ CLIPMAKER (R08): в одной команде съёмка и через Kie, и через мост Grok.\n"
                "Предполёт считает одно из двух: кредиты Kie или квоту моста. Раздели запуски."
            )
        if is_kie:
            kie_marker_check(marker, cmd, pdir, ttl)
        elif marker and marker.get("provider") == "api":
            block(
                "ГЕЙТ CLIPMAKER (R08): маркер предполёта посчитан для Kie, а партия идёт через мост Grok.\n"
                f"Папка: {pdir}\n"
                "Кредиты Kie и квота моста — разные деньги: маркер одного не пускает другое.\n"
                "Что сделать: python \"<plugin>/scripts/gate_preflight.py\" --project \"<папка>\" --provider bridge"
            )
        if not marker:
            block(
                "ГЕЙТ CLIPMAKER (R08): съёмка видео без предполёта заблокирована.\n"
                f"Свежего маркера .gates/preflight-ok.json нет в: {pdir}\n"
                + vorheriger_verbraucher(pdir) +
                "Что сделать:\n"
                "  1. python \"<plugin>/scripts/gate_preflight.py\" --project \"<папка проекта>\"\n"
                "  2. если папка проекта другая — задай $env:CLIP_PROJECT\n"
                f"Маркер живёт {ttl} мин и покрывает ОДНУ партию (R11)."
            )
        # Партия улетела — следующая требует нового предполёта. Вместе с гашением
        # остаётся записка: кто именно маркер забрал. Без неё потеря маркера молчит, а
        # хук решает по тексту команды и ошибаться будет снова — 03.10.2026 право на
        # партию унесла запись отчёта, в котором стояли слово python и имя съёмочного
        # скрипта. Записка превращает молчаливую потерю в читаемую причину.
        try:
            lib.write_marker(pdir, "preflight-used.json",
                             {"cmd": " ".join(cmd.split())[:200], "tool": tool})
        except Exception:
            pass
        try:
            (Path(pdir) / ".gates" / "preflight-ok.json").unlink()
        except Exception:
            pass
        sys.exit(0)

    if is_assembly:
        # R31: монтировать можно только сверенное. Маркер протухает не от времени,
        # а от появления новых роликов: докачали партию — сверка недействительна.
        marker = lib.read_marker(pdir, "conformance-ok.json", 0)
        newest = 0
        try:
            newest = max((p.stat().st_mtime for p in (Path(pdir) / "clips").glob("*.mp4")),
                         default=0)
        except Exception:
            pass
        if not marker or newest > marker.get("at", 0):
            stale = " (после сверки появились новые ролики)" if marker else ""
            block(
                f"ГЕЙТ CLIPMAKER (R31): монтаж без сверки со сценой заблокирован{stale}.\n"
                f"Свежего маркера .gates/conformance-ok.json нет в: {pdir}\n"
                "33 принятых ролика уже уезжали в монтаж чужими сценами — приёмка смотрела\n"
                "качество картинки и не сверяла кадр со сценой.\n"
                "Что сделать:\n"
                "  1. python \"<plugin>/scripts/gate_conformance.py\" --project \"<папка>\" --sheet\n"
                "  2. посмотреть clips/_review/contact-sheet-*.jpg глазами\n"
                "  3. проставить вердикты через панель: scene_ok + причина"
            )
        sys.exit(0)

    if is_frames or is_anchor:
        # Плотность визуала против энергии трека. Стоит ПЕРВЫМ, потому что это дефект
        # концепции: после него бессмысленно проверять шот-лист и промпты — они безупречно
        # опишут скучный клип. Цена пропуска (11.08.2026): два дня работы, 47 роликов,
        # вердикт «всё ради четырёх кадров, выбирать было нечего».
        if not lib.read_marker(pdir, "density-ok.json", 0):
            block(
                "ГЕЙТ CLIPMAKER (ПЛОТНОСТЬ): генерация без сверки визуала с музыкой заблокирована.\n"
                f"Маркера .gates/density-ok.json нет в: {pdir}\n"
                "Карта энергии трека и канон должны быть сведены ДО платного этапа:\n"
                "танцевальный трек с тремя якорями и медленной камерой даёт клип,\n"
                "в котором зрителю нечего смотреть, а переделка стоит уже кредитов.\n"
                "Что сделать:\n"
                "  1. python \"<plugin>/scripts/gate_density.py\" --project \"<папка проекта>\"\n"
                "  2. гейт упал — чинить КОНЦЕПЦИЮ (сценарий и канон), это бесплатно\n"
                "  3. разреженность намеренная — --sparse-ok \"причина словами\""
            )
        # Порядок студии в коде: промпт собирается из шот-листа, а не сочиняется.
        # Маркер script-ok не протухает — сценарий не устаревает за два часа.
        if not lib.read_marker(pdir, "script-ok.json", 0):
            block(
                "ГЕЙТ CLIPMAKER (СЦЕНАРИЙ): генерация без принятого шот-листа заблокирована.\n"
                f"Маркера .gates/script-ok.json нет в: {pdir}\n"
                "Промпты собираются из шот-листа, а не из головы: кадр без длины в долях,\n"
                "якоря и назначения нельзя ни проверить, ни воспроизвести при пересъёмке.\n"
                "Что сделать:\n"
                "  1. довести раскадровку до clip-memory/script/shotlist.json\n"
                "  2. python \"<plugin>/scripts/gate_script.py\" --project \"<папка проекта>\""
            )
        chto = "якоря" if is_anchor else "кадров"
        marker = lib.read_marker(pdir, "prompts-ok.json", ttl * 4)
        if not marker:
            block(
                f"ГЕЙТ CLIPMAKER (R05): генерация {chto} без проверки промптов заблокирована.\n"
                f"Свежего маркера .gates/prompts-ok.json нет в: {pdir}\n"
                "Что сделать:\n"
                "  1. python \"<plugin>/scripts/gate_prompts.py\" --project \"<папка проекта>\"\n"
                "  2. прогнать генератор с --dry и вычитать промпты глазами\n"
                "  3. запустить пакет\n"
                "Гейт больше НЕ требует залитых якорей, чтобы пройти: ожидание якорей едет\n"
                "в поле refs_pending того же маркера, и шаг I им открыт."
            )
        # Кадру сцены якорь нужен залитым, якорю — нет: он его и заливает. Маркер без
        # поля refs_pending писал прежний гейт, а тот появлялся только когда якоря уже
        # были в порядке, — значит отсутствие поля читается как «пусто».
        pending = marker.get("refs_pending") or []
        if is_frames and pending:
            block(
                "ГЕЙТ CLIPMAKER (R01): кадры сцен без залитых якорей заблокированы.\n"
                f"Ждём {len(pending)} якорей: {', '.join(pending)}\n"
                "Якорь держит то, что обязано быть одинаковым во всех сценах. Снять кадры\n"
                "раньше якоря — значит получить в каждом своё лицо и своё платье, и R04\n"
                "это уже не вылечит: i2i детали не удаляет.\n"
                "Что сделать:\n"
                "  1. шаг I: clip-anchors — снять якоря, приёмка Админом обязательна\n"
                "  2. node upload.js … → URL в canon.refs под именем якоря\n"
                "  3. python \"<plugin>/scripts/gate_prompts.py\" --project \"<папка проекта>\""
            )
        sys.exit(0)

if __name__ == "__main__":
    main()
