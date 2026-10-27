# gate_frames.py — глаз оператора: разбор кадров до видео (0.8.28).
#
# Зачем. Кадр стоит 6 кр., ролик 27–45. Свет не от того источника, рука в одном месте, а линия в
# другом, комки вместо пыли, пара «как неродные» — всё это видно уже на кадре. Разбор пишет
# clip-guardian в clip-memory/reports/frames-review.json, предполёт видео без него партию не пускает.
#
#   python gate_frames.py --project <клип> --template     заготовка разбора: sha1 кадров и виды проверок
#   python gate_frames.py --project <клип> [--only S01,S02]   проверить разбор; exit 2 — есть претензии
#
# Заготовка не пишет файл сама: разбор — работа глаза, а не скрипта.
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

lib.setup_io()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--file", help="явный путь к project.json")
    ap.add_argument("--only", help="сцены через запятую; по умолчанию все включённые")
    ap.add_argument("--template", action="store_true", help="напечатать заготовку frames-review.json")
    args = ap.parse_args()

    pdir = lib.project_dir(args.project)
    project = lib.read_json(lib.find_project_json(pdir, args.file))
    ids = [s.get("id") for s in project.get("scenes", []) if s.get("enabled") is not False]
    if args.only:
        want = [x.strip() for x in args.only.split(",") if x.strip()]
        unknown = [x for x in want if x not in ids]
        if unknown:
            lib.fail(f"нет таких включённых сцен: {', '.join(unknown)}")
        ids = want

    if args.template:
        frames = {}
        for sid in ids:
            fp = lib.frame_path(pdir, sid, project.get("project"))
            frames[sid] = {
                "sha1": lib.file_sha1(fp) if fp else None,
                "verdict": "accept | reject",
                "note": "",
                "checks": [{"id": k, "kind": k, "ok": None, "note": ""} for k in lib.FRAME_REVIEW_KINDS]
                + [{"id": "people", "kind": "people", "ok": None,
                    "note": "только если в кадре люди: поза, касание, вес, близость"}],
            }
        print(json.dumps({"reviewer": "clip-guardian", "frames": frames}, ensure_ascii=False, indent=1))
        return 0

    problems = lib.frames_review_problems(pdir, ids, project.get("project"))
    if problems:
        lib.fail("разбор кадров неполон:\n  · " + "\n  · ".join(problems))
    lib.ok(f"кадры разобраны и приняты: {', '.join(ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
