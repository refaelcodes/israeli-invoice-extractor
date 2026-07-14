# -*- coding: utf-8 -*-
"""בונה גרסה עברית RTL עם קריינות גברית.

Outputs:
  israeli_docs_demo_he.mp4
  israeli_docs_demo_he_github.mp4
  israeli_docs_demo_he.srt
  thumbnail_he.png
"""
from __future__ import annotations

import asyncio
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageOps

import build_video as base
import edge_tts  # base כבר חיבר את מאגר האישורים של Windows


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = base.ROOT
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets_he"
AUDIO = ASSETS / "audio"
SCENES = ASSETS / "scenes"
PARTS = ASSETS / "parts"

W, H, FPS = base.W, base.H, base.FPS
CONTENT_BOTTOM = base.CONTENT_BOTTOM
INK, MUTED, PANEL, PANEL_INK = base.INK, base.MUTED, base.PANEL, base.PANEL_INK
ACCENT, ACCENT_2, OK, WARN, ERR = base.ACCENT, base.ACCENT_2, base.OK, base.WARN, base.ERR


@dataclass(frozen=True)
class Scene:
    slug: str
    title: str
    narration: str
    target_seconds: float


SCENE_DATA = [
    Scene("01_hook", "מחשבונית לנתונים מוכנים",
          "חשבונית בעברית הופכת לנתונים מובנים בתוך שניות — בלי להעתיק ידנית שורות לטבלה.", 8.0),
    Scene("02_workflow", "תהליך אחד ברור",
          "מעלים קובץ PDF או תמונה. השירות מזהה גם מסמך רב־עמודי ומחזיר קובץ JSON מובנה אחד.", 11.0),
    Scene("03_result", "תוצאה מובנית",
          "בתוצאה אחת מקבלים ספק, לקוח, שורות חיוב, מע״מ, סכום סופי ומספר הקצאה. אפשר להעביר את השדות למערכת הנהלת החשבונות או לבדוק אותם ידנית.", 14.0),
    Scene("04_validation", "בדיקה — לא אמונה עיוורת ב-AI",
          "אחרי החילוץ מופעלת בדיקה חשבונאית עצמאית: סכום השורות, המע״מ והסכום הסופי חייבים להתאים. הבדיקה פועלת גם בלי נתוני אמת להשוואה.", 13.0),
    Scene("05_edge_case", "מקרה קצה: רואים את הטעויות",
          "טעויות לא מוסתרות. בבדיקה אמיתית שנשמרה, שמונה עשר מתוך עשרים ושניים שדות תאמו. ההבדלים מסומנים, ולכן המסמך עובר לבדיקה במקום להיכנס בשקט למערכת.", 15.0),
    Scene("06_privacy", "נתונים ופרטיות",
          "הדמו משתמש רק בנתונים סינתטיים. למסמכי לקוחות יש מצב API מסחרי, והמפתח נשאר בצד השרת. אפשר גם לספק את המערכת בהתקנה מקומית או בתוך הארגון.", 13.0),
    Scene("07_cta", "מתחילים בפיילוט קצר",
          "שלחו שלושה עד חמישה מסמכים טיפוסיים. אעריך ללא עלות את מבנה השדות, הסיכונים והמתכונת לפיילוט קצר עבור התהליך שלכם.", 12.0),
]


def rtl(text: str) -> str:
    return get_display(str(text), base_dir="R")


def draw_rtl(draw: ImageDraw.ImageDraw, xy, text: str, fnt, fill, anchor="ra") -> None:
    draw.text(xy, rtl(text), font=fnt, fill=fill, anchor=anchor)


def wrap_rtl(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), rtl(candidate), font=fnt)[2] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_wrapped_rtl(draw: ImageDraw.ImageDraw, right_x: int, y: int, text: str, fnt,
                     fill, max_width: int, spacing: int = 10) -> int:
    line_h = draw.textbbox((0, 0), "אבג", font=fnt)[3] + spacing
    for line in wrap_rtl(draw, text, fnt, max_width):
        draw_rtl(draw, (right_x, y), line, fnt, fill)
        y += line_h
    return y


def header(img: Image.Image, scene_no: int, title: str, kicker: str) -> None:
    draw = ImageDraw.Draw(img)
    draw.text((1832, 42), "ISRAELI DOCS  •  AI EXTRACTION", font=base.font(22, bold=True),
              fill=ACCENT, anchor="ra")
    draw.text((88, 42), f"{scene_no:02d} / {len(SCENE_DATA):02d}", font=base.font(20, mono=True),
              fill=MUTED)
    draw_rtl(draw, (1832, 100), title, base.font(62, bold=True), INK)
    draw_rtl(draw, (1830, 180), kicker, base.font(27), MUTED)


def subtitle_band(img: Image.Image, text: str) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle((0, CONTENT_BOTTOM, W, H), fill=(4, 12, 22, 238))
    d.rectangle((W - 14, CONTENT_BOTTOM, W, H), fill=ACCENT + (255,))
    img.paste(overlay, (0, 0), overlay)
    draw = ImageDraw.Draw(img)
    fnt = base.font(38, bold=True)
    lines = wrap_rtl(draw, text, fnt, 1700)
    line_h = 49
    y = CONTENT_BOTTOM + (H - CONTENT_BOTTOM - line_h * len(lines)) // 2 - 3
    for line in lines:
        draw_rtl(draw, (W // 2, y), line, fnt, (255, 255, 255), anchor="ma")
        y += line_h


def badge(draw: ImageDraw.ImageDraw, right_x: int, y: int, text: str, color=ACCENT) -> None:
    fnt = base.font(22, bold=True)
    visual = rtl(text)
    bbox = draw.textbbox((0, 0), visual, font=fnt)
    width = bbox[2] - bbox[0] + 38
    draw.rounded_rectangle((right_x - width, y, right_x, y + 44), radius=22, fill=color)
    draw.text((right_x - 18, y + 8), visual, font=fnt, fill=(255, 255, 255), anchor="ra")


def scene_hook(invoice: Image.Image, fields: dict, scene: Scene) -> Image.Image:
    img = base.gradient_background()
    header(img, 1, scene.title, "PDF / PNG  ←  JSON שניתן לאמת")
    draw = ImageDraw.Draw(img)
    base.paste_contain(img, invoice, (550, 220, 1050, 850), pad=12)
    base.rounded_panel(img, (90, 300, 650, 710), fill=(18, 31, 43), radius=24,
                       outline=(59, 82, 94), shadow=True)
    draw.text((118, 326), "extracted.json", font=base.font(22, bold=True), fill=(104, 211, 198))
    values = [
        ('"doc_type"', fields["doc_type"]),
        ('"seller"', fields["seller"]["name"]),
        ('"subtotal"', f'{fields["subtotal"]:.2f}'),
        ('"vat_rate"', f'{fields["vat_rate"]:.2f}'),
        ('"total"', f'{fields["total"]:.2f}'),
        ('"allocation_number"', str(fields["allocation_number"])),
    ]
    y = 382
    for key, value in values:
        draw.text((118, y), key, font=base.font(20, mono=True), fill=(104, 178, 255))
        if any("\u0590" <= ch <= "\u05ff" for ch in value):
            draw_rtl(draw, (620, y), value, base.font(21), (141, 220, 168))
        else:
            draw.text((620, y), value, font=base.font(21), fill=(225, 183, 91), anchor="ra")
        y += 48
    draw_rtl(draw, (1830, 305), "דקות של עבודה ידנית", base.font(34), MUTED)
    draw_rtl(draw, (1830, 365), "מוחלפות בפעולה אחת", base.font(34), MUTED)
    draw_rtl(draw, (1830, 430), "פשוטה וברורה", base.font(50, bold=True), INK)
    badge(draw, 1830, 535, "עברית + RTL", ACCENT_2)
    badge(draw, 1830, 595, "PDF / PNG / JPG", ACCENT)
    badge(draw, 1830, 655, "JSON מובנה", OK)
    subtitle_band(img, scene.narration)
    return img


def scene_workflow(invoice: Image.Image, scene: Scene) -> Image.Image:
    img = base.gradient_background()
    header(img, 2, scene.title, "תהליך אחד מקצה לקצה — במקום רשימת תכונות")
    draw = ImageDraw.Draw(img)
    cards = [
        (1350, 280, 1830, 760, "1", "מעלים", "PDF, PNG או JPG"),
        (720, 280, 1200, 760, "2", "מחלצים", "Vision AI + סכמת JSON"),
        (90, 280, 570, 760, "3", "בודקים", "שדות + חשבון"),
    ]
    for idx, (x1, y1, x2, y2, number, title, sub) in enumerate(cards):
        base.rounded_panel(img, (x1, y1, x2, y2), fill=PANEL, radius=30)
        draw.ellipse((x2 - 92, y1 + 30, x2 - 32, y1 + 90), fill=ACCENT)
        draw.text((x2 - 62, y1 + 59), number, font=base.font(28, bold=True),
                  fill=(255, 255, 255), anchor="mm")
        draw_rtl(draw, (x2 - 34, y1 + 120), title, base.font(43, bold=True), PANEL_INK)
        draw_rtl(draw, (x2 - 34, y1 + 180), sub, base.font(24), (73, 95, 103))
        if idx == 0:
            thumb = ImageOps.contain(invoice, (300, 300), Image.Resampling.LANCZOS)
            img.paste(thumb, (x1 + (x2 - x1 - thumb.width) // 2, y1 + 235))
        elif idx == 1:
            draw.rounded_rectangle((x1 + 75, y1 + 270, x2 - 75, y1 + 385), radius=18,
                                   fill=(225, 244, 242))
            draw.text(((x1 + x2) // 2, y1 + 325), "VISION", font=base.font(38, bold=True),
                      fill=ACCENT, anchor="mm")
            draw.text(((x1 + x2) // 2, y1 + 410), "tool_choice → schema",
                      font=base.font(21, mono=True), fill=(73, 95, 103), anchor="mm")
        else:
            for j, text in enumerate(("השדות תואמים", "הסכומים מסתדרים", "הסיכונים גלויים")):
                yy = y1 + 255 + j * 72
                draw.ellipse((x2 - 112, yy, x2 - 72, yy + 40), fill=OK)
                draw.text((x2 - 92, yy + 20), "✓", font=base.font(24, bold=True),
                          fill=(255, 255, 255), anchor="mm")
                draw_rtl(draw, (x2 - 135, yy + 5), text, base.font(27, bold=True), PANEL_INK)
    draw.text((1275, 510), "←", font=base.font(70, bold=True), fill=ACCENT, anchor="mm")
    draw.text((645, 510), "←", font=base.font(70, bold=True), fill=ACCENT, anchor="mm")
    subtitle_band(img, scene.narration)
    return img


def scene_result(invoice: Image.Image, fields: dict, scene: Scene) -> Image.Image:
    img = base.gradient_background()
    header(img, 3, scene.title, "מוכן למערכת הנהלת החשבונות או לבדיקה ידנית")
    base.paste_contain(img, invoice, (1230, 235, 1830, 860), pad=10)
    base.rounded_panel(img, (90, 235, 1170, 860), fill=PANEL, radius=30)
    draw = ImageDraw.Draw(img)
    labels = [
        ("סוג המסמך", fields["doc_type"]),
        ("ספק", fields["seller"]["name"]),
        ("לקוח", fields["customer"]["name"]),
        ("שורות", f'{len(fields["line_items"])} שורות'),
        ("מע״מ", f'{int(fields["vat_rate"] * 100)}%  •  {fields["vat_amount"]:,.2f} ₪'),
        ("מספר הקצאה", str(fields["allocation_number"])),
    ]
    y = 275
    for label, value in labels:
        draw_rtl(draw, (1120, y), label, base.font(18, bold=True), (98, 119, 124))
        draw_rtl(draw, (1120, y + 30), value, base.font(29, bold=True), PANEL_INK)
        draw.line((140, y + 74, 1120, y + 74), fill=(215, 227, 228), width=2)
        y += 92
    draw.rounded_rectangle((170, 690, 720, 820), radius=24, fill=(221, 247, 239))
    draw_rtl(draw, (680, 710), "סכום סופי", base.font(20, bold=True), OK)
    draw.text((680, 752), f'{fields["total"]:,.2f} ₪', font=base.font(48, bold=True),
              fill=(7, 106, 70), anchor="ra")
    subtitle_band(img, scene.narration)
    return img


def scene_validation(fields: dict, scene: Scene) -> Image.Image:
    img = base.gradient_background()
    header(img, 4, scene.title, "בדיקה חשבונאית עצמאית מעל תוצאת החילוץ")
    draw = ImageDraw.Draw(img)
    base.rounded_panel(img, (90, 250, 1830, 825), fill=PANEL, radius=32)
    items_sum = sum(x["line_total"] for x in fields["line_items"])
    checks = [
        ("סכום השורות שווה לסכום הביניים", f'{items_sum:,.2f} = {fields["subtotal"]:,.2f} ₪'),
        ("סכום ביניים כפול שיעור מע״מ", f'{fields["subtotal"]:,.2f} × 18% = {fields["vat_amount"]:,.2f} ₪'),
        ("סכום ביניים ועוד מע״מ שווה לסכום הסופי", f'{fields["subtotal"]:,.2f} + {fields["vat_amount"]:,.2f} = {fields["total"]:,.2f} ₪'),
        ("מספר הקצאה קיים מעל הסף", str(fields["allocation_number"])),
    ]
    y = 285
    for label, formula in checks:
        draw.rounded_rectangle((140, y, 1780, y + 105), radius=22, fill=(226, 247, 239))
        draw.ellipse((1685, y + 27, 1735, y + 77), fill=OK)
        draw.text((1710, y + 51), "✓", font=base.font(28, bold=True), fill=(255, 255, 255), anchor="mm")
        draw_rtl(draw, (1655, y + 20), label, base.font(28, bold=True), PANEL_INK)
        draw.text((1655, y + 62), formula, font=base.font(23, mono=True), fill=(52, 92, 83), anchor="ra")
        y += 125
    badge(draw, 1780, 785, "עובד גם ללא נתוני אמת", ACCENT_2)
    subtitle_band(img, scene.narration)
    return img


def scene_edge(receipt: Image.Image, scene: Scene) -> Image.Image:
    img = base.gradient_background()
    header(img, 5, scene.title, "בדיקה אמיתית שנשמרה • לא cherry-pick")
    base.paste_contain(img, receipt, (1230, 240, 1830, 840), pad=10)
    base.rounded_panel(img, (90, 240, 1175, 840), fill=PANEL, radius=30)
    draw = ImageDraw.Draw(img)
    badge(draw, 1805, 260, "פרטים אישיים הוסתרו", (91, 72, 160))
    draw.text((1120, 275), "81.8%", font=base.font(72, bold=True), fill=WARN, anchor="ra")
    draw_rtl(draw, (800, 305), "18 מתוך 22 שדות תאמו", base.font(29, bold=True), PANEL_INK)
    draw_rtl(draw, (1080, 380), "שדה", base.font(18, bold=True), (98, 119, 124))
    draw_rtl(draw, (720, 380), "נתון אמת", base.font(18, bold=True), (98, 119, 124))
    draw_rtl(draw, (350, 380), "חולץ", base.font(18, bold=True), (98, 119, 124))
    rows = [
        ("doc_number", "SLNGUWLR-0010", "2435-5242-0413"),
        ("item[0].description", "Max plan - 5x", "+ תקופת החיוב"),
        ("item[1].description", "Unused time…", "+ תקופת הזיכוי"),
        ("item[1].unit_price", "null", "-1.24"),
    ]
    y = 420
    for path, truth, pred in rows:
        draw.rounded_rectangle((135, y, 1135, y + 78), radius=14, fill=(253, 236, 236))
        draw.text((1100, y + 25), path, font=base.font(18, mono=True), fill=(114, 55, 55), anchor="ra")
        draw.text((720, y + 23), truth, font=base.font(20), fill=PANEL_INK, anchor="ra")
        if any("\u0590" <= ch <= "\u05ff" for ch in pred):
            draw_rtl(draw, (350, y + 23), pred, base.font(20), ERR)
        else:
            draw.text((350, y + 23), pred, font=base.font(20), fill=ERR, anchor="ra")
        y += 92
    draw.rounded_rectangle((135, 795, 1135, 830), radius=15, fill=(255, 244, 219))
    draw_rtl(draw, (635, 812), "ההבדלים גלויים לפני העברה למערכת", base.font(20, bold=True),
             (144, 84, 8), anchor="mm")
    subtitle_band(img, scene.narration)
    return img


def scene_privacy(scene: Scene) -> Image.Image:
    img = base.gradient_background()
    header(img, 6, scene.title, "מנגנונים ברורים — בלי הבטחות מעורפלות")
    draw = ImageDraw.Draw(img)
    badge(draw, 1830, 238, "בדמו יש רק נתונים סינתטיים", OK)
    cards = [
        (1300, 320, 1830, 740, "API", "למסמכי לקוחות", ACCENT,
         ["מצב מסחרי", "המפתח בצד השרת", "DPA ובסיס חוקי"]),
        (695, 320, 1225, 740, "SDK", "לפיתוח ובדיקות", ACCENT_2,
         ["מנוי אישי", "בדיקות פיתוח", "לא למסמכים של צד שלישי"]),
        (90, 320, 620, 740, "MOCK", "בדיקת ממשק אופליין", (91, 72, 160),
         ["ללא רשת", "ללא מפתח", "בדיקת מבנה הבקשה"]),
    ]
    for x1, y1, x2, y2, mode, sub, color, points in cards:
        base.rounded_panel(img, (x1, y1, x2, y2), fill=PANEL, radius=28)
        draw.rounded_rectangle((x2 - 150, y1 + 28, x2 - 30, y1 + 82), radius=20, fill=color)
        draw.text((x2 - 90, y1 + 55), mode, font=base.font(25, bold=True),
                  fill=(255, 255, 255), anchor="mm")
        draw_rtl(draw, (x2 - 30, y1 + 112), sub, base.font(30, bold=True), PANEL_INK)
        yy = y1 + 190
        for point in points:
            draw.ellipse((x2 - 64, yy + 3, x2 - 34, yy + 33), fill=color)
            draw.text((x2 - 49, yy + 18), "✓", font=base.font(17, bold=True),
                      fill=(255, 255, 255), anchor="mm")
            draw_rtl(draw, (x2 - 82, yy), point, base.font(23), (55, 78, 84))
            yy += 66
    draw.rounded_rectangle((310, 780, 1610, 842), radius=28, fill=(218, 239, 247))
    draw_rtl(draw, (960, 810), "אפשרות התקנה: מקומית / בתוך הארגון", base.font(27, bold=True),
             (3, 87, 132), anchor="mm")
    subtitle_band(img, scene.narration)
    return img


def scene_cta(scene: Scene) -> Image.Image:
    img = base.gradient_background()
    header(img, 7, scene.title, "צעד אחד ברור — בלי תהליך discovery ארוך")
    draw = ImageDraw.Draw(img)
    draw_rtl(draw, (1830, 290), "שלחו", base.font(42), MUTED)
    draw_rtl(draw, (1830, 350), "3–5 מסמכים טיפוסיים", base.font(67, bold=True), INK)
    draw_rtl(draw, (1830, 455), "ותקבלו:", base.font(30, bold=True), ACCENT)
    points = ["מפת שדות נדרשים", "הערכת איכות וסיכונים", "מתכונת לפיילוט קצר"]
    y = 515
    for i, point in enumerate(points, 1):
        draw.ellipse((1770, y, 1822, y + 52), fill=OK)
        draw.text((1796, y + 26), str(i), font=base.font(24, bold=True), fill=(255, 255, 255), anchor="mm")
        draw_rtl(draw, (1738, y + 4), point, base.font(34, bold=True), INK)
        y += 78
    base.rounded_panel(img, (90, 275, 780, 760), fill=PANEL, radius=34)
    draw_rtl(draw, (435, 350), "מוכנים", base.font(25, bold=True), ACCENT, anchor="mm")
    draw_rtl(draw, (435, 420), "לבדוק", base.font(48, bold=True), PANEL_INK, anchor="mm")
    draw_rtl(draw, (435, 480), "את התהליך שלכם?", base.font(48, bold=True), PANEL_INK, anchor="mm")
    draw.rounded_rectangle((180, 585, 690, 670), radius=38, fill=ACCENT)
    draw_rtl(draw, (435, 626), "שלחו הודעה ←", base.font(31, bold=True), (255, 255, 255), anchor="mm")
    subtitle_band(img, scene.narration)
    return img


def make_slides() -> list[Path]:
    invoice, fields = base.load_invoice()
    receipt = base.load_real_receipt()
    builders = [
        lambda s: scene_hook(invoice, fields, s),
        lambda s: scene_workflow(invoice, s),
        lambda s: scene_result(invoice, fields, s),
        lambda s: scene_validation(fields, s),
        lambda s: scene_edge(receipt, s),
        scene_privacy,
        scene_cta,
    ]
    paths = []
    for scene, builder in zip(SCENE_DATA, builders):
        path = SCENES / f"{scene.slug}.png"
        builder(scene).save(path, optimize=True)
        paths.append(path)
    shutil.copy2(paths[0], OUT / "thumbnail_he.png")
    return paths


async def make_audio() -> list[Path]:
    paths = []
    for scene in SCENE_DATA:
        path = AUDIO / f"{scene.slug}.mp3"
        if not path.exists() or path.stat().st_size < 1000:
            print(f"קריינות: {scene.slug}")
            voice = edge_tts.Communicate(scene.narration, voice="he-IL-AvriNeural",
                                         rate="+2%", pitch="-2Hz", volume="+0%")
            await voice.save(str(path))
        paths.append(path)
    return paths


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def duration(path: Path, ffprobe: str) -> float:
    result = subprocess.check_output([
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ], text=True).strip()
    return float(result)


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
        raise RuntimeError("ffmpeg/ffprobe missing")
    durations = [max(scene.target_seconds, duration(audio, ffprobe) + 1.0)
                 for scene, audio in zip(SCENE_DATA, audios)]
    parts = []
    for scene, slide, audio, seconds in zip(SCENE_DATA, slides, audios, durations):
        part = PARTS / f"{scene.slug}.mp4"
        frames = math.ceil(seconds * FPS)
        vf = (
            f"[0:v]scale={W}:{H},zoompan=z='min(zoom+0.00012,1.018)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
            f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(0.0, seconds-0.45):.3f}:d=0.35,"
            f"format=yuv420p[v];[1:a]afade=t=in:st=0:d=0.15,"
            f"afade=t=out:st={max(0.0, seconds-0.4):.3f}:d=0.3,apad=whole_dur={seconds:.3f}[a]"
        )
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(slide),
             "-i", str(audio), "-filter_complex", vf, "-map", "[v]", "-map", "[a]",
             "-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(part)])
        parts.append(part)

    concat = ASSETS / "concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    voice_video = ASSETS / "video_voice_only.mp4"
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(voice_video)])

    total = sum(durations)
    final = OUT / "israeli_docs_demo_he.mp4"
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(voice_video),
         "-f", "lavfi", "-i", f"sine=frequency=196:sample_rate=48000:duration={total:.3f}",
         "-filter_complex", "[1:a]volume=0.012[bed];[0:a][bed]amix=inputs=2:duration=first:"
         "dropout_transition=2,loudnorm=I=-16:TP=-1.5:LRA=11[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-movflags", "+faststart", str(final)])

    srt = []
    cursor = 0.0
    for idx, (scene, seconds) in enumerate(zip(SCENE_DATA, durations), 1):
        srt.extend([str(idx), f"{srt_time(cursor+0.15)} --> {srt_time(cursor+seconds-0.2)}",
                    scene.narration, ""])
        cursor += seconds
    (OUT / "israeli_docs_demo_he.srt").write_text("\n".join(srt), encoding="utf-8")

    github = OUT / "israeli_docs_demo_he_github.mp4"
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(final),
         "-c:v", "libx264", "-preset", "slow", "-crf", "25", "-maxrate", "650k",
         "-bufsize", "1300k", "-c:a", "aac", "-b:a", "96k", "-ar", "48000",
         "-movflags", "+faststart", str(github)])
    return final


def main() -> None:
    for directory in (ASSETS, AUDIO, SCENES, PARTS):
        directory.mkdir(parents=True, exist_ok=True)
    print("יצירת סצנות RTL…")
    slides = make_slides()
    audios = asyncio.run(make_audio())
    print("עריכת וידאו…")
    final = make_video(slides, audios)
    print(f"מוכן: {final}")


if __name__ == "__main__":
    main()
