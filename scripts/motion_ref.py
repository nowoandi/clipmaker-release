# motion_ref.py — карточка «полки движений»: как движение выглядит в жизни, по долям секунды.
#
# Зачем. Админ, 13.10.2026: «на реальных видео смотреть по физике, вот это всё, как это работает …
# хотя бы какие-то покадровые снимки, цак-цак-цак, и потом на базе этого делать свой сценарий …
# если мы будем каждый раз уходить на поиски, это время будет очень много занимать».
# Поэтому полка: одно движение — одна карточка, собирается ОДИН раз и лежит в плагине
# (shared/motion-refs/<slug>/). Новый клип сначала ищет на полке; поиск — только если движения нет.
# Брак своих прогонов — тоже карточка, со знаком «так не бывает»: он учит не хуже эталона.
#
#   python motion_ref.py --video <файл.mp4> --start 3.0 --end 6.0 --slug chalk-dust-wind \
#                        --title "Меловая пыль на ветру" --kind real|anti --source "<URL или путь>" \
#                        [--license "Pexels License"] [--fps 4]
#
# Пишет strip.jpg (кадры с шагом 1/fps с, по 8 в ряд) и card.md с полями, которые заполняет
# глаз, а не скрипт: что движется, тайминг в секундах, направление, чего не бывает, слова для
# промпта, проверка для приёмки. Существующую карточку не перезаписывает.
import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

lib.setup_io()

SHELF = lib.plugin_root() / "shared" / "motion-refs"

CARD = """# {title}

- slug: `{slug}`
- вид: **{kind_ru}**
- источник: {source}
- лицензия: {license}
- отрезок: {start:.2f}–{end:.2f} с, раскадровка `strip.jpg` — {n} кадров через {step:.2f} с
  (слева направо, сверху вниз; первый кадр = {start:.2f} с)
- заведена: {today}

## Что движется

(одной фразой: что, откуда, куда)

## Тайминг в секундах

(сколько длится каждая фаза: разгон, пик, затухание; по кадрам раскадровки)

## Направление и вес

(куда уходит, что тяжёлое и падает, что лёгкое и висит, как действует ветер / рука / тело)

## Чего не бывает

(что модель делает, а жизнь — нет; для карточки «так не бывает» — что именно здесь неправда)

## Слова для промпта

```
(английские слова для motion: причина → следствие, скорость, направление, размер частиц)
```

## Проверка для приёмки

(одна-две фразы, которые глаз оператора сверяет на кадре и на ролике; вид: physics / people)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--slug", required=True, help="латиницей, через дефис: chalk-dust-wind")
    ap.add_argument("--title", required=True)
    ap.add_argument("--kind", choices=["real", "anti", "technique"], required=True,
                    help="real — эталон из жизни; anti — брак своего прогона, «так не бывает»; "
                         "technique — приём, который мы сделали сами (монтаж, слой, симуляция): как получилось")
    ap.add_argument("--source", required=True)
    ap.add_argument("--license", default="—")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--shelf", default=str(SHELF))
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", args.slug):
        lib.fail(f"slug «{args.slug}»: латиница, цифры и дефис (R25)")
    if args.kind == "real" and args.license in ("", "—"):
        lib.fail("у эталона из жизни нужна лицензия источника (--license): полка лежит в репозитории")
    video = Path(args.video)
    if not video.exists():
        lib.fail(f"нет файла {video}")
    if not 0 <= args.start < args.end:
        lib.fail(f"отрезок {args.start}–{args.end} пустой или вывернут")
    if args.end - args.start > 12:
        lib.fail("отрезок длиннее 12 с: карточка — про одно движение, а не про сцену")

    cfg = lib.load_config()
    ffmpeg = cfg.get("ffmpeg")
    if not ffmpeg or not Path(ffmpeg).exists():
        lib.fail("ffmpeg из config/paths.json не найден (R22)")

    out = Path(args.shelf) / args.slug
    if (out / "card.md").exists():
        lib.fail(f"карточка {out / 'card.md'} уже есть: правится руками, а не перезаписывается")
    out.mkdir(parents=True, exist_ok=True)

    n = max(1, int(round((args.end - args.start) * args.fps)))
    cols = min(8, n)
    rows = (n + cols - 1) // cols
    # Шрифты для drawtext в поставке ffmpeg нет (fontconfig) — время кадра пишется в карточку.
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{args.start:.3f}", "-t", f"{args.end - args.start:.3f}", "-i", str(video),
                    "-vf", f"fps={args.fps},scale=240:-2,tile={cols}x{rows}:padding=4:color=black",
                    "-frames:v", "1", "-q:v", "4", str(out / "strip.jpg")], check=True)

    (out / "card.md").write_text(CARD.format(
        title=args.title, slug=args.slug,
        kind_ru={"real": "эталон из жизни", "anti": "так не бывает — брак своего прогона",
                 "technique": "приём: как мы это сделали"}[args.kind],
        source=args.source, license=args.license, start=args.start, end=args.end,
        n=n, step=1 / args.fps, today=date.today().isoformat()), encoding="utf-8")
    lib.ok(f"карточка заведена: {out / 'card.md'} и {out / 'strip.jpg'}. Поля карточки заполнить "
           f"глазом по раскадровке — скрипт их не знает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
