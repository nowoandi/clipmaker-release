# clip_studio.py — студийная панель: весь проект в одном окне.
#
# Зачем: состояние клипа лежит в десятке файлов — шот-лист, канон, кадры, клипы,
# вердикты, смета. Читать их по одному больно, а пересказывать в чат ещё и неточно.
# Здесь Админ открывает браузер и видит раскадровку, кадры, материал и деньги сразу,
# переходя между разделами, а не разыскивая файлы.
#
#   python clip_studio.py --project "<папка>" [--port 7788] [--open]
#
# Без зависимостей: только стандартная библиотека. Данные читаются с диска при каждом
# запросе — панель ничего не кэширует и не хранит своего состояния (R: состояние в файлах).
# Панель только ПОКАЗЫВАЕТ. Вердикты по-прежнему ставятся в панели приёмки (R17),
# генерации запускают роли — отсюда ничего не тратится.
import argparse
import io
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
UI_FILE = PLUGIN_ROOT / "ui" / "studio.html"
PROJECT_DIR = None  # текущий проект; меняется через /api/select

# Конвейер студии для схемы: волна → роли. Порядок и связи — из PIPELINE.md,
# держать синхронно с ним: схема, расходящаяся с конвейером, хуже, чем её отсутствие.
WAVES = [
    ("Разработка", "бесплатно, ошибка ничего не стоит", [
        ("clip-researcher",          "Ресёрчер темы",        "research/dossier.md"),
        ("clip-musicologist",        "Музыкальный аналитик", "song/grid.json"),
        ("clip-screenwriter",        "Сценарист",            "script/treatment.md"),
        ("clip-production-designer", "Художник-постановщик", "canon/anchor-brief.json"),
        ("clip-dop",                 "Оператор",             "canon/camera.json"),
        ("clip-storyboard",          "Раскадровка",          "script/shotlist.json"),
        ("clip-prompt-writer",       "Промпт-инженер",       None),
    ]),
    ("Питч", "единственная точка, где решение стоит ноль", [
        ("clip-line-producer",       "Директор картины",     "reports/budget.json"),
    ]),
    ("Съёмка", "дальше каждый шаг стоит денег", [
        ("clip-anchors",             "Якоря",                None),
        ("clip-frames",              "Кадры",                None),
        ("clip-shoot",               "Съёмка движения",      None),
    ]),
    ("Приёмка и пост", "проверка отдельным проходом (R19)", [
        ("clip-guardian",            "Приёмка",              "reports/qa-report.json"),
        ("clip-editor",              "Монтажёр",             None),
        ("clip-script-supervisor",   "Скрипт-супервайзер",   "reports/passport.md"),
        ("clip-cfo",                 "Финансовый директор",  None),
        ("clip-doctor",              "Доктор",               "doctor/lessons.md"),
    ]),
]
FRAGMENT_NAME = {  # роль → файл фрагмента (имена короче имён ролей, так исторически)
    "clip-researcher": "researcher", "clip-musicologist": "musicologist",
    "clip-screenwriter": "screenwriter", "clip-production-designer": "production-designer",
    "clip-dop": "dop", "clip-storyboard": "storyboard", "clip-prompt-writer": "prompt-writer",
    "clip-line-producer": "line-producer", "clip-anchors": "anchors", "clip-frames": "frames",
    "clip-shoot": "shoot", "clip-guardian": "guardian", "clip-editor": "editor",
    "clip-script-supervisor": "script-supervisor", "clip-cfo": "cfo", "clip-doctor": "doctor",
}

# ── чтение состояния ────────────────────────────────────────────────────────────

def read_text(p, limit=200_000):
    try:
        with io.open(str(p), "r", encoding="utf-8-sig") as f:
            return f.read(limit)
    except Exception:
        return None

def read_json_safe(p):
    try:
        return lib.read_json(p)
    except Exception:
        return None

def _beats_label(n):
    """Склонение доли — делаем на сервере, чтобы интерфейс не знал про русскую грамматику."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    t, o = n % 100, n % 10
    if 11 <= t <= 14:
        word = "долей"
    elif o == 1:
        word = "доля"
    elif 2 <= o <= 4:
        word = "доли"
    else:
        word = "долей"
    return f"{n} {word}"

def frame_ar(project):
    """Пропорция карточки кадра в панели — по render проекта: 9/16 у клипа, 3/4 у рекламы. Без
    render — 9/16, как было до рекламной ветки; вписывать товар в чужую пропорцию панель не должна."""
    try:
        r = (project or {}).get("render") or {}
        w, h = int(r.get("width")), int(r.get("height"))
        if w > 0 and h > 0:
            return f"{w}/{h}"
    except Exception:
        pass
    return "9/16"


def collect():
    """Всё состояние проекта одним объектом. Ничего не домысливаем: чего нет — то null."""
    pdir = Path(PROJECT_DIR)
    mem = pdir / "clip-memory"
    project = None
    try:
        project = lib.read_json(lib.find_project_json(pdir))
    except Exception:
        pass

    grid = read_json_safe(mem / "song" / "grid.json") or {}
    if not grid and project:
        # В проектах старого образца сетка лежит прямо в project.json, в разделе song.
        song = {k: v for k, v in (project.get("song") or {}).items() if not k.startswith("_")}
        if song:
            grid = {"duration": song.get("duration"), "bpm": song.get("bpm"),
                    "beat": song.get("beat"), "bar": song.get("bar"),
                    "sections": (project.get("edit") or {}).get("sections") or []}
    shotlist = read_json_safe(mem / "script" / "shotlist.json") or {}
    anchors_brief = read_json_safe(mem / "canon" / "anchor-brief.json") or {}
    camera = read_json_safe(mem / "canon" / "camera.json") or {}
    budget = read_json_safe(mem / "reports" / "budget.json") or {}
    qa = read_json_safe(mem / "reports" / "qa-report.json") or {}

    verdicts = {}
    vj = read_json_safe(lib.verdicts_path(pdir))
    if isinstance(vj, list):
        for v in vj:
            verdicts[str(v.get("clip", "")).replace(".mp4", "")] = v.get("verdict", "")

    frames_dir, clips_dir = pdir / "frames", pdir / "clips"
    scenes = {s.get("id"): s for s in (project or {}).get("scenes", []) if s.get("id")}

    def media_flags(sid, src=None):
        """Медиа ищется по источнику, если он задан, иначе по номеру кадра.
        Один источник даёт несколько планов (разные точки входа и крупности) — поэтому
        файл называется по нему, а не по S-номеру: два кадра могут делить один ролик."""
        base = (src or "").strip() or sid
        frame_rel = f"frames/{base}.png"
        clip_rel = f"clips/{base}.mp4"
        v2_rel = f"clips/{base}_v2.mp4"
        return {
            "has_frame": (pdir / frame_rel).exists(),
            "has_clip": (pdir / clip_rel).exists(),
            "has_v2": (pdir / v2_rel).exists(),
            "frame_rel": frame_rel, "clip_rel": clip_rel, "v2_rel": v2_rel,
            "verdict": verdicts.get(base, "") or verdicts.get(sid, ""),
        }

    shots, legacy = [], False
    if shotlist.get("shots"):
        for sh in shotlist["shots"]:
            sid = sh.get("id")
            scene = scenes.get(sid, {})
            shots.append({
                **sh, **media_flags(sid, sh.get("src")),
                "len_label": _beats_label(sh.get("beats")),
                "weight": float(sh.get("beats") or 0),
                "prompt": scene.get("scene"),
                "motion_prompt": scene.get("motion"),
            })
    elif scenes:
        # Проект старого образца: шот-листа нет, но сцены в project.json есть.
        # Показываем их как есть — длина в секундах, разделы по блокам. Панель обязана
        # открывать и то, что снято до появления новой структуры.
        legacy = True
        for sid, sc in scenes.items():
            cut = sc.get("cut")
            shots.append({
                "id": sid,
                "section": f"блок {sc.get('block')}" if sc.get("block") is not None else "",
                "beats": None, "weight": float(cut or 1),
                "len_label": (f"{float(cut):.1f} с" if cut else ""),
                "size": "", "angle": "", "movement": "",
                "anchors": sc.get("refs") or [],
                "content": sc.get("scene"), "light": "", "note": "",
                "prompt": sc.get("scene"), "motion_prompt": sc.get("motion"),
                **media_flags(sid),
            })

    # Этапы разработки — те же, что печатает clip_status.py, чтобы картинки не расходились.
    stages = [
        ("Ресёрч темы",   mem / "research" / "dossier.md",     "clip-researcher"),
        ("Разбор трека",  mem / "song" / "grid.json",          "clip-musicologist"),
        ("Сценарий",      mem / "script" / "treatment.md",     "clip-screenwriter"),
        ("Канон мира",    mem / "canon" / "anchor-brief.json", "clip-production-designer"),
        ("Канон камеры",  mem / "canon" / "camera.json",       "clip-dop"),
        ("Раскадровка",   mem / "script" / "shotlist.json",    "clip-storyboard"),
        ("Промпты",       None,                                "clip-prompt-writer"),
        ("Смета",         mem / "reports" / "budget.json",     "clip-line-producer"),
    ]
    stage_rows = []
    for title, path, agent in stages:
        done = bool(scenes) if path is None else path.exists()
        stage_rows.append({"title": title, "done": done, "agent": agent,
                           "path": str(path.relative_to(pdir)) if path else "project.json"})

    docs = []
    for title, rel in [
        ("Досье темы",        "clip-memory/research/dossier.md"),
        ("Карта жанра",       "clip-memory/research/genre-map.md"),
        ("Референсы",         "clip-memory/research/references.md"),
        ("Факт-банк",         "clip-memory/research/fact-bank.md"),
        ("Логлайн",           "clip-memory/script/logline.md"),
        ("Тритмент",          "clip-memory/script/treatment.md"),
        ("Экспликация",       "clip-memory/script/direction.md"),
        ("Структура трека",   "clip-memory/song/structure.md"),
        ("Питч",              "clip-memory/reports/pitch.md"),
        ("Паспорт",           "clip-memory/reports/passport.md"),
        ("Handoff",           "clip-memory/01-handoff.md"),
    ]:
        if (pdir / rel).exists():
            docs.append({"title": title, "rel": rel})

    gates = {}
    for name in ("research-ok.json", "script-ok.json", "prompts-ok.json", "preflight-ok.json"):
        gates[name.replace("-ok.json", "")] = (pdir / ".gates" / name).exists()

    n_frames = len(list(frames_dir.glob("*.png"))) if frames_dir.exists() else 0
    n_clips = len(list(clips_dir.glob("S*.mp4"))) if clips_dir.exists() else 0

    return {
        "project_dir": str(pdir),
        "project_name": (project or {}).get("project") or pdir.name,
        "frame_ar": frame_ar(project),
        "grid": grid,
        "shotlist": {k: v for k, v in shotlist.items() if k != "shots"},
        "shots": shots,
        "legacy": legacy,
        "anchors": anchors_brief.get("anchors") or [],
        "canon_refs": ((project or {}).get("canon") or {}).get("refs") or {},
        "camera": camera,
        "budget": budget,
        "qa": qa,
        "stages": stage_rows,
        "gates": gates,
        "docs": docs,
        "counts": {"frames": n_frames, "clips": n_clips,
                   "accepted": sum(1 for v in verdicts.values() if v == "accept"),
                   "rejected": sum(1 for v in verdicts.values() if v == "reject")},
        "next_step": next_step(),
        "generated_at": time.strftime("%d.%m.%Y %H:%M"),
    }

def write_starter(pdir):
    """Кладёт в папку проекта START.bat: двойной щелчок открывает Claude Code прямо здесь
    с нужной командой. Запускает человек, а не панель — прогон тратит деньги.
    Только ASCII внутри: cmd читает .bat в OEM-кодировке (R22)."""
    bat = Path(pdir) / "START.bat"
    # Двойной щелчок должен ЗАПУСКАТЬ работу, а не открывать окно, куда ещё надо
    # что-то вставлять. Команда передаётся Claude Code сразу; человек запускает сам.
    text = (
        "@echo off\r\n"
        "rem ClipMaker: start the studio on this project.\r\n"
        "rem ASCII only - cmd reads .bat in the OEM codepage (R22).\r\n"
        "chcp 65001 >nul\r\n"
        "title ClipMaker project\r\n"
        "cd /d \"%~dp0\"\r\n"
        "echo.\r\n"
        "echo   ClipMaker\r\n"
        "echo   ---------------------------------------------\r\n"
        "echo    1  start development  (research to pitch, free)\r\n"
        "echo    2  continue           (resume where it stopped)\r\n"
        "echo    3  just open Claude Code here\r\n"
        "echo.\r\n"
        "set \"CMD=/clipmaker:clip-new\"\r\n"
        "set /p PICK=  choice [1]: \r\n"
        "if \"%PICK%\"==\"2\" set \"CMD=/clipmaker:clip-continue\"\r\n"
        "if \"%PICK%\"==\"3\" set \"CMD=\"\r\n"
        "echo.\r\n"
        "if \"%CMD%\"==\"\" (claude) else (claude \"%CMD%\")\r\n"
    )
    try:
        with io.open(str(bat), "w", encoding="ascii", newline="") as f:
            f.write(text)
        return str(bat)
    except Exception:
        return None

def next_step():
    """Что человеку делать прямо сейчас: точная команда и папка, где её выполнить.
    Панель агентов не запускает: прогон тратит деньги и начинается с ведома человека."""
    pdir = Path(PROJECT_DIR)
    mem = pdir / "clip-memory"
    if not (mem / "00-brief.md").exists():
        return {"title": "Завести проект", "command": None, "where": str(pdir),
                "hint": "Раздел «＋ Новый клип»: название, тема, трек."}
    starter = pdir / "START.bat"
    if not starter.exists():
        write_starter(pdir)
    if not (mem / "research" / "dossier.md").exists():
        return {"title": "Запустить разработку", "command": "/clipmaker:clip-new",
                "where": str(pdir), "starter": str(starter),
                "hint": "Двойной щелчок по START.bat в папке проекта, дальше Enter — работа началась. "
                        "Студия пройдёт ресёрч, музыку, сценарий, канон, раскадровку и промпты "
                        "и остановится на питче: до него не тратится ничего."}
    return {"title": "Продолжить прогон", "command": "/clipmaker:clip-continue",
            "where": str(pdir), "starter": str(starter),
            "hint": "Двойной щелчок по START.bat, пункт 2 — прогон продолжится с первого "
                    "незакрытого шага. Состояние читается с диска, оплаченное не перегенерируется."}

def pipeline_state():
    """Кто из ролей отработал, кто следующий. Статус берётся из фрагмента роли —
    из той же строки «## Статус: …», которую роль пишет по decision-contract."""
    pdir = Path(PROJECT_DIR)
    mem = pdir / "clip-memory"
    frags = mem / "fragments"
    gates = {n.replace("-ok.json", ""): (pdir / ".gates" / n).exists()
             for n in ("research-ok.json", "script-ok.json", "prompts-ok.json", "preflight-ok.json")}

    def role_state(agent, artifact):
        frag = frags / f"{FRAGMENT_NAME.get(agent, agent)}.md"
        status, line = "pending", ""
        if frag.exists():
            text = read_text(frag, limit=4000) or ""
            for raw in text.splitlines():
                if "Статус" in raw:
                    line = raw.split(":", 1)[-1].strip()
                    break
            low = line.lower()
            if "blocker" in low or "❌" in line:
                status = "blocker"
            elif "needs" in low or "fixes" in low or "⚠️" in line:
                status = "attention"
            elif "skip" in low or "⏭" in line:
                status = "skipped"
            elif line:
                status = "done"
            else:
                status = "done"
        elif artifact and (mem / artifact).exists():
            status, line = "done", "по артефакту на диске"
        return {"agent": agent, "status": status, "note": line,
                "artifact": artifact, "has_fragment": frag.exists()}

    waves, first_pending = [], None
    for title, subtitle, roles in WAVES:
        items = []
        for agent, human, artifact in roles:
            st = role_state(agent, artifact)
            st["title"] = human
            if st["status"] == "pending" and first_pending is None:
                first_pending = agent
            items.append(st)
        waves.append({"title": title, "subtitle": subtitle, "roles": items})
    return {"waves": waves, "gates": gates, "next": first_pending}

def list_projects():
    """Список проектов для переключения прямо в панели."""
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    import clip_open
    cfg = lib.load_config()
    out = []
    for d in clip_open.find_projects(cfg):
        out.append({"name": d.name, "dir": str(d), "about": clip_open.describe(d),
                    "current": str(d) == str(PROJECT_DIR)})
    cur = Path(PROJECT_DIR)
    if not any(p["current"] for p in out):
        out.insert(0, {"name": cur.name, "dir": str(cur),
                       "about": "открыт сейчас", "current": True})
    return out

def create_project(payload):
    """Заводит проект с диска: папка латиницей (R25), память по протоколу, бриф с темой.
    Панель не запускает агентов — она готовит вход и отдаёт команду для Claude Code."""
    import lang_policy
    title = (payload.get("title") or "").strip()
    if not title:
        return {"error": "не задано название клипа"}
    cfg = lib.load_config()
    # Новый проект кладётся в отведённую под клипы папку, а не внутрь соседнего проекта:
    # project_roots перечисляет и сами проекты тоже, брать оттуда первый попавшийся нельзя.
    base = payload.get("root") or cfg.get("new_project_root")
    if not base:
        for r in (cfg.get("project_roots") or []):
            p = Path(r)
            if not (p / "clip-memory").exists() and not list(p.glob("project*.json")):
                base = r
                break
    base = Path(base or Path.home() / "ClipMaker")
    base.mkdir(parents=True, exist_ok=True)

    name = lang_policy.slug(title)
    target = base / name
    n = 2
    while target.exists():
        target, n = base / f"{name}-{n}", n + 1
    mem = target / "clip-memory"
    for sub in ("fragments", "research", "song", "script", "canon", "reports", "doctor"):
        (mem / sub).mkdir(parents=True, exist_ok=True)
    for sub in ("frames", "clips", "output"):
        (target / sub).mkdir(exist_ok=True)

    tpl = lib.read_json(PLUGIN_ROOT / "shared" / "project-template.json")
    tpl["project"] = name
    lib.write_json(target / f"project.{name}.json", tpl)

    brief = [f"# Бриф · {title}", "",
             f"Заведён из студийной панели {time.strftime('%d.%m.%Y %H:%M')}.", ""]
    for label, key in (("Тема", "theme"), ("Трек", "track"),
                       ("Ограничения", "limits"), ("Референсы", "refs")):
        val = (payload.get(key) or "").strip()
        brief.append(f"## {label}")
        brief.append(val if val else "_не задано — спросить у Админа_")
        brief.append("")
    with io.open(str(mem / "00-brief.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(brief))

    write_starter(target)

    return {"dir": str(target), "name": name,
            "command": f'/clipmaker:clip-new "{title}"',
            "hint": "Открой Claude Code в этой папке и запусти команду — студия пойдёт от ресёрча до питча."}

def money():
    """Отчёт бухгалтерии — тем же скриптом, что и в чате: одна правда на оба канала."""
    try:
        out = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "clip_ledger.py"), "report", "--days", "90"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        return {"text": (out.stdout or "") + (out.stderr or "")}
    except Exception as e:
        return {"text": f"бухгалтерия недоступна: {type(e).__name__}: {e}"}

# ── сервер ──────────────────────────────────────────────────────────────────────

def safe_under(root, rel):
    """Файлы отдаём только изнутри папки проекта: панель не должна стать файловым менеджером."""
    target = (Path(root) / rel).resolve()
    root = Path(root).resolve()
    if root == target or root in target.parents:
        return target
    return None

# Буфер отправки у сокета — 64 КБ, а состояние проекта давно больше: у <проект>
# 238 КБ. Пока клиент читает, разницы не видно; если он встал, запись одной строкой
# ждёт его без срока — поток панели виснет навсегда, и молча.
# 03.10.2026 /api/state так и оборвался: ушёл ровно один буфер (65536 = 189 байт
# заголовков + 65347 тела), дальше тишина до таймаута клиента. Повторить потом не
# удалось: ни в этом коде, ни в данных дефекта не нашли — отправка упиралась во
# что-то вне панели. Но след потерялся здесь, в «except Exception: pass» под записью,
# и неделю разбирались догадками. Поэтому: ждать с ограничением и говорить вслух.
SEND_CHUNK = 65536           # один буфер сокета за проход
SEND_STALL_S = 20.0          # сколько ждём клиента, который перестал читать
SEND_STALL_MEDIA_S = 600.0   # видео браузер тянет рывками: пауза в минуты здесь норма

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # тишина: панель не должна засорять консоль роли

    def _write_all(self, data, stall_s):
        """Отдать тело целиком. Возвращает, сколько ушло и что помешало.

        Срок стоит на каждой части и отсчитывается заново, пока дело идёт: медленный,
        но живой клиент дотянет ответ любой длины, а замерший отпустит поток за stall_s.
        """
        sock = self.connection
        was = sock.gettimeout()
        sock.settimeout(stall_s)
        view = memoryview(data)
        sent = 0
        try:
            while sent < len(view):
                n = sock.send(view[sent:sent + SEND_CHUNK])
                if not n:                      # страховка от вечного круга
                    return sent, "сокет принял 0 байт"
                sent += n
            return sent, None
        except Exception as e:
            return sent, f"{type(e).__name__}: {e}"
        finally:
            view.release()
            try:
                sock.settimeout(was)
            except Exception:
                pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", stall_s=SEND_STALL_S):
        data = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        sent, err = self._write_all(data, stall_s)
        if sent != len(data):
            # Недописанный ответ — это обрезанный JSON на той стороне. Про него надо
            # сказать вслух: иначе панель выглядит пустой, и в консоли пусто тоже.
            self.close_connection = True
            print(f"панель: ответ {self.path} оборван — ушло {sent} из {len(data)} байт"
                  + (f"; {err}" if err else ""), file=sys.stderr, flush=True)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            html = read_text(UI_FILE, limit=2_000_000)
            if html is None:
                return self._send(500, "ui/studio.html не найден", "text/plain; charset=utf-8")
            return self._send(200, html, "text/html; charset=utf-8")

        if u.path == "/api/state":
            return self._send(200, json.dumps(collect(), ensure_ascii=False))

        if u.path == "/api/money":
            return self._send(200, json.dumps(money(), ensure_ascii=False))

        if u.path == "/api/pipeline":
            return self._send(200, json.dumps(pipeline_state(), ensure_ascii=False))

        if u.path == "/api/projects":
            return self._send(200, json.dumps({"projects": list_projects()}, ensure_ascii=False))

        if u.path == "/api/next":
            return self._send(200, json.dumps(next_step(), ensure_ascii=False))

        if u.path == "/api/doc":
            rel = (q.get("rel") or [""])[0]
            target = safe_under(PROJECT_DIR, rel)
            if not target or not target.exists():
                return self._send(404, json.dumps({"error": "нет файла"}))
            return self._send(200, json.dumps({"rel": rel, "text": read_text(target)}, ensure_ascii=False))

        if u.path.startswith("/media/"):
            rel = u.path[len("/media/"):]
            target = safe_under(PROJECT_DIR, rel)
            if not target or not target.exists() or not target.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            try:
                return self._send(200, target.read_bytes(), ctype, stall_s=SEND_STALL_MEDIA_S)
            except Exception:
                return self._send(500, b"read error", "text/plain")

        return self._send(404, json.dumps({"error": "нет такого адреса"}))

    def do_POST(self):
        global PROJECT_DIR
        u = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            return self._send(400, json.dumps({"error": "не разобрал запрос"}))

        if u.path == "/api/select":
            d = Path(payload.get("dir") or "")
            if not d.exists() or not d.is_dir():
                return self._send(404, json.dumps({"error": "папка не найдена"}, ensure_ascii=False))
            PROJECT_DIR = str(d)
            lib.remember("last_project", PROJECT_DIR)
            return self._send(200, json.dumps({"ok": True, "dir": PROJECT_DIR}, ensure_ascii=False))

        if u.path == "/api/reveal":
            # Открыть папку проекта в проводнике: оттуда человек запускает START.bat.
            try:
                os.startfile(str(Path(PROJECT_DIR)))   # noqa: S606 — только папка проекта
                return self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))

        if u.path == "/api/new":
            res = create_project(payload)
            if res.get("error"):
                return self._send(400, json.dumps(res, ensure_ascii=False))
            PROJECT_DIR = res["dir"]        # сразу открываем заведённый проект
            lib.remember("last_project", PROJECT_DIR)
            return self._send(200, json.dumps(res, ensure_ascii=False))

        return self._send(404, json.dumps({"error": "нет такого адреса"}, ensure_ascii=False))

def export(out_path, max_media_mb=12):
    """Автономный снимок: тот же интерфейс, но данные и превью внутри файла.
    Нужен, чтобы показать состояние там, где сервера нет — в чате, в архиве прогона."""
    import base64
    import tempfile
    state = collect()
    pdir = Path(PROJECT_DIR)

    # Кадры Kie весят по мегабайту-другому; в снимок они идут миниатюрами, иначе файл
    # получается неподъёмным. Уменьшает ffmpeg — он всё равно нужен плагину (R22).
    ffmpeg = None
    try:
        cand = Path(lib.load_config().get("ffmpeg", ""))
        ffmpeg = str(cand) if cand.exists() else None
    except Exception:
        pass

    def thumb_bytes(path):
        if ffmpeg:
            tmp = Path(tempfile.gettempdir()) / f"clipmaker_thumb_{path.stem}.jpg"
            try:
                subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(path),
                                "-vf", "scale=320:-2", "-q:v", "6", str(tmp)],
                               capture_output=True, timeout=30)
                if tmp.exists() and tmp.stat().st_size:
                    data = tmp.read_bytes()
                    tmp.unlink(missing_ok=True)
                    return data, "image/jpeg"
            except Exception:
                pass
        return path.read_bytes(), "image/png"

    media, budget_left = {}, max_media_mb * 1024 * 1024
    for s in state["shots"]:
        rel = s.get("frame_rel") or f"frames/{s['id']}.png"
        p = pdir / rel
        if s.get("has_frame") and p.exists() and rel not in media:
            data, mime = thumb_bytes(p)
            if len(data) > budget_left:
                continue
            budget_left -= len(data)
            media[rel] = f"data:{mime};base64," + base64.b64encode(data).decode()
    for name, url in (state.get("canon_refs") or {}).items():
        pass  # якоря лежат по URL провайдера — в снимок не вшиваются

    docs = {}
    for d in state["docs"]:
        docs[d["rel"]] = read_text(pdir / d["rel"], limit=60_000)

    html = read_text(UI_FILE, limit=2_000_000) or ""
    payload = json.dumps({"state": state, "media": media, "docs": docs,
                          "pipeline": pipeline_state(), "money": money()["text"]},
                         ensure_ascii=False)
    inject = "<script>window.__SNAPSHOT__ = " + payload + ";</script>\n"
    html = html.replace("</head>", inject + "</head>", 1)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with io.open(str(out_path), "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    size = Path(out_path).stat().st_size / 1024 / 1024
    print(f"снимок: {out_path} ({size:.1f} МБ, кадров вшито {len(media)}, документов {len(docs)})")
    print("видео в снимок не вшивается — только кадры, тексты и цифры.")

def main():
    global PROJECT_DIR
    lib.setup_io()
    ap = argparse.ArgumentParser(description="Студийная панель ClipMaker")
    ap.add_argument("--project", default=None)
    ap.add_argument("--port", type=int, default=7788)
    ap.add_argument("--open", action="store_true", help="открыть браузер")
    ap.add_argument("--export", default=None, metavar="ФАЙЛ",
                    help="сохранить автономный снимок и выйти (сервер не поднимается)")
    args = ap.parse_args()

    PROJECT_DIR = str(lib.project_dir(args.project))
    if not Path(PROJECT_DIR).exists():
        lib.fail(f"папка проекта не найдена: {PROJECT_DIR}")

    if args.export:
        return export(args.export)

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Студия ClipMaker: {url}")
    print(f"проект: {PROJECT_DIR}")
    print("панель только показывает: вердикты — в панели приёмки (R17), генерации — у ролей.")
    print("Ctrl+C — остановить.")
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено.")

if __name__ == "__main__":
    main()
