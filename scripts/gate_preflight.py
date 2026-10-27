# gate_preflight.py — ПРЕДПОЛЁТ перед съёмкой видео (R08, R09, R10, R11, R14).
#
# Повторяет логику grok-bridge/budget.js на стороне плагина и добавляет
# проверки реестра и размера партии. При успехе пишет маркер
# <project>/.gates/preflight-ok.json — его требует hook_guard.py,
# без маркера съёмочная команда физически не запустится.
#
#   python gate_preflight.py --project <папка> [--planned N] [--retries 1]
#                            [--mode video|agent] [--allow-retries] [--force-estimate]
#                            [--provider bridge|api [--provider-reason "почему"]] [--only S01,S02] [--block N]
#
# --mode — чем пойдёт партия. Отправки стоят разного: видео ≈1,8% недельной
# квоты, связка Agent ≈7% (lib.grok_price, замеры в config/paths.json). До
# 03.10.2026 все считались по 2%, и смета связок Agent врала в 3,5 раза вниз.
#
# --provider — через что пойдёт партия: мост Grok (квота) или Kie API (кредиты).
# По умолчанию — project.json → video.provider, без него — мост. 12.10.2026
# в <проект> видео шло через Kie (video.js --provider api), а
# предполёт считал квоту моста, объявил «НЕ ВЛЕЗАЕМ» и маркера не дал; его
# перекрыли --force-estimate. Деньги Kie при этом не держал ни один код —
# потолок сметы стоял только словами в budget.json. Ветка api ниже это закрывает:
# баланс Kie, цена партии, потолок budget.json минус уже потраченное по книге.
#
# Выход: 0 — лететь можно; 2 — стоп (причина в stderr).
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib
import clip_ledger

def human_ms(ms):
    h = int(ms // 3600000)
    m = int(round((ms % 3600000) / 60000))
    if h >= 24:
        return f"{h // 24} сут {h % 24} ч"
    return f"{h} ч {m} мин"

def parse_until(iso):
    s = iso.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp() * 1000

def missing_clips(pdir, project):
    """Сцены, у которых ещё нет живого клипа: enabled и clips/<id>.mp4 отсутствует."""
    clips = Path(pdir) / "clips"
    out = []
    for sc in project.get("scenes", []):
        if not sc.get("enabled", True):
            continue
        sid = sc.get("id", "")
        if sid and not (clips / f"{sid}.mp4").exists():
            out.append(sid)
    return out

# ── Kie API ──────────────────────────────────────────────────────────────────
# Этапы книги, на которых платится видео. shoot — имя из clip_ledger record; у партий
# моста kie_spent пуст, и сумма их не задевает. retake сюда не входит: 12.10.2026 в
# <проект> им записан переген КАДРОВ, и 12 кр. кадров стали бы видео.
KIE_VIDEO_STAGES = {"shoot", "video", "motion", "video_kie"}

def kie_selection(project, only, block):
    """Сцены, которые возьмёт video.js: lib.js pickScenes (enabled, block), затем --only.

    Готовые ролики video.js пропускает, но в счёт они идут все: без --force он их
    не тронет, с --force оплатит, а флаг хук в команде видит не всегда. Завышенная
    смета лишь просит --only, заниженная пропускает партию, которой нет в деньгах.
    """
    picked = [s.get("id") for s in project.get("scenes", [])
              if s.get("enabled") is not False and (not block or s.get("block") == block)]
    if only is None:
        return picked, []
    return [sid for sid in picked if sid in only], [sid for sid in only if sid not in picked]

def kie_price_per_sec(video, budget):
    """(кредитов за секунду или None, кредитов за ролик или None, откуда взято).

    Цена за секунду — главная: video.js берёт одну длительность на запуск
    (video.duration), и цена ролика меняется вместе с ней. cost_hint — цена
    РОЛИКА, так её печатает video.js; при смене duration она врёт молча, поэтому
    идёт последней и с предупреждением.
    """
    if video.get("cost_per_sec"):
        return float(video["cost_per_sec"]), None, "project.json → video.cost_per_sec"
    motion = budget.get("motion") or {}
    if motion.get("credits_per_sec"):
        return float(motion["credits_per_sec"]), None, "budget.json → motion.credits_per_sec"
    # Смета 12.10.2026 держала цену в prices под именем модели. Берём, только если
    # такой ключ один: из двух цен выбирать — это уже догадка.
    keys = [k for k, v in (budget.get("prices") or {}).items()
            if k.endswith("credits_per_sec") and isinstance(v, (int, float))]
    if len(keys) == 1:
        return float(budget["prices"][keys[0]]), None, f"budget.json → prices.{keys[0]}"
    if video.get("cost_hint"):
        return None, float(video["cost_hint"]), "project.json → video.cost_hint (цена ролика)"
    return None, None, ""

def kie_spent_video(names):
    """Сколько кредитов Kie книга уже записала на видео этого проекта."""
    total = 0.0
    for e in clip_ledger.load_events():
        if (e.get("kind") == "spend" and e.get("project") in names
                and e.get("stage") in KIE_VIDEO_STAGES):
            total += float(e.get("kie_spent") or 0)
    return round(total, 2)

def frames_gate(args, pdir, scenes, project):
    """Глаз оператора (0.8.28): видео — только с кадров, разобранных clip-guardian.

    Разбор — clip-memory/reports/frames-review.json, привязан к sha1 файла кадра. Обход —
    --no-frames-review "причина": причина ложится в маркер и видна в журнале прогона.
    """
    problems = lib.frames_review_problems(pdir, scenes, project.get("project"))
    if not problems:
        print(f"  разбор кадров       : принят у всех {len(scenes)} ({', '.join(scenes)})")
        return "accepted"
    if args.no_frames_review:
        print(f"ПРЕДУПРЕЖДЕНИЕ (--no-frames-review): кадры не разобраны — {args.no_frames_review}")
        for p in problems:
            print(f"    · {p}")
        return {"skipped": args.no_frames_review}
    lib.fail("ГЛАЗ ОПЕРАТОРА: видео с неразобранных кадров не снимается — кадр стоит 6 кр., "
             "ролик 27–45, и брак света, оптики и физики дешевле всего поймать на кадре.\n  · "
             + "\n  · ".join(problems)
             + "\nРазбор — clip-guardian, раздел «Глаз оператора» (clip-memory/reports/frames-review.json). "
               "Осознанно без разбора: --no-frames-review \"причина\".")


def kie_preflight(args, cfg, pdir, pjson, project):
    video = project.get("video") or {}
    model = video.get("model")
    duration = video.get("duration") or 6          # то же умолчание, что video.js:86
    budget_path = Path(pdir) / "clip-memory" / "reports" / "budget.json"
    budget = {}
    if budget_path.exists():
        try:
            budget = lib.read_json(budget_path)
        except Exception as e:
            lib.fail(f"budget.json не читается ({type(e).__name__}: {e}). Без сметы потолка нет.")
    motion = budget.get("motion") or {}
    only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
    scenes, unknown = kie_selection(project, only, args.block)
    retries = args.retries if args.retries is not None else cfg.get("default_retries", 1)
    batch_max = cfg.get("batch_max", 5)
    pps, per_clip, price_src = kie_price_per_sec(video, budget)
    clip_cost = round(pps * float(duration), 2) if pps else per_clip
    batch_cost = round(len(scenes) * retries * clip_cost, 2) if clip_cost else None
    ceiling = motion.get("ceiling_credits") or (motion.get("with_reserve") or {}).get("credits")
    names = {Path(pdir).name, str(project.get("project") or ""), str(pdir)} - {""}
    spent = kie_spent_video(names)

    print(f"  провайдер           : Kie API (кредиты). Квота моста Grok эту партию не касается")
    print(f"  модель              : {model or '— нет в project.json'}, {duration} с на ролик")
    print(f"  сцены партии        : {len(scenes)}" + (f"  ({', '.join(scenes)})" if scenes else "")
          + ("" if only else "  — без --only: все включённые сцены" + (f" блока {args.block}" if args.block else "")))
    print(f"  цена                : " + (f"{pps} кр./с ({price_src}) → {clip_cost} кр. за ролик" if pps
                                       else f"{per_clip} кр. за ролик ({price_src})" if per_clip else "НЕТ"))
    if batch_cost is not None:
        print(f"  партия              : до {batch_cost} кр. ({len(scenes)} × {retries} попытка × {clip_cost})")
    print(f"  потолок сметы       : " + (f"{ceiling} кр. (budget.json → motion)" if ceiling else "НЕТ"))
    print(f"  по книге на видео   : {spent} кр. уже потрачено")

    if not model:
        lib.fail("в project.json нет video.model: video.js отправит задачу с model=undefined.")
    if unknown:
        lib.fail(f"--only называет сцены, которых video.js не возьмёт (нет, выключены или другой блок): "
                 f"{', '.join(unknown)}.")
    if not scenes:
        lib.fail("нечего снимать: в выборке нет ни одной сцены.")
    if args.planned is not None and args.planned != len(scenes):
        lib.fail(f"--planned {args.planned}, а video.js возьмёт {len(scenes)} сцен: у Kie партию "
                 f"задаёт --only, его и укажи (то же --only потом в команде video.js).")
    if retries > 1 and not args.allow_retries:
        lib.fail(f"retries={retries}, а правило R09 — одна попытка на сцену. "
                 f"Осознанно разрешить: --allow-retries.")
    if len(scenes) > batch_max:
        lib.fail(f"партия {len(scenes)} > {batch_max} (R11: проверка после каждой партии). "
                 f"Разбей через --only.")
    frames_review = frames_gate(args, pdir, scenes, project)

    # Смета — решение человека (clip-line-producer → «да» Админа). Без неё у партии
    # нет потолка, а без потолка любая цена «влезает».
    if not budget:
        lib.fail(f"нет сметы {budget_path}: потолок расхода Kie на видео не задан. "
                 f"Сначала clip-line-producer.")
    verdict = str(budget.get("verdict") or "")
    if "OK" not in verdict.upper() or "BLOCKER" in verdict.upper():
        lib.fail(f"вердикт сметы «{verdict or 'пусто'}», а нужен OK от директора картины.")
    if budget.get("generation_allowed") is False:
        lib.fail("в смете generation_allowed = false.")
    if motion.get("model") and motion["model"] != model:
        lib.fail(f"смета посчитана для {motion['model']}, а project.json снимает {model}. "
                 f"Другая модель — другая цена: нужна новая смета.")
    if not ceiling:
        lib.fail("в budget.json нет потолка видео (motion.ceiling_credits). Без потолка не летим.")
    if not clip_cost:
        lib.fail("цена ролика неизвестна: нет ни video.cost_per_sec в project.json, ни "
                 "motion.credits_per_sec в budget.json, ни video.cost_hint. Без цены партию не посчитать.")
    if not pps:
        print(f"  ВНИМАНИЕ: cost_hint — цена ролика, а не секунды. Сменится video.duration — смета "
              f"соврёт молча. Надёжнее video.cost_per_sec в project.json.")

    bal, err = clip_ledger.kie_balance(cfg)
    try:
        bal = float(bal) if bal is not None else None
    except (TypeError, ValueError):
        bal, err = None, f"баланс не число: {bal!r}"
    print(f"  баланс Kie          : " + (f"{bal} кр." if bal is not None else f"нет данных ({err})"))
    # Книга знает только записанное. 12.10.2026 прогон 1 этого же клипа (81 кр.) прошёл,
    # а в книгу не попал, и по ней одной от потолка 198 оставалось 186 вместо 117 —
    # S01–S03 по 10 с прошли бы второй раз. Поэтому потрачено — большее из книги и
    # падения баланса с момента сметы (budget.json → kie_balance.credits). Аккаунт общий:
    # чужой расход за это время тоже ляжет в счёт. Это лишний стоп, а не лишняя партия;
    # снимается свежим снимком баланса в смете.
    kb = (budget.get("kie_balance") or {}).get("credits")
    drop = round(kb - bal, 2) if bal is not None and isinstance(kb, (int, float)) else None
    if drop is not None:
        print(f"  со сметы баланс упал: {drop} кр. (снимок сметы {kb})")
        if drop > spent + 1:
            print(f"  ВНИМАНИЕ: книга знает {spent} кр. на видео, баланс — {drop}. Считаю от баланса. "
                  f"Не записанный прогон — clip_ledger.py record.")
            spent = drop

    # Потолок не снимает никакой флаг: сверх него — новая смета и новое «да» Админа.
    left_ceiling = round(float(ceiling) - spent, 2)
    if batch_cost > left_ceiling:
        lib.fail(f"ПОТОЛОК: партия до {batch_cost} кр., а от потолка {ceiling} кр. осталось "
                 f"{left_ceiling} (уже потрачено {spent}). Сверх потолка — новая смета и новое «да» Админа.")
    if bal is None:
        msg = f"баланс Kie не снят ({err}): влезает ли партия в счёт, неизвестно."
        if not args.force_estimate:
            lib.fail(msg + " Осознанно лететь без баланса: --force-estimate (потолок он не снимает).")
        print("ПРЕДУПРЕЖДЕНИЕ (--force-estimate): " + msg)
    elif bal < batch_cost:
        lib.fail(f"на балансе Kie {bal} кр., а партия до {batch_cost} кр.")
    print("─" * 46)

    lib.write_marker(pdir, "preflight-ok.json", {
        "provider": "api",          # хук сверяет его с тем, чем идёт команда
        "planned": len(scenes),
        "retries": retries,
        "scenes": scenes,
        "only": only is not None,   # без --only в предполёте — без --only и в команде
        "block": args.block or 0,
        "model": model,
        "duration": duration,       # сменится до запуска — хук партию не пустит
        "credits_per_clip": clip_cost,
        "batch_credits": batch_cost,
        "ceiling_credits": ceiling,
        "spent_before": spent,
        "kie_balance": bal,
        "frames_review": frames_review,
        "ttl_min": cfg.get("preflight_ttl_min", 30),
        "project": str(pjson),
    })
    lib.ok(f"предполёт Kie пройден: {len(scenes)} сцен до {batch_cost} кр., от потолка останется "
           f"{round(left_ceiling - batch_cost, 2)} кр. Маркер живёт {cfg.get('preflight_ttl_min', 30)} мин "
           f"и покрывает одну партию.")

def note_provider_decision(args, pdir, provider):
    """Журнал решений (R10, 0.8.36): явный --provider записывается, тихая смена видна.

    Ключ записи — video-provider:<папка проекта>. Не мешает запуску: любая ошибка журнала
    превращается в предупреждение, а гейт идёт дальше.
    """
    try:
        subject = Path(pdir).resolve().name
        last = lib.last_decision(pdir, "video-provider", subject)
        if args.provider:
            if last and last.get("choice") != provider and not args.provider_reason:
                print(f"[~] провайдер сменён с {last.get('choice')} на {provider} без --provider-reason: "
                      "причина в журнал решений не попадёт (R10 — смена только явным решением)",
                      file=sys.stderr)
            other = [x for x in ("bridge", "api") if x != provider]
            lib.log_decision(pdir, "video-provider", subject, provider, args.provider_reason or "",
                             rejected=other, source="gate_preflight --provider")
        elif last and last.get("choice") != provider:
            print(f"[~] провайдер {provider} (из project.json или умолчание), а в журнале решений "
                  f"последним стоит {last.get('choice')}: тихая смена (R10). Укажи --provider явно "
                  "и --provider-reason, если смена задумана", file=sys.stderr)
    except Exception as e:
        print(f"[~] журнал решений не записан: {e}", file=sys.stderr)


def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--file", default=None, help="явный путь к project.json")
    ap.add_argument("--planned", type=int, default=None,
                    help="сколько сцен снимаем в ЭТОМ запуске; по умолчанию min(несняты, batch_max)")
    ap.add_argument("--retries", type=int, default=None)
    ap.add_argument("--mode", default="video",
                    help="режим отправок этой партии: video (обычная) или agent (связка планов)")
    ap.add_argument("--allow-retries", action="store_true",
                    help="осознанно разрешить >1 попытки на сцену (R09)")
    ap.add_argument("--force-estimate", action="store_true",
                    help="перекрыть оценку по журналу (НЕ снимает стоп по слову Grok, R10, "
                         "и потолок сметы Kie)")
    ap.add_argument("--provider", choices=["bridge", "api"], default=None,
                    help="через что партия: bridge — мост Grok, api — Kie. "
                         "По умолчанию project.json → video.provider, иначе bridge")
    ap.add_argument("--provider-reason", default=None, metavar="ПРИЧИНА",
                    help="почему выбран именно этот провайдер; вместе с явным --provider уходит в "
                         "журнал решений clip-memory/reports/decisions.jsonl (ключ video-provider:<проект>)")
    ap.add_argument("--only", default=None,
                    help="Kie: сцены партии через запятую — тот же --only, что у video.js")
    ap.add_argument("--block", type=int, default=0,
                    help="Kie: блок сцен — тот же --block, что у video.js")
    ap.add_argument("--no-frames-review", default=None, metavar="ПРИЧИНА",
                    help="снимать без разбора кадров clip-guardian; причина ложится в маркер")
    args = ap.parse_args()

    cfg = lib.load_config()
    pdir = lib.project_dir(args.project)
    pjson = lib.find_project_json(pdir, args.file)
    project = lib.read_json(pjson)
    bridge = Path(cfg["grok_bridge"])
    now_ms = time.time() * 1000

    provider = args.provider or (project.get("video") or {}).get("provider") or "bridge"
    if provider not in ("bridge", "api"):
        lib.fail(f"video.provider = «{provider}»: известны bridge и api. Укажи --provider явно.")
    print(f"── ПРЕДПОЛЁТ · {project.get('project', pjson.name)} · {provider} " + "─" * 14)
    note_provider_decision(args, pdir, provider)
    if provider == "api":
        return kie_preflight(args, cfg, pdir, pjson, project)
    if args.only or args.block:
        lib.fail("--only и --block — для Kie (video.js). У моста партию задаёт --planned.")

    # 1) R10: жёсткий стоп по слову Grok. Никакой флаг его не снимает.
    reset_file = bridge / "grok-reset.json"
    if reset_file.exists():
        try:
            reset = lib.read_json(reset_file)
        except Exception:
            reset = None
        if reset and reset.get("until"):
            until_ms = parse_until(reset["until"])
            wait = until_ms - now_ms
            if wait > 0:
                print(f"  квота Grok  : ИСЧЕРПАНА (слово Grok, R10)", file=sys.stderr)
                print(f"  сброс       : {reset['until']}  (ждать {human_ms(wait)})", file=sys.stderr)
                if reset.get("note"):
                    print(f"  источник    : {reset['note']}", file=sys.stderr)
                lib.fail("квота Grok исчерпана. Этот стоп не обходится (R10). "
                         "После сброса перезапусти предполёт.")

    # 2) Расклад по журналу (оценка, R08).
    # Расход считается в ТЕКУЩЕМ пуле: от замера Grok, пока его пул жив, иначе
    # журналом от последнего сброса. Не скользящим окном в 7 суток: пул
    # обнуляется целиком, а окно ползёт — 15.08.2026 гейт натащил 46 отправок
    # прошлого пула и объявил 92% при реальных 35%, остановив работу за 17 часов
    # до сгорания двух третей квоты. Формула — lib.grok_quota(), её зеркало —
    # grok-bridge/budget.js quotaState(); правим обе или ни одной.
    quota = lib.grok_quota(bridge, cfg, now_ms)
    price = lib.grok_price(cfg)
    # Цена отправок ЭТОЙ партии. Остаток в отправках без режима не считается:
    # 44% квоты — это 24 обычные отправки или 6 связок Agent.
    mode_key = price.key(args.mode)
    pct_per_send = price(args.mode)
    spent_pct, left_pct = quota["spent_pct"], quota["left_pct"]
    left_sends = lib.grok_left_sends(left_pct, pct_per_send)

    # Неистраченное сгорает — про срок надо печатать, иначе «экономия» выбрасывает квоту.
    burn_note = None
    if quota["next_reset_ms"] is not None and quota["next_reset_ms"] > now_ms:
        burn_note = (f"пул обнулится через {human_ms(quota['next_reset_ms'] - now_ms)} "
                     f"({lib.fmt_ms(quota['next_reset_ms'])}"
                     + ("" if quota["next_reset_measured"] else ", по циклу — не замер")
                     + ") — неистраченное сгорит")

    # 3) План этого запуска.
    not_shot = missing_clips(pdir, project)
    batch_max = cfg.get("batch_max", 5)
    planned = args.planned if args.planned is not None else min(len(not_shot), batch_max)
    retries = args.retries if args.retries is not None else cfg.get("default_retries", 1)

    print(f"  не снято сцен       : {len(not_shot)}" +
          (f"  ({', '.join(not_shot[:8])}{'…' if len(not_shot) > 8 else ''})" if not_shot else ""))
    print(f"  план этого запуска  : {planned} сцен × до {retries} попыток, режим {mode_key} "
          f"(по {pct_per_send}% за отправку)")
    print(f"  основание счёта     : {quota['basis']}")
    print(f"  потрачено           : {spent_pct}%")
    print(f"  осталось            : {left_sends} отправок режима {mode_key} ({left_pct}%)")
    others = [f"{lib.grok_left_sends(left_pct, p)} {m}" for m, p in sorted(price.by_mode.items())
              if p > 0 and m != mode_key]
    if others:
        print(f"  тот же остаток      : " + ", или ".join(others))
    if burn_note:
        print(f"  {burn_note}")
    for note in quota["notes"]:
        print(f"  ВНИМАНИЕ: {note}")
    # Мост снимает несделанные сцены по порядку: партия — первые planned из них.
    frames_review = frames_gate(args, pdir, not_shot[:planned], project) if not_shot else "nothing-to-shoot"
    print("─" * 46)

    if planned <= 0:
        lib.fail("нечего снимать: все клипы на месте либо planned=0.")

    # 4) R09: одна попытка на сцену.
    if retries > 1 and not args.allow_retries:
        lib.fail(f"retries={retries}, а правило R09 — одна попытка на сцену "
                 f"(тройные повторы однажды сожгли половину недели). "
                 f"Осознанно разрешить: --allow-retries.")

    # 5) R11: партия не больше batch_max.
    if planned > batch_max:
        lib.fail(f"партия {planned} > {batch_max} (R11: мост не держит длинные прогоны). "
                 f"Снимай партиями: --planned {batch_max}, после партии — проверка.")

    # 6) R08, часть первая: журнал — нижняя граница расхода, не оценка.
    #
    # 28.09.2026 в проекте <проект> два окна между замерами интерфейса
    # не сошлись ни при какой цене за отправку: +3% квоты при НУЛЕ отправок в
    # журнале, и 13 отправок картинок на +17% вместо ожидаемых ~4,3%. То есть
    # учётку Grok тратит кто-то ещё (в том разборе подозрение на Grok Bot.exe,
    # запущенный на той же машине). Никакая таблица цен этого не видит: журнал
    # знает только свои нажатия.
    #
    # Поэтому после партии расход сверяется с интерфейсом. Замер бесплатный и
    # занимает полминуты, окно Grok для съёмки всё равно открыто. Порог —
    # grok_measure_after_sends (по умолчанию batch_max): одна партия без замера
    # проходит, вторая требует сверки. Это R11 в деньгах: проверка после каждой
    # партии, а не один раз перед монтажом.
    measure_after = int(cfg.get("grok_measure_after_sends", batch_max) or batch_max)
    since_measure = int(quota.get("sends_counted", 0) or 0)
    if measure_after > 0 and since_measure >= measure_after:
        msg = (f"после последнего замера квоты прошло {since_measure} отправок (порог {measure_after}): "
               f"счёт держится на журнале, а журнал не видит расход мимо себя. "
               f"Снять замер: node quota-read.js --save (в папке моста), потом повторить предполёт.")
        if not args.force_estimate:
            lib.fail(msg + " Осознанно лететь на журнале: --force-estimate.")
        print("ПРЕДУПРЕЖДЕНИЕ (--force-estimate): " + msg)

    # 6) R08, часть вторая: влезаем ли в оценку по журналу.
    worst = planned * retries
    if worst > left_sends:
        msg = (f"НЕ ВЛЕЗАЕМ по оценке журнала: нужно до {worst} отправок, осталось {left_sends}. "
               f"Уменьши план (--planned {max(1, left_sends // max(1, retries))}).")
        if not args.force_estimate:
            lib.fail(msg + " Осознанно перекрыть оценку: --force-estimate.")
        print("ПРЕДУПРЕЖДЕНИЕ (--force-estimate): " + msg)

    # 7) R14: реестр скачанного не должен быть пуст, если в проекте уже есть клипы.
    clips_dir = Path(pdir) / "clips"
    have_clips = list(clips_dir.glob("*.mp4")) if clips_dir.exists() else []
    registries = list(bridge.glob("seen-srcs*.json")) + list((bridge / "chain").glob("seen-srcs*.json")) \
        if bridge.exists() else []
    reg_entries = 0
    for reg in registries:
        try:
            data = lib.read_json(reg)
            reg_entries += len(data) if isinstance(data, (list, dict)) else 0
        except Exception:
            pass
    if have_clips and reg_entries == 0:
        lib.fail(f"в проекте {len(have_clips)} клипов, а реестр скачанных ссылок пуст (R14): "
                 f"страница поста Grok показывает ЛЕНТУ, пустой реестр затащит чужие ролики. "
                 f"Проверь seen-srcs*.json в {bridge}.")
    print(f"  реестр ссылок       : {reg_entries} записей в {len(registries)} файлах")

    # 8) Маркер для hook_guard.
    lib.write_marker(pdir, "preflight-ok.json", {
        "provider": "bridge",      # маркер без поля хук тоже читает как мост (до 0.8.26)
        "planned": planned,
        "retries": retries,
        "mode": mode_key,         # чем партия пойдёт: по этой цене её и считали
        "pct_per_send": pct_per_send,
        "frames_review": frames_review,
        "ttl_min": cfg.get("preflight_ttl_min", 30),
        "project": str(pjson),
    })
    lib.ok(f"предполёт пройден: {planned} сцен × {retries} попытка. "
           f"Маркер живёт {cfg.get('preflight_ttl_min', 30)} мин. Партия следующая — новый предполёт.")

if __name__ == "__main__":
    main()
