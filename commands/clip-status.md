---
description: Сводка проекта с диска и следующий шаг — главная команда восстановления контекста.
---

Покажи состояние проекта клипа с ДИСКА, не из памяти чата.

1. Определи папку проекта: $ARGUMENTS, иначе `$env:CLIP_PROJECT`, иначе текущая папка.
2. Запусти `python "${CLAUDE_PLUGIN_ROOT}/scripts/clip_status.py" --project "<папка>"`.
3. Покажи Админу сводку как есть (кадры / клипы / дубли / вердикты) и строку «→ дальше» из вывода скрипта.
4. Предложи следующий шаг ровно по подсказке скрипта и запусти соответствующую роль
   (clip-researcher / clip-musicologist / clip-screenwriter / clip-storyboard / clip-prompt-writer /
   clip-anchors / clip-frames / clip-shoot / clip-guardian / clip-editor).

Использовать всегда после перерыва, сжатия или переполнения контекста — продолжать «по памяти» нельзя.
