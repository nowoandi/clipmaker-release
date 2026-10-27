# clip_open.py — «нажал и открылось». Находит проекты клипов, поднимает студию, открывает браузер.
#
# Это точка входа для человека, а не для роли: ярлык на рабочем столе ведёт сюда.
# Один проект — открывается сразу. Несколько — короткое меню. Ни одного — честно об этом
# говорит и не делает вид, что что-то нашёл.
#
#   python clip_open.py [--project <папка>] [--port 7788] [--no-browser]
import argparse
import socket
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

SKIP = {"example", "template", "_thumbs", "node_modules", "__pycache__"}

def looks_like_project(d):
    """Проект клипа — это папка с файлом проекта или с памятью студии."""
    if not d.is_dir() or d.name.lower() in SKIP:
        return False
    if (d / "clip-memory").is_dir():
        return True
    for p in d.glob("project*.json"):
        if not any(s in p.stem.lower() for s in SKIP):
            return True
    return False

def find_projects(cfg, extra_roots=()):
    roots = [Path(r) for r in (cfg.get("project_roots") or [])]
    roots += [Path(r) for r in extra_roots if r]
    # Папки инструментов не проекты, даже если внутри лежит project*.json:
    # в pipeline-v3 живут генераторы и примеры, у моста — своя кухня.
    tools = {str(Path(cfg[k]).resolve()).lower() for k in ("pipeline", "grok_bridge") if cfg.get(k)}
    found, seen = [], set()
    for root in roots:
        if not root.exists():
            continue
        if looks_like_project(root):
            cands = [root]
        else:
            cands = [d for d in root.iterdir() if d.is_dir()]
        for d in cands:
            key = str(d.resolve())
            if key.lower() in tools:
                continue
            if looks_like_project(d) and key not in seen:
                seen.add(key)
                # свежесть — по самому позднему изменению внутри памяти или папки
                mtimes = [d.stat().st_mtime]
                mem = d / "clip-memory"
                if mem.exists():
                    mtimes += [p.stat().st_mtime for p in mem.rglob("*") if p.is_file()][:400]
                found.append((max(mtimes), d))
    found.sort(reverse=True)
    return [d for _, d in found]

def describe(d):
    """Короткая строка о проекте: что уже сделано. Без домыслов — только по файлам."""
    mem = d / "clip-memory"
    bits = []
    n_shots = 0
    sl = mem / "script" / "shotlist.json"
    if sl.exists():
        try:
            n_shots = len(lib.read_json(sl).get("shots") or [])
        except Exception:
            pass
    def plural(n, one, few, many):
        t, o = n % 100, n % 10
        return f"{n} " + (many if 11 <= t <= 14 else one if o == 1 else few if 2 <= o <= 4 else many)

    if n_shots:
        bits.append(plural(n_shots, "кадр", "кадра", "кадров") + " в плане")
    for name, forms in (("frames", ("кадр", "кадра", "кадров")),
                        ("clips", ("клип", "клипа", "клипов"))):
        p = d / name
        if p.exists():
            n = len(list(p.glob("*.png" if name == "frames" else "S*.mp4")))
            if n:
                bits.append(plural(n, *forms) + (" снято" if name == "frames" else ""))
    if not bits:
        bits.append("пусто" if not mem.exists() else "только начат")
    return " · ".join(bits)

def wait(msg):
    """Пауза перед закрытием окна. Без консоли (фоновый запуск) — просто выходим."""
    try:
        input(msg)
    except (EOFError, KeyboardInterrupt):
        pass

def port_busy(port):
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0

def studio_here(port):
    """Наша ли студия на этом порту и с каким проектом. Иначе плодятся панели
    на соседних портах, и человек смотрит не в ту — это уже случалось."""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1.5) as r:
            data = _json.loads(r.read().decode("utf-8"))
        return data.get("project_dir")
    except Exception:
        return None

def free_port(start):
    for port in range(start, start + 20):
        if not port_busy(port):
            return port
    return start

def choose(projects):
    last = lib.read_state().get("last_project")
    print("\n  Проекты клипов:\n")
    for i, d in enumerate(projects, 1):
        mark = "  ← последний" if last and str(Path(last).resolve()) == str(d.resolve()) else ""
        print(f"   {i}. {d.name}{mark}")
        print(f"      {describe(d)}")
        print(f"      {d}")
    print()
    while True:
        raw = input("  номер проекта (Enter — первый, q — выход): ").strip().lower()
        if raw in ("q", "quit", "exit"):
            return None
        if not raw:
            return projects[0]
        if raw.isdigit() and 1 <= int(raw) <= len(projects):
            return projects[int(raw) - 1]
        print("  не понял, повтори.")

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser(description="Открыть студию ClipMaker")
    ap.add_argument("--project", default=None)
    ap.add_argument("--port", type=int, default=7788)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--pick", action="store_true", help="показать список проектов, даже если помним последний")
    args = ap.parse_args()

    cfg = lib.load_config()
    print("\n  ClipMaker · Студия")
    print("  " + "─" * 46)

    target = Path(args.project) if args.project else None
    if target and not target.exists():
        print(f"  папка не найдена: {target}")
        target = None

    if not target:
        projects = find_projects(cfg)
        # Последний открытый проект идёт первым: студия помнит, где мы остановились.
        last = lib.read_state().get("last_project")
        if last and Path(last).exists():
            lastp = Path(last)
            projects = [lastp] + [p for p in projects if str(p.resolve()) != str(lastp.resolve())]
        if not projects:
            roots = ", ".join(cfg.get("project_roots") or []) or "(не заданы)"
            print("  Проектов клипов не нашлось.")
            print(f"  Искал в: {roots}")
            print("  Где искать — ключ project_roots в config/paths.json плагина.")
            print("  Новый клип заводится командой /clipmaker:clip-new в Claude Code.\n")
            wait("  Enter — закрыть окно...")
            return
        # Помним, где остановились: последний проект открывается сразу, без вопросов.
        # Меню — когда памяти нет и проектов несколько, либо по явному --pick.
        if args.pick or (len(projects) > 1 and not (last and Path(last).exists())):
            target = choose(projects)
            if target is None:
                return
        else:
            target = projects[0]
            if len(projects) > 1:
                print(f"  открываю последний проект: {target.name}")
                print("  другой — запуск с ключом --pick или смена проекта в самой панели")

    lib.remember("last_project", target)   # в следующий раз откроется он же

    # Студия уже открыта на этом порту — не поднимаем вторую, просто показываем её.
    if port_busy(args.port):
        running = studio_here(args.port)
        if running:
            url = f"http://127.0.0.1:{args.port}/"
            same = Path(running).resolve() == Path(target).resolve()
            print(f"\n  студия уже работает: {url}")
            print(f"  открытый проект: {Path(running).name}")
            if not same:
                print(f"  нужен другой ({Path(target).name}) — смени проект в самой панели,")
                print("  щелчком по названию слева вверху")
            if not args.no_browser:
                webbrowser.open(url)
            wait("\n  Enter — закрыть это окно (студия продолжит работать)...")
            return
        print(f"\n  порт {args.port} занят чужой программой — беру следующий свободный")

    port = free_port(args.port)
    print(f"\n  проект: {target.name}  ({describe(target)})")
    print(f"  адрес:  http://127.0.0.1:{port}/")
    print("  окно можно свернуть; закрыть его — остановить студию.\n")

    # Сервер живёт в этом же процессе: закрыл окно — закрылась студия.
    # Так не остаётся забытых процессов, висящих на портах.
    sys.argv = [sys.argv[0], "--project", str(target), "--port", str(port)]
    if not args.no_browser:
        sys.argv.append("--open")
    import clip_studio
    clip_studio.main()

if __name__ == "__main__":
    main()
