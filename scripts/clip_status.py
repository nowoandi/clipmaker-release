# clip_status.py — состояние проекта с диска, а не из памяти чата.
#
# Это якорь восстановления контекста: после сжатия/переполнения контекста
# Claude запускает этот скрипт и продолжает с точного места. Никаких
# «я помню, что мы остановились на…» — только файлы.
#
#   python clip_status.py --project <папка>
#
# Выход всегда 0 — это не гейт, а сводка.
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

def main():
    lib.setup_io()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--file", default=None)
    args = ap.parse_args()

    cfg = lib.load_config()
    pdir = lib.project_dir(args.project)
    pjson = lib.find_project_json(pdir, args.file)
    project = lib.read_json(pjson)
    scenes = [s for s in project.get("scenes", []) if s.get("enabled", True)]
    frames_dir, clips_dir = Path(pdir) / "frames", Path(pdir) / "clips"

    # Вердикты панели приёмки: clips/verdicts.json проекта (lib.verdicts_path).
    verdicts = {}
    vp = lib.verdicts_path(pdir)
    if vp.exists():
        try:
            for v in lib.read_json(vp):
                verdicts[str(v.get("clip", "")).replace(".mp4", "")] = v.get("verdict", "?")
        except Exception:
            pass

    n_frame = n_clip = n_v2 = n_ok = n_rej = 0
    rows = []
    for sc in scenes:
        sid = sc.get("id", "?")
        f = (frames_dir / f"{sid}.png").exists()
        c = (clips_dir / f"{sid}.mp4").exists()
        v2 = (clips_dir / f"{sid}_v2.mp4").exists()
        verdict = verdicts.get(sid, "")
        n_frame += f
        n_clip += c
        n_v2 += v2
        n_ok += verdict == "accept"
        n_rej += verdict == "reject"
        mark = ("К" if f else "·") + ("В" if c else "·") + ("2" if v2 else "·")
        vtxt = {"accept": "принят", "reject": "БРАК"}.get(verdict, "")
        rows.append(f"  {sid} [{mark}] {vtxt}")

    kind = " · реклама" if (Path(pdir) / "clip-memory" / "product" / "product.json").exists() else ""
    print(f"── СТАТУС · {project.get('project', pjson.name)}{kind} · {time.strftime('%d.%m %H:%M')} " + "─" * 8)
    # Платформа («для чего делаем», 0.8.37): подсказка про субтитры. Нет поля — старое поведение.
    pname, pprof, perr = lib.project_platform(pdir)
    if perr:
        print(f"  [~] platform в project.json: {perr}")
    else:
        print("  " + lib.subtitles_status_line(pname, pprof))
    print(f"  сцен активных: {len(scenes)} · кадров {n_frame} · клипов {n_clip} · дублей v2 {n_v2}")
    print(f"  вердиктов: принято {n_ok} · брак {n_rej} · без вердикта {n_clip - n_ok - n_rej}")
    print("  [К=кадр есть · В=видео есть · 2=дубль v2 есть]")
    for r in rows:
        print(r)
    print("─" * 46)

    # Разработка: пока она не закрыта, говорить про кадры бессмысленно.
    mem = Path(pdir) / "clip-memory"
    # Рекламный проект узнаётся по паспорту товара: трека у него нет, и «разбор трека» он не пройдёт
    # никогда — подсказка клипа отправила бы директора к музыковеду, которому нечего разбирать.
    ad = (mem / "product" / "product.json").exists()
    if ad:
        stages = [
            ("паспорт товара", Path(pdir) / ".gates" / "product-ok.json", "ad-director"),
            ("бриф ролика",    mem / "script" / "treatment.md",        "ad-storyboard"),
            ("якорь товара",   mem / "canon" / "anchor-brief.json",    "clip-production-designer"),
            ("канон камеры",   mem / "canon" / "camera.json",          "clip-dop"),
            ("раскадровка",    mem / "script" / "shotlist.json",       "ad-storyboard"),
            ("смета",          mem / "reports" / "budget.json",        "clip-line-producer"),
        ]
    else:
        stages = [
            ("ресёрч темы",   mem / "research" / "dossier.md",        "clip-researcher"),
            ("разбор трека",  mem / "song" / "grid.json",             "clip-musicologist"),
            ("сценарий",      mem / "script" / "treatment.md",        "clip-screenwriter"),
            ("канон мира",    mem / "canon" / "anchor-brief.json",    "clip-production-designer"),
            ("канон камеры",  mem / "canon" / "camera.json",          "clip-dop"),
            ("раскадровка",   mem / "script" / "shotlist.json",       "clip-storyboard"),
            ("смета",         mem / "reports" / "budget.json",        "clip-line-producer"),
        ]
    ready = [(title, path.exists(), agent) for title, path, agent in stages]
    missing = [(title, agent) for title, done, agent in ready if not done]
    # Проект старого образца (кадры есть, памяти нет) через разработку не гоняем.
    legacy = not mem.exists() and n_frame > 0
    if not legacy:
        marks = " ".join("+" if done else "·" for _, done, _ in ready)
        print(f"  разработка: {len(stages) - len(missing)}/{len(stages)}  {marks}")
    if missing and not legacy:
        title, agent = missing[0]
        print(f"→ дальше: {title} — роль {agent}. Дальше по цепочке PIPELINE.md.")
        print("─" * 46)
        return

    # Подсказка следующего шага — из фактов, не из памяти.
    if not scenes:
        print("→ дальше: промпты сцен — роль clip-prompt-writer (собирает scenes[] из шот-листа).")
        print("─" * 46)
        return
    if n_frame < len(scenes):
        print(f"→ дальше: кадры ({len(scenes) - n_frame} нет). Сначала gate_prompts.py, потом --dry, потом пакет.")
    elif n_clip < len(scenes):
        print(f"→ дальше: съёмка ({len(scenes) - n_clip} клипов нет). Сначала gate_preflight.py, партии по 4-5 (R11).")
    elif n_clip - n_ok - n_rej > 0:
        print(f"→ дальше: приёмка в панели ({n_clip - n_ok - n_rej} клипов без вердикта). "
              f"Запуск: {cfg.get('review_panel_bat', 'ПРИЁМКА.bat')} (R17). Дубли v2 сравнить A/B (R15).")
    elif n_rej > 0:
        print(f"→ дальше: пересъёмка брака ({n_rej} шт) точечно, через новый предполёт.")
    elif ad:
        print("→ дальше: сборка по секундам шот-листа — ad_assemble.py; посмотреть целиком и без звука.")
    else:
        print("→ дальше: сборка по сетке такта (R20), потом gate_assembly.py (R18).")

if __name__ == "__main__":
    main()
