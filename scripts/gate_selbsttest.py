# gate_selbsttest.py — самопроверка гейтов на синтетических данных.
#
# Зачем. У хука есть hook_guard_selbsttest.py, у гейтов самопроверки не было вовсе: правка
# gate_script.py или gate_assembly.py проверялась только запуском на живом проекте, а он при
# успехе пишет маркер. Эта проверка делает всё во временной папке и ничего не трогает.
#
#   python gate_selbsttest.py
#
# Выход: 0 — все случаи верны; 1 — есть расхождения.
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

lib.setup_io()
HERE = Path(__file__).resolve().parent
PY = sys.executable

# --- синтетический шот-лист: две крупности, чередуются, сходится с треком -------------------
GRID = {"beat": 0.5, "duration": 8.0, "sections": [{"name": "verse"}]}


def shotlist(form):
    shots = []
    for i in range(1, 5):
        shots.append({
            "id": f"S0{i}", "section": "verse", "beats": 4,
            "size": "WS" if i % 2 else "CU", "angle": "eye",
            "movement": "static" if i % 2 else "push_in_slow",
            "anchors": [], "anchors_free": True,
            "content": "кадр", "light": "окно слева", "note": "зачем",
        })
    return {"form": form, "lyric_relation": "illustrate", "change": "от одиночества к людям",
            "shots": shots}


def make_project(root, form, hero=None):
    mem = root / "clip-memory"
    (mem / "script").mkdir(parents=True)
    (mem / "song").mkdir(parents=True)
    (mem / "script" / "shotlist.json").write_text(
        json.dumps(shotlist(form), ensure_ascii=False), encoding="utf-8")
    (mem / "song" / "grid.json").write_text(json.dumps(GRID), encoding="utf-8")
    (root / "project.json").write_text('{"name": "selbsttest", "canon": {"refs": {}}}',
                                       encoding="utf-8")
    if hero is not None:
        (mem / "script" / "hero.json").write_text(
            json.dumps(hero, ensure_ascii=False), encoding="utf-8")


def run_script(root):
    r = subprocess.run([PY, str(HERE / "gate_script.py"), "--project", str(root)],
                       capture_output=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


FULL = {"treasure": "поёт на чужом языке", "secret": "ушла из дома", "flaw": "не умеет просить",
        "goal": "дойти до моря"}

# (описание, форма, герой, ожидаемый код, ждать ли предупреждение о герое)
SCRIPT_CASES = [
    ("concept без героя — не касается", "concept", None, 0, False),
    ("narrative без hero.json — предупреждение, не стоп", "narrative", None, 0, True),
    ("hybrid без hero.json — предупреждение, не стоп", "hybrid", None, 0, True),
    ("narrative с полным героем — тишина", "narrative", FULL, 0, False),
    ("narrative, не заполнена цель — предупреждение", "narrative",
     {**FULL, "goal": "  "}, 0, True),
    ("narrative, hero.json не объект — предупреждение", "narrative", ["не", "объект"], 0, True),
    ("performance без героя — не касается", "performance", None, 0, False),
]


def make_video(ffmpeg, path, fps, seconds=3):
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=1080x1920:rate={fps}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
                   check=True)


def make_audio(ffmpeg, path, seconds=3):
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)],
                   check=True)


# (описание, fps, ждать ли предупреждение)
FPS_CASES = [
    ("25 fps — норма", 25, False),
    ("30 fps — норма", 30, False),
    ("24 fps — норма", 24, False),
    ("23,976 fps считается 24", 23.976, False),
    ("29,97 fps считается 30", 29.97, False),
    ("50 fps — предупреждение (внешний разбор 08.09.2026)", 50, True),
    ("60 fps — предупреждение", 60, True),
]


# ── Место: три плана и красота (0.8.30) ───────────────────────────────────────────────────────

GOOD_SET = {"planes": {"fore": "размытые листья олеандра по краю", "mid": "стена павильона, скамья",
                       "back": "аллея с фонарями, кроны, луна"},
            "beauty_ru": "тёплый островок света в ночном парке", "palette": ["кремовый", "янтарный", "ночной синий"],
            "story_props": ["закрытый киоск мороженого"]}

PLACE_CASES = [
    # (описание, якорь, ошибок ждём, предупреждений ждём, фраза)
    ("место с тремя планами, красотой, палитрой и реквизитом — чисто",
     {"name": "park", "kind": "place", "set": GOOD_SET}, 0, 0, ""),
    ("голая стена: место без set — четыре претензии",
     {"name": "bench_wall_night", "kind": "place"}, 4, 0, "три глубину"),
    ("место с двумя планами — претензия к back",
     {"name": "p", "kind": "place", "set": {**GOOD_SET, "planes": {"fore": "x", "mid": "y"}}}, 1, 0, "back"),
    ("пять цветов в палитре — претензия", {"name": "p", "kind": "place",
                                          "set": {**GOOD_SET, "palette": list("abcde")}}, 1, 0, "1–3"),
    ("персонаж не проверяется на место", {"name": "heroine", "kind": "person"}, 0, 0, ""),
    ("якорь без kind — предупреждение, не ошибка", {"name": "old"}, 0, 1, "нет kind"),
]


def place_checks():
    res = []
    for desc, anchor, n_err, n_warn, frag in PLACE_CASES:
        errs, warns = lib.place_set_problems({"anchors": [anchor]})
        text = " ".join(errs + warns)
        ok = len(errs) == n_err and len(warns) == n_warn and (frag in text if frag else True)
        res.append((desc, ok, text))
    return res


# ── Регистр реальности (0.8.29) ────────────────────────────────────────────────────────────────

REALITY_CASES = [
    # (описание, поля клипа, поля кадра S01, код, фраза в выводе)
    ("reality не задан — реальный, предупреждение, маркер есть", {}, {}, 0, "reality не задан"),
    ("reality real — тишина", {"reality": "real"}, {}, 0, ""),
    ("reality fantasy без miracle — стоп", {"reality": "fantasy"}, {}, 2, "чудо одно и названо"),
    ("reality fantasy с miracle — проходит", {"reality": "fantasy",
                                             "miracle": "меловое сердце светится и улетает к звёздам"},
     {}, 0, ""),
    ("кадр heightened без miracle у кадра и клипа — стоп", {"reality": "real"},
     {"reality": "heightened"}, 2, "без miracle"),
    ("reality «magic» — стоп, вне словаря", {"reality": "magic"}, {}, 2, "допустимо"),
]


def reality_checks():
    res = []
    for desc, clip, shot, want, frag in REALITY_CASES:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            make_project(root, "concept")
            p = root / "clip-memory" / "script" / "shotlist.json"
            sl = json.loads(p.read_text(encoding="utf-8"))
            sl.update(clip)
            sl["shots"][0].update(shot)
            p.write_text(json.dumps(sl, ensure_ascii=False), encoding="utf-8")
            code, out = run_script(root)
            ok = code == want and (frag.lower() in out.lower() if frag else "reality" not in out)
            if want == 0:
                ok = ok and (root / ".gates" / "script-ok.json").exists()
            res.append((desc, ok, out))
    return res


# ── Формат hook: ролик под окно трека (12.10.2026) ────────────────────────────────────────────
# Повод — Suno-hook <проект>: 4 плана на 22,41 с при треке 219,96 с, gate_script
# сверял сумму с треком, gate_density требовал норму полного клипа, а без шот-листа писал маркер.
# Синтетика: трек 60 с при 100 BPM (баллада), доля 0,6 с, 4 плана по 4 доли = 9,6 с.

def hook_grid(hook="window", duration=60.0):
    g = {"duration": duration, "bpm": 100.0, "beat": 0.6,
         "sections": [{"name": "verse", "start": 0.0, "end": 20.0},
                      {"name": "chorus", "start": 20.0, "end": 30.0},
                      {"name": "outro", "start": 30.0, "end": duration}]}
    if hook == "window":
        g["hook"] = {"start": 20.0, "end": 29.6}
    elif hook is not None:
        g["hook"] = hook
    return g


def hook_project(root, grid, with_shots=True, section="chorus"):
    mem = root / "clip-memory"
    (mem / "script").mkdir(parents=True)
    (mem / "song").mkdir(parents=True)
    (mem / "song" / "grid.json").write_text(json.dumps(grid), encoding="utf-8")
    if with_shots:
        sl = shotlist("concept")
        for s in sl["shots"]:
            s["section"] = section
        (mem / "script" / "shotlist.json").write_text(json.dumps(sl, ensure_ascii=False),
                                                      encoding="utf-8")
    (root / "project.json").write_text(
        '{"name": "selbsttest", "canon": {"refs": {"wall": "u", "steps": "u"}}}', encoding="utf-8")


def hook_checks():
    res = []

    def rec(desc, ok, detail=""):
        res.append((desc, ok, detail))

    def script(grid, **kw):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            hook_project(root, grid, **kw)
            code, out = run_script(root)
            mk = root / ".gates" / "script-ok.json"
            return code, out, (json.loads(mk.read_text(encoding="utf-8")) if mk.exists() else None)

    def density(grid, **kw):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            hook_project(root, grid, **kw)
            code, out = run_py("gate_density.py", "--project", str(root))
            mk = root / ".gates" / "density-ok.json"
            return code, out, (json.loads(mk.read_text(encoding="utf-8")) if mk.exists() else None)

    code, out, mk = script(hook_grid())
    rec("gate_script: hook 9,6 с в треке 60 с — сумма сверяется с окном, маркер с format=hook",
        code == 0 and mk and mk.get("format") == "hook" and mk.get("window") == [20.0, 29.6], out.strip()[:200])
    code, out, mk = script(hook_grid(hook=None))
    rec("gate_script: тот же шот-лист без окна — полный клип, расхождение с треком, маркера нет",
        code == 2 and "длине трека" in out and mk is None, out.strip()[:200])
    code, out, _ = script({**hook_grid(), "hook": {"start": 20.0, "end": 40.0}})
    rec("gate_script: окно 20 с при 9,6 с долей — отказ с упоминанием окна",
        code == 2 and "окне hook" in out, out.strip()[:200])
    code, out, _ = script(hook_grid(hook={"start": 20.0}))
    rec("gate_script: в окне только start — отказ, а не тихий откат к полному клипу",
        code == 2 and "start и end" in out, out.strip()[:200])
    code, out, _ = script(hook_grid(hook={"start": 55.0, "end": 64.6}))
    rec("gate_script: конец окна за концом трека — отказ", code == 2 and "за концом трека" in out,
        out.strip()[:200])
    code, out, _ = script(hook_grid(), section="verse")
    rec("gate_script: кадр из раздела вне окна — отказ", code == 2 and "не пересекается" in out,
        out.strip()[:200])
    code, out, _ = script(hook_grid(hook={"recommended_start": 20.0, "recommended_end": 29.6}))
    rec("gate_script: подсказки музыковеда без start/end — полный клип и предупреждение",
        code == 2 and "[~]" in out and "hook.start" in out, out.strip()[:200])

    code, out, mk = density(hook_grid())
    rec("gate_density: hook 4 плана — норма считается на окно, проходит без --sparse-ok",
        code == 0 and mk and mk.get("format") == "hook" and not mk.get("sparse_ok")
        and mk.get("shots") == 4, out.strip()[:200])
    code, out, mk = density(hook_grid(hook=None))
    rec("gate_density: те же 4 плана как полный клип на 60 с — отказ по норме, маркера нет",
        code == 2 and "норма" in out and mk is None, out.strip()[:200])
    code, out, mk = density(hook_grid(), with_shots=False)
    rec("gate_density: без шот-листа — код 0, но маркер НЕ пишется (был ложный успех)",
        code == 0 and mk is None and "НЕ записан" in out, out.strip()[:200])
    code, out, mk = density(hook_grid(hook=None, duration=220.0), with_shots=False)
    rec("gate_density: без шот-листа 2 установки на трек 220 с — отказ (нужно 3)",
        code == 2 and mk is None and "установок нужно 3" in out, out.strip()[:200])
    return res


# ── Рекламная ветка (10.10.2026) ──────────────────────────────────────────────────────────────

def run_py(script, *args):
    r = subprocess.run([PY, str(HERE / script), *args], capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def new_ad(root, patch=None, kind="ad"):
    """Завести проект скаффолдом и (для рекламы) поправить паспорт. Вернуть папку проекта."""
    run_py("clip_scaffold.py", "--name", "Сумка", "--slug", "bag", "--kind", kind, "--root", str(root))
    pdir = root / "bag"
    if patch is not None:
        pp = pdir / "clip-memory" / "product" / "product.json"
        d = json.loads(pp.read_text(encoding="utf-8"))
        d.update(patch)
        pp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return pdir


PASSPORT_OK = {"format": "ad", "platforms": ["wb"], "duration_sec": 8,
               "photos": ["clip-memory/product/photos/a.jpg", "clip-memory/product/photos/b.jpg",
                          "clip-memory/product/photos/c.jpg"],
               "must_match": ["цвет", "пряжка", "ручка"], "must_not_claim": ["натуральная кожа"],
               "offer": {"slogan": "слоган", "hook": "крючок", "benefit": "", "cta": ""}}


def put_photos(pdir):
    for n in ("a.jpg", "b.jpg", "c.jpg"):
        (pdir / "clip-memory" / "product" / "photos" / n).write_bytes(b"\xff\xd8\xff\xd9")


def ad_shot(i, act, sec, size, mv, vis=True, anchors=("product",)):
    return {"id": f"S0{i}", "act": act, "sec": sec, "size": size, "angle": "eye", "movement": mv,
            "anchors": list(anchors), "product_visible": vis, "src": f"N0{i}",
            "content": "сумка", "light": "окно слева", "note": "зачем"}


def write_ad_shotlist(pdir, shots, **kw):
    sl = {"form": "ad", "format": "ad", "duration_sec": 8, "change": "от пустоты к вещи",
          "shots": shots, "sources": {f"N0{i}": {"desc": f"источник {i}"} for i in range(1, 8)}}
    sl.update(kw)
    mem = pdir / "clip-memory"
    (mem / "script").mkdir(parents=True, exist_ok=True)
    (mem / "script" / "shotlist.json").write_text(json.dumps(sl, ensure_ascii=False), encoding="utf-8")
    (mem / "canon").mkdir(parents=True, exist_ok=True)
    (mem / "canon" / "anchor-brief.json").write_text(
        json.dumps({"anchors": [{"name": "product", "kind": "anchor"}]}), encoding="utf-8")


GOOD4 = lambda: [ad_shot(1, "intro", 2, "WS", "static", vis=False), ad_shot(2, "turn", 2, "MS", "push_in_slow"),
                 ad_shot(3, "main", 2.5, "CU", "tracking"), ad_shot(4, "outro", 1.5, "MCU", "static")]


def ad_checks(ffmpeg):
    """Вернуть список (описание, ok, подробности) по рекламной ветке."""
    res = []

    def rec(desc, ok, detail=""):
        res.append((desc, bool(ok), detail))

    # ── скаффолд ──
    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t))
        rec("скаффолд --kind ad: паспорт товара создан", (pdir / "clip-memory/product/product.json").exists())
        rec("скаффолд --kind ad: папки трека нет (у рекламы его нет)", not (pdir / "clip-memory/song").exists())
        rec("скаффолд --kind ad: меню START.bat ведёт в ad-new",
            "ad-new" in (pdir / "START.bat").read_text(encoding="utf-8", errors="replace"))
        rec("скаффолд --kind ad: CLAUDE.md проекта — про рекламу",
            "рекламного ролика" in (pdir / "CLAUDE.md").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as t:
        code, _ = run_py("clip_scaffold.py", "--name", "Сумка", "--kind", "ad", "--root", t, "--track", "x.mp3")
        rec("скаффолд --kind ad с --track — отказ (у рекламы нет трека)", code != 0, f"код {code}")
    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t), kind="clip")
        rec("скаффолд клипа не затронут: папка трека на месте", (pdir / "clip-memory/song").exists())
        rec("скаффолд клипа не затронут: START.bat ведёт в clip-new",
            "clip-new" in (pdir / "START.bat").read_text(encoding="utf-8", errors="replace"))
        rec("скаффолд клипа не затронут: паспорта товара нет",
            not (pdir / "clip-memory/product").exists())

    # ── gate_product ──
    def gp(patch, photos=True):
        with tempfile.TemporaryDirectory() as t:
            pdir = new_ad(Path(t), patch)
            if photos:
                put_photos(pdir)
            return run_py("gate_product.py", "--project", str(pdir))

    code, out = gp(None)
    rec("гейт товара: свежий пустой паспорт — отказ", code == 2, f"код {code}")
    code, out = gp(PASSPORT_OK)
    rec("гейт товара: полный паспорт — принят", code == 0, out.strip()[:200])
    code, out = gp(PASSPORT_OK, photos=False)
    rec("гейт товара: фото в паспорте есть, файлов нет — отказ", code == 2 and "файла нет" in out)
    code, _ = gp({**PASSPORT_OK, "offer": {"slogan": "", "hook": "", "benefit": "", "cta": ""}})
    rec("гейт товара: для ad без слогана и крючка — отказ", code == 2)
    code, _ = gp({**PASSPORT_OK, "format": "card", "offer": {"slogan": "", "hook": "", "benefit": "", "cta": ""}})
    rec("гейт товара: для card слоган не нужен — принят", code == 0)
    code, _ = gp({**PASSPORT_OK, "format": "video"})
    rec("гейт товара: формат вне card/ad — отказ", code == 2)
    code, _ = gp({**PASSPORT_OK, "platforms": ["myspace"]})
    rec("гейт товара: площадка вне списка — отказ", code == 2)
    code, _ = gp({**PASSPORT_OK, "must_match": []})
    rec("гейт товара: пустой must_match — отказ (приёмке нечего сверять)", code == 2)
    code, out = gp({**PASSPORT_OK, "photos": PASSPORT_OK["photos"][:1]})
    rec("гейт товара: одно фото — принят, но с предупреждением", code == 0 and "[~]" in out)

    # ── формат кадра: 3:4 (Админ 10.10.2026) ──
    def project_json(pdir):
        return json.loads(next(pdir.glob("project.*.json")).read_text(encoding="utf-8"))

    def passport_of(pdir):
        return json.loads((pdir / "clip-memory/product/product.json").read_text(encoding="utf-8"))

    import clip_studio
    import gate_conformance

    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t))
        pj = project_json(pdir)
        rec("формат кадра: в паспорте рекламы умолчание 3:4", passport_of(pdir).get("aspect") == "3:4")
        rec("формат кадра: project.json рекламы приведён к 3:4 (кадры, видео, сборка 1080x1440)",
            pj["image"]["aspect_ratio"] == "3:4" and pj["video"]["aspect_ratio"] == "3:4"
            and (pj["render"]["width"], pj["render"]["height"]) == (1080, 1440), str(pj.get("render")))
        rec("формат кадра: CLAUDE.md проекта называет формат",
            "формат кадра: **3:4**" in (pdir / "CLAUDE.md").read_text(encoding="utf-8"))
        rec("формат кадра: лист сверки со сценой рисует плитки 3:4, а не 9:16",
            abs(gate_conformance.frame_ratio(pdir) - 4 / 3) < 1e-6, str(gate_conformance.frame_ratio(pdir)))
        rec("формат кадра: карточки студийной панели — 3:4", clip_studio.frame_ar(pj) == "1080/1440")
    with tempfile.TemporaryDirectory() as t:
        code, _ = run_py("clip_scaffold.py", "--name", "Сумка", "--slug", "bag", "--kind", "ad",
                         "--aspect", "1:1", "--root", t)
        pj = project_json(Path(t) / "bag")
        rec("формат кадра: --aspect 1:1 — квадрат и в паспорте, и в project.json",
            code == 0 and passport_of(Path(t) / "bag").get("aspect") == "1:1"
            and pj["video"]["aspect_ratio"] == "1:1"
            and (pj["render"]["width"], pj["render"]["height"]) == (1080, 1080), f"код {code}")
    with tempfile.TemporaryDirectory() as t:
        code, _ = run_py("clip_scaffold.py", "--name", "Клип", "--kind", "clip", "--aspect", "3:4", "--root", t)
        rec("формат кадра: --aspect клипу — отказ (клип всегда 9:16)", code != 0, f"код {code}")
    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t), kind="clip")
        pj = project_json(pdir)
        rec("формат кадра: клип остался 9:16 (кадры, видео, 1080x1920)",
            pj["image"]["aspect_ratio"] == "9:16" and pj["video"]["aspect_ratio"] == "9:16"
            and (pj["render"]["width"], pj["render"]["height"]) == (1080, 1920), str(pj.get("render")))
        rec("формат кадра: лист сверки клипа остался 9:16",
            abs(gate_conformance.frame_ratio(pdir) - 16 / 9) < 1e-6)
    code, out = gp({**PASSPORT_OK, "aspect": "5:7"})
    rec("гейт товара: формат кадра вне набора 3:4 / 1:1 / 9:16 — отказ", code == 2 and "aspect" in out,
        out.strip()[:200])
    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t), PASSPORT_OK)
        put_photos(pdir)
        pp = pdir / "clip-memory/product/product.json"
        d = json.loads(pp.read_text(encoding="utf-8"))
        d.pop("aspect", None)
        pp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        code, out = run_py("gate_product.py", "--project", str(pdir))
        rec("гейт товара: aspect не записан — принят с предупреждением, берётся 3:4",
            code == 0 and "aspect не записан" in out, out.strip()[:200])
    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t), {**PASSPORT_OK, "aspect": "9:16"})   # project.json остался 3:4
        put_photos(pdir)
        code, out = run_py("gate_product.py", "--project", str(pdir))
        rec("гейт товара: паспорт 9:16, а project.json 3:4 — отказ с подсказкой --apply-aspect",
            code == 2 and "--apply-aspect" in out, out.strip()[:240])
        code, out = run_py("gate_product.py", "--project", str(pdir), "--apply-aspect")
        pj = project_json(pdir)
        rec("гейт товара: --apply-aspect приводит project.json к паспорту и пропускает",
            code == 0 and pj["video"]["aspect_ratio"] == "9:16" and pj["image"]["aspect_ratio"] == "9:16"
            and pj["render"]["height"] == 1920, out.strip()[:240])
    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t), {**PASSPORT_OK, "aspect": "1:1"})   # project.json остался 3:4
        put_photos(pdir)
        write_ad_shotlist(pdir, GOOD4())
        code, out = run_py("gate_ad_script.py", "--project", str(pdir))
        rec("рекламный шот-лист: формат паспорта разошёлся с project.json — отказ (кадры ушли бы не в том формате)",
            code == 2 and "формат кадра расходится" in out, out.strip()[:240])

    # ── gate_ad_script ──
    def gs(shots, **kw):
        with tempfile.TemporaryDirectory() as t:
            pdir = new_ad(Path(t), PASSPORT_OK)
            put_photos(pdir)
            write_ad_shotlist(pdir, shots, **kw)
            code, out = run_py("gate_ad_script.py", "--project", str(pdir))
            markers = sorted(p.name for p in (pdir / ".gates").glob("*.json")) if (pdir / ".gates").exists() else []
            return code, out, markers

    code, out, mk = gs(GOOD4())
    rec("рекламный шот-лист: корректный — принят", code == 0, out.strip()[:200])
    rec("рекламный шот-лист: пишет script-ok и density-ok для хука",
        "script-ok.json" in mk and "density-ok.json" in mk, str(mk))
    bad = GOOD4(); bad[-1]["product_visible"] = False
    code, out, _ = gs(bad)
    rec("рекламный шот-лист: в финале нет товара — отказ", code == 2 and "нет товара" in out)
    bad = GOOD4(); bad[1]["anchors"] = []; bad[1]["anchors_free"] = True
    code, out, _ = gs(bad)
    rec("рекламный шот-лист: товар в кадре без якоря товара — отказ", code == 2 and "product" in out)
    bad = GOOD4(); bad[0]["sec"] = 5
    code, out, _ = gs(bad)
    rec("рекламный шот-лист: сумма секунд не сходится — отказ", code == 2 and "сумма sec" in out)
    bad = GOOD4(); bad[1]["size"], bad[1]["movement"] = bad[0]["size"], bad[0]["movement"]
    code, out, _ = gs(bad)
    rec("рекламный шот-лист: соседи с одной крупностью и движением — отказ", code == 2)
    aba = [ad_shot(1, "intro", 2, "WS", "static", vis=False), ad_shot(2, "turn", 2, "CU", "push_in_slow"),
           ad_shot(3, "main", 2.5, "WS", "tracking"), ad_shot(4, "outro", 1.5, "MCU", "static")]
    code, out, _ = gs(aba)
    rec("рекламный шот-лист: «через один» — предупреждение, не отказ",
        code == 0 and "через один" in out, out.strip()[:160])
    code, out, _ = gs(GOOD4())
    rec("рекламный шот-лист: без красных пар крупностей предупреждения «звезды» нет",
        code == 0 and "схеме «звезда»" not in out, out.strip()[:160])
    red = [ad_shot(1, "intro", 2, "EWS", "static", vis=False), ad_shot(2, "turn", 2, "CU", "push_in_slow"),
           ad_shot(3, "main", 2.5, "MS", "tracking"), ad_shot(4, "outro", 1.5, "MCU", "static")]
    code, out, _ = gs(red)
    rec("рекламный шот-лист: Дальний рядом с Крупным — предупреждение схемы «звезда», не отказ",
        code == 0 and "схеме «звезда»" in out and "EWS и CU" in out, out.strip()[:200])
    noturn = GOOD4(); noturn[1]["act"] = "main"
    code, out, _ = gs(noturn)
    rec("рекламный шот-лист: нет поворота — предупреждение", code == 0 and "act=turn" in out)
    longout = GOOD4()   # сумма держится на 8 с: 0,5 + 0,5 + 0,5 + 6,5
    for shot, sec in zip(longout, (0.5, 0.5, 0.5, 6.5)):
        shot["sec"] = sec
    code, out, _ = gs(longout)
    rec("рекламный шот-лист: развязка длиннее 5 с — предупреждение", code == 0 and "развязка" in out)
    code, out, _ = gs(GOOD4(), form="narrative")
    rec("рекламный шот-лист: form не ad — отказ", code == 2)
    code, out, _ = gs(GOOD4()[:2])
    rec("рекламный шот-лист: два плана для ad — отказ (нужно 3–7)", code == 2)

    # ── статус ──
    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t), PASSPORT_OK)
        code, out = run_py("clip_status.py", "--project", str(pdir))
        rec("статус рекламного проекта: узнаёт рекламу, подсказывает паспорт товара",
            code == 0 and "реклама" in out and "паспорт товара" in out, out.strip()[-160:])

    # ── сборка (нужен ffmpeg) ──
    if not ffmpeg or not Path(ffmpeg).exists():
        res.append(("рекламная сборка пропущена: нет ffmpeg", True, ""))
        return res
    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t), PASSPORT_OK)
        put_photos(pdir)
        write_ad_shotlist(pdir, GOOD4())
        for i in range(1, 5):
            # Клип 24 к/с, а ролик собирается в 30: именно на разнице частот первая версия теряла кадры.
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            f"testsrc2=size=1080x1920:rate=24:duration=4", "-c:v", "libx264", "-pix_fmt",
                            "yuv420p", str(pdir / "clips" / f"N0{i}.mp4")], check=True)
        code, out = run_py("ad_assemble.py", "--project", str(pdir))
        rec("рекламная сборка: 4 плана из клипов 24 к/с → ролик 30 к/с", code == 0, out.strip()[:200])
        rec("рекламная сборка: ровно 240 кадров (потери кадра на стыках нет)", "кадров : 240 (ждали 240)" in out, out)
        rec("рекламная сборка: на нормальном 30 к/с ложного предупреждения о частоте нет (метаданные врут)",
            "[~] частота кадров" not in out, out)
        rec("рекламная сборка: размер по формату проекта — 1080x1440, а не клиповые 1080x1920",
            "· 1080x1440 ·" in out, out)
        rec("рекламная сборка: клипы 9:16 в кадре 3:4 — предупреждение, что теряется четверть высоты",
            "[~]" in out and "теряется 25% высоты" in out, out)
        short = pdir / "clips" / "N03.mp4"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=1080x1920:rate=24:duration=1", "-c:v", "libx264", "-pix_fmt",
                        "yuv420p", str(short)], check=True)
        code, out = run_py("ad_assemble.py", "--project", str(pdir), "--out", "short")
        rec("рекламная сборка: клип короче плана — отказ, не растяжка (R21)",
            code == 2 and "не хватает материала" in out, out.strip()[:200])
    with tempfile.TemporaryDirectory() as t:
        pdir = new_ad(Path(t), PASSPORT_OK)
        put_photos(pdir)
        write_ad_shotlist(pdir, GOOD4())
        for i in range(1, 5):
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            f"testsrc2=size=1080x1440:rate=24:duration=4", "-c:v", "libx264", "-pix_fmt",
                            "yuv420p", str(pdir / "clips" / f"N0{i}.mp4")], check=True)
        code, out = run_py("ad_assemble.py", "--project", str(pdir))
        rec("рекламная сборка: клипы уже 3:4 — ролик 1080x1440 и ни слова об обрезке",
            code == 0 and "1080x1440" in out and "теряется" not in out, out.strip()[:240])
        code, out = run_py("ad_assemble.py", "--project", str(pdir), "--size", "1080x1920", "--out", "tall")
        rec("рекламная сборка: --size перекрывает формат проекта (1080x1920), обрезка 3:4 в 9:16 названа",
            code == 0 and "· 1080x1920 ·" in out and "теряется" in out, out.strip()[:240])
    return res


# --- предполёт: мост против Kie (12.10.2026, <проект>) -------------------------
# Видео шло через Kie, а предполёт считал квоту моста и стоял на «НЕ ВЛЕЗАЕМ»; деньги Kie не
# держал никакой код. Здесь — во временной папке: свой конфиг, своя книга расходов, а баланс
# Kie подменяется, потому что настоящий запрос ушёл бы в сеть с настоящим ключом.
# Цифры — из сметы того прогона: 4,5 кр./с, потолок 198, ролик 6 с = 27 кр.
def preflight_checks():
    import contextlib
    import io
    import os
    import clip_ledger
    import gate_preflight

    results = []

    def rec(desc, ok, detail=""):
        results.append((desc, ok, detail))

    def run(pdir, argv, balance):
        orig_bal, orig_argv = clip_ledger.kie_balance, sys.argv
        clip_ledger.kie_balance = (lambda cfg: (balance, None)) if balance is not None \
            else (lambda cfg: (None, "selbsttest: без сети"))
        sys.argv = ["gate_preflight.py", "--project", str(pdir), *argv]
        buf, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                gate_preflight.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
        finally:
            clip_ledger.kie_balance, sys.argv = orig_bal, orig_argv
        return code, buf.getvalue()

    env_old = {k: os.environ.get(k) for k in ("CLIPMAKER_CONFIG", "LOCALAPPDATA")}
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        bridge = root / "bruecke"
        bridge.mkdir()
        cfg = lib.load_config()
        cfg.update({"grok_bridge": str(bridge), "batch_max": 5, "default_retries": 1})
        (root / "paths.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        os.environ["CLIPMAKER_CONFIG"] = str(root / "paths.json")
        os.environ["LOCALAPPDATA"] = str(root / "appdata")
        ledger = clip_ledger.ledger_path()
        try:
            n = [0]

            def case(desc, argv, want, frag="", balance=8146.1, video=None, budget="ok",
                     spent=0.0, marker=None, stage="shoot", review="ok"):
                n[0] += 1
                pdir = root / f"p{n[0]}"
                v = {"provider": "bridge", "model": "grok-imagine/image-to-video", "duration": 6}
                v.update(video or {})
                v = {k: x for k, x in v.items() if x is not None}
                scenes = [{"id": f"S0{i}", "block": 1 if i <= 4 else 2} for i in range(1, 7)]
                lib.write_json(pdir / "project.json", {"project": pdir.name, "video": v, "scenes": scenes})
                # Глаз оператора (0.8.28): кадры и их разбор. review — ok | None | stale | reject | nokinds.
                frames = {}
                for sc in scenes:
                    fp = pdir / "frames" / f"{sc['id']}.png"
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_bytes(b"frame " + sc["id"].encode())
                    kinds = ["light", "camera"] if review == "nokinds" else list(lib.FRAME_REVIEW_KINDS)
                    frames[sc["id"]] = {
                        "sha1": "0" * 40 if review == "stale" else lib.file_sha1(fp),
                        "verdict": "reject" if review == "reject" else "accept",
                        "note": "рука и линия в разных местах" if review == "reject" else "",
                        "checks": [{"id": k, "kind": k, "ok": True} for k in kinds]}
                if review:
                    lib.write_json(pdir / "clip-memory" / "reports" / "frames-review.json",
                                   {"reviewer": "clip-guardian", "frames": frames})
                if budget:
                    b = {"verdict": "OK", "generation_allowed": True,
                         "prices": {"kie_grok_imagine_i2v_720p_credits_per_sec": 4.5},
                         "kie_balance": {"credits": 8146.1},
                         "motion": {"model": "grok-imagine/image-to-video", "ceiling_credits": 198.0}}
                    if isinstance(budget, dict):
                        b.update(budget)
                    lib.write_json(pdir / "clip-memory" / "reports" / "budget.json", b)
                # Чужой проект в книге — всегда: его траты в потолок этого не идут.
                rows = [{"kind": "spend", "project": "anderer-clip", "stage": "shoot", "kie_spent": 150.0}]
                if spent:
                    rows.append({"kind": "spend", "project": pdir.name, "stage": stage, "kie_spent": spent})
                ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
                code, out = run(pdir, argv, balance)
                mk = lib.read_marker(pdir, "preflight-ok.json", 0)
                ok = code == want and frag in out and (want != 0 or bool(mk))
                if ok and marker:
                    ok = all(mk.get(k) == x for k, x in marker.items())
                rec(f"{desc}: код {code} (ждали {want})", ok, out)

            api = ["--provider", "api"]
            one = api + ["--only", "S01"]
            case("глаз оператора: кадры не разобраны — стоп", one, 2, "ГЛАЗ ОПЕРАТОРА", review=None)
            case("глаз оператора: разбор от прежнего файла кадра — стоп", one, 2, "перегенерирован",
                 review="stale")
            case("глаз оператора: кадр отклонён — стоп с причиной", one, 2, "рука и линия", review="reject")
            case("глаз оператора: нет проверок цвета и физики — стоп", one, 2, "color, physics",
                 review="nokinds")
            case("глаз оператора: --no-frames-review с причиной — проходит, причина в маркере",
                 one + ["--no-frames-review", "проба модели"], 0, "ПРЕДУПРЕЖДЕНИЕ", review=None,
                 marker={"frames_review": {"skipped": "проба модели"}})
            case("глаз оператора: принятый разбор — маркер frames_review accepted", one, 0,
                 marker={"frames_review": "accepted"})
            case("журнал решений: явный --provider api с причиной — гейт проходит, запись video-provider:<проект>",
                 one + ["--provider-reason", "проба Kie на S01"], 0)
            dec = lib.last_decision(root / f"p{n[0]}", "video-provider", f"p{n[0]}")
            rec("журнал решений: в decisions.jsonl choice api, причина, отвергнут bridge",
                bool(dec) and dec["choice"] == "api" and dec["reason"] == "проба Kie на S01"
                and dec["rejected"] == ["bridge"], str(dec))
            case("Kie, прогон 1 сметы: S01–S03 по 6 с = 81 кр. — маркер provider api",
                 api + ["--only", "S01,S02,S03"], 0,
                 marker={"provider": "api", "batch_credits": 81.0, "scenes": ["S01", "S02", "S03"],
                         "only": True, "duration": 6})
            case("форма 12.10: квота моста пуста, Kie это не касается — проходит",
                 api + ["--only", "S04"], 0, video={"duration": 10}, marker={"batch_credits": 45.0})
            case("Kie, блок 1 без --only: 4 × 27 = 108 кр.", api + ["--block", "1"], 0,
                 marker={"only": False, "scenes": ["S01", "S02", "S03", "S04"], "block": 1})
            case("provider api из project.json без флага — ветка Kie", ["--only", "S01"], 0,
                 video={"provider": "api"}, marker={"provider": "api"})
            case("СТОП-2 сметы: блок 1 по 10 с = 180 кр. после 81 по книге — потолок",
                 api + ["--block", "1"], 2, "ПОТОЛОК", video={"duration": 10}, spent=81.0)
            case("потолок не снимает --force-estimate", api + ["--block", "1", "--force-estimate"], 2,
                 "ПОТОЛОК", video={"duration": 10}, spent=81.0)
            case("баланс Kie меньше партии — стоп", api + ["--only", "S01,S02,S03"], 2, "на балансе",
                 balance=50.0, budget={"kie_balance": {"credits": 60.0}})
            # Живой случай 12.10.2026 23:38: прогон 1 (81 кр.) прошёл, в книгу не попал.
            case("прогон не в книге: баланс со сметы упал на 81 — блок 1 по 10 с упирается в потолок",
                 api + ["--block", "1"], 2, "ПОТОЛОК", video={"duration": 10}, balance=8065.1)
            case("прогон не в книге: S04 по 10 с = 45 из оставшихся 117 — летим, счёт от баланса",
                 api + ["--only", "S04"], 0, "Считаю от баланса", video={"duration": 10}, balance=8065.1,
                 marker={"spent_before": 81.0})
            case("retake в книге — переген кадров, не видео (12.10.2026)", api + ["--only", "S01"], 0,
                 spent=12.0, stage="retake", marker={"spent_before": 0.0})
            case("баланс не снят — стоп", api + ["--only", "S01"], 2, "баланс Kie не снят", balance=None)
            case("баланс не снят, --force-estimate — летим с предупреждением",
                 api + ["--only", "S01", "--force-estimate"], 0, "ПРЕДУПРЕЖДЕНИЕ", balance=None)
            case("нет budget.json — потолка нет, стоп", api + ["--only", "S01"], 2, "нет сметы", budget=None)
            case("вердикт сметы BLOCKER — стоп", api + ["--only", "S01"], 2, "вердикт сметы",
                 budget={"verdict": "BLOCKER"})
            case("смета на другую модель — стоп", api + ["--only", "S01"], 2, "Другая модель",
                 budget={"motion": {"model": "seedance", "ceiling_credits": 198.0}})
            case("--only со сценой не из выборки — стоп", api + ["--only", "S01,S09"], 2, "S09")
            case("нет video.model — стоп", api + ["--only", "S01"], 2, "video.model", video={"model": None})
            case("6 сцен без --only — больше batch_max, стоп (R11)", api, 2, "6 > 5")
            case("--planned не равен выборке — стоп", api + ["--only", "S01,S02", "--planned", "3"], 2,
                 "--planned 3")
            # Модели нет в motion_prices: иначе цену дала бы таблица, а не cost_hint.
            nomodel = {"prices": {}, "motion": {"model": "unknown/model", "ceiling_credits": 198.0}}
            case("цена только cost_hint (модели нет в таблице) — летим, но с предупреждением",
                 api + ["--only", "S01"], 0, "cost_hint — цена ролика",
                 video={"cost_hint": 27, "model": "unknown/model"}, budget=nomodel,
                 marker={"batch_credits": 27.0})
            case("нет цены вовсе (модели нет в таблице) — стоп", api + ["--only", "S01"], 2,
                 "цена ролика неизвестна", video={"model": "unknown/model"}, budget=nomodel)
            case("мост по video.provider проекта — как прежде, маркер provider bridge",
                 ["--planned", "4"], 0, "отправок режима", marker={"provider": "bridge", "planned": 4})
            case("--only у моста — стоп: партию моста задаёт --planned", ["--only", "S01"], 2, "--planned")
            # 29.10.2026: бесплатный мост Grok кончился. Умолчание — Kie, цена — из motion_prices.
            case("умолчание 29.10.2026: ни флага, ни video.provider — ветка Kie, не мост",
                 ["--only", "S01"], 0, video={"provider": None}, marker={"provider": "api"})
            case("умолчание: без провайдера --planned моста не годится — партию Kie задаёт --only",
                 ["--planned", "4"], 2, "--planned 4", video={"provider": None})
            case("цена из таблицы: проект и смета её не дают — Grok 6 с = 27 кр. по motion_prices",
                 api + ["--only", "S01"], 0, "motion_prices", budget={"prices": {}},
                 marker={"credits_per_clip": 27.0, "batch_credits": 27.0})
            veo_budget = {"prices": {}, "motion": {"model": "veo3_lite", "ceiling_credits": 198.0}}
            case("Veo 3.1 Lite 8 с — ролик 30 кр. по таблице (цена ролика, не секунды)",
                 api + ["--only", "S01"], 0, "motion_prices", video={"model": "veo3_lite", "duration": 8},
                 budget=veo_budget, marker={"credits_per_clip": 30.0, "batch_credits": 30.0, "model": "veo3_lite"})
            case("доллары на экране: партия Veo Lite 30 кр. ≈ $0.15",
                 api + ["--only", "S01"], 0, "≈ $0.15", video={"model": "veo3_lite", "duration": 8},
                 budget=veo_budget)
            case("Veo Lite на 6 с — стоп: у модели цена задана только для 8 с",
                 api + ["--only", "S01"], 2, "длительностей 8 с", video={"model": "veo3_lite", "duration": 6},
                 budget=veo_budget)
            case("смета считает 3,0 кр./с, таблица 4,5 — ВНИМАНИЕ о расхождении, летим по смете",
                 api + ["--only", "S01"], 0, "расходится с таблицей",
                 budget={"motion": {"model": "grok-imagine/image-to-video", "ceiling_credits": 198.0,
                                    "credits_per_sec": 3.0}},
                 marker={"credits_per_clip": 18.0})
        finally:
            for k, x in env_old.items():
                if x is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = x
    return results


# --- смета движения: цена из таблицы, не из головы (29.10.2026) ----------------------------------
# Бесплатный мост Grok кончился, движение стало платным, а Grok в Kie подорожал с 18 до 27 кр. за
# ролик 6 с. Смета с одним дублем занижала расход (в октябре на сцену ушло 1,94 съёмки): цену и
# дубли теперь считает код (motion_prices.py, motion_cost.py), роль только вставляет напечатанное.
def motion_cost_checks():
    import contextlib
    import io
    import motion_cost
    import motion_prices as mp

    results = []

    def rec(desc, ok, detail=""):
        results.append((desc, ok, detail))

    cfg = lib.load_config()

    def est(model, dur, scenes, takes=None):
        try:
            return motion_cost.estimate(cfg, model, dur, scenes, takes), ""
        except mp.NoPrice as e:
            return None, str(e)

    grok = "grok-imagine/image-to-video"
    r, _ = est(grok, 6, 10, 1.0)
    rec("Grok 6 с: ролик 27 кр., 10 сцен одним дублем = 270 кр. = $1,35",
        bool(r) and r["credits_per_clip"] == 27.0 and r["credits_one_take"] == 270.0
        and r["usd_one_take"] == 1.35 and r["credits_per_sec"] == 4.5, str(r))
    r, _ = est(grok, 6, 10, 1.94)
    rec("Grok 6 с, 10 сцен × 1,94 съёмки = 523,8 кр., потолок 524, $2,62",
        bool(r) and r["credits_with_takes"] == 523.8 and r["ceiling_credits"] == 524
        and r["usd_with_takes"] == 2.62, str(r))
    r, _ = est(grok, 6, 10)
    rec("дубли по умолчанию — video_takes_factor из конфига (1,94 по книге октября)",
        bool(r) and r["takes_factor"] == mp.takes_factor(cfg) == 1.94 and r["ceiling_credits"] == 524, str(r))
    r, _ = est(grok, 10, 1, 1.0)
    rec("Grok 10 с = 45 кр. (книга: 45 кр. за ролик 10 с)", bool(r) and r["credits_per_clip"] == 45.0, str(r))
    r, _ = est("veo3_lite", 8, 3, 1.0)
    rec("Veo 3.1 Lite 8 с — цена ролика 30 кр., цены секунды нет, статус «замер»",
        bool(r) and r["credits_per_clip"] == 30.0 and r["credits_per_sec"] is None and r["price_status"] == "замер",
        str(r))
    r, err = est("veo3_lite", 6, 3, 1.0)
    rec("Veo Lite на 6 с — стоп: цена задана только для 8 с", r is None and "8 с" in err, err)
    r, _ = est("google/gemini-omni-flash-1-1", 6, 1, 1.0)
    rec("Omni 6 с = 84 кр., статус «страница» (с прайса, не замерено)",
        bool(r) and r["credits_per_clip"] == 84.0 and r["price_status"] == "страница", str(r))
    r, err = est("seedance-1.5-pro", 6, 1, 1.0)
    rec("модели нет в таблице (Seedance сегодня не подтверждён) — стоп, а не догадка",
        r is None and "нет в motion_prices" in err, err)

    def cli(*argv):
        buf, code = io.StringIO(), 0
        old = sys.argv
        sys.argv = ["motion_cost.py", *argv]
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                motion_cost.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
        finally:
            sys.argv = old
        return code, buf.getvalue()

    code, out = cli("--model", grok, "--duration", "6", "--scenes", "10", "--takes", "1.94", "--json")
    try:
        block = json.loads(out)
    except ValueError:
        block = {}
    rec("--json печатает блок для budget.json → motion: потолок 524, цена секунды 4,5",
        code == 0 and block.get("ceiling_credits") == 524 and block.get("credits_per_sec") == 4.5
        and block.get("price_status") == "замер", out)
    code, out = cli("--model", "veo3_lite", "--duration", "8", "--scenes", "2", "--takes", "1")
    rec("Veo Lite на экране: $0,30 за два ролика и ВНИМАНИЕ про прайс не нужно (статус «замер»)",
        code == 0 and "$0.3" in out and "ВНИМАНИЕ" not in out, out)
    code, out = cli("--model", "google/gemini-omni-flash-1-1", "--duration", "6", "--scenes", "1", "--takes", "1")
    rec("цена с прайса — на экране ВНИМАНИЕ: заявлено, проверяется пилотом (R23)",
        code == 0 and "ВНИМАНИЕ" in out and "R23" in out, out)
    code, out = cli("--model", "veo3_lite", "--duration", "6", "--scenes", "1")
    rec("нет цены на экране — код 2", code == 2 and "8 с" in out, out)
    return results


# --- книга расходов: цена принятой секунды движения (29.10.2026) ---------------------------------
# Сырая секунда Grok в Kie — $0,0225, принятая в октябре — $0,051: брак (1,94 съёмки на сцену)
# удваивает цену. Пока он не посчитан в деньгах, экономика врёт в свою пользу (R24).
def ledger_checks():
    import contextlib
    import io
    import os
    import clip_ledger

    results = []

    def rec(desc, ok, detail=""):
        results.append((desc, ok, detail))

    def run(*argv):
        buf, code = io.StringIO(), 0
        old_argv, old_bal = sys.argv, clip_ledger.kie_balance
        clip_ledger.kie_balance = lambda cfg: (None, "selbsttest: без сети")
        sys.argv = ["clip_ledger.py", *argv]
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                clip_ledger.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
        finally:
            sys.argv, clip_ledger.kie_balance = old_argv, old_bal
        return code, buf.getvalue()

    g = "grok-imagine/image-to-video"
    env_old = os.environ.get("LOCALAPPDATA")
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        os.environ["LOCALAPPDATA"] = str(root / "appdata")
        try:
            def mkproject(name, accepted, rejected):
                pdir = root / name
                lib.write_json(pdir / "project.json",
                               {"project": name, "video": {"model": g, "duration": 6}, "scenes": []})
                lib.write_json(lib.verdicts_path(pdir),
                               [{"verdict": "accept"}] * accepted + [{"verdict": "reject"}] * rejected)
                return pdir

            pdir = mkproject("pL", 3, 3)
            code, out = run("record", "--project", "pL", "--stage", "shoot", "--before", "1000",
                            "--after", "892", "--items", "4", "--model", g, "--seconds", "6")
            ev = clip_ledger.load_events()
            rec("record с --model и --seconds: поля в книге; 108 кр. на 4 ролика по 6 с = 4,50 кр./с",
                code == 0 and bool(ev) and ev[-1].get("model") == g and ev[-1].get("clip_seconds") == 6.0
                and ev[-1].get("kie_spent") == 108.0 and "4.50 кр./с" in out, out)
            run("record", "--project", "pL", "--stage", "shoot", "--before", "892", "--after", "838",
                "--items", "2", "--model", g, "--seconds", "6")
            code, out = run("report", "--project", "pL", "--project-dir", str(pdir))
            rec("report: цена принятой секунды движения = 162 кр. / (3 принятых × 6 с) = 9,00 кр./с = $0,045",
                code == 0 and "9.00 кр./с = $0.045" in out and "3 клипов по 6 с" in out, out)
            rec("report: сырая секунда по модели отдельно — 4,50 кр./с = $0,0225 (дрейф прайса виден)",
                "4.50 кр./с = $0.0225/с" in out, out)

            pdir2 = mkproject("pM", 0, 2)
            run("record", "--project", "pM", "--stage", "shoot", "--before", "838", "--after", "784",
                "--items", "2", "--model", g, "--seconds", "6")
            code, out = run("report", "--project", "pM", "--project-dir", str(pdir2))
            rec("report: принятых нет — «принятых клипов нет», а не деление на ноль",
                code == 0 and "принятых клипов нет" in out and "54 кр." in out, out)

            pdir3 = mkproject("pN", 2, 0)
            run("record", "--project", "pN", "--stage", "anchors", "--before", "500", "--after", "470", "--items", "5")
            code, out = run("report", "--project", "pN", "--project-dir", str(pdir3))
            rec("report: видео Kie не тратилось (только якоря) — строки про принятую секунду движения нет",
                code == 0 and "цена принятой секунды движения" not in out, out)
        finally:
            if env_old is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = env_old
    return results


# ── Suno-ветка: упаковка ролика под hook (13.10.2026) ─────────────────────────────────────────
# Повод — <проект>: звук трека вшивали руками, копию под загрузку (инструмент Chrome
# берёт до 10 МБ) пережимали руками. Синтетика: трек 20 с, окно 4–16 с (12 с, Suno требует ≥ 10).

def suno_media(ffmpeg, path, seconds, size="1080x1920", heavy=False):
    # heavy: шум без сжатия — мастер тяжелее потолка загрузки, как живой Grok-монтаж (20 МБ на 22 с).
    src = (f"nullsrc=s={size}:d={seconds}:r=24,geq=random(1)*255:128:128" if heavy
           else f"testsrc=duration={seconds}:size={size}:rate=24")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", src,
                    "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
                    "-shortest", "-c:v", "libx264", "-b:v", "8M" if heavy else "1M",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
                   check=True)


def suno_project(root, ffmpeg, hook=(4.0, 16.0)):
    (root / "clip-memory" / "song").mkdir(parents=True)
    grid = {"duration": 20.0, "bpm": 100.0, "beat": 0.6, "sections": [{"name": "chorus"}]}
    if hook:
        grid["hook"] = {"start": hook[0], "end": hook[1]}
    (root / "clip-memory" / "song" / "grid.json").write_text(json.dumps(grid), encoding="utf-8")
    make_audio(ffmpeg, root / "song.mp3", seconds=20)


def run_pack(root, *extra, review=False):
    # Разбор склеек (0.8.35) у большинства случаев не предмет проверки: у них --no-cuts-review.
    skip = [] if review else ["--no-cuts-review", "selbsttest"]
    r = subprocess.run([PY, str(HERE / "suno_pack.py"), "--project", str(root), *skip, *extra],
                       capture_output=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def two_shot_video(ffmpeg, path, seconds=12, size="1080x1920", colors=("red", "blue")):
    """Две заливки встык: красная и синяя; склейка ровно посередине."""
    half = seconds / 2
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c={colors[0]}:s={size}:d={half}:r=24",
                    "-f", "lavfi", "-i", f"color=c={colors[1]}:s={size}:d={half}:r=24",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


def run_cuts(root, *extra):
    r = subprocess.run([PY, str(HERE / "cut_review.py"), "--project", str(root), *extra],
                       capture_output=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def fill_review(root, spec):
    """spec: {критерий: (state, note)} на единственной склейке разбора."""
    path = root / "clip-memory" / "reports" / "cuts-review.json"
    d = lib.read_json(path)
    for c in d["cuts"]:
        c["criteria"] = {k: {"state": v[0], "note": v[1]} for k, v in spec.items()}
    lib.write_json(path, d)


ALL_KEPT = {k: ("kept", "") for k in ("emotion", "story", "rhythm", "eye_trace", "plane", "space")}


def cuts_checks(ffmpeg):
    res = []
    if not ffmpeg or not Path(ffmpeg).exists():
        return res
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        suno_project(root, ffmpeg)
        two_shot_video(ffmpeg, root / "m.mp4")
        code, out = run_cuts(root, "--video", "m.mp4", "--cuts", "6")
        rv = root / "clip-memory" / "reports" / "cuts-review.json"
        data = lib.read_json(rv) if rv.exists() else {}
        res.append(("склейки: шаблон разбора со склейкой 6 с, измерено, лист кадров записан",
                    code == 0 and data.get("cuts_in_review") == 1
                    and data["cuts"][0]["luma"]["before"] != data["cuts"][0]["luma"]["after"]
                    and (root / "output" / "cuts" / "cuts-sheet.jpg").exists(), out))
        code, out = run_cuts(root, "--video", "m.mp4", "--check")
        res.append(("склейки: пустой шаблон не принят — нет вердикта по критериям",
                    code == 2 and "нет вердикта" in out, out))
        fill_review(root, {**ALL_KEPT, "emotion": ("sacrificed", "ради ритма")})
        code, out = run_cuts(root, "--video", "m.mp4", "--check")
        res.append(("склейки: эмоция принесена в жертву при сохранённом ритме — нарушен порядок приоритета",
                    code == 2 and "жертвуют снизу вверх" in out, out))
        fill_review(root, {**ALL_KEPT, "space": ("sacrificed", "")})
        code, out = run_cuts(root, "--video", "m.mp4", "--check")
        res.append(("склейки: жертва без причины — отказ", code == 2 and "без причины" in out, out))
        fill_review(root, {**ALL_KEPT, "plane": ("sacrificed", "пара меняется местами"),
                           "space": ("sacrificed", "обратный ракурс")})
        code, out = run_cuts(root, "--video", "m.mp4", "--check")
        mk = lib.read_marker(root, "cuts-ok.json", 0)
        res.append(("склейки: жертвуют снизу вверх (плоскость и пространство) — принят, маркер на sha1 монтажа",
                    code == 0 and bool(mk) and mk.get("video_sha1") == lib.file_sha1(root / "m.mp4"), out))
        code, out = run_pack(root, "--master", "m.mp4", review=True)
        res.append(("упаковка: разобранный монтаж проходит, паспорт знает о разборе склеек",
                    code == 0 and (lib.read_json(root / "publish" / "suno-hook.json")
                                   .get("cuts_review") or {}).get("cuts") == 1, out))
        two_shot_video(ffmpeg, root / "m2.mp4", seconds=12, colors=("green", "yellow"))
        code, out = run_pack(root, "--master", "m2.mp4", "--force", review=True)
        res.append(("упаковка: тот же монтаж другим файлом без своего разбора — стоп по правилу шести",
                    code == 2 and "правило шести" in out, out))
        code, out = run_cuts(root, "--video", "m.mp4", "--auto", "--thr", "0.3")
        res.append(("склейки: перезапись заполненного разбора не затирает его",
                    code == 2 and "уже заполнен" in out, out))
    return res


# Вывод ebur128: строки с текущим I: идут до блока Summary и не должны попасть в замер.
EBUR_SAMPLE = """t: 0.1 I: -70.0 LUFS
Summary:
 Integrated loudness:
  I: -14.3 LUFS
 True peak:
  Peak: -0.4 dBFS
"""
EBUR_SILENCE = """Summary:
 Integrated loudness:
  I: -inf LUFS
 True peak:
  Peak: -inf dBFS
"""


def suno_checks(ffmpeg):
    res = []
    if not ffmpeg or not Path(ffmpeg).exists():
        return res
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        suno_project(root, ffmpeg)
        suno_media(ffmpeg, root / "ok.mp4", 12)
        code, out = run_pack(root, "--master", "ok.mp4", "--fade-from", "15")
        rec = root / "publish" / "suno-hook.json"
        good = code == 0 and rec.exists() and (root / "output" / f"{root.name}-suno.mp4").exists()
        if good:
            r = lib.read_json(rec)
            good = (r["audio_source"] == "video" and r["window"]["length"] == 12.0
                    and r["status"] == "ready" and r["url"] is None)
        res.append(("Suno: годный ролик 9:16 ровно в окно — упакован, паспорт status ready", good, out))

        # Админ, 14.10.2026: первый кадр — это hook и обложка; после публикации он не правится.
        ff = root / "output" / f"{root.name}-first-frame.jpg"
        good = (good and ff.exists() and ff.stat().st_size > 0 and "ПЕРВЫЙ КАДР" in out
                and lib.read_json(rec).get("first_frame") == f"output/{ff.name}")
        res.append(("Suno: рядом с роликом лежит первый кадр, упаковщик напоминает его посмотреть до загрузки",
                    good, out))

        # Громкость итога (0.8.36): замер пишется в паспорт и в вывод. Синусоида sine по умолчанию тихая
        # (около -22 LUFS) — предупреждение о громкости обязано быть, но пакет упакован (код 0).
        loud = lib.read_json(rec).get("loudness") or {}
        good = (isinstance(loud.get("integrated_lufs"), float) and isinstance(loud.get("true_peak_dbtp"), float)
                and loud.get("target_lufs") == -14.0 and loud.get("warnings")
                and "ПРЕДУПРЕЖДЕНИЕ (громкость)" in out and "сторонних обзоров" in out)
        res.append(("Suno: громкость итога замерена (LUFS, истинный пик), тихий трек — предупреждение, не отказ",
                    bool(good), out))

        # Тот же ролик с треком на ~-15 LUFS: предупреждения нет. Мастер сведён автором — не нормализуется.
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=330:duration=20", "-af", "volume=7dB", str(root / "song.mp3")], check=True)
        code, out = run_pack(root, "--master", "ok.mp4", "--force")
        loud = lib.read_json(rec).get("loudness") or {}
        res.append(("Suno: трек в ориентире громкости — без предупреждения; замер около -15 LUFS",
                    code == 0 and not loud.get("warnings") and -17 < (loud.get("integrated_lufs") or 0) < -13
                    and "ПРЕДУПРЕЖДЕНИЕ (громкость)" not in out, out))
        import suno_pack
        res.append(("Suno: разбор вывода ebur128 — берётся блок Summary, тишина (-inf) не число",
                    suno_pack.parse_ebur128(EBUR_SAMPLE)
                    == {"integrated_lufs": -14.3, "true_peak_dbtp": -0.4}
                    and suno_pack.parse_ebur128(EBUR_SILENCE) is None, ""))
        w = suno_pack.loudness_warnings({"integrated_lufs": -14.0, "true_peak_dbtp": -0.2})
        res.append(("Suno: истинный пик выше -1 dBTP — предупреждение, громкость в ориентире — без него",
                    len(w) == 1 and "пик" in w[0], str(w)))

        # Тяжёлый мастер → копия под загрузку ниже потолка.
        suno_media(ffmpeg, root / "heavy.mp4", 12, heavy=True)
        code, out = run_pack(root, "--master", "heavy.mp4", "--max-mb", "3")
        up = root / "output" / f"{root.name}-suno-upload.mp4"
        full = root / "output" / f"{root.name}-suno.mp4"
        good = (code == 0 and up.exists() and up.stat().st_size / 1e6 <= 3
                and full.stat().st_size / 1e6 > 3)
        res.append(("Suno: мастер тяжелее --max-mb — пережатая копия под загрузку", good, out))

        # Потолок, под который выходит только мыло, — честный отказ, а не мутная копия.
        code, out = run_pack(root, "--master", "heavy.mp4", "--max-mb", "0.5")
        res.append(("Suno: под потолок только мыло (< 800 кбит/с) — отказ",
                    code == 2 and "мыло" in out, out))

        # Опубликованный hook не затирается повторной упаковкой.
        r = lib.read_json(rec)
        r["url"] = "https://suno.com/hook/x"
        lib.write_json(rec, r)
        code, out = run_pack(root, "--master", "ok.mp4")
        res.append(("Suno: паспорт опубликованного hook'а без --force не перезаписывается",
                    code == 2 and "уже опубликован" in out, out))

    for desc, size, secs, hook, want in [
        ("Suno: квадратный кадр — стоп", "1080x1080", 12, (4.0, 16.0), "не 9:16"),
        ("Suno: ролик 8 с при окне 12 с — стоп, звук разойдётся", "1080x1920", 8, (4.0, 16.0),
         "звук разойдётся"),
        ("Suno: окно 6 с — стоп, Suno короче 10 с не примет", "1080x1920", 6, (4.0, 10.0),
         "короче 10"),
        ("Suno: в grid.json нет окна — стоп, это полный клип", "1080x1920", 12, None, "нет окна"),
    ]:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            suno_project(root, ffmpeg, hook)
            suno_media(ffmpeg, root / "m.mp4", secs, size)
            code, out = run_pack(root, "--master", "m.mp4")
            res.append((desc, code == 2 and want in out, out))
    return res


# ── полка движений: карточка из ролика (0.8.28) ──────────────────────────────────────────────

def motion_checks(ffmpeg):
    res = []
    if not ffmpeg or not Path(ffmpeg).exists():
        return res
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        suno_media(ffmpeg, root / "v.mp4", 4)

        def run(*extra):
            r = subprocess.run([PY, str(HERE / "motion_ref.py"), "--video", str(root / "v.mp4"),
                                "--shelf", str(root / "shelf"), *extra],
                               capture_output=True, encoding="utf-8", errors="replace")
            return r.returncode, (r.stdout or "") + (r.stderr or "")

        base = ["--start", "0.5", "--end", "2.5", "--title", "Тест", "--source", "selbsttest"]
        code, out = run("--slug", "test-anti", "--kind", "anti", *base)
        card = root / "shelf" / "test-anti"
        res.append(("полка: карточка «так не бывает» — strip.jpg и card.md с 8 кадрами",
                    code == 0 and (card / "strip.jpg").exists()
                    and "8 кадров" in (card / "card.md").read_text(encoding="utf-8"), out))
        code, out = run("--slug", "test-anti", "--kind", "anti", *base)
        res.append(("полка: существующая карточка не перезаписывается", code == 2 and "уже есть" in out, out))
        code, out = run("--slug", "test-real", "--kind", "real", *base)
        res.append(("полка: эталон без лицензии — стоп", code == 2 and "лицензия" in out, out))
        code, out = run("--slug", "test-tech", "--kind", "technique", *base)
        res.append(("полка: приём (technique) заводится без лицензии, вид указан в карточке",
                    code == 0 and "приём: как мы это сделали"
                    in (root / "shelf" / "test-tech" / "card.md").read_text(encoding="utf-8"), out))
        code, out = run("--slug", "Мел ветер", "--kind", "anti", *base)
        res.append(("полка: slug не латиницей — стоп (R25)", code == 2 and "slug" in out, out))
    return res


# ── слайдшоу-риск шот-листа (0.8.36) ──────────────────────────────────────────────────────────

def slideshow_checks():
    import gate_slideshow as gs
    res = []

    def shot(i, size, mv, beats=4, src=None):
        d = {"id": f"S{i:02d}", "size": size, "movement": mv, "beats": beats}
        if src:
            d["src"] = src
        return d

    lively = [shot(1, "WS", "static", src="a"), shot(2, "CU", "push_in_slow", src="b"),
              shot(3, "MS", "tracking", src="c"), shot(4, "ECU", "static", src="d"),
              shot(5, "WS", "pan", src="e")]
    r = gs.analyze(lively, beat=0.5)
    res.append(("слайдшоу: живой шот-лист (смена крупностей и движения) — риск низкий, флагов нет",
                r["verdict"] == "низкий" and not r["flags"], str(r)))

    dead = [shot(i, "MS", "static", beats=8, src="a") for i in range(1, 7)]
    r = gs.analyze(dead, beat=0.5)
    codes = {f["code"] for f in r["flags"]}
    res.append(("слайдшоу: шесть статичных планов одной крупности от одного источника — высокий риск, "
                "флаги статики, повтора крупности и источника",
                r["verdict"] == "высокий" and {"static_share", "static_run", "size_run", "src_reuse"} <= codes
                and r["metrics"]["static_share"] == 1.0, str(r)))

    # Статичная камера — законный выбор: короткий шот-лист с разными крупностями не тревожит.
    r = gs.analyze([shot(1, "WS", "static"), shot(2, "CU", "static"), shot(3, "MS", "pan")], beat=0.5)
    res.append(("слайдшоу: два статичных плана из трёх разных крупностей — не тревога",
                r["verdict"] == "низкий", str(r)))

    r = gs.analyze([{"id": "S01", "size": "WS", "movement": "static", "sec": 10.0}] +
                   [{"id": f"S0{i}", "size": s_, "movement": "pan", "sec": 2.0}
                    for i, s_ in zip((2, 3), ("CU", "MS"))])
    res.append(("слайдшоу: реклама в секундах (sec) — план 10 с помечен как слишком долгий",
                any(f["code"] == "long_shot" for f in r["flags"]) and r["metrics"]["timed"], str(r)))

    r = gs.analyze([{"id": "S01", "size": "WS", "movement": "static"}] * 4)
    res.append(("слайдшоу: длин планов нет — доли считаются по числу планов, в метриках пометка",
                r["metrics"]["timed"] is False and "note" in r["metrics"], str(r)))

    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        (root / "clip-memory" / "script").mkdir(parents=True)
        (root / "clip-memory" / "song").mkdir(parents=True)
        (root / "clip-memory" / "song" / "grid.json").write_text(json.dumps({"beat": 0.5}), encoding="utf-8")
        (root / "clip-memory" / "script" / "shotlist.json").write_text(
            json.dumps({"shots": dead}), encoding="utf-8")
        r_ = subprocess.run([PY, str(HERE / "gate_slideshow.py"), "--project", str(root)],
                            capture_output=True, encoding="utf-8", errors="replace")
        out = (r_.stdout or "") + (r_.stderr or "")
        rep = root / "clip-memory" / "reports" / "slideshow-risk.json"
        res.append(("слайдшоу: скрипт на проекте — код 0 (предупреждение, не блок), отчёт на диске, [~] в выводе",
                    r_.returncode == 0 and rep.exists() and lib.read_json(rep)["verdict"] == "высокий"
                    and "[~]" in out and "не блок" in out, out))
        r_ = subprocess.run([PY, str(HERE / "gate_slideshow.py"), "--project", str(root / "нет")],
                            capture_output=True, encoding="utf-8", errors="replace")
        res.append(("слайдшоу: нет шот-листа — стоп с понятной причиной",
                    r_.returncode == 2 and "нет шот-листа" in (r_.stderr or ""), r_.stderr or ""))
    return res


# ── журнал решений о провайдере (0.8.36) ──────────────────────────────────────────────────────

def note_to(pdir, args, provider):
    import contextlib
    import io
    import gate_preflight
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        gate_preflight.note_provider_decision(args, pdir, provider)
    return buf.getvalue()


class _Args:
    provider = None
    provider_reason = None


def decisions_checks():
    res = []
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        r1 = lib.log_decision(root, "video-provider", "p", "api", "Kie: квота моста пуста", ["bridge"], "selbsttest")
        again = lib.log_decision(root, "video-provider", "p", "api")
        same_reason = lib.log_decision(root, "video-provider", "p", "api", "Kie: квота моста пуста")
        r2 = lib.log_decision(root, "video-provider", "p", "bridge", "квота сброшена")
        other = lib.log_decision(root, "video-provider", "q", "api", "другой проект")
        rows = lib.read_decisions(root, "video-provider", "p")
        res.append(("журнал решений: запись с ключом, повтор без изменений не дописывается, смена — новая запись "
                    "со ссылкой на прежний выбор",
                    bool(r1 and again is None and same_reason is None and r2 and r2["supersedes"] == "api"
                         and [x["choice"] for x in rows] == ["api", "bridge"] and other
                         and len(lib.read_decisions(root)) == 3 and rows[0]["rejected"] == ["bridge"]), str(rows)))
        # Битая строка в середине не роняет чтение: журнал дописывается руками и агентами.
        with open(lib.decisions_path(root), "a", encoding="utf-8") as f:
            f.write("не json\n")
        res.append(("журнал решений: битая строка пропускается",
                    len(lib.read_decisions(root, "video-provider", "p")) == 2, ""))

        pdir = root / "proj"
        pdir.mkdir()
        a_ = _Args()
        a_.provider, a_.provider_reason = "api", "проба Kie"
        e1 = note_to(pdir, a_, "api")
        e2 = note_to(pdir, _Args(), "bridge")     # без --provider, а в журнале api
        a_.provider, a_.provider_reason = "bridge", None
        e3 = note_to(pdir, a_, "bridge")          # явная смена без причины
        last = lib.last_decision(pdir, "video-provider", "proj")
        res.append(("журнал решений: молча сменённый провайдер (project.json против журнала) — предупреждение R10",
                    e1 == "" and "тихая смена" in e2 and "api" in e2, e2))
        res.append(("журнал решений: явная смена без --provider-reason — предупреждение, запись всё равно есть",
                    "без --provider-reason" in e3 and last["choice"] == "bridge" and last["supersedes"] == "api", e3))
    return res


# ── субтитры (0.8.36) ─────────────────────────────────────────────────────────────────────────

SUB_WORDS = [("Пять", 0.2, 0.6), ("дней", 0.6, 0.9), ("хватит,", 0.9, 1.6), ("я", 1.7, 1.8),
             ("дверь", 1.8, 2.1), ("закрываю", 2.1, 3.0), ("Внутри", 3.0, 3.5), ("уже", 3.5, 3.7),
             ("легче,", 3.7, 4.4), ("и", 5.4, 5.5), ("я", 5.5, 5.6), ("оживаю", 5.6, 6.4)]
SUB_LYRICS = ("# Текст песни\n\nслужебная строка до разделителя\n---\n[Verse 1][Female]\nПять дней и хватит\n"
              "Я дверь закрываю\nВнутри уже легче\nИ я оживаю\nСтрока которой нет в тайминге вовсе\n")


def run_sub(*args, env_extra=None):
    import os
    env = dict(os.environ)
    env.update(env_extra or {})
    r = subprocess.run([PY, str(HERE / "subtitles.py"), *args], capture_output=True,
                       encoding="utf-8", errors="replace", env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def psnr_avg(ffmpeg, a, b, t, region):
    import re
    r = subprocess.run([ffmpeg, "-hide_banner", "-ss", str(t), "-i", str(a), "-ss", str(t), "-i", str(b),
                        "-frames:v", "1", "-lavfi", f"[0:v]crop={region}[x];[1:v]crop={region}[y];[x][y]psnr",
                        "-f", "null", "-"], capture_output=True, encoding="utf-8", errors="replace")
    m = re.search(r"average:(inf|[\d.]+)", r.stderr or "")
    if not m:
        return None
    return float("inf") if m.group(1) == "inf" else float(m.group(1))


def subtitles_checks(ffmpeg):
    import re
    import subtitles as st
    res = []
    words = [{"word": w, "start": a, "end": b} for w, a, b in SUB_WORDS]

    ph = st.phrase_times(st.group_words(words, caps_break=st.is_cyrillic(words)))
    texts = [" ".join(x["word"] for x in p["words"]) for p in ph]
    res.append(("субтитры: фразы по запятой, большой букве и паузе (кириллица) — четыре строки песни",
                texts == ["Пять дней хватит,", "я дверь закрываю", "Внутри уже легче,", "и я оживаю"], str(texts)))
    de = [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.28}
          for i, w in enumerate("Ich schreibe Namen an die Wand".split())]
    res.append(("субтитры: в немецком большие буквы существительных строку не ломают (caps_break выключен)",
                len(st.group_words(de, caps_break=st.is_cyrillic(de))) == 1, ""))
    long_ = [{"word": "слово", "start": i * 0.3, "end": i * 0.3 + 0.28} for i in range(20)]
    res.append(("субтитры: длинная фраза режется по max_chars, ни одна не длиннее предела",
                all(len(" ".join(x["word"] for x in p)) <= 40 for p in st.group_words(long_)), ""))
    ph1 = st.phrase_times([[{"word": "да", "start": 1.0, "end": 1.1}], [{"word": "нет", "start": 1.2, "end": 1.3}]])
    res.append(("субтитры: фраза короче 0,35 с продлевается, но не налезает на следующую",
                ph1[0]["end"] <= ph1[1]["start"] and ph1[0]["end"] > 1.1, str(ph1)))
    srt = st.to_srt(ph)
    res.append(("субтитры: SRT — нумерация, запятая в миллисекундах, времена по словам",
                srt.startswith("1\n00:00:00,200 --> 00:00:01,") and "\n2\n00:00:01,700 --> " in srt, srt[:120]))
    ass = st.to_ass(ph, 1080, 1920, "Arial", karaoke=True)
    k_ok = True
    dl = [x for x in ass.splitlines() if x.startswith("Dialogue")]
    for p, line in zip(ph, dl):
        ks = [int(x) for x in re.findall(r"\\k(\d+)", line)]
        k_ok = k_ok and len(ks) == len(p["words"]) and abs(sum(ks) - round((p["end"] - p["start"]) * 100)) <= 1
    res.append(("субтитры: караоке ASS — метка \\k на каждое слово, сумма равна длине фразы",
                k_ok and len(dl) == len(ph) and ",2,90,90,576,1" in ass, ass[-300:]))
    land = st.style_params(1920, 1080)
    res.append(("безопасная зона: вертикаль — низ текста на 30 % выше кромки (MarginV 576), горизонталь — 8 %",
                st.style_params(1080, 1920)["margin_v"] == 576 and st.style_params(1080, 1920)["text_bottom_y"] == 1344
                and land["margin_v"] == 86, str(land)))
    cw = st.cut_window(words, 3.0, 4.5)
    res.append(("субтитры: окно трека сдвигает слова к нулю ролика, слова вне окна отброшены",
                [w["word"] for w in cw] == ["Внутри", "уже", "легче,"] and cw[0]["start"] == 0.0, str(cw)))

    m, dropped = st.align_lyrics(st.parse_lyrics(SUB_LYRICS), words)
    res.append(("субтитры --lyrics: текст автора привязан к таймингам, «оживаю» без «о» в whisper — "
                "по сходству, строка без слов в тайминге выпала",
                [x["text"] for x in m] == ["Пять дней и хватит", "Я дверь закрываю", "Внутри уже легче",
                                           "И я оживаю"] and len(dropped) == 1
                and m[3]["words"][-1]["word"] == "оживаю" and m[3]["words"][-1]["start"] == 5.6, str(m)))

    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        (root / "clip-memory" / "song").mkdir(parents=True)
        wjson = json.dumps([{"word": w, "start": a, "end": b} for w, a, b in SUB_WORDS], ensure_ascii=False)
        (root / "clip-memory" / "song" / "words.json").write_text(wjson, encoding="utf-8")
        (root / "clip-memory" / "song" / "lyrics-author.md").write_text(SUB_LYRICS, encoding="utf-8")
        code, out = run_sub("--project", str(root), "--lyrics")
        res.append(("субтитры: показ фраз по умолчанию без записи файлов, текст автора из lyrics-author.md",
                    code == 0 and "Пять дней и хватит" in out and "привязано 4" in out, out))
        code, out = run_sub("--project", str(root), "--srt", str(root / "o.srt"), "--ass", str(root / "o.ass"),
                            "--karaoke")
        ass_text = (root / "o.ass").read_text(encoding="utf-8") if (root / "o.ass").exists() else ""
        res.append(("субтитры: SRT и ASS записаны, шрифт назван в стиле",
                    code == 0 and (root / "o.srt").exists() and "Style: Cap," in ass_text and "\\k" in ass_text, out))
        empty = root / "nofonts"
        empty.mkdir()
        code, out = run_sub("--project", str(root), "--ass", str(root / "x.ass"),
                            env_extra={"CLIPMAKER_FONTS_DIR": str(empty)})
        res.append(("субтитры: нет шрифта с кириллицей — отказ, а не молчаливая подмена",
                    code == 2 and "нет шрифта" in out and not (root / "x.ass").exists(), out))
        code, out = run_sub("--project", str(root), "--ass", str(root / "x.ass"), "--font-file", str(root / "нет.ttf"))
        res.append(("субтитры: явный --font-file не найден — отказ", code == 2 and "не найден" in out, out))
        code, out = run_sub("--check-fonts", env_extra={"CLIPMAKER_FONTS_DIR": str(empty)})
        res.append(("субтитры: проверка шрифтов без единого годного — код 2", code == 2, out))

        # Suno-hook: букв в кадре нет. Выжигание отказывает по grid.json → hook; SRT отдаётся с предупреждением.
        hook = root / "hook"
        (hook / "clip-memory" / "song").mkdir(parents=True)
        (hook / "clip-memory" / "song" / "words.json").write_text(wjson, encoding="utf-8")
        (hook / "clip-memory" / "song" / "grid.json").write_text(
            json.dumps({"duration": 20.0, "hook": {"start": 2.0, "end": 14.0}}), encoding="utf-8")
        code, out = run_sub("--project", str(hook), "--burn", str(hook / "v.mp4"), "--out", str(hook / "o.mp4"))
        res.append(("субтитры: на проекте с окном hook выжигание отказывает — букв в кадре Suno-hook быть не должно",
                    code == 2 and "Suno-hook" in out and "букв в кадре" in out and not (hook / "o.mp4").exists(), out))
        code, out = run_sub("--project", str(hook), "--srt", str(hook / "o.srt"))
        res.append(("субтитры: на hook файл SRT отдаётся с предупреждением «не вшивать»",
                    code == 0 and "не вшивать" in out and (hook / "o.srt").exists(), out))
        (root / "publish").mkdir()
        (root / "publish" / "suno-hook.json").write_text("{}", encoding="utf-8")
        code, out = run_sub("--project", str(root), "--burn", str(root / "v.mp4"), "--out", str(root / "o.mp4"))
        res.append(("субтитры: паспорт publish/suno-hook.json тоже признак hook — выжигание отказывает",
                    code == 2 and "Suno-hook" in out, out))
        (root / "publish" / "suno-hook.json").unlink()

        if ffmpeg and Path(ffmpeg).exists() and any(r["ok"] for r in st.font_report()):
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc=duration=7:size=1080x1920:rate=24", "-f", "lavfi", "-i",
                            "sine=frequency=330:duration=7", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", str(root / "v.mp4")], check=True)
            code, out = run_sub("--project", str(root), "--lyrics", "--karaoke", "--burn", str(root / "v.mp4"),
                                "--out", str(root / "o.mp4"))
            ok = code == 0 and (root / "o.mp4").exists()
            if ok:
                # Фраза «Я дверь закрываю» идёт 1,7–3,0 с. Картинка отличается от исходной в средней части кадра
                # (текст есть) и совпадает в нижних 30 % (там пусто). Видео сжато с потерями, поэтому судим по PSNR.
                mid = psnr_avg(ffmpeg, root / "v.mp4", root / "o.mp4", 2.5, "iw:ih*0.3:0:ih*0.6")
                low = psnr_avg(ffmpeg, root / "v.mp4", root / "o.mp4", 2.5, "iw:ih*0.3:0:ih*0.7")
                ok = mid is not None and low is not None and mid < 35 and low > 38
                out += f" | PSNR текстовой полосы {mid}, нижних 30 % {low}"
            res.append(("субтитры: выжигание ffmpeg — текст виден в средней части кадра и не заходит в нижние 30 %",
                        ok, out))
            code, out = run_sub("--project", str(root), "--burn", str(root / "v.mp4"))
            res.append(("субтитры: --burn без --out — отказ", code == 2 and "--out" in out, out))
    return res


# ── платформы: «для чего делаем» (0.8.37) ─────────────────────────────────────────────────────

def put_platform(root, name, extra=None):
    d = {"project": "selbsttest", "platform": name} if name else {"project": "selbsttest"}
    d.update(extra or {})
    (Path(root) / "project.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def run_scaffold(*args):
    r = subprocess.run([PY, str(HERE / "clip_scaffold.py"), *args], capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def platform_checks(ffmpeg):
    import os
    import subtitles as st
    res = []
    names = {"suno-hook", "instagram-reels", "tiktok", "youtube-shorts", "youtube-long", "vk-clips",
             "ads-ozon-wb", "generic-vertical"}
    data = lib.load_platforms()
    profs = data["profiles"]
    complete = set(profs) == names
    for n, p in profs.items():
        _, err = lib.platform_check(n)
        z = p.get("safe_zone", {})
        complete = (complete and err is None and re.fullmatch(r"\d+:\d+", p["aspect"])
                    and all(0 <= z.get(k, -1) < 0.5 for k in ("bottom", "top", "side"))
                    and set(p["provenance"]) >= {"aspect", "length_sec", "subtitles", "safe_zone", "loudness"})
    res.append(("платформы: восемь профилей, у каждого aspect, длина, субтитры, безопасная зона, громкость и "
                "происхождение чисел", bool(complete), str(sorted(profs))))
    res.append(("платформы: suno-hook — субтитры запрещены (forbidden), остальные профили — нет, и метка «проверено» "
                "у suno-hook стоит только на aspect и длине",
                profs["suno-hook"]["subtitles"] == "forbidden"
                and all(p["subtitles"] != "forbidden" for n, p in profs.items() if n != "suno-hook")
                and "проверено" in profs["suno-hook"]["provenance"]["aspect"]
                and "проверено" not in profs["suno-hook"]["provenance"]["safe_zone"]
                and "сверить с площадкой" in profs["instagram-reels"]["provenance"]["length_sec"], ""))
    prof, err = lib.platform_check("инстаграм")
    res.append(("платформы: неизвестное имя — ошибка со списком допустимых", prof is None and "instagram-reels" in err, err))
    with tempfile.TemporaryDirectory() as t:
        bad = Path(t) / "bad.json"
        bad.write_text(json.dumps({"profiles": {"x": {"title": "x", "aspect": "9:16"}}}), encoding="utf-8")
        old = os.environ.get("CLIPMAKER_PLATFORMS")
        os.environ["CLIPMAKER_PLATFORMS"] = str(bad)
        try:
            _, err = lib.platform_check("x")
        finally:
            if old is None:
                os.environ.pop("CLIPMAKER_PLATFORMS", None)
            else:
                os.environ["CLIPMAKER_PLATFORMS"] = old
        res.append(("платформы: профиль без обязательных полей — ошибка, а не молчаливое умолчание",
                    err and "нет полей" in err, str(err)))
    w = lib.platform_warnings(profs["suno-hook"], 1080, 1080, 5.0)
    res.append(("платформы: ролик не того кадра и короче ориентира — предупреждения, не отказ",
                len(w) == 2 and any("9:16" in x for x in w) and any("короче" in x for x in w), str(w)))

    # скаффолд: платформа пишется в project.json при заведении
    with tempfile.TemporaryDirectory() as t:
        def plat(slug):
            f = list((Path(t) / slug).glob("project.*.json"))
            return lib.read_json(f[0]).get("platform") if f else "нет файла"
        c1, o1 = run_scaffold("--name", "Т1", "--slug", "t-clip", "--root", t)
        c2, o2 = run_scaffold("--name", "Т2", "--slug", "t-hook", "--root", t, "--hook")
        c3, o3 = run_scaffold("--name", "Т3", "--slug", "t-reels", "--root", t, "--platform", "instagram-reels")
        c4, o4 = run_scaffold("--name", "Т4", "--slug", "t-ad", "--root", t, "--kind", "ad")
        res.append(("скаффолд: платформа по умолчанию — клип generic-vertical, --hook suno-hook, реклама ads-ozon-wb, "
                    "явная --platform главнее",
                    (c1, c2, c3, c4) == (0, 0, 0, 0) and (plat("t-clip"), plat("t-hook"), plat("t-reels"), plat("t-ad"))
                    == ("generic-vertical", "suno-hook", "instagram-reels", "ads-ozon-wb")
                    and "ЗАПРЕЩЕНЫ" in o2 and "t-reels" in o3
                    and "instagram-reels" in (Path(t) / "t-reels" / "clip-memory" / "00-brief.md").read_text(encoding="utf-8"),
                    o1 + o2))
        c, o = run_scaffold("--name", "Т5", "--slug", "t-bad", "--root", t, "--platform", "nope")
        res.append(("скаффолд: неизвестная платформа — стоп, папка не создана",
                    c == 2 and "неизвестна" in o and not (Path(t) / "t-bad").exists(), o))
        c, o = run_scaffold("--name", "Т6", "--slug", "t-bad2", "--root", t, "--kind", "ad", "--hook")
        res.append(("скаффолд: --hook у рекламы — стоп", c == 2 and "--hook" in o, o))
        # Существующий проект без явного ключа не трогается; с ключом — платформа меняется.
        pj = next((Path(t) / "t-clip").glob("project.*.json"))
        d = lib.read_json(pj)
        d.pop("platform")
        lib.write_json(pj, d)
        c, o = run_scaffold("--name", "Т1", "--slug", "t-clip", "--root", t)
        untouched = "platform" not in lib.read_json(pj)
        c2_, o2_ = run_scaffold("--name", "Т1", "--slug", "t-clip", "--root", t, "--platform", "tiktok")
        res.append(("скаффолд: у существующего проекта без --platform поле не появляется (старое поведение), "
                    "с --platform — меняется",
                    c == 0 and untouched and c2_ == 0 and lib.read_json(pj)["platform"] == "tiktok", o + o2_))

    # статус: подсказка про субтитры
    def status(name, extra=None):
        with tempfile.TemporaryDirectory() as t:
            put_platform(t, name, extra)
            r = subprocess.run([PY, str(HERE / "clip_status.py"), "--project", t], capture_output=True,
                               encoding="utf-8", errors="replace")
            return r.returncode, (r.stdout or "") + (r.stderr or "")
    c, o1 = status("instagram-reels")
    c_, o2 = status("suno-hook")
    c__, o3 = status(None)
    c___, o4 = status("инстаграм")
    res.append(("статус: подсказка «субтитры: включены/ЗАПРЕЩЕНЫ для платформы X»; нет поля — «не задана»; "
                "опечатка — предупреждение, сводка не падает",
                (c, c_, c__, c___) == (0, 0, 0, 0) and "субтитры: включены (рекомендуются) для платформы instagram-reels" in o1
                and "субтитры: ЗАПРЕЩЕНЫ для платформы suno-hook" in o2 and "платформа не задана" in o3
                and "неизвестна" in o4, o1 + o2 + o3 + o4))

    # субтитры по платформе
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        (root / "clip-memory" / "song").mkdir(parents=True)
        wjson = json.dumps([{"word": w_, "start": a, "end": b} for w_, a, b in SUB_WORDS], ensure_ascii=False)
        (root / "clip-memory" / "song" / "words.json").write_text(wjson, encoding="utf-8")
        (root / "clip-memory" / "song" / "grid.json").write_text(
            json.dumps({"duration": 20.0, "hook": {"start": 2.0, "end": 14.0}}), encoding="utf-8")
        put_platform(root, "suno-hook")
        code, out = run_sub("--project", str(root), "--burn", str(root / "v.mp4"), "--out", str(root / "o.mp4"))
        res.append(("субтитры по платформе: suno-hook в project.json — выжигание отказывает «запрещены профилем»",
                    code == 2 and "запрещены" in out and not (root / "o.mp4").exists(), out))
        code, out = run_sub("--project", str(root), "--srt", str(root / "o.srt"))
        res.append(("субтитры по платформе: suno-hook — SRT отдаётся с предупреждением «не вшивать»",
                    code == 0 and "не вшивать" in out, out))
        put_platform(root, "instagram-reels")
        code, out = run_sub("--project", str(root), "--srt", str(root / "o.srt"))
        res.append(("субтитры по платформе: instagram-reels на проекте с окном hook в grid.json — явная платформа "
                    "главнее, предупреждения про Suno-hook нет",
                    code == 0 and "Suno-hook" not in out and "субтитры включены (рекомендуются)" in out, out))
        put_platform(root, "инстаграм")
        code, out = run_sub("--project", str(root), "--srt", str(root / "o.srt"))
        res.append(("субтитры по платформе: опечатка в project.json → platform — отказ со списком",
                    code == 2 and "неизвестна" in out, out))
        put_platform(root, "suno-hook")
        code, out = run_sub("--project", str(root), "--platform", "tiktok", "--srt", str(root / "o.srt"))
        res.append(("субтитры по платформе: --platform tiktok главнее project.json (suno-hook)",
                    code == 0 and "платформа tiktok" in out and "не вшивать" not in out, out))
        code, out = run_sub("--project", str(root), "--platform", "suno-hook", "--burn", str(root / "v.mp4"),
                            "--out", str(root / "o.mp4"))
        res.append(("субтитры по платформе: --platform suno-hook — выжигание отказывает",
                    code == 2 and "запрещены" in out, out))
        code, out = run_sub("--project", str(root), "--platform", "nope", "--srt", str(root / "o.srt"))
        res.append(("субтитры по платформе: неизвестная --platform — отказ", code == 2 and "неизвестна" in out, out))

        # безопасная зона берётся из профиля
        def margin(*a):
            c, o = run_sub("--project", str(root), "--ass", str(root / "z.ass"), *a)
            txt = (root / "z.ass").read_text(encoding="utf-8") if (root / "z.ass").exists() else ""
            m = re.search(r"Style: Cap,[^\n]*,2,(\d+),(\d+),(\d+),1", txt)
            return c, (int(m.group(3)) if m else None)
        put_platform(root, "generic-vertical")
        res.append(("безопасная зона из профиля: вертикаль 30 % (576), youtube-long 1920x1080 — 8 % (86), "
                    "ads-ozon-wb 1080x1440 — 10 % (144)",
                    margin("--size", "1080x1920") == (0, 576)
                    and margin("--platform", "youtube-long", "--size", "1920x1080") == (0, 86)
                    and margin("--platform", "ads-ozon-wb", "--size", "1080x1440") == (0, 144), ""))

        if ffmpeg and Path(ffmpeg).exists() and any(r["ok"] for r in st.font_report()):
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc=duration=7:size=1080x1920:rate=24", "-f", "lavfi", "-i",
                            "sine=frequency=330:duration=7", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", str(root / "v.mp4")], check=True)
            put_platform(root, "instagram-reels")
            code, out = run_sub("--project", str(root), "--burn", str(root / "v.mp4"), "--out", str(root / "o.mp4"))
            res.append(("субтитры по платформе: instagram-reels — выжигание разрешено и выполнено",
                        code == 0 and (root / "o.mp4").exists(), out))
            shutil_copy = root / "clip-suno-final.mp4"
            shutil_copy.write_bytes((root / "v.mp4").read_bytes())
            code, out = run_sub("--project", str(root), "--burn", str(shutil_copy), "--out", str(root / "o2.mp4"))
            res.append(("субтитры по платформе: файл «*-suno*.mp4» (упаковка под Suno) отказывает даже при instagram-reels",
                        code == 2 and "под Suno" in out and not (root / "o2.mp4").exists(), out))
            put_platform(root, "youtube-long")
            code, out = run_sub("--project", str(root), "--burn", str(root / "v.mp4"), "--out", str(root / "o3.mp4"))
            res.append(("субтитры по платформе: кадр 9:16 при профиле 16:9 — предупреждение про кадр, выжигание идёт",
                        code == 0 and "ждёт 16:9" in out, out))

    # упаковка Suno с платформой в project.json
    if ffmpeg and Path(ffmpeg).exists():
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            suno_project(root, ffmpeg)
            suno_media(ffmpeg, root / "ok.mp4", 12)
            put_platform(root, "instagram-reels")
            code, out = run_pack(root, "--master", "ok.mp4")
            res.append(("упаковка Suno: в project.json другая платформа — предупреждение, упаковка идёт",
                        code == 0 and "[~] в project.json платформа instagram-reels" in out, out))
            put_platform(root, "инстаграм")
            code, out = run_pack(root, "--master", "ok.mp4", "--force")
            res.append(("упаковка Suno: опечатка в platform — стоп до всякой работы", code == 2 and "неизвестна" in out, out))
    return res


def main():
    errors = 0
    print("── gate_script: герой СТНЦ ──")
    for desc, form, hero, want_code, want_warn in SCRIPT_CASES:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            make_project(root, form, hero)
            code, out = run_script(root)
            warned = "[~]" in out and "hero.json" in out
            ok = code == want_code and warned == want_warn
            errors += not ok
            print(f"{'ok  ' if ok else 'FALSCH'} {desc}: код {code}, предупреждение {warned}"
                  f" (ждали {want_code}/{want_warn})")
            if not ok:
                print("      вывод:", out.strip()[:300].replace("\n", " | "))

    # Герой не должен отнимать пройденный маркер: гейт зелёный → script-ok на месте.
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        make_project(root, "narrative", None)
        run_script(root)
        marker = root / ".gates" / "script-ok.json"
        ok = marker.exists()
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} narrative без героя: маркер script-ok записан (ждали да)")

    print("\n── регистр реальности: reality и miracle в шот-листе ──")
    reality_results = reality_checks()
    place_results = place_checks()
    for desc, ok, detail in place_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail[:300])
    for desc, ok, detail in reality_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[:300].replace("\n", " | "))

    print("\n── формат hook: gate_script и gate_density по окну трека ──")
    hook_results = hook_checks()
    for desc, ok, detail in hook_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[:300].replace("\n", " | "))

    print("\n── gate_preflight: мост Grok против Kie API ──")
    preflight_results = preflight_checks()
    for desc, ok, detail in preflight_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[-400:].replace("\n", " | "))

    print("\n── смета движения: цена из таблицы, дубли из конфига ──")
    for desc, ok, detail in motion_cost_checks():
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[-400:].replace("\n", " | "))

    print("\n── книга расходов: цена принятой секунды движения ──")
    for desc, ok, detail in ledger_checks():
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[-400:].replace("\n", " | "))

    print("\n── gate_assembly: частота кадров ──")
    cfg = lib.load_config()
    ffmpeg = cfg.get("ffmpeg")
    if not ffmpeg or not Path(ffmpeg).exists():
        print("[~] ffmpeg из config/paths.json не найден — проверка fps пропущена")
    else:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            audio = root / "a.mp3"
            make_audio(ffmpeg, audio)
            for desc, fps, want_warn in FPS_CASES:
                video = root / f"v_{fps}.mp4"
                make_video(ffmpeg, video, fps)
                r = subprocess.run([PY, str(HERE / "gate_assembly.py"), "--video", str(video),
                                    "--audio", str(audio)],
                                   capture_output=True, encoding="utf-8", errors="replace")
                out = (r.stdout or "") + (r.stderr or "")
                warned = "[~] частота кадров" in out
                # fps — предупреждение, не брак: код выхода остаётся 0 при любой частоте.
                ok = r.returncode == 0 and warned == want_warn
                errors += not ok
                print(f"{'ok  ' if ok else 'FALSCH'} {desc}: код {r.returncode}, "
                      f"предупреждение {warned} (ждали 0/{want_warn})")
                if not ok:
                    print("      вывод:", out.strip()[:300].replace("\n", " | "))

    print("\n── рекламная ветка: скаффолд, гейт товара, рекламный шот-лист, статус, сборка ──")
    ad_results = ad_checks(ffmpeg)
    for desc, ok, detail in ad_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[:300].replace("\n", " | "))

    print("\n── Suno-ветка: упаковка ролика под hook ──")
    suno_results = suno_checks(ffmpeg)
    if not suno_results:
        print("[~] ffmpeg из config/paths.json не найден — проверка Suno пропущена")
    for desc, ok, detail in suno_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[-400:].replace("\n", " | "))

    print("\n── правило шести: разбор склеек и требование при упаковке ──")
    cuts_results = cuts_checks(ffmpeg)
    for desc, ok, detail in cuts_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[-400:].replace("\n", " | "))

    print("\n── полка движений: карточка из ролика ──")
    motion_results = motion_checks(ffmpeg)
    for desc, ok, detail in motion_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[-400:].replace("\n", " | "))

    print("\n── слайдшоу-риск шот-листа ──")
    slideshow_results = slideshow_checks()
    for desc, ok, detail in slideshow_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[-400:].replace("\n", " | "))

    print("\n── журнал решений о провайдере ──")
    decisions_results = decisions_checks()
    for desc, ok, detail in decisions_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", str(detail).strip()[-400:].replace("\n", " | "))

    print("\n── субтитры: фразы, SRT/ASS, текст автора, шрифты, hook, выжигание ──")
    subtitles_results = subtitles_checks(ffmpeg)
    for desc, ok, detail in subtitles_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", detail.strip()[-400:].replace("\n", " | "))

    print("\n── платформы: профили, скаффолд, статус, субтитры и упаковка по платформе ──")
    platform_results = platform_checks(ffmpeg)
    for desc, ok, detail in platform_results:
        errors += not ok
        print(f"{'ok  ' if ok else 'FALSCH'} {desc}")
        if not ok and detail:
            print("      вывод:", str(detail).strip()[-400:].replace("\n", " | "))

    total = (len(SCRIPT_CASES) + 1 + (len(FPS_CASES) if ffmpeg and Path(ffmpeg).exists() else 0)
             + len(ad_results) + len(hook_results) + len(preflight_results) + len(suno_results)
             + len(motion_results) + len(reality_results) + len(place_results) + len(cuts_results)
             + len(slideshow_results) + len(decisions_results) + len(subtitles_results)
             + len(platform_results))
    print()
    if errors:
        print(f"{errors} из {total} случаев неверны.")
        return 1
    print(f"Все {total} случаев верны.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
