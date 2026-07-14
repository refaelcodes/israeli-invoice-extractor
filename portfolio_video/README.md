# Сопровождающее демо-видео

Готовые ролики:

- `israeli_docs_demo_ru.mp4` — мастер;
- `israeli_docs_demo_ru_github.mp4` — компактная версия меньше 10 МБ для GitHub;
- `israeli_docs_demo_he.mp4` — мастер на иврите с мужской озвучкой;
- `israeli_docs_demo_he_github.mp4` — компактная ивритская версия для GitHub.

- 1080p, 16:9;
- русская и ивритская озвучка; в версии на иврите используется мужской голос;
- субтитры встроены в изображение и доступны отдельно в `.srt`;
- один сквозной сценарий;
- показан сохранённый реальный edge case (18/22 поля);
- приватность и один CTA вынесены в отдельные сцены.

Повторная сборка:

```powershell
python portfolio_video\build_video.py
python portfolio_video\build_video_he.py
```

Нужны `ffmpeg`, `ffprobe`, Chromium не требуется. Озвучка создаётся через `edge-tts`.
