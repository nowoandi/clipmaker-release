# subtitles.py — субтитры и текст песни на экране: words.json → фразы → SRT / ASS → выжигание ffmpeg.
#
# Зачем. Админ, 18.10.2026: «Субтитры — очень классная штука, особенно когда лежишь вечером и включил
# видео не для того, чтобы смотреть, а практически прочитать». Пословные тайминги у нас уже есть:
# faster-whisper локально, бесплатно, `clip-memory/song/words.json`. Не хватало слоя, который собирает
# из них читаемые фразы и кладёт в кадр. Идея разбивки по паузам и знакам взята из разбора video-use
# (18.10.2026); код и пороги здесь свои.
#
# ВАЖНО. В Suno-hook букв в кадре быть не должно: Suno сам показывает текст песни (Админ, 18.10.2026).
# Режим берётся из платформы (0.8.37, config/platforms.json): поле `platform` в project.json или ключ
# --platform. subtitles = forbidden (suno-hook) — выжигание отказывает с кодом 2; иначе разрешено, а безопасная
# зона берётся из профиля. Платформа не задана — старое поведение: hook узнаётся по grid.json → hook.start/end,
# publish/suno-hook.json или файлу `*-suno*.mp4`, там выжигание отказывает; SRT/ASS отдаются с предупреждением.
# Явная платформа не-Suno главнее grid.json (тот же ролик могут пустить и в Инстаграм), но файл `*-suno*.mp4`
# — упаковка под Suno — отказывает всегда.
#
#   python subtitles.py --project <папка>                      # показать фразы, ничего не писать
#   python subtitles.py --project <папка> --srt out.srt --ass out.ass [--karaoke]
#   python subtitles.py --project <папка> --burn in.mp4 --out out.mp4 [--karaoke]
#   python subtitles.py --project <папка> --lyrics --burn in.mp4 --out out.mp4   # текст автора
#   python subtitles.py --check-fonts                          # какие шрифты годятся (кириллица, умляуты)
#   --start/--end — окно трека в секундах: слова берутся из него, время сдвигается к нулю ролика.
#
# Безопасная зона: низ текста — на 30 % высоты выше нижней кромки для вертикали (интерфейс площадки),
# 8 % для горизонтали. Числа — ориентир из сторонних обзоров (`shared/suno/05-safe-zone.md`).
# Выход: 0 — готово; 2 — отказ (причина в stderr).
import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

lib.setup_io()

# ── пороги разбивки (ориентиры, не измерены нами: R23) ──────────────────────────────────────
GAP_BREAK = 0.5       # пауза между словами, на которой фраза закрывается, с
MIN_SHOW = 0.35       # фраза короче не показывается: её продлевают или клеят к соседней, с
HOLD = 0.12           # сколько фраза держится после последнего слова, если соседняя не мешает, с
NEXT_GAP = 0.02       # зазор до следующей фразы, с
BOTTOM_SAFE_PORTRAIT = 0.30   # доля высоты снизу под интерфейс площадки (вертикаль)
BOTTOM_SAFE_LANDSCAPE = 0.08
SIDE_MARGIN = 90 / 1080       # поля слева и справа как доля ширины (зона 900 из 1080)
FONT_PX_1080 = 64             # размер шрифта при ширине кадра 1080
SENT_END = ".!?…"
SOFT_END = ",;:–—"
CLOSERS = "»\"”’')]"

# Шрифты Windows, где есть кириллица и умляуты. (семейство в ASS, файлы жирного и обычного начертаний)
FONT_CANDIDATES = [
    ("Segoe UI", ["segoeuib.ttf"], ["segoeui.ttf"]),
    ("Arial", ["arialbd.ttf"], ["arial.ttf"]),
    ("Tahoma", ["tahomabd.ttf"], ["tahoma.ttf"]),
    ("Verdana", ["verdanab.ttf"], ["verdana.ttf"]),
    ("Trebuchet MS", ["trebucbd.ttf"], ["trebuc.ttf"]),
    ("Calibri", ["calibrib.ttf"], ["calibri.ttf"]),
    ("Impact", [], ["impact.ttf"]),
]
# Символы, без которых шрифт не годится: русские буквы с ё/й/ъ/ы, немецкие умляуты и ß, типографика.
REQUIRED_CHARS = "АЯаяЁёЙйЪъЫыЭэЮюäöüÄÖÜß’“”–—…"


# ── слова ───────────────────────────────────────────────────────────────────────────────────
def load_words(path):
    """words.json → список {word, start, end[, line]}. Форматы: список или {"words": [...]}.

    Пустые слова выбрасываются, слово с концом не позже начала получает длину 0,1 с.
    """
    data = lib.read_json(path)
    raw = data.get("words") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise ValueError(f"{path}: ждали список слов или объект с полем words")
    out = []
    for w in raw:
        if not isinstance(w, dict) or not str(w.get("word", "")).strip():
            continue
        try:
            s, e = float(w["start"]), float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if e <= s:
            e = s + 0.1
        item = {"word": str(w["word"]).strip(), "start": s, "end": e}
        if "line" in w:
            item["line"] = w["line"]
        out.append(item)
    out.sort(key=lambda x: x["start"])
    return out


def cut_window(words, start=None, end=None):
    """Слова окна [start, end] трека со сдвигом к нулю; слово берётся, если его середина в окне."""
    if start is None and end is None:
        return [dict(w) for w in words]
    lo = float(start or 0.0)
    hi = float(end) if end is not None else float("inf")
    out = []
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        if lo <= mid <= hi:
            x = dict(w)
            x["start"] = max(0.0, w["start"] - lo)
            x["end"] = max(x["start"] + 0.05, w["end"] - lo)
            out.append(x)
    return out


def is_cyrillic(words):
    letters = [c for w in words for c in w["word"] if c.isalpha()]
    if not letters:
        return False
    return sum("а" <= c.lower() <= "я" or c.lower() == "ё" for c in letters) / len(letters) > 0.5


def _core(word):
    return word.rstrip(CLOSERS)


def ends_sentence(word):
    return bool(_core(word)) and _core(word)[-1] in SENT_END


def ends_soft(word):
    return bool(_core(word)) and _core(word)[-1] in SOFT_END


# ── фразы ───────────────────────────────────────────────────────────────────────────────────
def group_words(words, max_chars=40, gap=GAP_BREAK, caps_break=False):
    """Слова → фразы (списки слов). Фраза закрывается на: паузе >= gap, конце предложения,
    запятой при двух и больше словах, заглавной (если caps_break — песни по-русски и по-английски,
    где whisper пишет строки с большой буквы; в немецком это не годится: существительные тоже с большой),
    переполнении max_chars. Если у слов есть `line` — границы строк автора главнее знаков.
    """
    phrases, cur = [], []
    for w in words:
        if cur:
            prev = cur[-1]
            g = w["start"] - prev["end"]
            n = len(" ".join(x["word"] for x in cur)) + 1 + len(w["word"])
            if "line" in w and "line" in prev:
                brk = w["line"] != prev["line"] or g >= gap or n > max_chars
            else:
                brk = (g >= gap or n > max_chars or ends_sentence(prev["word"])
                       or (ends_soft(prev["word"]) and len(cur) >= 2)
                       or (caps_break and len(cur) >= 2 and w["word"][:1].isupper()))
            if brk:
                phrases.append(cur)
                cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return _merge_short(phrases, max_chars, gap)


def _text_len(ph):
    return len(" ".join(x["word"] for x in ph))


def _merge_short(phrases, max_chars, gap):
    """Осколки («я», «и», фраза короче MIN_SHOW) клеятся к соседней, если помещаются и пауза мала."""
    changed = True
    while changed and len(phrases) > 1:
        changed = False
        for i, ph in enumerate(phrases):
            dur = ph[-1]["end"] - ph[0]["start"]
            if _text_len(ph) >= 6 and dur >= MIN_SHOW:
                continue
            if "line" in ph[0] and i + 1 < len(phrases) and phrases[i + 1][0].get("line") != ph[0].get("line"):
                continue
            for j in (i + 1, i - 1):
                if not 0 <= j < len(phrases):
                    continue
                a, b = (ph, phrases[j]) if j > i else (phrases[j], ph)
                if b[0]["start"] - a[-1]["end"] < gap and _text_len(a + b) <= max_chars:
                    phrases[min(i, j):max(i, j) + 1] = [a + b]
                    changed = True
                    break
            if changed:
                break
    return phrases


def phrase_times(phrases, video_len=None):
    """Фразы → [{start, end, words}] с удержанием, минимумом показа и без наложений."""
    out = []
    for i, ph in enumerate(phrases):
        start = ph[0]["start"]
        end = ph[-1]["end"] + HOLD
        limit = phrases[i + 1][0]["start"] - NEXT_GAP if i + 1 < len(phrases) else float("inf")
        end = min(end, limit)
        if end - start < MIN_SHOW:
            end = min(start + MIN_SHOW, limit)
        if video_len:
            end = min(end, video_len)
        if end > start:
            out.append({"start": start, "end": end, "words": ph})
    return out


def wrap_index(words, line_chars):
    """Индекс слова, перед которым ставится перенос строки, или None. Фраза делится пополам по знакам."""
    text = " ".join(w["word"] for w in words)
    if len(text) <= line_chars or len(words) < 2:
        return None
    best, best_d = None, None
    for i in range(1, len(words)):
        left = len(" ".join(w["word"] for w in words[:i]))
        right = len(" ".join(w["word"] for w in words[i:]))
        d = abs(left - right)
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


# ── время и экспорт ─────────────────────────────────────────────────────────────────────────
def t_srt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def t_ass(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def to_srt(phrases, line_chars=24):
    blocks = []
    for n, p in enumerate(phrases, 1):
        cut = wrap_index(p["words"], line_chars)
        ws = [w["word"] for w in p["words"]]
        text = " ".join(ws) if cut is None else " ".join(ws[:cut]) + "\n" + " ".join(ws[cut:])
        blocks.append(f"{n}\n{t_srt(p['start'])} --> {t_srt(p['end'])}\n{text}\n")
    return "\n".join(blocks)


def _ass_escape(t):
    return t.replace("{", "(").replace("}", ")").replace("\\", "/")


def style_params(w, h, bottom_safe=None, font_size=None, side_frac=None):
    portrait = h / w >= 1.5
    safe = BOTTOM_SAFE_PORTRAIT if portrait else BOTTOM_SAFE_LANDSCAPE
    if bottom_safe is not None:
        safe = bottom_safe
    size = int(font_size or round(w * FONT_PX_1080 / 1080))
    side = int(round(w * (SIDE_MARGIN if side_frac is None else side_frac)))
    usable = w - 2 * side
    line_chars = max(10, int(usable / (size * 0.58)))
    return {"bottom_safe": safe, "margin_v": int(round(h * safe)), "font_size": size,
            "margin_lr": side, "line_chars": line_chars, "text_bottom_y": int(round(h * (1 - safe)))}


def to_ass(phrases, w, h, font, karaoke=False, bottom_safe=None, font_size=None, bold=True, side_frac=None):
    sp = style_params(w, h, bottom_safe, font_size, side_frac)
    outline = max(2, round(sp["font_size"] / 16))
    # Цвета ASS — &HAABBGGRR. Primary у караоке — «уже спето» (жёлтый), Secondary — «ещё нет» (белый).
    primary = "&H0000DCFF" if karaoke else "&H00FFFFFF"
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{font},{sp['font_size']},{primary},&H00FFFFFF,&H00000000,&H80000000,"
        f"{-1 if bold else 0},0,0,0,100,100,0,0,1,{outline},0,2,{sp['margin_lr']},{sp['margin_lr']},"
        f"{sp['margin_v']},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n")
    lines = []
    for p in phrases:
        ws = p["words"]
        cut = wrap_index(ws, sp["line_chars"])
        parts = []
        for i, wd in enumerate(ws):
            if karaoke:
                nxt = ws[i + 1]["start"] if i + 1 < len(ws) else p["end"]
                k = max(1, int(round((nxt - p["start"]) * 100)) - int(round((wd["start"] - p["start"]) * 100)))
                tag = "{\\k%d}" % k
            else:
                tag = ""
            sep = "\\N" if cut is not None and i == cut else (" " if i else "")
            parts.append(f"{sep}{tag}{_ass_escape(wd['word'])}")
        lines.append(f"Dialogue: 0,{t_ass(p['start'])},{t_ass(p['end'])},Cap,,0,0,0,,{''.join(parts)}")
    return head + "\n".join(lines) + "\n"


# ── шрифты ──────────────────────────────────────────────────────────────────────────────────
def font_dirs():
    """Каталоги шрифтов. CLIPMAKER_FONTS_DIR (через os.pathsep) заменяет системные — для самотеста."""
    env = os.environ.get("CLIPMAKER_FONTS_DIR")
    if env is not None:
        return [Path(x) for x in env.split(os.pathsep) if x]
    win = Path(os.environ.get("WINDIR") or r"C:\Windows")
    local = os.environ.get("LOCALAPPDATA")
    dirs = [win / "Fonts"]
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    return dirs


def _find_file(name):
    for d in font_dirs():
        p = d / name
        if p.exists():
            return p
    return None


def missing_glyphs(path):
    """Символы из REQUIRED_CHARS, которых нет в шрифте; None — проверить нечем (нет fontTools)."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    try:
        font = TTFont(str(path), lazy=True, fontNumber=0)
        cmap = font.getBestCmap() or {}
        font.close()
    except Exception:
        return None
    return [c for c in REQUIRED_CHARS if ord(c) not in cmap]


def font_report():
    """По каждому кандидату: найден ли, чего не хватает. Не бросает."""
    rows = []
    for family, bold, regular in FONT_CANDIDATES:
        bp = [_find_file(x) for x in bold]
        rp = [_find_file(x) for x in regular]
        files = [p for p in bp + rp if p]
        main = files[0] if files else None
        miss = missing_glyphs(main) if main else None
        rows.append({"family": family, "found": bool(main), "bold": any(bp),
                     "files": files, "missing": miss,
                     "ok": bool(main) and (miss == [] or miss is None)})
    return rows


def choose_font(family=None, file=None):
    """Шрифт для ASS: {family, files, bold}. Не нашёл — SystemExit 2: молчаливой подмены нет."""
    if file:
        p = Path(file)
        if not p.exists():
            lib.fail(f"шрифт {p} не найден: путь указан явно, подменять нечем")
        miss = missing_glyphs(p)
        if miss:
            lib.fail(f"в шрифте {p.name} нет символов: {' '.join(miss)} — нужны кириллица и умляуты")
        fam = family or p.stem
        return {"family": fam, "files": [p], "bold": False}
    rows = font_report()
    if family:
        rows = [r for r in rows if r["family"].lower() == family.lower()]
        if not rows:
            lib.fail(f"шрифт «{family}» не в списке проверенных ({', '.join(c[0] for c in FONT_CANDIDATES)}); "
                     "свой файл — --font-file")
    for r in rows:
        if r["ok"]:
            return {"family": r["family"], "files": r["files"], "bold": r["bold"]}
    where = ", ".join(str(d) for d in font_dirs()) or "(каталогов нет)"
    lib.fail("нет шрифта с кириллицей и умляутами среди "
             f"{', '.join(c[0] for c in FONT_CANDIDATES)} в {where}. Субтитры без шрифта получились бы "
             "квадратиками или чужой гарнитурой — отказ вместо молчаливой подмены. Выход: --font-file "
             "путь_к_ttf")


# ── выжигание ───────────────────────────────────────────────────────────────────────────────
def burn(ffmpeg, video, ass_text, out, font, crf=18):
    """Выжигает ASS в видео. Рабочая папка с копией шрифта и файла субтитров: пути с дисками и
    пробелами в фильтре libass ломаются, поэтому в -vf только короткие относительные имена."""
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        (work / "fonts").mkdir()
        for f in font["files"]:
            shutil.copy(str(f), str(work / "fonts" / Path(f).name))
        (work / "sub.ass").write_text(ass_text, encoding="utf-8")
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(Path(video).resolve()),
               "-vf", "ass=sub.ass:fontsdir=fonts", "-c:v", "libx264", "-crf", str(crf),
               "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
               str(Path(out).resolve())]
        r = subprocess.run(cmd, cwd=str(work), capture_output=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            lib.fail("ffmpeg не выжег субтитры:\n" + (r.stderr or "")[-600:])


# ── текст автора (--lyrics) ─────────────────────────────────────────────────────────────────
def parse_lyrics(text):
    """lyrics-author.md → строки песни. Служебное — заголовок до `---`, теги [Verse], # и > — отбрасывается;
    лишний текст не страшен: строки, не нашедшие слов в тайминге, выпадают при привязке."""
    lines = text.splitlines()
    for i, ln in enumerate(lines[:40]):
        if ln.strip() == "---":
            lines = lines[i + 1:]
            break
    out = []
    for ln in lines:
        s = re.sub(r"\[[^\]]*\]", "", ln).strip()
        s = re.sub(r"^[-*•]\s+", "", s)
        if not s or s.startswith(("#", ">", "|", "```")):
            continue
        out.append(s)
    return out


def _norm(t):
    return re.sub(r"[^\w]+", "", t.lower().replace("ё", "е"))


_sim_cache = {}


def _sim(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    key = (a, b)
    if key in _sim_cache:
        return _sim_cache[key]
    if a[0] != b[0] and a[-1] != b[-1]:
        v = 0.0
    else:
        v = difflib.SequenceMatcher(None, a, b).ratio()
    _sim_cache[key] = v
    return v


MATCH_MIN = 0.6
GAP_COST = -0.3
MISMATCH = -0.8


def align_lyrics(lines, words):
    """Привязка строк автора к словам whisper: полуглобальное выравнивание по токенам.

    Начало и конец слов/текста можно пропускать бесплатно (окно hook — кусок песни; текст — вся песня).
    Возвращает ([{text, words:[{word,start,end,matched}]}], [не привязанные строки]).
    Токен без пары внутри привязанной строки получает время интерполяцией между соседями.
    """
    toks = []
    for li, ln in enumerate(lines):
        for t in ln.split():
            if _norm(t):
                toks.append((li, t))
    n, m = len(toks), len(words)
    if not n or not m:
        return [], list(lines)
    L = [_norm(t) for _, t in toks]
    W = [_norm(w["word"]) for w in words]
    H = [[0.0] * (m + 1) for _ in range(n + 1)]
    P = [[0] * (m + 1) for _ in range(n + 1)]   # 1 диагональ, 2 пропуск токена текста, 3 пропуск слова
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = _sim(L[i - 1], W[j - 1])
            diag = H[i - 1][j - 1] + (2.0 * s if s >= MATCH_MIN else MISMATCH)
            up = H[i - 1][j] + GAP_COST
            left = H[i][j - 1] + GAP_COST
            best = max(diag, up, left)
            H[i][j] = best
            P[i][j] = 1 if best == diag else (2 if best == up else 3)
    # Конец — лучшая клетка последней строки или последнего столбца (хвосты бесплатны).
    cells = [(H[n][j], n, j) for j in range(m + 1)] + [(H[i][m], i, m) for i in range(n + 1)]
    _, i, j = max(cells)
    pair = {}
    while i > 0 and j > 0:
        move = P[i][j]
        if move == 1:
            pair[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif move == 2:
            i -= 1
        else:
            j -= 1
    timed = {k: (words[v]["start"], words[v]["end"], _sim(L[k], W[v]) >= MATCH_MIN) for k, v in pair.items()}
    # Строка привязана, если у половины её токенов есть пара.
    by_line = {}
    for k, (li, _) in enumerate(toks):
        by_line.setdefault(li, []).append(k)
    kept, dropped = [], []
    for li in range(len(lines)):
        ks = by_line.get(li, [])
        got = [k for k in ks if k in timed]
        (kept if ks and len(got) * 2 >= len(ks) else dropped).append(li)
    out = []
    anchors = sorted(timed)
    for li in kept:
        ks = by_line[li]
        ws = []
        for k in ks:
            if k in timed:
                s, e, ok = timed[k]
            else:
                prev = max((a for a in anchors if a < k), default=None)
                nxt = min((a for a in anchors if a > k), default=None)
                if prev is not None and nxt is not None:
                    gap_n = nxt - prev
                    s0, e1 = timed[prev][1], timed[nxt][0]
                    s = s0 + (e1 - s0) * (k - prev) / gap_n
                    e = s0 + (e1 - s0) * (k - prev + 0.8) / gap_n
                elif prev is not None:
                    s = timed[prev][1] + 0.3 * (k - prev)
                    e = s + 0.25
                else:
                    s = timed[nxt][0] - 0.3 * (nxt - k)
                    e = s + 0.25
                ok = False
            ws.append({"word": toks[k][1], "start": max(0.0, s), "end": max(e, s + 0.05), "matched": ok})
        out.append({"line": li, "text": lines[li], "words": ws})
    return out, [lines[li] for li in dropped]


# ── безопасность и вход ─────────────────────────────────────────────────────────────────────
def hook_reason(pdir, video=None):
    """Причина, по которой проект/ролик — Suno-hook (там букв нет), или None."""
    grid = Path(pdir) / "clip-memory" / "song" / "grid.json"
    if grid.exists():
        try:
            if lib.hook_window(lib.read_json(grid)):
                return "в grid.json есть окно hook.start/hook.end"
        except Exception:
            pass
    if (Path(pdir) / "publish" / "suno-hook.json").exists():
        return "есть паспорт publish/suno-hook.json"
    if video and "-suno" in Path(video).name.lower():
        return f"файл {Path(video).name} — упаковка suno_pack.py"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--platform", help="профиль из config/platforms.json (иначе — поле platform в project.json)")
    ap.add_argument("--words", help="words.json; по умолчанию clip-memory/song/words.json")
    ap.add_argument("--lyrics", nargs="?", const="", default=None, metavar="ФАЙЛ",
                    help="показывать текст автора (по умолчанию clip-memory/song/lyrics-author.md), "
                         "тайминги — из words.json")
    ap.add_argument("--start", type=float, help="начало окна трека, с")
    ap.add_argument("--end", type=float, help="конец окна трека, с")
    ap.add_argument("--srt", help="записать SRT")
    ap.add_argument("--ass", help="записать ASS")
    ap.add_argument("--burn", metavar="ВИДЕО", help="выжечь субтитры в это видео (нужен --out)")
    ap.add_argument("--out", help="куда писать выжженное видео")
    ap.add_argument("--karaoke", action="store_true", help="подсветка слов по ходу пения (ASS)")
    ap.add_argument("--font", help="семейство из списка проверенных шрифтов")
    ap.add_argument("--font-file", help="свой ttf/otf (кириллица и умляуты обязательны)")
    ap.add_argument("--font-size", type=int)
    ap.add_argument("--bottom-safe", type=float, help="доля высоты снизу, куда текст не заходит "
                                                       "(0,30 для вертикали, 0,08 для горизонтали)")
    ap.add_argument("--max-chars", type=int, default=40)
    ap.add_argument("--gap", type=float, default=GAP_BREAK)
    ap.add_argument("--caps-break", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--size", default="1080x1920", help="кадр для SRT/ASS без видео, ШxВ")
    ap.add_argument("--check-fonts", action="store_true", help="проверить шрифты и выйти")
    a = ap.parse_args()

    if a.check_fonts:
        rows = font_report()
        for r in rows:
            note = ("нет файла" if not r["found"] else
                    "покрытие не проверено (нет fontTools)" if r["missing"] is None else
                    "нет: " + " ".join(r["missing"]) if r["missing"] else "кириллица и умляуты есть")
            print(f"  {'ok  ' if r['ok'] else '--  '}{r['family']:<14} {note}")
        good = [r["family"] for r in rows if r["ok"]]
        if not good:
            lib.fail("ни один шрифт из списка не годится; --font-file путь_к_ttf")
        lib.ok("годятся: " + ", ".join(good))
        return 0

    pdir = lib.project_dir(a.project)
    cfg = lib.load_config()
    ffmpeg = cfg.get("ffmpeg")

    # Платформа: --platform главнее поля project.json; неизвестная — отказ, а не молчаливое умолчание.
    pname, prof = a.platform, None
    if pname:
        prof = lib.platform_profile(pname)
    else:
        pname, prof, perr = lib.project_platform(pdir)
        if perr:
            lib.fail(f"project.json → platform: {perr}")
    reason = hook_reason(pdir, a.burn)
    burning = bool(a.burn or a.out)
    if prof is not None:
        if prof["subtitles"] == "forbidden":
            if burning:
                lib.fail(f"платформа {pname}: субтитры запрещены профилем (config/platforms.json): букв в кадре "
                         "быть не должно, текст песни показывает сам Suno (Админ, 18.10.2026). Выжигание отменено. "
                         "Для Инстаграма и прочего — project.json → platform или --platform instagram-reels.")
            print(f"[~] платформа {pname}: файлы SRT/ASS можно отдать, но в кадр не вшивать", file=sys.stderr)
        elif a.burn and "-suno" in Path(a.burn).name.lower() and burning:
            lib.fail(f"это упаковка под Suno (файл {Path(a.burn).name}): букв в кадре быть не должно. Выжигание отменено.")
        else:
            print(f"  платформа {pname}: субтитры {lib.SUBTITLE_TEXT[prof['subtitles']]}")
    elif reason:
        if burning:
            lib.fail(f"это Suno-hook ({reason}): букв в кадре быть не должно, текст песни показывает сам Suno "
                     "(Админ, 18.10.2026). Выжигание отменено. Субтитры нужны обычным клипам, рилсам и рекламе; "
                     "для них укажи платформу: --platform instagram-reels (или поле platform в project.json).")
        print(f"[~] Suno-hook ({reason}): файлы SRT/ASS можно отдать, но в кадр hook'а их не вшивать",
              file=sys.stderr)
    if a.burn and not a.out:
        lib.fail("--burn нужен с --out: куда писать ролик с субтитрами")

    words_path = Path(a.words) if a.words else pdir / "clip-memory" / "song" / "words.json"
    if not words_path.exists():
        lib.fail(f"нет {words_path}: сначала транскрипция (faster-whisper, пословные тайминги)")
    try:
        words = cut_window(load_words(words_path), a.start, a.end)
    except ValueError as e:
        lib.fail(str(e))
    if not words:
        lib.fail("в окне нет слов: проверь --start/--end и words.json")

    lyrics_note = ""
    if a.lyrics is not None:
        lp = Path(a.lyrics) if a.lyrics else pdir / "clip-memory" / "song" / "lyrics-author.md"
        if not lp.exists():
            lib.fail(f"нет текста автора {lp}")
        full = load_words(words_path)
        src = cut_window(full, a.start, a.end)
        matched, dropped = align_lyrics(parse_lyrics(lp.read_text(encoding="utf-8-sig")), src)
        if not matched:
            lib.fail("текст автора не привязался ни к одному слову окна: проверь файл и окно")
        words = []
        for m in matched:
            for w in m["words"]:
                words.append({**w, "line": m["line"]})
        lyrics_note = f"текст автора: строк привязано {len(matched)}, не привязано {len(dropped)}"
        if dropped:
            print(f"[~] не привязаны к словам (вне окна или служебные): {len(dropped)}", file=sys.stderr)

    caps = a.caps_break == "on" or (a.caps_break == "auto" and is_cyrillic(words))
    phrases = phrase_times(group_words(words, a.max_chars, a.gap, caps))

    w = h = None
    if a.burn:
        if not ffmpeg or not Path(ffmpeg).exists():
            lib.fail("ffmpeg из config/paths.json не найден (R22)")
        import suno_pack
        vdur, w, h = suno_pack.probe(ffmpeg, a.burn)
        phrases = phrase_times(group_words(words, a.max_chars, a.gap, caps), video_len=vdur)
    else:
        try:
            w, h = (int(x) for x in a.size.lower().split("x"))
        except ValueError:
            lib.fail("--size в виде 1080x1920")

    zone = (prof or {}).get("safe_zone") or {}
    bottom = a.bottom_safe if a.bottom_safe is not None else zone.get("bottom")
    sp = style_params(w, h, bottom, a.font_size, zone.get("side"))
    if prof is not None and a.burn:
        for pw in lib.platform_warnings(prof, w, h, vdur):
            print(f"[~] платформа {pname}: {pw} (ориентир, сверить с площадкой)", file=sys.stderr)
    print(f"  фраз: {len(phrases)} из {len(words)} слов; кадр {w}x{h}; низ текста не ниже y={sp['text_bottom_y']} "
          f"(зона интерфейса {sp['bottom_safe'] * 100:.0f}% снизу — ориентир, shared/suno/05-safe-zone.md)")
    if lyrics_note:
        print("  " + lyrics_note)

    if not (a.srt or a.ass or a.burn):
        for p in phrases:
            print(f"  {t_srt(p['start'])} → {t_srt(p['end'])}  {' '.join(x['word'] for x in p['words'])}")
        lib.ok("показ без записи; --srt / --ass / --burn пишут файлы")
        return 0

    if a.srt:
        Path(a.srt).parent.mkdir(parents=True, exist_ok=True)
        Path(a.srt).write_text(to_srt(phrases, sp["line_chars"]), encoding="utf-8")
        print(f"  SRT: {a.srt}")
    font = choose_font(a.font, a.font_file) if (a.ass or a.burn) else None
    if font:
        ass_text = to_ass(phrases, w, h, font["family"], a.karaoke, bottom, a.font_size, font["bold"], zone.get("side"))
        if a.ass:
            Path(a.ass).parent.mkdir(parents=True, exist_ok=True)
            Path(a.ass).write_text(ass_text, encoding="utf-8")
            print(f"  ASS: {a.ass} (шрифт {font['family']})")
        if a.burn:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            burn(ffmpeg, a.burn, ass_text, a.out, font)
            print(f"  ролик с субтитрами: {a.out}")
    lib.ok("субтитры готовы. Посмотреть глазами: читаются ли на экране телефона и не заходят ли под интерфейс")
    return 0


if __name__ == "__main__":
    sys.exit(main())
