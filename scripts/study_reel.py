# study_reel.py — расшифровка ролика-источника в текст и кадры.
#
# Зачем. Админ присылает ссылки на Instagram-ролики с ремеслом (10.10.2026:
# «иногда информация идёт в самом видео»). Подпись к посту знание не несёт — оно
# в речи и в надписях на экране. Этот скрипт превращает ролик в текст, который
# можно положить в shared/ads/ или shared/cinema/ и потом искать.
#
#   python study_reel.py --audio <URL> [--video <URL>] [--name reel-01] [--frames 12]
#
# Где брать URL. Instagram отдаёт ролик DASH-ом: видео и звук РАЗНЫМИ файлами, а в
# <video> стоит blob:, который не скачать. Прямые ссылки лежат в performance-записях
# страницы; снимает их браузер (встроенная панель), не этот скрипт:
#
#   const base = u => u.split('&bytestart')[0];
#   const tag  = u => JSON.parse(atob(decodeURIComponent(u.match(/efg=([^&]+)/)[1]))).vencode_tag;
#   performance.getEntriesByType('resource').map(r=>base(r.name))
#     .filter(u=>/\/o1\/v\/t2\//.test(u)).filter((u,i,a)=>a.indexOf(u)===i)
#     .map(u=>({tag:tag(u), u}))   // *_audio — звук, dash_vp9_* — картинка
#
# Ссылка подписана и живёт недолго: скачивать сразу, как снял.
#
# Звук → faster-whisper. Кадры → ffmpeg, их читает глазами модель: в этих роликах
# половина смысла в надписях, и распознавалка речи их не видит.
import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_lib as lib


def hol(url, ziel):
    """Скачать по подписанной ссылке CDN. Без User-Agent отдаётся 403."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(ziel, "wb") as f:
        f.write(r.read())
    return ziel.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="прямая ссылка на звуковую дорожку")
    ap.add_argument("--video", default=None, help="прямая ссылка на картинку (для кадров)")
    ap.add_argument("--name", default="reel", help="имя для файлов (латиницей, R25)")
    ap.add_argument("--out", default=None, help="куда класть; по умолчанию рядом, в study/")
    ap.add_argument("--frames", type=int, default=0, help="сколько кадров вынуть для чтения надписей")
    ap.add_argument("--model", default="small", help="модель whisper: small быстрее, medium точнее")
    args = ap.parse_args()

    lib.setup_io()
    cfg = lib.load_config()
    ffmpeg = cfg.get("ffmpeg")
    if not ffmpeg or not Path(ffmpeg).exists():
        lib.fail("в config/paths.json нет рабочего пути к ffmpeg")

    out = Path(args.out) if args.out else Path.cwd() / "study" / args.name
    out.mkdir(parents=True, exist_ok=True)

    audio_roh = out / "audio.mp4"
    print(f"[·] звук: {hol(args.audio, audio_roh)} байт")
    wav = out / "audio.wav"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(audio_roh), "-ar", "16000", "-ac", "1", str(wav)], check=True)

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segs, info = model.transcribe(str(wav), language=None, vad_filter=True)
    zeilen, daten = [], []
    for s in segs:
        text = s.text.strip()
        zeilen.append(f"[{s.start:6.1f}] {text}")
        daten.append({"start": round(s.start, 1), "end": round(s.end, 1), "text": text})
    kopf = f"# {args.name}\n\nЯзык {info.language} ({info.language_probability:.2f}).\n\n"
    # Распознавалка коверкает имена техники: «Кодок vision 3 500 t» — это Kodak
    # Vision3 500T, «Cook S4i» — Cooke S4/i. Расшифровка — черновик, а не источник.
    kopf += "Расшифровка машинная: названия камер, оптики и плёнки сверять руками.\n\n"
    (out / "transcript.md").write_text(kopf + "\n".join(zeilen) + "\n", encoding="utf-8")
    (out / "transcript.json").write_text(
        json.dumps({"language": info.language, "segments": daten}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"[+] расшифровка: {len(daten)} реплик → {out / 'transcript.md'}")

    if args.frames and args.video:
        video_roh = out / "video.mp4"
        print(f"[·] картинка: {hol(args.video, video_roh)} байт")
        kader = out / "frames"
        kader.mkdir(exist_ok=True)
        dauer = max((d["end"] for d in daten), default=0) or 30
        schritt = max(dauer / args.frames, 0.5)
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(video_roh), "-vf", f"fps=1/{schritt:.2f},scale=720:-1",
                        str(kader / "f%02d.jpg")], check=True)
        n = len(list(kader.glob("*.jpg")))
        print(f"[+] кадры: {n} шт. раз в {schritt:.1f} с → {kader}")
        print("    надписи на них читает модель глазами — whisper их не видит.")

    lib.ok(f"источник разобран: {out}")


if __name__ == "__main__":
    main()
