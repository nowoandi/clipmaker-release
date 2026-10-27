# clip_ledger.py — бухгалтерская книга студии: сколько реально потрачено.
#
# Почему это отдельный скрипт, а не память роли: генераторы печатают
# «БАЛАНС ДО 412 … потрачено 84 кр.» в консоль и не пишут никуда. Консоль умирает
# вместе с сессией, и через неделю на вопрос «сколько стоил клип» ответа нет.
# Здесь факт расхода фиксируется на диск и переживает всё.
#
# Хранилище — вне репозитория плагина (траты не коммитятся):
#   %LOCALAPPDATA%\ClipMaker\ledger.jsonl   (одна строка = одно событие)
#
# Режимы:
#   snapshot                     — снять баланс Kie по API и остаток квоты Grok
#   record --project P --stage frames --before 412 --after 328 --items 14
#   report  [--project P] [--days 30]
#
# Единица правды — не «цена генерации», а ЦЕНА ПРИНЯТОЙ СЕКУНДЫ (R24):
# брак оплачен теми же деньгами, и пока он не учтён, экономика врёт в свою пользу.
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

KIE_CREDIT_URL = "https://api.kie.ai/api/v1/chat/credit"
ENV_CANDIDATES = []  # ключ ищется в .env рядом с pipeline или в kie_env_file из config

def ledger_path():
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ClipMaker"
    base.mkdir(parents=True, exist_ok=True)
    return base / "ledger.jsonl"

def append(event):
    event["at"] = int(time.time())
    with io.open(str(ledger_path()), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def load_events():
    p = ledger_path()
    if not p.exists():
        return []
    out = []
    for line in io.open(str(p), "r", encoding="utf-8-sig"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

def kie_key(cfg):
    """Ключ читается, но НИКОГДА не печатается — ни в лог, ни в отчёт."""
    paths = list(ENV_CANDIDATES)
    pipeline = cfg.get("pipeline")
    if pipeline:
        paths.insert(0, str(Path(pipeline) / ".env"))
    env_override = cfg.get("kie_env_file")
    if env_override:
        paths.insert(0, env_override)
    for p in paths:
        try:
            for line in io.open(p, "r", encoding="utf-8-sig"):
                m = re.match(r"\s*KIE_API_KEY\s*=\s*(.+)", line)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
        except Exception:
            continue
    return None

def kie_balance(cfg):
    key = kie_key(cfg)
    if not key:
        return None, "KIE_API_KEY не найден (проверь .env рядом с pipeline)"
    req = urllib.request.Request(KIE_CREDIT_URL, headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("data"), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def grok_state(cfg):
    """Расход квоты по журналу моста. Журнал — оценка, не факт: право вето у провайдера (R10).

    Процент считает та же lib.grok_quota(), что и предполёт. До 0.8.3 здесь было
    своё окно в 7 суток, и 26.09.2026 книга показывала 18% при 26% у гейта и ~6%
    по журналу после сброса: три счётчика — три числа, и ни одному нельзя верить.
    """
    bridge = Path(cfg.get("grok_bridge", ""))
    log = bridge / "grok-sent-log.json"
    reset = bridge / "grok-reset.json"

    backfilled, total = 0, 0
    if log.exists():
        try:
            rows = lib.read_json(log)
            total = len(rows)
            backfilled = sum(1 for r in rows if str(r.get("id")) == "backfill")
        except Exception:
            pass
    block = None
    if reset.exists():
        try:
            block = lib.read_json(reset)
        except Exception:
            pass
    q = lib.grok_quota(bridge, cfg)
    return {
        "sends_week": q["sends_week"], "entries_total": total, "backfilled": backfilled,
        "spent_pct": q["spent_pct"], "left_pct": q["left_pct"],
        "basis": q["basis"], "notes": q["notes"],
        "reset": block,
    }

def project_yield(pdir):
    """Что получено за деньги: принятые клипы и секунды в сборке."""
    pdir = Path(pdir)
    accepted = rejected = 0
    for vp in (lib.verdicts_path(pdir),):
        if vp.exists():
            try:
                for v in lib.read_json(vp):
                    verdict = str(v.get("verdict", ""))
                    accepted += verdict == "accept"
                    rejected += verdict == "reject"
            except Exception:
                pass
    clips = len(list((pdir / "clips").glob("S*.mp4"))) if (pdir / "clips").exists() else 0
    frames = len(list((pdir / "frames").glob("*.png"))) if (pdir / "frames").exists() else 0
    seconds = None
    grid = pdir / "clip-memory" / "song" / "grid.json"
    if grid.exists():
        try:
            seconds = float(lib.read_json(grid).get("duration") or 0) or None
        except Exception:
            pass
    return {"accepted": accepted, "rejected": rejected, "clips": clips,
            "frames": frames, "target_seconds": seconds}

def cmd_snapshot(args, cfg):
    bal, err = kie_balance(cfg)
    grok = grok_state(cfg)
    append({"kind": "snapshot", "kie_balance": bal, "kie_error": err,
            "grok": grok, "note": args.note or ""})
    print(f"Kie баланс: {bal if bal is not None else 'нет данных (' + str(err) + ')'}")
    print(f"Grok: потрачено ~{grok['spent_pct']:.0f}% недельной квоты, "
          f"остаток ~{grok['left_pct']:.0f}%, отправок за 7 суток {grok['sends_week']}")
    print(f"  основание: {grok['basis']}")
    for note in grok["notes"]:
        print(f"  ВНИМАНИЕ: {note}")
    if grok["backfilled"]:
        print(f"  ВНИМАНИЕ: {grok['backfilled']} из {grok['entries_total']} записей журнала — "
              f"backfill, то есть проставлены задним числом. Расход Grok сейчас ОЦЕНКА, не факт.")
    if grok["reset"]:
        print(f"  вето провайдера до: {grok['reset'].get('until')} ({grok['reset'].get('note','')})")

def cmd_record(args, cfg):
    spent = None
    if args.before is not None and args.after is not None:
        spent = round(args.before - args.after, 2)
    # Режим отправок пишется в книгу вместе с их числом: отправки стоят разного
    # (видео ≈1,8% квоты, связка Agent ≈7%), и без режима записанное «5 отправок»
    # потом не перевести в проценты. У событий до 03.10.2026 режима нет — они
    # считаются по grok_pct_per_send, как и считались.
    price = lib.grok_price(cfg)
    mode_key = price.key(args.send_mode)
    append({"kind": "spend", "project": args.project or "", "stage": args.stage,
            "items": args.items, "kie_before": args.before, "kie_after": args.after,
            "kie_spent": spent, "grok_sends": args.sends,
            "grok_mode": mode_key if args.sends else None, "note": args.note or ""})
    parts = [f"записано: {args.stage}"]
    if spent is not None:
        parts.append(f"{spent} кр. Kie на {args.items or '?'} шт.")
        if args.items:
            parts.append(f"({spent / args.items:.1f} кр./шт.)")
    if args.sends:
        parts.append(f"{args.sends} отправок Grok, режим {mode_key} "
                     f"(~{args.sends * price(args.send_mode):.1f}% квоты)")
    print(" · ".join(parts))

def cmd_report(args, cfg):
    events = load_events()
    since = time.time() - args.days * 24 * 3600 if args.days else 0
    spends = [e for e in events if e.get("kind") == "spend" and e.get("at", 0) >= since
              and (not args.project or e.get("project") == args.project)]
    print(f"── БУХГАЛТЕРИЯ · событий {len(spends)} за {args.days} дн. " + "─" * 8)
    if not spends:
        print("  пусто. Расход не фиксировался — значит ответа «сколько стоило» нет.")
        print(f"  книга: {ledger_path()}")
        return

    price = lib.grok_price(cfg)
    by_project = {}
    for e in spends:
        p = e.get("project") or "(без проекта)"
        d = by_project.setdefault(p, {"kie": 0.0, "sends": 0, "grok_pct": 0.0, "items": 0, "stages": {}})
        d["kie"] += float(e.get("kie_spent") or 0)
        d["sends"] += int(e.get("grok_sends") or 0)
        # Каждое событие — по цене своего режима; у событий без режима она прежняя.
        d["grok_pct"] += int(e.get("grok_sends") or 0) * price(e.get("grok_mode"))
        d["items"] += int(e.get("items") or 0)
        d["stages"][e.get("stage", "?")] = d["stages"].get(e.get("stage", "?"), 0) + float(e.get("kie_spent") or 0)

    total_kie = sum(d["kie"] for d in by_project.values())
    total_sends = sum(d["sends"] for d in by_project.values())
    total_pct = sum(d["grok_pct"] for d in by_project.values())
    for name, d in sorted(by_project.items(), key=lambda kv: -kv[1]["kie"]):
        print(f"\n  {name}")
        print(f"    Kie: {d['kie']:.0f} кр. на {d['items']} генераций"
              + (f" ({d['kie'] / d['items']:.1f} кр./шт.)" if d["items"] else ""))
        print(f"    Grok: {d['sends']} отправок ≈ {d['grok_pct']:.0f}% недельной квоты")
        if d["stages"]:
            print("    по этапам: " + ", ".join(f"{k} {v:.0f}" for k, v in d["stages"].items()))
        if args.project:
            y = project_yield(args.project_dir or ".")
            print(f"    получено: принято {y['accepted']}, брак {y['rejected']}, "
                  f"кадров {y['frames']}, клипов {y['clips']}")
            # R24: делим на то, что ПРИНЯТО, а не на то, что сгенерировано.
            if y["accepted"] and y["target_seconds"]:
                per_sec = d["kie"] / y["target_seconds"]
                print(f"    цена принятой секунды: {per_sec:.2f} кр./с "
                      f"(при {y['target_seconds']:.0f} с готового клипа)")
            if y["accepted"] + y["rejected"]:
                waste = y["rejected"] / (y["accepted"] + y["rejected"])
                print(f"    доля брака: {waste * 100:.0f}% — эти деньги оплачены и выброшены")

    print(f"\n  ИТОГО: {total_kie:.0f} кр. Kie · {total_sends} отправок Grok ≈ {total_pct:.0f}% квоты")
    bal, err = kie_balance(cfg)
    if bal is not None:
        print(f"  баланс Kie сейчас: {bal}")
    print(f"  книга: {ledger_path()}")

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser(description="Бухгалтерия ClipMaker")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="снять баланс Kie и остаток квоты Grok")
    s.add_argument("--note", default=None)

    r = sub.add_parser("record", help="записать расход этапа")
    r.add_argument("--project", default=None)
    r.add_argument("--stage", required=True, help="anchors | frames | shoot | retake")
    r.add_argument("--before", type=float, default=None, help="баланс Kie ДО")
    r.add_argument("--after", type=float, default=None, help="баланс Kie ПОСЛЕ")
    r.add_argument("--items", type=int, default=None, help="сколько штук сгенерировано")
    r.add_argument("--sends", type=int, default=None, help="отправок в Grok")
    r.add_argument("--send-mode", default="video",
                   help="режим этих отправок: video | bild | agent (цены — config/paths.json)")
    r.add_argument("--note", default=None)

    p = sub.add_parser("report", help="сводка расходов и единичная экономика")
    p.add_argument("--project", default=None)
    p.add_argument("--project-dir", default=None, help="папка проекта для подсчёта принятого")
    p.add_argument("--days", type=int, default=30)

    args = ap.parse_args()
    cfg = lib.load_config()
    {"snapshot": cmd_snapshot, "record": cmd_record, "report": cmd_report}[args.cmd](args, cfg)

if __name__ == "__main__":
    main()
