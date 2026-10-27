# Физика движения в AI-видео

Повод — <проект>, 12–13.10.2026: «ветер сдувает меловое сердце» дал падающие комки
«штукатурки» при целом сердце, «рука дорисовывает сердце» — петлю и восьмёрку мимо линии.
Админ: «это нужно как-то … по физике должно быть более». Разведка 13.10.2026 (25 источников,
полный отчёт сжат сюда). Метки: **[подтв.]** — офдока или первичный источник, **[косв.]** — блог
платформы или пересказ, **[гипотеза]** — вывод, проверить своим прогоном (R23). Эталоны и брак —
на полке движений `shared/motion-refs/`.

**Регистр.** Всё ниже — закон для `reality: real` и для всего, кроме объявленного допущения, в
`heightened` и `fantasy` (`12-reality-register.md`: чудо одно и названо, остальное по физике).

## Что известно точно

- **Гайдов по физике нет ни у одного вендора.** xAI про физику и частицы не пишет ничего;
  единственный пример — «Make the water crash down and slowly pan out the camera» (действие +
  один ход камеры) [подтв., docs.x.ai]. У Google Veo раздела физики нет [подтв.].
- **Красиво ≠ физично.** Physics-IQ (DeepMind, WACV 2026): понимание физики у видеомоделей
  «severely limited, and unrelated to visual realism» [подтв., arXiv 2501.09038]. Нельзя
  рассчитывать, что модель «знает», как ведёт себя пыль: траекторию надо написать.
- **Grok Imagine не воспроизводим даже с тем же seed** [подтв., ComfyUI] — на сложное движение
  закладывать 3–4 прогона, а не один.
- **Grok Imagine 1.5, reference-to-video:** до 14 референсов, можно закрепить первый,
  последний и средние кадры [подтв., docs.x.ai]. Есть ли это у модели на Kie — проверить.

## Правила

1. **Одно главное движение и один ход камеры на ролик.** Лучше `locked-off camera, static tripod
   shot`. Ветер + рука + камера одновременно — каша. [косв., несколько платформ]
2. **i2v-промпт описывает только изменение.** Картинку не пересказывать — она уже в кадре. [косв.]
3. **Причина → движение → конечное состояние.** `a steady breeze from frame left lifts … carries …
   thins out and fades`. У эффекта есть начало, путь и конец. [косв.]
4. **Мелкий порошок — облаком, не кусками.** Слова: `fine powder`, `airy haze`, `soft cloud`,
   `finer than flour`, `weightless`, `stays airborne`. Не писать `crumble`, `plaster`, `chunks`,
   `flakes`, `debris`, `falling pieces` — они вызывают падающие куски. [гипотеза, из физики]
5. **Источник частиц — по имени.** `lifts off the chalk lines themselves; the wall behind stays
   clean` — иначе модель сама выберет, что осыпается. [гипотеза]
6. **Ветер — направление, сила, время.** `a steady light breeze from frame left to frame right,
   over 3 seconds`, а не `windy`. [косв.]
7. **Частицы видны только в свете.** `backlit`, `a single shaft of light`, тёмный фон
   (`floating dust motes in a sunbeam` — пример Google) [подтв.].
8. **Темп словами и секундами.** `slow motion`, `slowly`, `over 4 seconds`, `at the 2nd second`.
   Не `cinematic`, `epic`, `magical`. [подтв. для Veo и Kling]
9. **Позитивно, а не «no».** Google прямо советует перечислять нежелательное в отдельном поле, а
   не писать «no/don't» [подтв.]; у Grok поля негатива не найдено. Писать, что ДЕЛАЕТСЯ:
   `the dust stays airborne and drifts sideways, nothing falls`.
10. **Инвариант.** `everything else stays unchanged; the existing lines remain as in the first
    frame`. [косв.]
11. **Короткие ролики для контакта руки.** 3–5 с, один штрих — один ролик; ошибки рук копятся со
    временем. [косв.]
12. **Ткань и волосы — от внешней силы.** `a breeze lifts strands of her hair and lets them fall
    back`, а не `flowing hair`. Вес: `weight shifts onto`, `settles into`, `sinks slightly`;
    инерция: `eases to a stop`. [косв.]
13. **Чего модель не сыграет — не просить.** Ветер почти не снимает мел с камня; рисунок
    исчезает от дождя, ладони или склейкой. Красивая неправда без механизма даёт брак (полка:
    `chalk-crumble-anti`).
14. **Что не получилось за 3–4 прогона — в монтаж.** Линию рисунка можно проявить маской
    (stroke-reveal), исчезновение — растворением, пыль — отдельным слоем поверх. [гипотеза]

Почему модель ведёт себя так (дым из слова, коса, тюль, наезд в зум) и какой метки заслуживает каждая
причина — `13-failure-causes-research.md`.

## Словарь частиц (VFX)

drift — медленный снос; swirl, eddy — завихрения; billow — клубами; plume — шлейф; wisp, tendril —
струйки; haze — дымка; puff — клуб; lift off, kick up — подняться с поверхности; disperse,
dissipate, thin out — рассеяться; linger, hang in the air, suspended — зависать; settle — оседать;
float; rise; trail; motes; residue; volumetric light, light shafts; backlit particles.

## Рецепты под наши провалы (гипотезы, проверять)

**Пыль с рисунка.** `Locked-off camera. A steady breeze from frame left lifts the chalk lines off
the wall as a fine pale powder, finer than flour; the powder forms a soft airy haze that drifts to
frame right and slowly thins. The powder stays airborne, nothing falls; the wall behind stays
clean. Slow motion, 4 seconds.` Надёжнее с последним кадром «стена со следами» — тогда «рисунок
остался целым» невозможен.

**Рука дорисовывает.** Крупно: кисть и кончик мела. `Locked-off close-up. Her chalk slowly draws
one continuous curved line completing the right half of the heart. The line appears only at the
tip of the chalk, exactly under the fingertips, and follows the hand's path. The left half stays
unchanged. Slow, steady motion, 3 seconds.`

## Источники

docs.x.ai/docs/guides/video-generation · docs.comfy.org (Grok Imagine Video 1.5) ·
docs.cloud.google.com/vertex-ai/…/video-gen-prompt-guide · cloud.google.com/blog (Veo 3.1, 16.10.2025)
· kling.ai/quickstart (Video 3.0, start/end frames) · higgsfield.ai, fal.ai, atlabs.ai, morphic.com,
scenario.com (платформы, коммерческие) · tessl.io seedance-vfx (сообщество) · arXiv 2501.09038
(Physics-IQ). Просмотрено 13.10.2026. Не прочитаны: офгайды Seedance 2.0 и Kling prompt guide
(страницы на JS), оригинал блога Replicate про Grok 1.5.
