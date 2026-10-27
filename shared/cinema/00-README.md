# Киношная база знаний ClipMaker

Здесь лежит ремесло, а не правила проекта. Правила, оплаченные квотой, — в `shared/RULES.md`
(R01–R25). Здесь — как вообще устроено производство клипа: формы, тритмент, язык кадра,
монтаж под музыку, специфика AI-видео.

Эти файлы читают роли, а не человек. Каждый файл — вход для конкретного отдела.

| Файл | Кто обязан прочитать |
|---|---|
| `01-music-video-forms.md` | screenwriter, director |
| `02-treatment-and-script.md` | screenwriter, storyboard |
| `03-shot-language.md` | dop, storyboard, prompt-writer |
| `04-editing-to-music.md` | musicologist, storyboard, editor |
| `05-ai-video-craft.md` | prompt-writer, production-designer, anchors, shoot |
| `06-classic-rules.md` | storyboard, dop, editor, guardian |
| `10-physics-in-motion.md` | dop, prompt-writer, guardian |
| `11-two-people-closeness.md` | screenwriter, storyboard, dop, prompt-writer, guardian |
| `12-reality-register.md` | screenwriter, dop, prompt-writer, guardian |
| `13-failure-causes-research.md` | prompt-writer, dop, guardian |

## Чем это отличается от RULES.md

`RULES.md` отвечает на вопрос «чего нельзя делать в нашем пайплайне» — каждая строка оплачена
сожжённой квотой или ночью отладки. Здесь — «как это делают в профессии». Конфликта быть
не должно: если ремесло советует то, что у нас запрещено правилом, побеждает правило,
а расхождение записывается в `fix-queue.md` для разбора доктором.

## Обновление

База собрана веб-ресёрчем 09.08.2026. AI-часть (`05-ai-video-craft.md`) стареет быстрее всего —
модели и их границы меняются раз в пару месяцев. Обновляет её `clip-researcher` по команде,
а не сам по себе: незаметная подмена знания хуже устаревшего знания.

10.10.2026 дописаны разделы из роликов, которые прислал Админ: композиция и киношный вид —
в `03-shot-language.md`, якорь-лист — в `05-ai-video-craft.md`. Схема склейки — в `06`, п. 9.
13.10.2026 — `10-physics-in-motion.md` и `11-two-people-closeness.md` (разведка по 25 источникам после
брака <проект>: комки вместо пыли, рука мимо линии, пара «как неродные»), и полка движений
`shared/motion-refs/` — раскадровки движений из жизни и из своего брака. Все помечены непроверенными
(R23): это чужие обещания, пока наш прогон не даст числа. Откуда взяты и чего в них нет —
`shared/ads/01-sources.md`. Там же порядок разбора ролика: смысл в речи и в надписях, а не
в подписи к посту, и достаёт его `scripts/study_reel.py`.
