---
name: clip-shoot
description: Съёмка видео партиями 4–5 через Kie API (по умолчанию) или мост Grok (явно) — предполёт перед каждой партией, одна попытка на сцену, паспорт и журнал. Use when shooting video clips for scenes via Kie API or the Grok bridge.
---

# Clip Shoot

## Перед КАЖДОЙ партией

1. `$env:CLIP_PROJECT = "<папка проекта>"` — его читает хук.
2. `python "${CLAUDE_PLUGIN_ROOT}/scripts/gate_preflight.py" --project "<папка>"` — стоп по слову Grok (R10), расклад по журналу (R08), retries (R09), размер партии (R11), реестр скачанного (R14).

Маркер `.gates/preflight-ok.json` живёт `preflight_ttl_min` (30 мин по умолчанию) и покрывает ОДНУ партию: хук сжигает его после запуска съёмочной команды. Следующая партия = новый предполёт (R08, R11).

## Правила съёмки

- R09: одна попытка на сцену (`retries=1`); больше — только осознанно, флагом `--allow-retries`.
- R10: Grok сказал «исчерпано» — не спорить арифметикой. Записать дату сброса через `setReset` в `budget.js` (папка `grok_bridge` из `${CLAUDE_PLUGIN_ROOT}/config/paths.json`); до сброса стоп, `--force-estimate` этот стоп не снимает.
- R11: партии по 4–5 отправок, после каждой — проверка результата, потом следующая.
- R13: у каждого клипа паспорт (рецепт, вход, настройки, адрес поста, файлы, полный промпт) и журнал попыток — одна строка на попытку, включая провалы.
- R15: Grok отдаёт ДВА ролика на отправку — второй сохранять как `<id>_v2.mp4`, не выбрасывать.
- R34: пресетная сцена, забракованная на приёмке, переснимается заранее собранным запасным
  вариантом, а не новым текстом: `preset_build.py --project <папка> --use-fallback S05:B`,
  потом `gate_prompts.py`, потом отправка. Запасная отправка — вторая попытка, она в смете.

## Запуск процессов (R22)

Съёмочные скрипты (`clips-sk.js`, `chain-link.js`) — в папке `grok_bridge` из `config/paths.json`. Запуск только `Start-Process … -WindowStyle Hidden`, пути с пробелами в кавычках, запуск и проверка статуса — РАЗНЫМИ вызовами (обёртка рвётся на 60 с).

## Провайдер

`video.provider` в project.json: `api` (Kie, платно) — умолчание с 29.10.2026 (`default_video_provider` в `config/paths.json`: бесплатный доступ к Grok через мост закончился, слова Админа 29.10.2026) | `bridge` (Grok Desktop, квота; только если мост снова включён явно). Предполёт без `--provider` идёт веткой Kie и требует `--only` или `--block`; для моста — `--provider bridge --planned N`. Тихий фолбэк bridge↔api ЗАПРЕЩЁН — смена провайдера только явным решением Админа и между клипами (R10).

**Партия через Kie** (`video.js --provider api`) — предполёт тем же провайдером и той же выборкой:

```powershell
python "${CLAUDE_PLUGIN_ROOT}/scripts/gate_preflight.py" --project "<папка>" --provider api --only S01,S02,S03
node "<pipeline>\video.js" project.<клип>.json --provider api --only S01,S02,S03
```

Квоту моста эта ветка не смотрит. Она считает партию: сцены × `video.duration` × цена секунды
(`video.cost_per_sec` проекта, иначе `motion.credits_per_sec` или единственный `prices.*credits_per_sec`
в `budget.json`, последним — `video.cost_hint` как цена ролика). Сверяет с потолком
`budget.json → motion.ceiling_credits` минус уже потраченное (большее из книги `clip_ledger` по этапу
`shoot` и падения баланса Kie со снимка `budget.json → kie_balance.credits`), с вердиктом сметы и
балансом Kie. Потолок `--force-estimate` не снимает. Хук пускает `video.js` только по маркеру Kie,
только сценами из него и только при тех же `video.duration` и `video.model`; маркер моста партию
Kie не пускает, и наоборот. После партии — `clip_ledger.py record --stage shoot --before … --after … --items N --model <video.model> --seconds <video.duration>` (так `report` посчитает цену принятой секунды движения).

## После партии

`python "${CLAUDE_PLUGIN_ROOT}/scripts/clip_status.py" --project "<папка>"` — что снялось, что нет. Дальше приёмка (скилл clip-review), а не следующая партия вслепую.
