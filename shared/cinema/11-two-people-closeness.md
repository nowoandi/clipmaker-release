# Близость двух людей в кадре

Повод — <проект>, 13.10.2026, план «двое на ступенях»: Админ — «сидят как будто
неродные … он её обнимает за плечо одной рукой». Разведка 13.10.2026. Метки — как в `10`:
**[подтв.]**, **[косв.]**, **[гипотеза]**.

## Главное: близость делается в кадре, а не в видео

i2v берёт позу из первого кадра. Все задокументированные исправления контактных сцен работают
через картинку, а не через текст: «prompt rewriting alone did not fix the problem» [косв.,
invideo, коммерческий]. Поэтому:

- контакт, вес и наклон — **в кадре сцены** (first frame); приёмка кадра (глаз оператора, вид
  `people`) не выпускает в видео пару, которая на кадре сидит «чужими»;
- видео-промпт пары — **микродвижение**: дыхание, ветер в волосах, медленный наезд;
- активное действие (садятся, обнимает, кладёт голову) — отдельным коротким роликом, лучше от
  кадра «до» к кадру «после» [гипотеза; функция first/last есть у Grok 1.5, Veo 3.1, Kling].

Причина поломок: у модели нет скелета и столкновений; на границе касания пиксели усредняются —
слитые руки, лишние пальцы, тела, которые не давят друг на друга [косв.].

## Дистанция — проксемика (Hall)

Интимная зона — до ~0,46 м, личная — 0,46–1,22 м, социальная — 1,2–3,7 м [подтв., Hall 1966].
«Родные» — интимная зона: зазора нет, корпуса развёрнуты друг к другу. Чем ближе камера, тем
сильнее связь зрителя с героями.

## Правила

1. **Контакт — частями тела, не словом «romantic».** `sitting shoulder to shoulder, hips and
   thighs pressed together, no gap between them`; `his right arm around her far shoulder, his hand
   curved over her upper arm`; `her hand rests on his knee`. Не писать `a romantic couple
   embracing`, `intimate`, `passionate`. [косв.]
2. **Вес и наклон.** `she leans her weight into his side`, `her head rests on his shoulder`,
   `his torso angled slightly toward her`, `their bodies sink into each other`. [гипотеза]
3. **Одна форма.** `they read as one connected silhouette`; контровой свет и тёмный фон
   сливают двоих в один силуэт. [гипотеза]
4. **Общий предмет закрывает стык тел.** Одно пальто или плед на двоих: модели не нужно рисовать
   линию касания. [гипотеза]
5. **Ветер связывает.** `a light breeze moves her hair across his shoulder` — волосы касаются
   обоих. [гипотеза]
6. **Дыхание.** `slow breathing, their shoulders rise and fall together`; синхронность двух тел в
   источниках не проверена. [гипотеза]
7. **Камера.** `locked-off, shot from behind, medium two-shot` + `very slow push-in`; руки не
   крупным планом. В 9:16 пара в полный рост на ступенях проигрывает среднему плану по пояс со
   спины. [косв.]
8. **Лица и губы.** `seen from behind, faces turned up to the sky`, `lips closed and still, no
   speech`; если у модели есть звук — `no speech, no music, ambient night wind only`. [гипотеза]
9. **Не в одном ролике подход + касание + удержание.** Разбить; в среднем 3 генерации на годный
   план. [косв.]
10. **Одежда разных тонов** — меньше слияния тканей и кожи. [косв.]

## Ошибки и обходы

| Ошибка | Обход |
|---|---|
| руки сливаются, лишние пальцы | спрятать руки за тело или пальто, средний план, короткий ролик |
| тела не касаются | контакт в кадре; «no gap» словами; общий предмет |
| позы как у манекенов | дыхание, ветер, наезд; вес глаголами lean, sink |
| подмена лиц | со спины или в профиль; короткие ролики |
| шевеление губ | лица со спины; `lips closed and still`; без речи в звуке |

## Каркас «двое под своим сердцем» (гипотеза для захода 2)

Кадр: `two people sit close on a low stone bench at the foot of a whitewashed wall at night, seen
from behind, shoulder to shoulder with no gap, his arm around her far shoulder, her head resting
on his shoulder, faces turned up to the stars; a faint chalk heart on the wall above them.`
Видео: `Locked-off camera, very slow push-in. They stay seated, leaning into each other, shoulders
rising and falling together with slow breathing. A light breeze moves her hair across his
shoulder. Nothing else moves.`

## Проверено прогоном: «Am Morgen», утро в постели, 14.10.2026 [подтв., наш прогон]

Задача Админа: она спит на подушке, на лице играют солнечные зайчики, он смотрит и убирает прядь с
её лица; близко, тепло, лёгкий намёк на интим «буквально чуть-чуть». Семь стартовых кадров
(`gpt-image-2`, 6 кр.) и пять клипов Grok i2v (27 кр.), из них три годных.

- **Кадр делает работу.** Промпт кадра (≈550 символов): поза и контакт (`sleeps on her side on a
  white linen pillow`, `a man propped on his elbow behind her, his fingertips resting near her
  temple`), один источник света с направлением (`warm low sun through a sheer curtain and tree
  leaves throws dappled flecks of light over her cheek`), «как снято» одной фразой (`Arri Alexa 35,
  85mm Cooke T2, Kodak Portra 400, soft halation, shallow depth of field`). Из трёх проб кадра
  годились все три. Видео-промпт — микродвижение и ОДНО действие.
- **Те же лица в других планах** — i2i от принятого кадра (`gpt-image-2-image-to-image` по
  `input_urls`, 6 кр.): крупный план лица и боковой план пары вышли теми же людьми.
- **Взгляд уходит в камеру.** Первый клип с рукой, убирающей прядь, на 1,0–3,5 с развернул его
  голову, и он посмотрел в объектив с приоткрытым ртом; рука взлетела с волос и упала на лоб.
  Помогло в одной пробе из двух: `his head stays still and relaxed, his eyes stay lowered on her
  face the whole time, he never looks toward the camera and his mouth stays closed` и `his hand
  stays in contact with her hair … in one smooth continuous motion, never lifting away`. Запрет на
  взгляд писать явно, а путь руки — одним непрерывным движением без отрыва. Брать две пробы.
- **Чистые планы без рук** (лицо крупно, пара лицом к лицу) вышли с первой пробы: зайчики света
  плывут по щеке, улыбка проявляется, в конце пара касается щёками без слияния лиц.
- **Лёгкая интимность** делается светом и тканью (плечи, лён, дыхание), а не позой: ни один кадр не
  пришлось править на откровенность.

Цена темы целиком: 177 кр. при трёх годных клипах (лишние пробы кадров и один брак руки).

## Источники

Hall, The Hidden Dimension (1966) — через en.wikipedia.org/wiki/Proxemics · Senses of Cinema,
«Bodies in filmic space» (2013) · invideo FAQ о контактных сценах (коммерческий) · StudioBinder,
blocking and staging · гайды Grok, Veo, Kling — см. `10`. Просмотрено 13.10.2026. Кинопримеры
(«Eternal Sunshine», «In the Mood for Love») — названия для поиска, кадры не проверены.
