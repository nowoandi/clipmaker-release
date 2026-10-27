# gate_env.py — проверка окружения перед работой (R22).
# Выход 0 — всё на месте; 2 — чего-то нет, работа не начинается.
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib

def main():
    lib.setup_io()
    cfg = lib.load_config()
    problems = []

    ffmpeg = Path(cfg["ffmpeg"])
    if ffmpeg.exists():
        print(f"[+] ffmpeg: {ffmpeg}")
    else:
        problems.append(f"ffmpeg не найден: {ffmpeg} (путь в config/paths.json)")

    node = shutil.which("node")
    if node:
        print(f"[+] node: {node}")
    else:
        problems.append("node не найден в PATH — съёмочные скрипты не запустятся")

    bridge = Path(cfg["grok_bridge"])
    if (bridge / "budget.js").exists():
        print(f"[+] grok-bridge с budget.js: {bridge}")
    else:
        problems.append(f"grok-bridge/budget.js не найден: {bridge}")

    pipeline = Path(cfg["pipeline"])
    if pipeline.exists():
        print(f"[+] pipeline-v3: {pipeline}")
    else:
        problems.append(f"pipeline-v3 не найден: {pipeline}")

    try:
        out = subprocess.run([str(ffmpeg), "-version"], capture_output=True, text=True, timeout=15)
        ver = (out.stdout or "").splitlines()[0] if out.stdout else "?"
        print(f"[+] ffmpeg отвечает: {ver}")
    except Exception as e:
        problems.append(f"ffmpeg не запускается: {e}")

    # Музыкальный слой: без него нет ни сетки такта, ни пословных таймингов (R20).
    # Раньше здесь стояла заметка «faster-whisper сломан» — теперь это проверяется
    # фактом, а не памятью: заметка однажды устарела и полгода отправляла работу в облако.
    import importlib
    audio = {
        "librosa": "сетка долей, такты, BPM",
        "soundfile": "чтение аудио для librosa",
        "faster_whisper": "пословные тайминги (word_timestamps)",
    }
    missing = []
    for mod, why in audio.items():
        try:
            m = importlib.import_module(mod)
            print(f"[+] {mod} {getattr(m, '__version__', '')} — {why}")
        except Exception as e:
            missing.append(f"{mod} не импортируется ({type(e).__name__}) — нет: {why}")
    if missing:
        for m in missing:
            problems.append(m)
        problems.append(
            f"поставить: \"{sys.executable}\" -m pip install librosa soundfile faster-whisper"
        )

    if problems:
        for p in problems:
            print("[-] " + p, file=sys.stderr)
        lib.fail("окружение неполное, см. выше.")
    lib.ok("окружение готово.")

if __name__ == "__main__":
    main()
