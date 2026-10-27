# gate_recipes.py — рецепты промптов не правятся, только новые файлы (R12).
#
# Держит sha256-лок на файлы рецептов. Изменение существующего файла — СТОП:
# 02.08.2026 правка v1 на месте стоила восстановления рецепта по переписке.
#
#   python gate_recipes.py check  [--dir <папка рецептов>]
#   python gate_recipes.py update [--dir <папка рецептов>]   # благословить текущее состояние
#
# Выход: 0 — лок сходится; 2 — существующий рецепт изменён.
import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

LOCK_NAME = "recipes.lock.json"

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def collect(rdir):
    return {p.name: sha256(p) for p in sorted(Path(rdir).glob("*.json")) if p.name != LOCK_NAME}

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["check", "update"], nargs="?", default="check")
    ap.add_argument("--dir", default=None, help="папка рецептов; по умолчанию <grok_bridge>/prompts")
    args = ap.parse_args()

    cfg = lib.load_config()
    rdir = Path(args.dir) if args.dir else Path(cfg["grok_bridge"]) / "prompts"
    if not rdir.exists():
        lib.fail(f"папки рецептов нет: {rdir}")
    lock_path = rdir / LOCK_NAME
    current = collect(rdir)

    if args.command == "update":
        lib.write_json(lock_path, current)
        lib.ok(f"лок обновлён: {len(current)} рецептов в {rdir}")
        return

    if not lock_path.exists():
        lib.write_json(lock_path, current)
        lib.ok(f"лок создан впервые: {len(current)} рецептов зафиксировано в {rdir}")
        return

    locked = lib.read_json(lock_path)
    changed = [n for n in locked if n in current and current[n] != locked[n]]
    new = [n for n in current if n not in locked]
    gone = [n for n in locked if n not in current]

    for n in new:
        print(f"[i] новый рецепт: {n} — это правильный путь (R12). Заблессуй: gate_recipes.py update")
    for n in gone:
        print(f"[~] рецепт исчез: {n}")
    if changed:
        for n in changed:
            print(f"[-] ИЗМЕНЁН существующий рецепт: {n}", file=sys.stderr)
        lib.fail("правка рецепта на месте запрещена (R12): каждая правка = НОВЫЙ файл "
                 "recipe-vN.json. Верни файл как был и создай новую версию.")
    lib.ok(f"лок сходится: {len(current)} рецептов, изменённых нет" +
           (f", новых {len(new)}" if new else ""))

if __name__ == "__main__":
    main()
