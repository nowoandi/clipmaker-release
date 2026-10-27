# lang_policy.py — где кириллица уместна, а где ломает машину.
#
# Правило простое (R25): всё, что читает человек, — по-русски; всё, что читает машина, —
# латиницей. Машина здесь это: файловая система, cmd, генераторы промптов, ffmpeg, node.
# Каждая из них уже подводила нас по кодировке, и каждый раз чинилось одинаково —
# переводом строки в латиницу.
#
# Кириллица РАЗРЕШЕНА и нужна: тритмент, досье, экспликация, note кадра, why якоря,
# вердикты, отчёты, фрагменты, README. Это описания процесса, их читает Админ.
#
# Кириллица ЗАПРЕЩЕНА: имена файлов и папок, идентификаторы, значения словарей,
# любые тексты, уходящие в модель (промпты, канон, стиль, негатив), .bat и .cmd.
import re
import unicodedata

CYR = re.compile(r"[А-Яа-яЁё]")

def has_cyr(text):
    return bool(text) and bool(CYR.search(str(text)))

TRANSLIT = {
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i",
    "й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t",
    "у":"u","ф":"f","х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"",
    "э":"e","ю":"yu","я":"ya",
}

def slug(text, fallback="clip"):
    """Имя папки или файла из русского названия: «Рубка связи» → rubka-svyazi.
    Файловая система, node и ffmpeg на этой машине спотыкаются о кириллицу и пробелы,
    поэтому имена делаются латиницей один раз — при заведении проекта."""
    s = unicodedata.normalize("NFKD", str(text or "")).lower()
    out = []
    for ch in s:
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isalnum() and ord(ch) < 128:
            out.append(ch)
        elif ch in " -_./\\":
            out.append("-")
    res = re.sub(r"-{2,}", "-", "".join(out)).strip("-")
    return res or fallback

# Что проверяем в каких файлах. Ключ — путь до поля, значение — почему нельзя кириллицу.
MACHINE_FIELDS = {
    "project.json": {
        "scenes[].scene":      "промпт кадра уходит в генератор",
        "scenes[].motion":     "промпт движения уходит в генератор",
        "canon.style":         "хвост промпта",
        "canon.style_short":   "хвост промпта",
        "canon.neg":           "негатив уходит в генератор",
        "canon.neg_short":     "негатив уходит в генератор",
        "canon.must":          "дописывается в каждый промпт (R03)",
        "canon.must_short":    "дописывается в каждый промпт (R03)",
        "canon.ref_rule":      "правило удержания референса уходит в промпт",
        "canon.silence":       "сверяется со словами промпта (R02)",
        "canon.refs{}":        "имя якоря подставляется в запрос",
    },
    "shotlist.json": {
        "shots[].id":        "идентификатор кадра становится именем файла",
        "shots[].section":   "имя раздела сверяется с сеткой такта машинно",
        "shots[].size":      "значение словаря, проверяется гейтом",
        "shots[].angle":     "значение словаря, проверяется гейтом",
        "shots[].movement":  "значение словаря, проверяется гейтом",
        "shots[].anchors[]": "имя якоря подставляется в запрос",
        "shots[].content":   "содержание кадра уходит в промпт",
        "shots[].light":     "описание света уходит в промпт",
    },
    "anchor-brief.json": {
        "anchors[].name":   "имя якоря становится ключом и попадает в запрос",
        "anchors[].prompt": "промпт якоря уходит в генератор",
    },
}

# Поля, где кириллица — норма: это разговор с человеком, а не с машиной.
HUMAN_FIELDS = (
    "note", "why", "what", "change", "holds", "does_not_hold",
    "risks", "adjacency_rules", "notes", "defect", "action",
)

def check_value(path, value, problems, why=""):
    """Рекурсивно проверяет значение на кириллицу, пропуская человеческие поля."""
    last = path.rsplit(".", 1)[-1].rstrip("[]{}")
    if last in HUMAN_FIELDS:
        return
    if isinstance(value, str):
        if has_cyr(value):
            snippet = value.strip().replace("\n", " ")[:70]
            problems.append(f"{path}: кириллица — {why or 'машинное поле'} · «{snippet}»")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            check_value(f"{path}[{i}]", v, problems, why)
    elif isinstance(value, dict):
        for k, v in value.items():
            if has_cyr(k):
                problems.append(f"{path}.{k}: кириллица в имени ключа — {why or 'машинное поле'}")
            check_value(f"{path}.{k}", v, problems, why)
