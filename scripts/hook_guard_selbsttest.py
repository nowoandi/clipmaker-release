# hook_guard_selbsttest.py — самопроверка границ хука.
#
# ПОВОД (Админ, 29.08.2026): «Хук в клипмейкере, почему он там вообще
# появился, что он постоянно исполняется, это, конечно, вообще нонсенс, надо
# сразу проанализировать, чтоб в следующий раз такого не случилось.»
#
# Что случилось. hook_guard.py висит на КАЖДОМ вызове Bash и PowerShell во всех
# проектах сразу — так устроены хуки плагина: плагин включён, значит хук стоит
# везде. Решал он только по регуляркам на текст команды, а VIDEO_RE ловит
# `video.js` — имя самой распространённой библиотеки видеоплеера в вебе.
#
# 29.08.2026 это сработало вживую: в чужом проекте (магазин на Next.js) команда
# `node video.js --build` была остановлена с сообщением про предполёт съёмки.
# Человек в том проекте не понял бы из него ничего.
#
# Поэтому в хук добавлена граница: похоже на съёмку — ещё не повод, папка
# должна быть папкой клипа. Этот файл сторожит именно ту границу, потому что
# она невидима: если она отвалится, всё продолжит работать — и только в чужих
# проектах начнут падать команды.
#
# ВТОРОЙ ПОВОД (18.09.2026, сессия Bravo). Внутри папки клипа хук
# останавливал команды, которые ничего не запускали. Только чтение:
#   foreach ($f in "frames\kie-jobs.json","frames.json","clips.json",
#                  "clips\clip-jobs.json") { Get-Content (Join-Path $b $f) }
# — «ГЕЙТ CLIPMAKER (R08): съёмка видео без предполёта», потому что шаблон
# clips.js совпадал с началом clips.json. И Get-Content assemble.py — «R31:
# монтаж без сверки», потому что шаблон ловил любое упоминание имени. При
# свежем маркере предполёта первое чтение ещё и сжигало маркер молча.
# Теперь хук останавливает только запуск: интерпретатор в команде или скрипт
# первым словом. Случаи ниже держат обе стороны: чтение проходит, запуск —
# в том числе старые копии вроде clips-bnb.js и Start-Process из роли съёмки —
# стоит, пока нет маркера.
#
# ТРЕТИЙ ПОВОД (26.09.2026, сессия Alpha). Остановлены два
# чтения — случаи ниже взяты дословно из журнала. Интерпретатор стоял в одной
# команде строки (python -c, python hook_guard.py), имя — аргументом grep в
# другой, а правило «интерпретатор где угодно» сложило их в запуск. Теперь звено,
# которое только читает, из разбора вычёркивается. Случаи с «2» рядом держат
# границу этого исключения: чтение, отданное в node, копия через >, подстановка
# $( ) и имя в переменной цикла по-прежнему стоят.
#
# ЧЕТВЁРТЫЙ ПОВОД (26.09.2026, та же сессия). Остановлен коммит самого плагина:
# git commit -q -F - <<'EOF' с сообщением про clips.js, python и
# "(cat clips.js | node)". Хук резал тело heredoc по строкам, и строки
# сообщения стали командами. Теперь тело — данные той команды, что его
# получает: git commit и читатель его не исполняют, python -, bash, cat | node и
# cat > файл — исполняют или отдают на запуск, и такие случаи стоят. То же для
# here-string PowerShell @'…'@ и @"…"@.
#
# Запуск:  python scripts/hook_guard_selbsttest.py
# Итог:    exit 0 — все случаи верны, exit 1 — какой-то нет.
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib  # noqa: E402  — тот же приём, что в hook_guard.py

# R22-Nachbar: ohne das druckt die Windows-Konsole (cp1252) bei kyrillischem
# Text einen UnicodeEncodeError statt des Ergebnisses. Beim ersten Lauf dieses
# Selbsttests genau so passiert.
lib.setup_io()

HOOK = Path(__file__).resolve().parent / "hook_guard.py"

# Имена собираются из кусков намеренно: если писать их целиком, ЭТОТ файл
# станет ловушкой для самого хука, когда его открывают через grep в командной
# строке. Та же грабля, что он и проверяет.
VIDEO_JS = "vid" + "eo.js"
CLIPS_JS = "cli" + "ps.js"
CLIPS_BNB_JS = "cli" + "ps-bnb.js"
CLIPS_JSON = "cli" + "ps.json"
FRAMES_JS = "fra" + "mes.js"
FRAMES_JSON = "fra" + "mes.json"
ASSEMBLE_REPORT_PY = "assem" + "ble_report.py"
ASSEMBLE_PY = "assem" + "ble.py"
EDIT_V2_PY = "ed" + "it-v2.py"
AGENT_SHOT_JS = "age" + "nt-shot.js"
AGENT_TEST_JS = "age" + "nt-test.js"
AGENT_UTIL_JS = "age" + "nt-utils.js"
FRAMES_SANDY_JS = "fra" + "mes-sandy.js"
T2I_JS = "t2" + "i.js"
I2I_JS = "i2" + "i.js"
ANCHOR_JS = "anc" + "hor.js"

# Две команды 26.09.2026 в том виде, в каком хук их остановил (журнал сессии
# afa22ebf). Имя подставляется, по той же причине, что выше.
LEDGER_UND_GREP = """cd "$LOCALAPPDATA/ClipMaker" 2>/dev/null && PYTHONIOENCODING=utf-8 python -c "
import json,datetime as dt
for line in open('ledger.jsonl',encoding='utf-8-sig'):
  line=line.strip()
  if not line: continue
  e=json.loads(line)
  if e.get('kind')=='snapshot':
    print(dt.datetime.fromtimestamp(e['at'],dt.UTC).isoformat(timespec='minutes'), json.dumps(e.get('grok'),ensure_ascii=False)[:300], e.get('note','')[:100])
"; cd "C:/ClipMaker/grok-bridge" && head -c 600 grok-sent-log.json.bak-2026-08-11; echo; grep -rn -i "16.08\\|09.08\\|20.09\\|27.09" budget.js @CLIPS@ sends.js quota-read.js | head""".replace("@CLIPS@", CLIPS_JS)
HOOK_IM_CYCLUS = """cd "C:/ClipMaker/projects/<проект>" && for c in 'grep -n foo budget.js @CLIPS@ sends.js' 'head -c 10 a.json; echo; grep -rn -i "x" budget.js @CLIPS@ sends.js | head'; do printf '%s' "{\\"tool_name\\":\\"Bash\\",\\"tool_input\\":{\\"command\\":$(python -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$c")}}" | python "C:/ClipMaker/plugin/scripts/hook_guard.py" >/dev/null 2>&1; echo "exit $? :: $c"; done""".replace("@CLIPS@", CLIPS_JS)
# Коммит 26.09.2026 в той форме, в какой его остановили: цепочка до него, тело с
# кавычками и скобками, push следующей строкой.
KOMMIT_HEREDOC = """cd "C:/ClipMaker/plugin" && git add scripts/hook_guard.py && git commit -q -F - <<'EOF'
0.8.4 — хук не принимает grep по @CLIPS@ за съёмку

python -c "…" стоял в одной команде, @CLIPS@ — аргументом grep в другой.
Звено решает по-старому, если дальше не читатель: "(cat @CLIPS@ | node)".
EOF
git push -q origin main""".replace("@CLIPS@", CLIPS_JS)
# Запись отчёта 03.10.2026 в той форме, в какой хук её остановил: в теле документа
# стоят слово python и имя съёмочного скрипта, вывод уходит в .md.
OTCHET_MD = """mkdir -p clip-memory/reports && cat > clip-memory/reports/gates-anchors.md <<'MDEOF'
Узкий список имён однажды пропустил съёмку мимо предполёта: @BNB@ не совпадал
ни с одним шаблоном. Проверяется python-скриптом, запуск идёт через node.
MDEOF
echo "записано"; wc -l clip-memory/reports/gates-anchors.md""".replace("@BNB@", CLIPS_BNB_JS)
OTCHET_MD_OHNE_QUOTES = OTCHET_MD.replace("<<'MDEOF'", "<<MDEOF")
# Ограничитель без кавычек сам по себе ещё не опасен: inert у тела считается по
# СОДЕРЖИМОМУ — подставлять нечего, значит и раскрывать нечего. Опасна подстановка
# в таком теле, и вот она. Проверено 03.10.2026: сначала ждал стопа от самого
# отсутствия кавычек, прогон показал, что правило тоньше.
OTCHET_MD_MIT_SUBST = ("cat > clip-memory/reports/g.md <<MDEOF\n"
                       "партия: $(node @CLIPS@ --block 1)\nMDEOF").replace("@CLIPS@", CLIPS_JS)
# Копия скрипта В документ — всё ещё копия: node исполнит её под любым расширением.
KOPIE_IN_DOKUMENT = f"cat {CLIPS_JS} > notes.md && node notes.md"
PYTHON_HEREDOC = """python - <<'EOF'
import subprocess
subprocess.run(["node", "@CLIPS@", "--block", "1"])
EOF
""".replace("@CLIPS@", CLIPS_JS)

# (Beschreibung, Kommando, Projektart, erwarteter Exit[, Werkzeug])
#   0 = durchlassen, 2 = blocken; Werkzeug по умолчанию Bash — от него зависит,
#   чем экранируют: \ в bash, ` в PowerShell.
FAELLE = [
    ("обычная команда в чужой папке", "git status", "fremd", 0),
    (f"{VIDEO_JS} в чужой папке — библиотека плеера, не съёмка", f"node {VIDEO_JS} --build", "fremd", 0),
    (f"{ASSEMBLE_REPORT_PY} в чужой папке — отчёт, не монтаж", f"python {ASSEMBLE_REPORT_PY}", "fremd", 0),
    (f"{CLIPS_JS} в чужой папке", f"node {CLIPS_JS}", "fremd", 0),
    ("съёмка в папке клипа без маркера — обязана встать", f"node {CLIPS_JS}", "klip", 2),
    ("генерация кадров в папке клипа без маркера — обязана встать", f"node {FRAMES_JS}", "klip", 2),
    ("генерация с --dry в папке клипа — свободна, ничего не тратит", f"node {FRAMES_JS} --dry", "klip", 0),
    ("проба модели в папке клипа — свободна", "node mc-video --help", "klip", 0),
    # 18.09.2026: имя как файл данных или цель чтения — не запуск.
    (f"чтение {CLIPS_JSON} — данные, не скрипт", f"Get-Content {CLIPS_JSON}", "klip", 0),
    (f"python читает {CLIPS_JSON} — запущен peek.py, а не съёмка", f"python peek.py {CLIPS_JSON}", "klip", 0),
    (f"чтение {ASSEMBLE_PY} — не монтаж", f"Get-Content {ASSEMBLE_PY}", "klip", 0),
    ("та самая команда 18.09: перебор json моста",
     f'foreach ($f in "frames\\kie-jobs.json","{FRAMES_JSON}","{CLIPS_JSON}","clips\\clip-jobs.json") '
     "{ Get-Content (Join-Path $b $f) -Raw }", "klip", 0),
    (f"копия {CLIPS_JS} перед правкой — не съёмка",
     f'Copy-Item "$b\\{CLIPS_JS}" "$b\\{CLIPS_JS}.bak-2026-09-18"', "klip", 0),
    # Запуск стоит по-прежнему, в каждой форме, в которой его запускали на деле.
    (f"{CLIPS_JS} с --project без маркера — обязана встать",
     f'node {CLIPS_JS} --project "C:/ClipMaker/projects/x"', "klip", 2),
    (f"старая копия {CLIPS_BNB_JS} без маркера — обязана встать", f"node {CLIPS_BNB_JS}", "klip", 2),
    ("Start-Process, как запускает роль съёмки (R22) — обязан встать",
     f'Start-Process -FilePath "node" -ArgumentList "{CLIPS_BNB_JS}","--block","1" -WindowStyle Hidden',
     "klip", 2),
    ("кадры по пути с пробелами — обязаны встать",
     f'node "C:\\ClipMaker\\projects\\x\\{FRAMES_JS}" --block 1', "klip", 2),
    (f"монтаж {EDIT_V2_PY} без сверки — обязан встать", f"python {EDIT_V2_PY}", "klip", 2),
    (f"монтаж прямым запуском .\\{ASSEMBLE_PY} — обязан встать", f".\\{ASSEMBLE_PY} --out final.mp4", "klip", 2),
    # 28.09.2026: черновик (аниматик) узнаётся явно и свободен; черновик, пишущий final, — монтаж.
    ("черновик draft_v1_build.py без сверки — свободен", "python draft_v1_build.py --only S21", "klip", 0),
    ("animatic.py — свободен", 'python animatic.py --project "C:/ClipMaker/projects/x"', "klip", 0),
    ("черновик, пишущий output/final.mp4, — обязан встать",
     "python draft_v1_build.py --out output/final.mp4", "klip", 2),
    # 26.09.2026: имя — аргумент читающей команды, интерпретатор — в соседней.
    (f"та самая команда 26.09: python читает ledger, grep ищет по {CLIPS_JS}",
     LEDGER_UND_GREP, "klip", 0),
    (f"та самая команда 26.09: цикл подаёт хуку строки grep по {CLIPS_JS}",
     HOOK_IM_CYCLUS, "klip", 0),
    (f"Get-Content {CLIPS_JS} | Select-String \"node\" — слово node лишь образец поиска",
     f'Get-Content "$b\\{CLIPS_JS}" | Select-String "node"', "klip", 0, "PowerShell"),
    # Граница исключения: чтение, которое на деле ведёт к запуску, стоит.
    (f"grep по {CLIPS_JS}, потом его запуск в той же строке — обязан встать",
     f"grep -n budget {CLIPS_JS}; node {CLIPS_JS}", "klip", 2),
    (f"cat {CLIPS_JS} | node — чтение отдано интерпретатору, обязан встать",
     f"cat {CLIPS_JS} | node", "klip", 2),
    (f"cat {CLIPS_JS} > shoot.js и node shoot.js — копия под другим именем, обязан встать",
     f"cat {CLIPS_JS} > shoot.js && node shoot.js", "klip", 2),
    (f"echo $(node {CLIPS_JS}) — запуск в подстановке, обязан встать",
     f"echo $(node {CLIPS_JS})", "klip", 2),
    (f"имя в переменной цикла, node $s — обязан встать",
     f"for s in {CLIPS_BNB_JS}; do node $s; done", "klip", 2),
    ("Start-Process с переносом строки через ` (PowerShell) — обязан встать",
     f'Start-Process -FilePath "node" `\n    -ArgumentList "{CLIPS_BNB_JS}","--block","1"',
     "klip", 2, "PowerShell"),
    # 26.09.2026: тело heredoc — данные получателя, а не строки команд.
    (f"heredoc-сообщение коммита про {CLIPS_JS} и python — текст, не запуск",
     f"git commit -F - <<'EOF'\nfix: {CLIPS_JS} liest budget via python\nEOF\n", "klip", 0),
    (f"тот самый коммит 26.09: цепочка, кавычки и \"(cat {CLIPS_JS} | node)\" в теле",
     KOMMIT_HEREDOC, "klip", 0),
    (f"git commit -m \"…{CLIPS_JS}…python…\" — тот же текст в кавычках",
     f'git commit -m "fix: {CLIPS_JS} liest budget via python"', "klip", 0),
    ("here-string PowerShell в git commit — текст, не запуск",
     f"@'\nfix: {CLIPS_JS} liest budget via python\n'@ | git commit -F -", "klip", 0, "PowerShell"),
    # Граница: тело, которое исполняют или отдают на запуск, стоит.
    (f"python - <<'EOF' запускает {CLIPS_JS} через subprocess — обязан встать",
     PYTHON_HEREDOC, "klip", 2),
    (f"bash <<EOF с node {CLIPS_JS} в теле — обязан встать",
     f"bash <<EOF\nnode {CLIPS_JS} --block 1\nEOF\n", "klip", 2),
    ("cat <<'EOF' | node — тело отдано интерпретатору, обязан встать",
     f"cat <<'EOF' | node\nrequire('./{CLIPS_JS}')\nEOF\n", "klip", 2),
    (f"cat > shoot.js <<'EOF' и node shoot.js — тело стало скриптом, обязан встать",
     f"cat > shoot.js <<'EOF'\nrequire('./{CLIPS_JS}')\nEOF\nnode shoot.js", "klip", 2),
    (f"cat <<EOF без кавычек: bash раскроет $(node {CLIPS_JS}) — обязан встать",
     f"cat <<EOF\nпартия: $(node {CLIPS_JS} --block 1)\nEOF\n", "klip", 2),
    (f"GIT_EDITOR=\"node {CLIPS_JS}\" git commit — git запустит редактор, обязан встать",
     f'GIT_EDITOR="node {CLIPS_JS}" git commit', "klip", 2),
    ("here-string PowerShell в python - — обязан встать",
     f"@'\nimport subprocess\nsubprocess.run(['node', '{CLIPS_JS}'])\n'@ | python -",
     "klip", 2, "PowerShell"),
    (f"@\"…$(node {CLIPS_JS})…\"@ в git commit — PowerShell раскроет $( ), обязан встать",
     f'@"\nпартия: $(node {CLIPS_JS})\n"@ | git commit -F -', "klip", 2, "PowerShell"),
    # 03.10.2026: режим Agent — самая дорогая отправка (≈7% недели против 1,8%),
    # и до этой правки ни одно имя из VIDEO_RE ей не подходило. Проба 18.09
    # сожгла 7% мимо предполёта именно так.
    (f"связка Agent {AGENT_SHOT_JS} без маркера — обязана встать",
     f'node {AGENT_SHOT_JS} --project "C:/ClipMaker/projects/x" --id AG1 --prompt p.txt', "klip", 2),
    (f"проба под другим именем {AGENT_TEST_JS} — тоже съёмка, обязана встать",
     f"node {AGENT_TEST_JS} --id AG1", "klip", 2),
    (f"{AGENT_UTIL_JS} в папке клипа — шаблон широкий намеренно, лучше лишний стоп, чем 7% мимо гейта",
     f"node {AGENT_UTIL_JS}", "klip", 2),
    (f"чтение {AGENT_SHOT_JS} — не съёмка", f"Get-Content {AGENT_SHOT_JS}", "klip", 0),
    (f"{AGENT_SHOT_JS} в чужой папке — не наше дело", f"node {AGENT_SHOT_JS}", "fremd", 0),
    # 03.10.2026: якоря (шаг I) и копия генератора кадров под проект (R32).
    (f"якорь {T2I_JS} без маркеров — обязан встать", f"node {T2I_JS} p.txt A1 out", "klip", 2),
    (f"производный якорь {I2I_JS} без маркеров — обязан встать",
     f'node {I2I_JS} https://x/a.png A2 "ubrat okno"', "klip", 2),
    (f"{ANCHOR_JS} без маркеров — обязан встать; до 03.10 хук его не видел вовсе, "
     f"и ровно им 18.09 ушли деньги мимо гейтов",
     f"node {ANCHOR_JS} anchor-v6 A1", "klip", 2),
    (f"{ANCHOR_JS} с --dry — освобождения у якорей нет, обязан встать",
     f"node {ANCHOR_JS} anchor-v6 A1 --dry", "klip", 2),
    (f"копия генератора под проект {FRAMES_SANDY_JS} без маркеров — обязана встать (R32)",
     f"node {FRAMES_SANDY_JS} --block 1", "klip", 2),
    (f"чтение {ANCHOR_JS} — не генерация", f"Get-Content {ANCHOR_JS}", "klip", 0),
    (f"{ANCHOR_JS} в чужой папке — не наше дело", f"node {ANCHOR_JS} anchor-v6", "fremd", 0),
    # 03.10.2026: запись документа. Markdown никто не запускает, поэтому обоснование
    # «вывод уходит в файл» (cat clips.js > shoot.js делает копию для запуска) на .md
    # не распространяется. Отчёт о самих гейтах встал на этом сообщением про предполёт.
    ("запись отчёта в .md, в тексте python и имя съёмочного скрипта — не съёмка",
     OTCHET_MD, "klip", 0),
    ("тот же отчёт с ограничителем без кавычек — подставлять в теле нечего, не съёмка",
     OTCHET_MD_OHNE_QUOTES, "klip", 0),
    ("запись в .md с подстановкой $(node …) в теле без кавычек — обязана встать",
     OTCHET_MD_MIT_SUBST, "klip", 2),
    ("копия скрипта в .md и запуск её через node — обязана встать: расширение ничего "
     "не решает, node исполнит любое",
     KOPIE_IN_DOKUMENT, "klip", 2),
    ("отчёт в .txt — то же освобождение, что у .md",
     OTCHET_MD.replace(".md", ".txt"), "klip", 0),
    ("отчёт в .md, а следующей командой настоящая съёмка — обязан встать",
     f"{OTCHET_MD}\nnode {CLIPS_JS} --block 1", "klip", 2),
    (f"копия под запуск всё ещё живая: cat > shoot.js и node shoot.js — обязан встать",
     f"cat > shoot.js <<'EOF'\nrequire('./{CLIPS_JS}')\nEOF\nnode shoot.js", "klip", 2),
]

# Шаг I (якоря) против шага J (кадры сцен) — оба ждут prompts-ok, но якорю ЗАЛИТЫЕ
# якоря не нужны: он их и заливает. До 03.10.2026 оба ждали одного маркера целиком,
# а гейт промптов не писал его, пока canon.refs пусты, — шаг якорей запирал сам себя,
# и в Bravo из этого вышел обход через anchor.js.
# refs_pending = None означает «prompts-ok не писали вовсе».
# (Beschreibung, Kommando, refs_pending, erwarteter Exit)
ANKER_FAELLE = [
    (f"якорь {T2I_JS} при ожидании якорей — шаг I открыт",
     f"node {T2I_JS} p.txt A1 out", ["beach", "heroine"], 0),
    (f"производный якорь {I2I_JS} при ожидании — открыт",
     f'node {I2I_JS} https://x/a.png A2 "ubrat okno"', ["beach"], 0),
    (f"{ANCHOR_JS} при ожидании — открыт, но теперь хук его ВИДИТ",
     f"node {ANCHOR_JS} anchor-v6 A1", ["beach"], 0),
    ("кадры сцен при ожидании якорей — обязаны встать (R01)",
     f"node {FRAMES_JS} --block 1", ["beach"], 2),
    (f"копия {FRAMES_SANDY_JS} при ожидании якорей — тоже встаёт",
     f"node {FRAMES_SANDY_JS} --block 1", ["beach"], 2),
    ("кадры сцен, якоря залиты — проходят",
     f"node {FRAMES_JS} --block 1", [], 0),
    ("якорь, якоря залиты — проходит тоже: пересъёмка якоря законна",
     f"node {T2I_JS} p.txt A1 out", [], 0),
    ("старый маркер без поля refs_pending — читается как «пусто», кадры проходят",
     f"node {FRAMES_JS} --block 1", "ohne_feld", 0),
    (f"кадры сцен с --dry при ожидании — освобождение настоящее, ничего не тратит",
     f"node {FRAMES_JS} --dry", ["beach"], 0),
]

# Маркер предполёта покрывает ОДНУ партию (R11): хук сжигает его при запуске.
# До 18.09.2026 его сжигало и чтение — отсюда отдельная проверка файла маркера.
# (Beschreibung, Kommando, erwarteter Exit, Marker bleibt)
MARKER_FAELLE = [
    (f"чтение {CLIPS_JSON} при свежем маркере — маркер цел", f"Get-Content {CLIPS_JSON}", 0, True),
    ("съёмка при свежем маркере — проходит и сжигает его", f"node {CLIPS_JS}", 0, False),
    # Из-за этого случая у agent-shot.js снята своя проверка маркера (03.10.2026):
    # хук гасит маркер ДО запуска скрипта, и проверка внутри скрипта увидела бы пустоту.
    (f"связка Agent при свежем маркере — проходит и сжигает его",
     f"node {AGENT_SHOT_JS} --id AG1", 0, False),
    # Самый дорогой из разобранных случаев: 03.10.2026 запись отчёта при свежем маркере
    # проходила МОЛЧА и уносила право на партию — следующая настоящая отправка встала бы
    # без понятной причины. Стоп был бы лишь неудобством, тихое гашение — нет.
    ("запись отчёта в .md при свежем маркере — маркер обязан остаться цел",
     OTCHET_MD, 0, True),
]


# ПЯТЫЙ ПОВОД (12.10.2026, <проект>). Роль якорей работала с cwd =
# корень клипов (C:\ClipMaker\projects — сам он не клип) и запускала платный
# генератор командой «Set-Location <клип>; node <pipeline>\anchor.js …». Хук брал
# папку из cwd события — а это cwd ДО Set-Location, — решал «чужой проект» и выходил
# с 0, не глядя на гейты. Случаи ниже строят ту же раскладку во временной папке:
# корень, клип без маркеров, клип со свежими маркерами, pipeline с project.example.json
# (как у настоящего — признак клипа на нём срабатывает) и чужую папку вне корня.
# Ожидаемый фрагмент сообщения отличает «встал на гейте проекта» от «проект не найден».
# (Beschreibung, Kommando-Vorlage, cwd, erwarteter Exit, Fragment, Werkzeug)
#   {proj} — клип без маркеров, {fertig} — клип с маркерами, {pipe} — pipeline.
ORT_FAELLE = [
    ("форма 12.10: cwd = корень, Set-Location в клип без маркеров — обязан встать на гейте клипа",
     'Set-Location "{proj}"; node "{pipe}\\' + ANCHOR_JS + '" anchor-heroine-v1',
     "wurzel", 2, "ПЛОТНОСТЬ", "PowerShell"),
    ("то же в bash: cd в клип && node — обязан встать на гейте клипа",
     'cd "{proj}" && node "{pipe}/' + ANCHOR_JS + '" anchor-heroine-v1',
     "wurzel", 2, "ПЛОТНОСТЬ", "Bash"),
    ("cwd = подпапка клипа anchors/ — клип её родитель, обязан встать на его гейте",
     'node "{pipe}\\' + ANCHOR_JS + '" anchor-heroine-v1',
     "anchors", 2, "ПЛОТНОСТЬ", "PowerShell"),
    ("cwd = корень, клипа в команде нет — проект не определён, обязан встать",
     'node "{pipe}\\' + ANCHOR_JS + '" anchor-heroine-v1',
     "wurzel", 2, "без папки проекта", "PowerShell"),
    ("cwd = pipeline — это инструмент, а не клип, хоть в нём и лежит project.example.json",
     f"node {ANCHOR_JS} anchor-v6", "pipe", 2, "без папки проекта", "PowerShell"),
    ("cwd = корень, путь к клипу только аргументом — клип найден по пути, обязан встать на его гейте",
     'node "{pipe}/' + FRAMES_SANDY_JS + '" --out "{proj}/frames"',
     "wurzel", 2, "ПЛОТНОСТЬ", "Bash"),
    ("cwd = корень, Set-Location в клип со свежими маркерами — проходит",
     'Set-Location "{fertig}"; node "{pipe}\\' + ANCHOR_JS + '" anchor-heroine-v1',
     "wurzel", 0, "", "PowerShell"),
    ("cwd = клип с маркерами, Set-Location в клип без них — решает место запуска, обязан встать",
     'Set-Location "{proj}"; node "{pipe}\\' + ANCHOR_JS + '" anchor-heroine-v1',
     "fertig", 2, "ПЛОТНОСТЬ", "PowerShell"),
    ("переход в два клипа в одной команде — какой проверять, неясно, обязан встать",
     'cd "{fertig}"; ls; cd "{proj}"; node "{pipe}/' + ANCHOR_JS + '" x',
     "wurzel", 2, "несколько проектов", "Bash"),
    ("cwd = корень, только чтение генератора — не запуск, свободно",
     'Get-Content "{pipe}\\' + ANCHOR_JS + '"', "wurzel", 0, "", "PowerShell"),
    (f"чужая папка вне корня, команда про {VIDEO_JS} — граница 29.08 цела",
     f"node {VIDEO_JS} --build", "fremd", 0, "", "Bash"),
]

# ШЕСТОЙ ПОВОД (12.10.2026, <проект>). Видео шло через Kie
# (video.js --provider api), а предполёт знал только квоту моста. Маркера не было,
# пока его не выбили --force-estimate, — и хук пустил бы по нему партию Kie, хотя
# денег Kie никто не считал. Теперь маркер несёт provider, а у Kie ещё и выборку,
# длительность и модель. Проект ниже нарочно с provider bridge, как настоящий: там
# Kie шёл только явным флагом.
#   (Beschreibung, Marker | None, Kommando, video.duration, Exit, Fragment, Marker bleibt, Werkzeug)
KIE_MARKER = {"provider": "api", "scenes": ["S01", "S02", "S03"], "only": True, "block": 0,
              "model": "grok-imagine/image-to-video", "duration": 6}
KIE_ALLE = dict(KIE_MARKER, scenes=["S01", "S02", "S03", "S04"], only=False)
BRUECKE = {"provider": "bridge", "planned": 4}
KIE_FAELLE = [
    ("Kie по маркеру Kie, --only внутри посчитанного — проходит и сжигает маркер",
     KIE_MARKER, f"node {VIDEO_JS} project.json --provider api --only S01,S02", 6, 0, "", False, "Bash"),
    ("Start-Process из роли съёмки, аргументы списком — разобран, проходит",
     KIE_MARKER, f'Start-Process -FilePath "node" -ArgumentList "{VIDEO_JS}","project.json","--provider","api",'
                 f'"--only","S01,S02,S03"', 6, 0, "", False, "PowerShell"),
    ("форма 12.10: Kie по маркеру моста — стоит, маркер цел",
     BRUECKE, f"node {VIDEO_JS} project.json --provider api --only S01", 6, 2, "посчитан для моста", True, "Bash"),
    ("Kie по старому маркеру без provider — это мост, стоит",
     {"planned": 4}, f"node {VIDEO_JS} project.json --provider api --only S01", 6, 2, "посчитан для моста", True, "Bash"),
    ("Kie без маркера — стоит с сообщением про Kie",
     None, f"node {VIDEO_JS} project.json --provider api --only S01", 6, 2, "через Kie без предполёта", None, "Bash"),
    ("Kie со сценой, которой предполёт не считал — стоит",
     KIE_MARKER, f"node {VIDEO_JS} project.json --provider api --only S03,S04", 6, 2, "не считал", True, "Bash"),
    ("предполёт на --only, команда без --only — video.js возьмёт всё, стоит",
     KIE_MARKER, f"node {VIDEO_JS} project.json --provider api", 6, 2, "без --only", True, "Bash"),
    ("предполёт на все сцены, команда без --only — проходит",
     KIE_ALLE, f"node {VIDEO_JS} project.json --provider api", 6, 0, "", False, "Bash"),
    ("после предполёта video.duration 6 → 10 (СТОП-2 сметы) — стоит",
     KIE_MARKER, f"node {VIDEO_JS} project.json --provider api --only S01", 10, 2, "сменились", True, "Bash"),
    ("провайдер в переменной — не понять, мост или Kie, стоит",
     KIE_MARKER, f"node {VIDEO_JS} project.json --provider $p --only S01", 6, 2, "не понял", True, "Bash"),
    ("video.js без --provider при video.provider = bridge — это мост, маркер Kie не пускает",
     KIE_MARKER, f"node {VIDEO_JS} project.json --only S01", 6, 2, "посчитан для Kie", True, "Bash"),
    ("съёмка мостом по маркеру Kie — стоит",
     KIE_MARKER, f"node {CLIPS_JS} --block 1", 6, 2, "посчитан для Kie", True, "Bash"),
    ("съёмка мостом по маркеру моста — как прежде, проходит и сжигает",
     BRUECKE, f"node {CLIPS_JS} --block 1", 6, 0, "", False, "Bash"),
    ("Kie и мост в одной команде — стоит",
     KIE_MARKER, f"node {VIDEO_JS} project.json --provider api --only S01; node {CLIPS_JS}", 6, 2,
     "и через Kie, и через мост", True, "Bash"),
]

KONFIG = None


def lauf(kommando, ordner, werkzeug="Bash", mit_text=False):
    payload = json.dumps({
        "tool_name": werkzeug,
        "cwd": str(ordner),
        "tool_input": {"command": kommando},
    })
    # CLIP_PROJECT leeren: sonst entscheidet die Umgebung des Prüfers mit.
    # CLIPMAKER_CONFIG — Testkonfiguration mit Pfaden im Temp-Ordner (main()).
    env = {"PATH": __import__("os").environ.get("PATH", ""), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    if KONFIG:
        env["CLIPMAKER_CONFIG"] = str(KONFIG)
    ergebnis = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload.encode("utf-8"),
        capture_output=True,
        env=env,
    )
    if mit_text:
        return ergebnis.returncode, ergebnis.stderr.decode("utf-8", "replace")
    return ergebnis.returncode


def main():
    global KONFIG
    with tempfile.TemporaryDirectory() as tmp:
        # Раскладка машины, но во временной папке: корень клипов, pipeline, мост.
        # Без неё случаи ниже зависели бы от того, где лежит настоящий D:\Projects.
        wurzel = Path(tmp) / "wurzel"
        pipe = Path(tmp) / "pipe"
        for d in (wurzel, pipe, Path(tmp) / "bruecke"):
            d.mkdir()
        (pipe / "project.example.json").write_text("{}", encoding="utf-8")
        cfg = lib.load_config()
        cfg.update({"project_roots": [str(wurzel)], "pipeline": str(pipe),
                    "grok_bridge": str(Path(tmp) / "bruecke")})
        KONFIG = Path(tmp) / "paths.json"
        KONFIG.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

        fremd = Path(tmp) / "fremd"
        klip = Path(tmp) / "klip"
        fremd.mkdir()
        klip.mkdir()
        # Минимальный признак папки клипа. Хук принимает три: project*.json,
        # clip-memory/, .gates/ — здесь проверяется первый.
        (klip / "project.json").write_text('{"name": "selbsttest"}', encoding="utf-8")

        ordner = {"fremd": fremd, "klip": klip}
        fehler = 0
        for beschreibung, kommando, art, erwartet, *werkzeug in FAELLE:
            tatsaechlich = lauf(kommando, ordner[art], *werkzeug)
            ok = tatsaechlich == erwartet
            if not ok:
                fehler += 1
            zeichen = "ok  " if ok else "FALSCH"
            print(f"{zeichen} [{art}] {beschreibung}: erwartet {erwartet}, bekommen {tatsaechlich}")

        marker = klip / ".gates" / "preflight-ok.json"
        for beschreibung, kommando, erwartet, bleibt in MARKER_FAELLE:
            lib.write_marker(klip, "preflight-ok.json", {"gate": "selbsttest"})
            tatsaechlich = lauf(kommando, klip)
            ok = tatsaechlich == erwartet and marker.exists() == bleibt
            if not ok:
                fehler += 1
            zeichen = "ok  " if ok else "FALSCH"
            soll = "Marker bleibt" if bleibt else "Marker weg"
            ist = "Marker bleibt" if marker.exists() else "Marker weg"
            print(f"{zeichen} [klip+marker] {beschreibung}: erwartet {erwartet}/{soll}, "
                  f"bekommen {tatsaechlich}/{ist}")

        # Шаг I против шага J: своя папка, чтобы маркеры гейтов разработки не мешали
        # случаям выше, где их нет вовсе.
        anker = Path(tmp) / "anker"
        anker.mkdir()
        (anker / "project.json").write_text('{"name": "selbsttest"}', encoding="utf-8")
        gates = anker / ".gates"
        for beschreibung, kommando, pending, erwartet in ANKER_FAELLE:
            lib.write_marker(anker, "density-ok.json", {"gate": "selbsttest"})
            lib.write_marker(anker, "script-ok.json", {"gate": "selbsttest"})
            (gates / "prompts-ok.json").unlink(missing_ok=True)
            if pending == "ohne_feld":
                lib.write_marker(anker, "prompts-ok.json", {"scenes": 22})
            elif pending is not None:
                lib.write_marker(anker, "prompts-ok.json", {"scenes": 22, "refs_pending": pending})
            tatsaechlich = lauf(kommando, anker)
            ok = tatsaechlich == erwartet
            if not ok:
                fehler += 1
            zeichen = "ok  " if ok else "FALSCH"
            warten = "ohne Feld" if pending == "ohne_feld" else (
                "ohne Marker" if pending is None else f"wartet auf {len(pending)}")
            print(f"{zeichen} [anker: {warten}] {beschreibung}: erwartet {erwartet}, "
                  f"bekommen {tatsaechlich}")

        # Где лежит проект (12.10.2026): cwd события против места запуска.
        proj = wurzel / "proj"
        fertig = wurzel / "fertig"
        for d in (proj, fertig):
            d.mkdir()
            (d / "project.json").write_text('{"name": "selbsttest"}', encoding="utf-8")
        (proj / "anchors").mkdir()
        for name in ("density-ok.json", "script-ok.json"):
            lib.write_marker(fertig, name, {"gate": "selbsttest"})
        lib.write_marker(fertig, "prompts-ok.json", {"scenes": 4, "refs_pending": []})
        orte = {"wurzel": wurzel, "anchors": proj / "anchors", "pipe": pipe,
                "fertig": fertig, "fremd": fremd}
        for beschreibung, vorlage, ort, erwartet, fragment, werkzeug in ORT_FAELLE:
            kommando = vorlage.format(proj=proj, fertig=fertig, pipe=pipe)
            tatsaechlich, text = lauf(kommando, orte[ort], werkzeug, mit_text=True)
            ok = tatsaechlich == erwartet and fragment in text
            if not ok:
                fehler += 1
            zeichen = "ok  " if ok else "FALSCH"
            hinweis = "" if ok or not text else " :: " + text.splitlines()[0]
            soll = f"{erwartet} «{fragment}»" if fragment else str(erwartet)
            print(f"{zeichen} [ort: {ort}] {beschreibung}: erwartet {soll}, "
                  f"bekommen {tatsaechlich}{hinweis}")

        # Мост против Kie (12.10.2026): своя папка, маркер на каждый случай свой.
        kie = Path(tmp) / "kie"
        kie.mkdir()
        k_marker = kie / ".gates" / "preflight-ok.json"
        for beschreibung, mk, kommando, dauer, erwartet, fragment, bleibt, werkzeug in KIE_FAELLE:
            (kie / "project.json").write_text(json.dumps({
                "project": "kie-selbsttest",
                "video": {"provider": "bridge", "model": "grok-imagine/image-to-video", "duration": dauer},
                "scenes": [{"id": f"S0{i}", "block": 1} for i in range(1, 5)],
            }), encoding="utf-8")
            k_marker.unlink(missing_ok=True)
            if mk is not None:
                lib.write_marker(kie, "preflight-ok.json", mk)
            tatsaechlich, text = lauf(kommando, kie, werkzeug, mit_text=True)
            ok = (tatsaechlich == erwartet and fragment in text
                  and (bleibt is None or k_marker.exists() == bleibt))
            if not ok:
                fehler += 1
            zeichen = "ok  " if ok else "FALSCH"
            hinweis = "" if ok or not text else " :: " + text.splitlines()[0]
            ist = "Marker bleibt" if k_marker.exists() else "Marker weg"
            print(f"{zeichen} [kie] {beschreibung}: erwartet {erwartet}, bekommen {tatsaechlich}/{ist}{hinweis}")

        gesamt = (len(FAELLE) + len(MARKER_FAELLE) + len(ANKER_FAELLE) + len(ORT_FAELLE)
                  + len(KIE_FAELLE))
        print()
        if fehler:
            print(f"{fehler} von {gesamt} Faellen falsch.")
            print("Bei exit 2 statt 0: der Hook greift in einem fremden Projekt oder bei einem")
            print("Kommando, das nichts startet — pruefe ist_clip_projekt() und runs_script()")
            print("in hook_guard.py. Bei 0 statt 2: das Gate ist offen, und Aufnahmen laufen")
            print("ohne Vorflug — das kostet Geld.")
            return 1
        print(f"Alle {gesamt} Faelle richtig.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
