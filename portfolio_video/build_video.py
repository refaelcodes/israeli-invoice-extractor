# -*- coding: utf-8 -*-
"""Собирает русское SMB-демо-видео из реальных артефактов проекта.

Выход:
  portfolio_video/israeli_docs_demo_ru.mp4
  portfolio_video/israeli_docs_demo_ru.srt
  portfolio_video/thumbnail.png

Требования: Pillow, PyMuPDF, edge-tts, ffmpeg/ffprobe в PATH.
"""
from __future__ import annotations

import asyncio
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz
import truststore
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


# edge-tts по умолчанию использует certifi. На Windows с корпоративным/локальным
# корневым сертификатом безопаснее опираться на системное хранилище доверия.
truststore.inject_into_ssl()
import edge_tts  # noqa: E402  (важен порядок после inject_into_ssl)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
AUDIO = ASSETS / "audio"
SCENES = ASSETS / "scenes"
PARTS = ASSETS / "parts"

W, H = 1920, 1080
CONTENT_BOTTOM = 900
FPS = 30

BG_TOP = (8, 22, 38)
BG_BOTTOM = (13, 52, 61)
INK = (235, 245, 244)
MUTED = (164, 188, 190)
PANEL = (244, 249, 249)
PANEL_INK = (20, 42, 48)
ACCENT = (13, 148, 136)
ACCENT_2 = (3, 105, 161)
OK = (10, 157, 99)
WARN = (217, 119, 6)
ERR = (214, 69, 69)

FONT_REG = Path("C:/Windows/Fonts/segoeui.ttf")
FONT_SEMI = Path("C:/Windows/Fonts/seguisb.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/segoeuib.ttf")
FONT_MONO = Path("C:/Windows/Fonts/consola.ttf")


@dataclass(frozen=True)
class Scene:
    slug: str
    title: str
    narration: str
    target_seconds: float


SCENE_DATA = [
    Scene(
        "01_hook",
        "Счёт → готовые данные",
        "Счёт на иврите превращается в готовые данные за секунды — без ручного переноса строк в таблицу.",
        8.0,
    ),
    Scene(
        "02_workflow",
        "Один понятный сценарий",
        "Загрузите PDF или изображение. Сервис распознаёт многостраничный документ и возвращает единый структурированный JSON.",
        11.0,
    ),
    Scene(
        "03_result",
        "Структурированный результат",
        "В одном результате — поставщик, клиент, позиции, НДС, итог и номер аллокации. Поля можно сразу передать в учётную систему или проверить вручную.",
        14.0,
    ),
    Scene(
        "04_validation",
        "Проверка без слепой веры в AI",
        "После распознавания срабатывает независимая арифметическая проверка: сумма строк, НДС и итог должны сходиться. Она работает даже без эталонного ответа.",
        13.0,
    ),
    Scene(
        "05_edge_case",
        "Edge case: ошибки видны",
        "Ошибки не прячутся. На сохранённом реальном тесте совпало восемнадцать из двадцати двух полей. Расхождения подсвечены, поэтому документ уходит на проверку, а не молча в учёт.",
        15.0,
    ),
    Scene(
        "06_privacy",
        "Данные и приватность",
        "Для демо используются только синтетические данные. Для клиентских документов предусмотрен коммерческий API-режим; ключ остаётся на бэкенде. Возможна локальная или on-premise поставка.",
        13.0,
    ),
    Scene(
        "07_cta",
        "Начнём с короткого пилота",
        "Пришлите три-пять типичных документов. Я бесплатно оценю структуру полей, риски и формат короткого пилота для вашего процесса.",
        12.0,
    ),
]


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_MONO if mono else (FONT_BOLD if bold else FONT_REG)
    return ImageFont.truetype(str(path), size=size)


def gradient_background() -> Image.Image:
    img = Image.new("RGB", (W, H), BG_TOP)
    px = img.load()
    for y in range(H):
        t = y / max(1, H - 1)
        color = tuple(round(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3))
        for x in range(W):
            px[x, y] = color
    draw = ImageDraw.Draw(img, "RGBA")
    draw.ellipse((1370, -310, 2170, 490), fill=(13, 148, 136, 34))
    draw.ellipse((-260, 570, 480, 1310), fill=(3, 105, 161, 24))
    return img


def rounded_panel(img: Image.Image, box: tuple[int, int, int, int], fill=PANEL, radius=28,
                  shadow=True, outline=None, width=2) -> None:
    x1, y1, x2, y2 = box
    if shadow:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.rounded_rectangle((x1 + 8, y1 + 12, x2 + 8, y2 + 12), radius=radius,
                             fill=(0, 0, 0, 78))
        layer = layer.filter(ImageFilter.GaussianBlur(14))
        img.paste(layer, (0, 0), layer)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrap_lines(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=fnt)[2] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fnt,
                 fill, max_width: int, spacing: int = 10, max_lines: int | None = None,
                 anchor: str | None = None) -> int:
    lines = wrap_lines(draw, text, fnt, max_width)
    if max_lines:
        lines = lines[:max_lines]
    x, y = xy
    line_h = draw.textbbox((0, 0), "Аg", font=fnt)[3] + spacing
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill, anchor=anchor)
        y += line_h
    return y


def header(img: Image.Image, scene_no: int, title: str, kicker: str) -> None:
    draw = ImageDraw.Draw(img)
    draw.text((88, 42), "ISRAELI DOCS  •  AI EXTRACTION", font=font(22, bold=True), fill=ACCENT)
    draw.text((1832, 42), f"{scene_no:02d} / {len(SCENE_DATA):02d}", font=font(20, mono=True),
              fill=MUTED, anchor="ra")
    draw.text((88, 100), title, font=font(62, bold=True), fill=INK)
    draw.text((90, 180), kicker, font=font(27), fill=MUTED)


def subtitle_band(img: Image.Image, text: str) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle((0, CONTENT_BOTTOM, W, H), fill=(4, 12, 22, 238))
    d.rectangle((0, CONTENT_BOTTOM, 14, H), fill=ACCENT + (255,))
    img.paste(overlay, (0, 0), overlay)
    draw = ImageDraw.Draw(img)
    fnt = font(37, bold=True)
    lines = wrap_lines(draw, text, fnt, 1700)
    line_h = 48
    start_y = CONTENT_BOTTOM + (H - CONTENT_BOTTOM - line_h * len(lines)) // 2 - 3
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=fnt)
        x = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, start_y), line, font=fnt, fill=(255, 255, 255))
        start_y += line_h


def paste_contain(img: Image.Image, source: Image.Image, box: tuple[int, int, int, int],
                  pad=18, background=(255, 255, 255)) -> None:
    x1, y1, x2, y2 = box
    rounded_panel(img, box, fill=background, radius=26)
    inner = (x1 + pad, y1 + pad, x2 - pad, y2 - pad)
    fitted = ImageOps.contain(source.convert("RGB"), (inner[2] - inner[0], inner[3] - inner[1]),
                              Image.Resampling.LANCZOS)
    px = inner[0] + (inner[2] - inner[0] - fitted.width) // 2
    py = inner[1] + (inner[3] - inner[1] - fitted.height) // 2
    img.paste(fitted, (px, py))


def badge(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, color=ACCENT,
          text_color=(255, 255, 255)) -> None:
    x, y = xy
    fnt = font(22, bold=True)
    bbox = draw.textbbox((0, 0), text, font=fnt)
    w = bbox[2] - bbox[0] + 34
    draw.rounded_rectangle((x, y, x + w, y + 42), radius=21, fill=color)
    draw.text((x + 17, y + 8), text, font=fnt, fill=text_color)


def load_invoice() -> tuple[Image.Image, dict]:
    png = ROOT / "01_invoice_tax" / "01_invoice_tax_1.png"
    rec = json.loads((ROOT / "01_invoice_tax" / "01_invoice_tax_1.json").read_text(encoding="utf-8"))
    return Image.open(png).convert("RGB"), rec["fields"]


def load_real_receipt() -> Image.Image:
    pdf = next((ROOT / "real_test").glob("*.pdf"))
    with fitz.open(pdf) as doc:
        pix = doc[0].get_pixmap(dpi=110, alpha=False)
        receipt = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    # В исходном реальном тесте есть персональный e-mail. Публичное видео показывает
    # сам edge case, но не должно раскрывать PII: закрываем весь customer-блок.
    draw = ImageDraw.Draw(receipt)
    x1, y1 = int(receipt.width * 0.30), int(receipt.height * 0.11)
    x2, y2 = int(receipt.width * 0.96), int(receipt.height * 0.31)
    draw.rectangle((x1, y1, x2, y2), fill=(255, 255, 255))
    small = font(max(13, round(receipt.width * 0.018)), bold=True)
    regular = font(max(12, round(receipt.width * 0.016)))
    draw.text((x1 + 10, y1 + 10), "Bill to", font=small, fill=(28, 34, 38))
    draw.text((x1 + 10, y1 + 42), "Demo Client", font=regular, fill=(28, 34, 38))
    draw.text((x1 + 10, y1 + 70), "demo@example.com", font=regular, fill=(28, 34, 38))
    draw.text((x1 + 10, y1 + 98), "PII masked for public demo", font=regular, fill=ACCENT)
    # Маскируем строку платёжного метода/последние цифры карты в истории платежей.
    px1, py1 = int(receipt.width * 0.05), int(receipt.height * 0.74)
    px2, py2 = int(receipt.width * 0.98), int(receipt.height * 0.96)
    draw.rectangle((px1, py1, px2, py2), fill=(255, 255, 255))
    draw.text((px1 + 10, py1 + 12), "Payment details masked for public demo",
              font=regular, fill=ACCENT)
    return receipt


def json_card(img: Image.Image, fields: dict, box: tuple[int, int, int, int]) -> None:
    rounded_panel(img, box, fill=(18, 31, 43), radius=24, outline=(59, 82, 94), shadow=True)
    draw = ImageDraw.Draw(img)
    x1, y1, x2, _ = box
    draw.text((x1 + 28, y1 + 24), "extracted.json", font=font(22, bold=True), fill=(104, 211, 198))
    snippets = [
        ('"doc_type"', f'"{fields["doc_type"]}"'),
        ('"seller"', f'"{fields["seller"]["name"]}"'),
        ('"subtotal"', f'{fields["subtotal"]:.2f}'),
        ('"vat_rate"', f'{fields["vat_rate"]:.2f}'),
        ('"total"', f'{fields["total"]:.2f}'),
        ('"allocation_number"', f'"{fields["allocation_number"]}"'),
    ]
    y = y1 + 78
    key_font = font(21, mono=True)
    value_font = font(21)
    for key, value in snippets:
        draw.text((x1 + 32, y), key, font=key_font, fill=(104, 178, 255))
        draw.text((x1 + 286, y), ":", font=key_font, fill=MUTED)
        draw.text((x1 + 312, y), value, font=value_font,
                  fill=(141, 220, 168) if value.startswith('"') else (225, 183, 91))
        y += 48


def scene_hook(invoice: Image.Image, fields: dict, scene: Scene) -> Image.Image:
    img = gradient_background()
    header(img, 1, scene.title, "PDF / PNG → проверяемый JSON")
    draw = ImageDraw.Draw(img)
    paste_contain(img, invoice, (870, 220, 1370, 850), pad=12)
    json_card(img, fields, (1280, 300, 1830, 710))
    draw.text((90, 300), "Минуты ручной работы", font=font(33), fill=MUTED)
    draw.text((90, 350), "заменяются одним", font=font(33), fill=MUTED)
    draw.text((90, 410), "понятным действием", font=font(48, bold=True), fill=INK)
    badge(draw, (90, 520), "ИВРИТ + RTL", ACCENT_2)
    badge(draw, (90, 580), "PDF / PNG / JPG", ACCENT)
    badge(draw, (90, 640), "СТРУКТУРНЫЙ JSON", OK)
    subtitle_band(img, scene.narration)
    return img


def scene_workflow(invoice: Image.Image, scene: Scene) -> Image.Image:
    img = gradient_background()
    header(img, 2, scene.title, "Один workflow вместо списка функций")
    draw = ImageDraw.Draw(img)
    cards = [
        (90, 280, 570, 760, "1", "Загрузить", "PDF, PNG или JPG"),
        (720, 280, 1200, 760, "2", "Извлечь", "Vision AI + JSON-схема"),
        (1350, 280, 1830, 760, "3", "Проверить", "Поля + арифметика"),
    ]
    for idx, (x1, y1, x2, y2, number, title, sub) in enumerate(cards):
        rounded_panel(img, (x1, y1, x2, y2), fill=PANEL, radius=30)
        draw.ellipse((x1 + 32, y1 + 30, x1 + 92, y1 + 90), fill=ACCENT)
        draw.text((x1 + 62, y1 + 59), number, font=font(28, bold=True), fill=(255, 255, 255), anchor="mm")
        draw.text((x1 + 34, y1 + 120), title, font=font(43, bold=True), fill=PANEL_INK)
        draw.text((x1 + 34, y1 + 178), sub, font=font(24), fill=(73, 95, 103))
        if idx == 0:
            thumb = ImageOps.contain(invoice, (300, 300), Image.Resampling.LANCZOS)
            img.paste(thumb, (x1 + (x2 - x1 - thumb.width) // 2, y1 + 235))
        elif idx == 1:
            draw.rounded_rectangle((x1 + 75, y1 + 270, x2 - 75, y1 + 385), radius=18,
                                   fill=(225, 244, 242))
            draw.text(((x1 + x2) // 2, y1 + 325), "VISION", font=font(38, bold=True), fill=ACCENT,
                      anchor="mm")
            draw.text(((x1 + x2) // 2, y1 + 410), "tool_choice → schema", font=font(21, mono=True),
                      fill=(73, 95, 103), anchor="mm")
        else:
            for j, text in enumerate(("Поля совпали", "Суммы сходятся", "Риски видны")):
                yy = y1 + 255 + j * 72
                draw.ellipse((x1 + 72, yy, x1 + 112, yy + 40), fill=OK)
                draw.text((x1 + 92, yy + 20), "✓", font=font(24, bold=True), fill=(255, 255, 255), anchor="mm")
                draw.text((x1 + 135, yy + 5), text, font=font(27, bold=True), fill=PANEL_INK)
    draw.text((645, 510), "→", font=font(70, bold=True), fill=ACCENT)
    draw.text((1275, 510), "→", font=font(70, bold=True), fill=ACCENT)
    subtitle_band(img, scene.narration)
    return img


def scene_result(invoice: Image.Image, fields: dict, scene: Scene) -> Image.Image:
    img = gradient_background()
    header(img, 3, scene.title, "Поля готовы для учётной системы или ручной сверки")
    paste_contain(img, invoice, (90, 235, 690, 860), pad=10)
    rounded_panel(img, (750, 235, 1830, 860), fill=PANEL, radius=30)
    draw = ImageDraw.Draw(img)
    labels = [
        ("Тип документа", fields["doc_type"]),
        ("Поставщик", fields["seller"]["name"]),
        ("Клиент", fields["customer"]["name"]),
        ("Позиции", f'{len(fields["line_items"])} строк'),
        ("НДС", f'{int(fields["vat_rate"] * 100)}%  •  {fields["vat_amount"]:,.2f} ₪'),
        ("Номер аллокации", str(fields["allocation_number"])),
    ]
    y = 275
    for label, value in labels:
        draw.text((800, y), label.upper(), font=font(18, bold=True), fill=(98, 119, 124))
        draw.text((800, y + 30), value, font=font(29, bold=True), fill=PANEL_INK)
        draw.line((800, y + 74, 1775, y + 74), fill=(215, 227, 228), width=2)
        y += 92
    draw.rounded_rectangle((1225, 690, 1775, 820), radius=24, fill=(221, 247, 239))
    draw.text((1260, 710), "ИТОГО", font=font(20, bold=True), fill=OK)
    draw.text((1260, 745), f'{fields["total"]:,.2f} ₪', font=font(48, bold=True), fill=(7, 106, 70))
    subtitle_band(img, scene.narration)
    return img


def scene_validation(fields: dict, scene: Scene) -> Image.Image:
    img = gradient_background()
    header(img, 4, scene.title, "Независимая арифметика поверх AI-результата")
    draw = ImageDraw.Draw(img)
    rounded_panel(img, (90, 250, 1830, 825), fill=PANEL, radius=32)
    items_sum = sum(x["line_total"] for x in fields["line_items"])
    checks = [
        ("Сумма позиций = subtotal", f'{items_sum:,.2f} = {fields["subtotal"]:,.2f} ₪'),
        ("subtotal × ставка = НДС", f'{fields["subtotal"]:,.2f} × 18% = {fields["vat_amount"]:,.2f} ₪'),
        ("subtotal + НДС = total", f'{fields["subtotal"]:,.2f} + {fields["vat_amount"]:,.2f} = {fields["total"]:,.2f} ₪'),
        ("Номер аллокации выше порога", str(fields["allocation_number"])),
    ]
    y = 285
    for label, formula in checks:
        draw.rounded_rectangle((140, y, 1780, y + 105), radius=22, fill=(226, 247, 239))
        draw.ellipse((175, y + 27, 225, y + 77), fill=OK)
        draw.text((200, y + 51), "✓", font=font(28, bold=True), fill=(255, 255, 255), anchor="mm")
        draw.text((255, y + 20), label, font=font(28, bold=True), fill=PANEL_INK)
        draw.text((255, y + 60), formula, font=font(23, mono=True), fill=(52, 92, 83))
        y += 125
    badge(draw, (140, 785), "РАБОТАЕТ БЕЗ GROUND-TRUTH", ACCENT_2)
    subtitle_band(img, scene.narration)
    return img


def scene_edge_case(receipt: Image.Image, scene: Scene) -> Image.Image:
    img = gradient_background()
    header(img, 5, scene.title, "Сохранённый реальный тест • не cherry-pick")
    paste_contain(img, receipt, (90, 240, 690, 840), pad=10)
    rounded_panel(img, (745, 240, 1830, 840), fill=PANEL, radius=30)
    draw = ImageDraw.Draw(img)
    badge(draw, (115, 260), "PII MASKED", (91, 72, 160))
    draw.text((800, 275), "81,8%", font=font(72, bold=True), fill=WARN)
    draw.text((1075, 306), "18 из 22 полей совпали", font=font(29, bold=True), fill=PANEL_INK)
    draw.text((800, 380), "ПОЛЕ", font=font(18, bold=True), fill=(98, 119, 124))
    draw.text((1160, 380), "ЭТАЛОН", font=font(18, bold=True), fill=(98, 119, 124))
    draw.text((1490, 380), "ИЗВЛЕЧЕНО", font=font(18, bold=True), fill=(98, 119, 124))
    rows = [
        ("doc_number", "SLNGUWLR-0010", "2435-5242-0413"),
        ("item[0].description", "Max plan - 5x", "+ период тарифа"),
        ("item[1].description", "Unused time…", "+ период возврата"),
        ("item[1].unit_price", "null", "-1.24"),
    ]
    y = 420
    for path, truth, pred in rows:
        draw.rounded_rectangle((790, y, 1785, y + 78), radius=14, fill=(253, 236, 236))
        draw.text((815, y + 24), path, font=font(18, mono=True), fill=(114, 55, 55))
        draw.text((1160, y + 22), truth, font=font(20), fill=PANEL_INK)
        draw.text((1490, y + 22), pred, font=font(20), fill=ERR)
        y += 92
    draw.rounded_rectangle((790, 795, 1785, 830), radius=15, fill=(255, 244, 219))
    draw.text((1288, 812), "⚠ Расхождения видны до передачи в учёт", font=font(20, bold=True),
              fill=(144, 84, 8), anchor="mm")
    subtitle_band(img, scene.narration)
    return img


def scene_privacy(scene: Scene) -> Image.Image:
    img = gradient_background()
    header(img, 6, scene.title, "Механизмы показаны явно — без расплывчатых обещаний")
    draw = ImageDraw.Draw(img)
    badge(draw, (90, 238), "ДЕМО: ТОЛЬКО СИНТЕТИЧЕСКИЕ ДАННЫЕ", OK)
    cards = [
        (90, 320, 620, 740, "API", "Для реальных клиентов", ACCENT,
         ["Коммерческий режим", "Ключ на бэкенде", "DPA / законное основание"]),
        (695, 320, 1225, 740, "SDK", "Для разработки", ACCENT_2,
         ["Личная подписка", "Тестирование", "Не для чужих документов"]),
        (1300, 320, 1830, 740, "MOCK", "Офлайн-проверка UI", (91, 72, 160),
         ["Без сети", "Без ключа", "Проверка структуры запроса"]),
    ]
    for x1, y1, x2, y2, mode, sub, color, points in cards:
        rounded_panel(img, (x1, y1, x2, y2), fill=PANEL, radius=28)
        draw.rounded_rectangle((x1 + 30, y1 + 28, x1 + 150, y1 + 82), radius=20, fill=color)
        draw.text((x1 + 90, y1 + 55), mode, font=font(25, bold=True), fill=(255, 255, 255), anchor="mm")
        draw.text((x1 + 30, y1 + 112), sub, font=font(30, bold=True), fill=PANEL_INK)
        yy = y1 + 190
        for point in points:
            draw.ellipse((x1 + 34, yy + 3, x1 + 64, yy + 33), fill=color)
            draw.text((x1 + 49, yy + 18), "✓", font=font(17, bold=True), fill=(255, 255, 255), anchor="mm")
            draw.text((x1 + 82, yy), point, font=font(23), fill=(55, 78, 84))
            yy += 66
    draw.rounded_rectangle((310, 780, 1610, 842), radius=28, fill=(218, 239, 247))
    draw.text((960, 810), "Опция поставки: локально / on-premise", font=font(27, bold=True),
              fill=(3, 87, 132), anchor="mm")
    subtitle_band(img, scene.narration)
    return img


def scene_cta(scene: Scene) -> Image.Image:
    img = gradient_background()
    header(img, 7, scene.title, "Один следующий шаг — без длинного discovery")
    draw = ImageDraw.Draw(img)
    draw.text((90, 290), "Пришлите", font=font(42), fill=MUTED)
    draw.text((90, 348), "3–5 типичных документов", font=font(67, bold=True), fill=INK)
    draw.text((90, 450), "В ответ вы получите:", font=font(30, bold=True), fill=ACCENT)
    points = ["карту нужных полей", "оценку рисков и качества", "формат короткого пилота"]
    y = 515
    for i, point in enumerate(points, 1):
        draw.ellipse((100, y, 152, y + 52), fill=OK)
        draw.text((126, y + 26), str(i), font=font(24, bold=True), fill=(255, 255, 255), anchor="mm")
        draw.text((180, y + 4), point, font=font(34, bold=True), fill=INK)
        y += 78
    rounded_panel(img, (1120, 275, 1810, 760), fill=PANEL, radius=34)
    draw.text((1465, 350), "ГОТОВЫ", font=font(25, bold=True), fill=ACCENT, anchor="mm")
    draw.text((1465, 420), "проверить", font=font(48, bold=True), fill=PANEL_INK, anchor="mm")
    draw.text((1465, 480), "ваш процесс?", font=font(48, bold=True), fill=PANEL_INK, anchor="mm")
    draw.rounded_rectangle((1210, 585, 1720, 670), radius=38, fill=ACCENT)
    draw.text((1465, 626), "Ответьте сообщением →", font=font(31, bold=True), fill=(255, 255, 255), anchor="mm")
    subtitle_band(img, scene.narration)
    return img


def make_slides() -> list[Path]:
    invoice, fields = load_invoice()
    receipt = load_real_receipt()
    builders = [
        lambda s: scene_hook(invoice, fields, s),
        lambda s: scene_workflow(invoice, s),
        lambda s: scene_result(invoice, fields, s),
        lambda s: scene_validation(fields, s),
        lambda s: scene_edge_case(receipt, s),
        scene_privacy,
        scene_cta,
    ]
    paths = []
    for scene, builder in zip(SCENE_DATA, builders):
        path = SCENES / f"{scene.slug}.png"
        builder(scene).save(path, optimize=True)
        paths.append(path)
    shutil.copy2(paths[0], OUT / "thumbnail.png")
    return paths


async def make_audio() -> list[Path]:
    paths = []
    for scene in SCENE_DATA:
        path = AUDIO / f"{scene.slug}.mp3"
        if not path.exists() or path.stat().st_size < 1000:
            print(f"Озвучка: {scene.slug}")
            communicate = edge_tts.Communicate(scene.narration, voice="ru-RU-SvetlanaNeural",
                                                rate="+4%", pitch="-2Hz", volume="+0%")
            await communicate.save(str(path))
        paths.append(path)
    return paths


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def duration(path: Path, ffprobe: str) -> float:
    out = subprocess.check_output([
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ], text=True).strip()
    return float(out)


def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_video(slides: list[Path], audios: list[Path]) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg/ffprobe не найдены в PATH")

    scene_durations = [max(scene.target_seconds, duration(audio, ffprobe) + 1.0)
                       for scene, audio in zip(SCENE_DATA, audios)]
    part_paths = []
    for scene, slide, audio, seconds in zip(SCENE_DATA, slides, audios, scene_durations):
        part = PARTS / f"{scene.slug}.mp4"
        frames = math.ceil(seconds * FPS)
        fade_out = max(0.0, seconds - 0.45)
        video_filter = (
            f"[0:v]scale={W}:{H},"
            f"zoompan=z='min(zoom+0.00012,1.018)':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
            f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out:.3f}:d=0.35,format=yuv420p[v];"
            f"[1:a]afade=t=in:st=0:d=0.15,afade=t=out:st={max(0.0, seconds - 0.4):.3f}:d=0.3,"
            f"apad=whole_dur={seconds:.3f}[a]"
        )
        run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-i", str(slide), "-i", str(audio),
            "-filter_complex", video_filter,
            "-map", "[v]", "-map", "[a]", "-t", f"{seconds:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(part),
        ])
        part_paths.append(part)

    concat_file = ASSETS / "concat.txt"
    concat_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in part_paths), encoding="utf-8")
    silent_video = ASSETS / "video_voice_only.mp4"
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(concat_file),
         "-c", "copy", "-movflags", "+faststart", str(silent_video)])

    final = OUT / "israeli_docs_demo_ru.mp4"
    total = sum(scene_durations)
    run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(silent_video),
        "-f", "lavfi", "-i", f"sine=frequency=196:sample_rate=48000:duration={total:.3f}",
        "-filter_complex",
        "[1:a]volume=0.012[bed];[0:a][bed]amix=inputs=2:duration=first:dropout_transition=2,"
        "loudnorm=I=-16:TP=-1.5:LRA=11[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(final),
    ])

    srt_lines = []
    cursor = 0.0
    for idx, (scene, seconds) in enumerate(zip(SCENE_DATA, scene_durations), 1):
        srt_lines.extend([
            str(idx),
            f"{srt_time(cursor + 0.15)} --> {srt_time(cursor + seconds - 0.2)}",
            scene.narration,
            "",
        ])
        cursor += seconds
    (OUT / "israeli_docs_demo_ru.srt").write_text("\n".join(srt_lines), encoding="utf-8")

    # Компактная версия для прямой загрузки в GitHub (лимит бесплатного аккаунта — 10 МБ).
    github = OUT / "israeli_docs_demo_ru_github.mp4"
    run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(final),
        "-c:v", "libx264", "-preset", "slow", "-crf", "25",
        "-maxrate", "650k", "-bufsize", "1300k",
        "-c:a", "aac", "-b:a", "96k", "-ar", "48000",
        "-movflags", "+faststart", str(github),
    ])
    return final


def main() -> None:
    for directory in (ASSETS, AUDIO, SCENES, PARTS):
        directory.mkdir(parents=True, exist_ok=True)
    print("Рендер сцен…")
    slides = make_slides()
    audios = asyncio.run(make_audio())
    print("Сборка видео…")
    final = make_video(slides, audios)
    print(f"Готово: {final}")


if __name__ == "__main__":
    main()
