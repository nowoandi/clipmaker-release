# clip_lib.py — общий слой гейтов ClipMaker: конфиг, проект, маркеры.
# Все файлы читаются как utf-8-sig (R22: PowerShell дописывает BOM,
# и молча падающий JSON.parse уже один раз отключил бюджетный гейт).
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

def setup_io():
    # R22: Python на Windows печатает в cp1252 и падает на кириллице.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

def plugin_root():
    return Path(__file__).resolve().parent.parent

def load_config():
    cfg_path = os.environ.get("CLIPMAKER_CONFIG") or str(plugin_root() / "config" / "paths.json")
    with io.open(cfg_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)

def read_json(path):
    with io.open(str(path), "r", encoding="utf-8-sig") as f:
        return json.load(f)

def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # BOM не пишем никогда (R22).
    with io.open(str(path), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

def project_dir(cli_arg=None):
    """Папка проекта: --project > $CLIP_PROJECT > cwd."""
    d = cli_arg or os.environ.get("CLIP_PROJECT") or os.getcwd()
    return Path(d)

def find_project_json(pdir, explicit=None):
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise SystemExit(f"СТОП: файл проекта не найден: {p}")
        return p
    candidates = [p for p in Path(pdir).glob("project*.json")
                  if not p.name.endswith(".bak") and ".bak" not in p.suffixes and "bak" not in p.name.lower()]
    if not candidates:
        raise SystemExit(f"СТОП: в {pdir} нет project*.json. Укажи --project или --file.")
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates)
        raise SystemExit(f"СТОП: в {pdir} несколько файлов проекта ({names}). Укажи --file явно.")
    return candidates[0]

def verdicts_path(pdir):
    """Вердикты панели приёмки — одно место на все скрипты.

    Панель (review-server.js моста) пишет verdicts.json в свою REVIEW_MEDIA, а
    ПРИЁМКА.bat проекта ставит REVIEW_MEDIA = <проект>/clips (clip_scaffold.py).
    До 18.09.2026 gate_conformance читал отсюда, а clip_status, clip_studio и
    clip_ledger — из корня проекта, где файла не бывает: сводки показывали ноль
    принятых при заполненной приёмке. Запасного пути в chain/ моста нет
    намеренно: та папка ничья, и её вердикты приписались бы чужому проекту.
    """
    return Path(pdir) / "clips" / "verdicts.json"

def gates_dir(pdir):
    d = Path(pdir) / ".gates"
    d.mkdir(parents=True, exist_ok=True)
    return d

def write_marker(pdir, name, payload):
    payload = dict(payload)
    payload["at"] = int(time.time())
    write_json(gates_dir(pdir) / name, payload)

def read_marker(pdir, name, ttl_min):
    p = Path(pdir) / ".gates" / name
    if not p.exists():
        return None
    try:
        data = read_json(p)
    except Exception:
        return None
    if ttl_min and int(time.time()) - int(data.get("at", 0)) > ttl_min * 60:
        return None
    return data

def state_path():
    """Память самой студии — какой проект открывали последним. Живёт вне проекта
    и вне репозитория: это состояние рабочего места, а не данные клипа."""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ClipMaker"
    base.mkdir(parents=True, exist_ok=True)
    return base / "state.json"

def read_state():
    try:
        return read_json(state_path())
    except Exception:
        return {}

def remember(key, value):
    st = read_state()
    st[key] = str(value)
    st["at"] = int(time.time())
    try:
        write_json(state_path(), st)
    except Exception:
        pass  # память удобства: не смогли записать — не повод ронять работу

# ── Квота Grok ───────────────────────────────────────────────────────────────
# Одна функция на gate_preflight и clip_ledger: 26.09.2026 три счётчика давали
# три числа (26%, 18% и ~6% по журналу), и ни одно не было правдой.
# Зеркало — quotaState() в grok-bridge/budget.js. Правим обе или ни одной.

WEEK_MS = 7 * 24 * 3600 * 1000

def iso_ms(value):
    """ISO-дата → мс эпохи; None, если даты нет или она нечитаема."""
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp() * 1000

def fmt_ms(ms):
    # Местное время: так же дату сброса показывает интерфейс Grok («Setzt … um 13:02»).
    return datetime.fromtimestamp(ms / 1000).strftime("%d.%m %H:%M")

def grok_price(cfg):
    """Цена ОДНОЙ отправки Grok по её режиму, % недельной квоты.

    До 03.10.2026 любая отправка считалась одинаково (2%), и ошибка шла в обе
    стороны сразу. Замеры интерфейса 27–29.09 (22 видео и 35 картинок, пять
    замеров подряд) и 18.09 (одна связка Agent) дали разброс в двадцать раз:
    видео ≈1,8%, картинка ≈0,35%, связка Agent ≈7%. Картинки смета завышала
    в шесть раз, Agent занижала в 3,5 — и занижение опаснее: по нему предполёт
    разрешает отправки, которых в пуле нет. Разбор: в проекте <проект>,
    clip-memory/reports/grok-agent-price.md.

    Режим берётся из поля mode строки журнала — мост пишет его так, как режим
    назван в интерфейсе Grok («Bild», «Video», «Agent»), и имена со временем
    менялись: отсюда таблица псевдонимов и сверка без учёта регистра. Режим не
    опознан или строка старая (до 15.08.2026 поля mode не было) — цена
    grok_pct_per_send: лишний процент в оценке дешевле пропущенной отправки.

    Зеркало — PREIS/ALIAS в grok-bridge/budget.js. Правим обе или ни одной.
    """
    default = float(cfg.get("grok_pct_per_send", 2) or 2)
    by_mode = {str(k).strip().lower(): float(v)
               for k, v in (cfg.get("grok_pct_per_send_by_mode") or {}).items()}
    aliases = {str(k).strip().lower(): str(v).strip().lower()
               for k, v in (cfg.get("grok_mode_aliases") or {}).items()}

    def key_of(mode):
        k = str(mode or "").strip().lower()
        return aliases.get(k, k)

    def price(mode):
        return by_mode.get(key_of(mode), default)

    price.key = key_of
    price.default = default
    price.by_mode = by_mode
    return price

def grok_left_sends(left_pct, pct_per_send):
    """Сколько отправок по цене pct_per_send влезает в остаток left_pct.

    Счёт в десятых долях процента и только целыми. Причина (03.10.2026): на
    дробной цене `2 // 0.4` в Python даёт 4, а Math.floor(2 / 0.4) в JS — 5.
    Зеркала budget.js и clip_lib.py разошлись бы на одну отправку там, где
    остаток ровно делится, — то есть у самого края квоты, где это и важно.
    """
    tenths = int(round(float(pct_per_send) * 10))
    if tenths <= 0:
        return 0
    return int(round(float(left_pct) * 10)) // tenths

def grok_quota(bridge, cfg, now_ms=None):
    """Сколько недельной квоты Grok потрачено в ТЕКУЩЕМ пуле и на чём держится счёт.

    Возвращает dict: spent_pct, left_pct, basis (строка «от чего считали»),
    notes (что напечатать как предупреждение), pool_start_ms, next_reset_ms,
    next_reset_measured (True — дата из интерфейса Grok, False — выведена циклом),
    sends_counted, sends_week, sends_by_mode (сколько отправок какого режима
    вошло в счёт — по ним и считана цена, см. grok_price()).
    """
    bridge = Path(bridge)
    now = time.time() * 1000 if now_ms is None else now_ms
    price = grok_price(cfg)
    budget = cfg.get("grok_week_budget_pct", 100)

    def load(name):
        try:
            return read_json(bridge / name)
        except Exception:
            return None

    sends = load("grok-sent-log.json")
    sends = sends if isinstance(sends, list) else []
    sends = [r for r in sends if isinstance(r, dict) and float(r.get("at", 0) or 0) <= now]
    bal = load("grok-balance.json")
    if not (isinstance(bal, dict) and isinstance(bal.get("pct"), (int, float))):
        bal = None
    veto = load("grok-reset.json")
    veto = veto if isinstance(veto, dict) else {}

    def rows_after(t):
        return [r for r in sends if float(r.get("at", 0) or 0) > t]

    def count_after(t):
        return len(rows_after(t))

    def cost_after(t):
        """Цена отправок после момента t — сумма по режиму каждой, а не штуки × ставка."""
        return round(sum(price(r.get("mode")) for r in rows_after(t)), 1)

    def modes_after(t):
        out = {}
        for r in rows_after(t):
            k = price.key(r.get("mode")) or "?"
            out[k] = out.get(k, 0) + 1
        return out

    def mode_list(by_mode):
        # «3 video, 12 bild» — чтобы из основания счёта было видно, чем потрачено.
        return ", ".join(f"{n} {m}" for m, n in sorted(by_mode.items(), key=lambda kv: -kv[1]))

    bal_at = float(bal.get("at", 0) or 0) if bal else None
    bal_until = iso_ms(bal.get("until")) if bal else None
    veto_until = iso_ms(veto.get("until"))

    # Сбросы, которые назвал сам Grok: дата у замера (интерфейс, «Setzt … um»)
    # и дата из вето (его слова «лимит исчерпан до …»). Только прошедшие.
    known = [(t, src) for t, src in ((bal_until, "grok-balance.json"), (veto_until, "grok-reset.json"))
             if t is not None and t <= now]
    # При равных датах — первая, из интерфейса: так же выбирает budget.js.
    last_reset, last_src = max(known, key=lambda k: k[0]) if known else (None, None)

    notes = []
    out = {"sends_week": count_after(now - WEEK_MS), "next_reset_ms": None,
           "next_reset_measured": False, "pool_start_ms": None}

    # 1) Замер годен, только если его пул ещё жив.
    # Дефект до 0.8.3: замер брался всегда. Замер 92% от 18.09 относится к пулу,
    # сгоревшему 20.09 11:02 UTC, а гейт 26.09 прибавлял к нему 9 отправок из
    # двух разных пулов и показывал 26% при ~6%. После следующего сброса тот же
    # замер начал бы ложно останавливать съёмку, как окно в 7 суток 15.08.
    stale = None
    if bal:
        after = [t for t, _ in known if t > bal_at]
        if after:
            stale = f"его пул сгорел {fmt_ms(max(after))}"
        elif bal_until is None and now - bal_at >= WEEK_MS:
            stale = "он старше недели, а пул недельный"
        elif bal_until is None:
            notes.append("у замера нет даты сброса — жив ли его пул, не проверить. "
                         "Снять замер с датой: node quota-read.js --save")

    if bal and not stale:
        since = count_after(bal_at)
        cost = cost_after(bal_at)
        by_mode = modes_after(bal_at)
        out["spent_pct"] = min(budget, (budget - bal["pct"]) + cost)
        out["basis"] = (f"замер Grok {bal['pct']}% от {fmt_ms(bal_at)} + {since} отправок после него"
                        + (f" ({mode_list(by_mode)}) на {cost}%" if since else ""))
        out["sends_counted"] = since
        out["sends_by_mode"] = by_mode
        if bal_until is not None and bal_until > now:
            out["next_reset_ms"], out["next_reset_measured"] = bal_until, True
    else:
        # 2) Замера текущего пула нет — считаем журнал с начала пула.
        # Начало пула — последний сброс, названный Grok. Если он старше недели,
        # после него был ещё сброс, которого никто не видел: откладываем неделю
        # от даты из интерфейса. Цикл подтверждают три воскресенья: 09.08 (вето
        # <проект>), 16.08 (счётчик Админа, скаут bnb-2), 20.09 11:02 UTC
        # (grok-balance.json). Если пул на деле идёт от первой отправки, настоящий
        # сброс не раньше выведенного — счёт выйдет с запасом, а не в долг.
        # От даты вето цикл не разворачивается: 11.08 туда вписали фиктивную
        # 01.08 00:00, чтобы снять ложное вето, — сетка от неё врала бы на полтора дня.
        pool_start = None
        if last_reset is not None and now - last_reset < WEEK_MS:
            pool_start = last_reset
            how = f"сброс {fmt_ms(last_reset)} ({last_src})"
        elif bal_until is not None and bal_until <= now:
            pool_start = bal_until + ((now - bal_until) // WEEK_MS) * WEEK_MS
            how = f"сброс {fmt_ms(pool_start)} — выведен недельным циклом от {fmt_ms(bal_until)}, не замерен"
            notes.append(f"дата сброса {fmt_ms(pool_start)} — предположение по недельному циклу, а не замер")
        if pool_start is not None:
            since = count_after(pool_start)
            by_mode = modes_after(pool_start)
            out["spent_pct"] = min(budget, cost_after(pool_start))
            out["basis"] = (f"журнал после сброса: {since} отправок"
                            + (f" ({mode_list(by_mode)})" if since else "") + f"; {how}")
            out["sends_counted"] = since
            out["sends_by_mode"] = by_mode
            out["pool_start_ms"] = pool_start
            out["next_reset_ms"] = pool_start + WEEK_MS
        else:
            # Дата сброса неизвестна. Окно 7 суток — верхняя граница: недельный
            # пул начался не раньше, чем неделю назад. Молча не гадаем.
            week_start = now - WEEK_MS
            by_mode = modes_after(week_start)
            out["spent_pct"] = min(budget, cost_after(week_start))
            out["basis"] = (f"окно 7 суток: {out['sends_week']} отправок"
                            + (f" ({mode_list(by_mode)})" if out["sends_week"] else ""))
            out["sends_counted"] = out["sends_week"]
            out["sends_by_mode"] = by_mode
            notes.append("дата последнего сброса НЕИЗВЕСТНА — счёт окном 7 суток, "
                         "он может захватить прошлый пул и завысить расход")
        if bal:
            notes.append(f"замер {bal['pct']}% от {fmt_ms(bal_at)} не участвует: {stale}")
        notes.append("замера в текущем пуле нет — это оценка по журналу: ручной расход в окне "
                     "Grok в него не попадает. Снять замер: node quota-read.js --save (в папке моста)")

    out["left_pct"] = max(0, budget - out["spent_pct"])
    out["notes"] = notes
    return out

# ── формат «hook»: ролик под фрагмент трека ───────────────────────────────────
# Suno-hook (<проект>, 12.10.2026): 4 плана, 22,41 с под первый припев, а трек —
# 219,96 с. gate_script сверял сумму долей с длиной всего трека и падал на −197,6 с, gate_density
# требовал 25 планов полного клипа. Окно задаётся ЯВНО — grid.json → hook.start / hook.end, в
# секундах трека. Подсказки музыковеда (recommended_start и т. п.) окном не считаются: окно —
# решение, а не замер. Нет start/end — гейты проверяют полный клип, как раньше.

def hook_window(grid):
    """Окно фрагмента {start, end, length} или None, если это полный клип.

    Битое окно — ValueError с текстом для гейта: молча откатиться к полному клипу нельзя,
    иначе опечатка в окне превращается в претензию «не хватает 197 секунд».
    """
    h = grid.get("hook")
    if not isinstance(h, dict) or ("start" not in h and "end" not in h):
        return None
    try:
        start, end = float(h["start"]), float(h["end"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("grid.json → hook: нужны оба поля start и end, числа в секундах трека")
    duration = float(grid.get("duration") or 0)
    if not 0 <= start < end:
        raise ValueError(f"grid.json → hook: окно {start}–{end} с пустое или вывернуто")
    # 0,05 с — запас на округление: длина трека и конец окна пишутся до сотых.
    if duration and end > duration + 0.05:
        raise ValueError(f"grid.json → hook: конец окна {end} с за концом трека {duration} с")
    return {"start": start, "end": end, "length": end - start}

def hook_hint(grid):
    """Строка-предупреждение, если блок hook в grid.json есть, а окна в нём нет."""
    h = grid.get("hook")
    if isinstance(h, dict) and "start" not in h and "end" not in h:
        return ("в grid.json есть блок hook, но без start/end — проверяется полный клип. "
                "Ролик под фрагмент: записать окно в hook.start и hook.end (секунды трека)")
    return None

def fail(msg, code=2):
    print("СТОП. " + msg, file=sys.stderr)
    raise SystemExit(code)

def ok(msg):
    print("OK. " + msg)


# ── формат кадра рекламной ветки ──────────────────────────────────────────────
# Админ 10.10.2026: «по карточкам я бы делал, наверное, лучше три на четыре, это более универсальный
# формат. Думаю, высокие нам точно не нужны, потому что это карточка товара максимум три на четыре
# или вообще квадратные». Поэтому у рекламы умолчание 3:4, а 9:16 — только по явному решению
# (лента Reels/Shorts). Клипа таблица не касается: его шаблон по-прежнему 9:16.
#
# Источник правды — поле `aspect` паспорта товара (решение человека). project.json только исполняет:
# его читают генераторы (image/video.aspect_ratio) и сборка (render). Расхождение между ними —
# кадры уйдут в генерацию не в том формате, а это деньги, поэтому его ловят гейты.
AD_ASPECTS = {"3:4": (1080, 1440), "1:1": (1080, 1080), "9:16": (1080, 1920)}
AD_ASPECT_DEFAULT = "3:4"


def ad_aspect(passport):
    """Формат кадра из паспорта: (имя, (ширина, высота)); размер None, если имя неизвестно.
    Поля нет — умолчание рекламы."""
    name = str((passport or {}).get("aspect") or AD_ASPECT_DEFAULT).strip()
    return name, AD_ASPECTS.get(name)


def ad_frame_problems(pdir, passport, project_json=None):
    """Расхождения между форматом паспорта и project.json. Пусто — сходится, либо проверять
    нечего (имя формата неизвестное — это ловит гейт паспорта; файла проекта ещё нет)."""
    name, dims = ad_aspect(passport)
    if dims is None:
        return []
    try:
        pj = read_json(find_project_json(pdir, project_json))
    except (SystemExit, Exception):
        return []
    out = []
    for sect in ("image", "video"):
        got = (pj.get(sect) or {}).get("aspect_ratio")
        if got != name:
            out.append(f"{sect}.aspect_ratio «{got}» при формате паспорта «{name}»")
    r = pj.get("render") or {}
    if (r.get("width"), r.get("height")) != dims:
        out.append(f"render {r.get('width')}x{r.get('height')} вместо {dims[0]}x{dims[1]}")
    return out


def apply_ad_aspect(pdir, passport, project_json=None):
    """Привести project.json к формату паспорта: image.aspect_ratio, video.aspect_ratio, render.
    Трогает только эти поля. Возвращает список изменений (пустой — уже сходилось)."""
    name, dims = ad_aspect(passport)
    if dims is None:
        raise ValueError(f"формат «{name}» не из набора {sorted(AD_ASPECTS)}")
    path = find_project_json(pdir, project_json)
    pj = read_json(path)
    changed = []
    for sect in ("image", "video"):
        d = pj.setdefault(sect, {})
        if d.get("aspect_ratio") != name:
            changed.append(f"{sect}.aspect_ratio: {d.get('aspect_ratio')} → {name}")
            d["aspect_ratio"] = name
    r = pj.setdefault("render", {})
    if (r.get("width"), r.get("height")) != dims:
        changed.append(f"render: {r.get('width')}x{r.get('height')} → {dims[0]}x{dims[1]}")
        r["width"], r["height"] = dims
    if changed:
        write_json(path, pj)
    return changed


# ── глаз оператора: разбор кадров до видео (0.8.28) ────────────────────────────────────────────
# Админ, 13.10.2026: «У нас есть какой-то агент, который проверяет … именно правильную съёмку,
# чтобы что отличает лохушников от профессионалов?» — не было. Оператор свет и оптику ЗАДАВАЛ,
# приёмщик проверял сцену и эмоцию, а свет, оптику, цвет и физику на готовом кадре не смотрел
# никто: кривая рука с мелом и комки «штукатурки» в <проект> дошли до Админа.
# Самая дешёвая точка — кадр до видео: кадр стоит 6 кр., ролик 27–45.
#
# Разбор пишет clip-guardian в clip-memory/reports/frames-review.json; предполёт видео пускает
# сцену только с принятым разбором ЭТОГО файла кадра (sha1): перегенерировали кадр — разбор заново.
FRAME_REVIEW_FILE = ("clip-memory", "reports", "frames-review.json")
# Виды проверок, без которых разбор неполон. people — только если в кадре люди, поэтому не здесь.
# composition (0.8.30): три плана, шум, 1–3 цвета, есть ли в кадре красота — голая стена прошла
# разбор захода 2 с accept, потому что этого вида проверки не было.
FRAME_REVIEW_KINDS = ("light", "camera", "color", "physics", "composition")


def frame_path(pdir, sid, project_name=None):
    """Кадр сцены: frames/<id>.png проекта, иначе out/<project>/frames/<id>.png (video.js)."""
    pdir = Path(pdir)
    for p in [pdir / "frames" / f"{sid}.png",
              pdir / "out" / (project_name or pdir.name) / "frames" / f"{sid}.png"]:
        if p.exists():
            return p
    return None


def file_sha1(path):
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def frames_review_problems(pdir, scene_ids, project_name=None):
    """Претензии к разбору кадров перечисленных сцен; пустой список — можно снимать видео."""
    path = Path(pdir).joinpath(*FRAME_REVIEW_FILE)
    review = {}
    if path.exists():
        try:
            review = (read_json(path) or {}).get("frames") or {}
        except Exception as e:
            return [f"frames-review.json не читается ({type(e).__name__}: {e})"]
    problems = []
    for sid in scene_ids:
        fp = frame_path(pdir, sid, project_name)
        if not fp:
            problems.append(f"{sid}: нет кадра frames/{sid}.png — снимать не с чего")
            continue
        r = review.get(sid)
        if not r:
            problems.append(f"{sid}: кадр не разобран (frames-review.json → frames.{sid})")
            continue
        if r.get("sha1") != file_sha1(fp):
            problems.append(f"{sid}: разбор относится к другому файлу кадра — кадр перегенерирован, "
                            "разбор заново")
            continue
        if r.get("verdict") != "accept":
            problems.append(f"{sid}: вердикт «{r.get('verdict')}» — {r.get('note') or 'без причины'}")
            continue
        checks = r.get("checks") or []
        bad = [c for c in checks if not c.get("ok")]
        if bad:
            problems.append(f"{sid}: принят, но не пройдены проверки: "
                            + "; ".join(f"{c.get('id')} ({c.get('note') or 'без пояснения'})" for c in bad))
        kinds = {c.get("kind") for c in checks}
        missing = [k for k in FRAME_REVIEW_KINDS if k not in kinds]
        if missing:
            problems.append(f"{sid}: в разборе нет проверок вида {', '.join(missing)} — "
                            "свет, камера, цвет, физика и композиция смотрятся у каждого кадра")
    return problems


# ── место: три плана и красота (0.8.30) ───────────────────────────────────────────────────────
# <проект>, заход 2, 13.10.2026: якорь места «стена заполняет кадр, простая скамья,
# фонаря, неба, людей нет» — голая кирпичная стена. Админ: «Ужасная скамейка, ужасная стена …
# В парке стена павильона … кушают мороженое вечером, фонарик, красиво. А тут голая стена. В чём
# здесь красота?» Правила сет-дизайна (cinema/09 разд. 6: три плана, шум, 1–3 цвета,
# говорящий реквизит) стояли у художника в списке «прочитай», но ни одно поле выхода их не
# требовало — и они не применились. Теперь у места это обязательные поля задания на якорь.
PLACE_PLANES = ("fore", "mid", "back")


def place_set_problems(brief):
    """(ошибки, предупреждения) по местам в anchor-brief.json: kind=place → set с тремя планами."""
    errors, warnings = [], []
    for a in (brief or {}).get("anchors") or []:
        name = a.get("name") or a.get("id") or "?"
        kind = a.get("kind")
        if kind is None:
            warnings.append(f"якорь {name}: нет kind (place | person | object) — место без kind "
                            "не проверяется на три плана и красоту")
            continue
        if kind != "place":
            continue
        s = a.get("set") or {}
        planes = s.get("planes") or {}
        missing = [p for p in PLACE_PLANES if not str(planes.get(p) or "").strip()]
        if missing:
            errors.append(f"место {name}: в set.planes пусто {', '.join(missing)} — два плана дают "
                          "плоскость, три глубину (cinema/09, разд. 6)")
        if not str(s.get("beauty_ru") or "").strip():
            errors.append(f"место {name}: нет set.beauty_ru — одной фразой, чем это место красиво "
                          "и почему здесь хочется быть")
        pal = s.get("palette") or []
        if not 1 <= len(pal) <= 3:
            errors.append(f"место {name}: set.palette — 1–3 основных цвета, сейчас {len(pal)} "
                          "(cinema/09, разд. 6)")
        if not s.get("story_props"):
            errors.append(f"место {name}: нет set.story_props — что в месте работает на историю "
                          "(говорящий реквизит, cinema/08 и 09)")
    return errors, warnings


# ── журнал решений (0.8.36) ──────────────────────────────────────────────────────────────────
# Идея — из разбора OpenMontage (18.10.2026): решение — запись с ключом (category, subject);
# смена решения не затирает старое, а добавляет новую запись с тем же ключом. Так тихая смена
# провайдера (R10) видна в файле, а не только в памяти чата. Формат — shared/decision-contract.md.
# Журнал дописывается и не читается гейтами как условие запуска: он память, а не замок.

DECISIONS_FILE = ("clip-memory", "reports", "decisions.jsonl")


def decisions_path(pdir):
    return Path(pdir).joinpath(*DECISIONS_FILE)


def read_decisions(pdir, category=None, subject=None):
    """Записи журнала по порядку; битые строки пропускаются. Фильтр по ключу, если задан."""
    p = decisions_path(pdir)
    if not p.exists():
        return []
    out = []
    with io.open(str(p), "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            if category is not None and r.get("category") != category:
                continue
            if subject is not None and r.get("subject") != subject:
                continue
            out.append(r)
    return out


def last_decision(pdir, category, subject):
    rows = read_decisions(pdir, category, subject)
    return rows[-1] if rows else None


def log_decision(pdir, category, subject, choice, reason="", rejected=None, source=""):
    """Дописывает решение; возвращает запись или None, если оно не изменилось.

    «Не изменилось» — тот же choice и та же причина (или причина не названа): повтор команды
    с тем же --provider не раздувает журнал. Смена choice, а также новая причина — новая запись.
    """
    choice = str(choice)
    reason = (reason or "").strip()
    last = last_decision(pdir, category, subject)
    if last and last.get("choice") == choice and (not reason or last.get("reason") == reason):
        return None
    rec = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "category": category, "subject": subject, "choice": choice, "reason": reason,
           "rejected": list(rejected or []), "source": source}
    if last and last.get("choice") != choice:
        rec["supersedes"] = last.get("choice")
    p = decisions_path(pdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with io.open(str(p), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# ── платформа: «для чего делаем ролик» (0.8.37) ───────────────────────────────────────────────
# Админ, 18.10.2026: субтитры для Suno не нужны, но для Инстаграма и прочего нужны — пусть включаются
# в зависимости от платформы, достаточно указать, для чего делаем. Поле `platform` в project.json
# выбирает профиль из config/platforms.json. Нет поля — старое поведение (ничего не включается и не
# запрещается, hook узнаётся по grid.json): существующие проекты не переписываются.

SUBTITLE_MODES = ("forbidden", "off", "recommended", "required")
SUBTITLE_TEXT = {"forbidden": "ЗАПРЕЩЕНЫ", "off": "выключены", "recommended": "включены (рекомендуются)",
                 "required": "включены (обязательны)"}
PLATFORM_KEYS = ("title", "aspect", "length_sec", "subtitles", "safe_zone", "loudness")


def platforms_path():
    return Path(os.environ.get("CLIPMAKER_PLATFORMS") or (plugin_root() / "config" / "platforms.json"))


def load_platforms():
    """{'default_for': {...}, 'profiles': {имя: профиль}}."""
    return read_json(platforms_path())


def platform_check(name):
    """(профиль, None) или (None, текст ошибки). Проверяет и имя, и полноту профиля."""
    data = load_platforms()
    profiles = data.get("profiles") or {}
    if name not in profiles:
        return None, f"платформа «{name}» неизвестна; есть: {', '.join(sorted(profiles))}"
    prof = profiles[name]
    missing = [k for k in PLATFORM_KEYS if k not in prof]
    if missing:
        return None, f"в профиле {name} нет полей: {', '.join(missing)}"
    if prof["subtitles"] not in SUBTITLE_MODES:
        return None, f"в профиле {name} subtitles = «{prof['subtitles']}», допустимо {', '.join(SUBTITLE_MODES)}"
    return prof, None


def platform_profile(name):
    prof, err = platform_check(name)
    if err:
        fail(err)
    return prof


def project_platform(pdir):
    """Платформа проекта из project.json → (имя | None, профиль | None, ошибка | None).

    Нет project.json или поля — (None, None, None): старое поведение. Неизвестное имя — ошибка текстом,
    а не исключение: сводка статуса не должна падать из-за опечатки.
    """
    try:
        pj = read_json(find_project_json(pdir))
    except SystemExit:
        return None, None, None
    except Exception as e:
        return None, None, f"project.json не читается: {e}"
    name = pj.get("platform") if isinstance(pj, dict) else None
    if not name:
        return None, None, None
    prof, err = platform_check(str(name))
    return (str(name), prof, err) if not err else (str(name), None, err)


def subtitles_status_line(name, prof):
    """Подсказка для статуса: «субтитры: включены/выключены для платформы X»."""
    if not name:
        return "платформа не задана (старое поведение; hook узнаётся по grid.json)"
    return f"платформа {name} · субтитры: {SUBTITLE_TEXT[prof['subtitles']]} для платформы {name}"


def platform_warnings(prof, width=None, height=None, duration=None):
    """Предупреждения о несовпадении ролика с профилем: кадр, длина. Только ориентиры, не отказ."""
    out = []
    if width and height and prof.get("aspect"):
        aw, ah = (int(x) for x in prof["aspect"].split(":"))
        if abs(width / height - aw / ah) > 0.06:
            out.append(f"кадр {width}x{height}, а профиль ждёт {prof['aspect']}")
    ln = prof.get("length_sec") or {}
    if duration:
        if ln.get("min") and duration < ln["min"]:
            out.append(f"ролик {duration:.1f} с короче ориентира {ln['min']} с")
        if ln.get("max") and duration > ln["max"]:
            out.append(f"ролик {duration:.1f} с длиннее ориентира {ln['max']} с")
    return out
