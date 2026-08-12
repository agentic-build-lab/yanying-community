import io
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import uuid4

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

MAX_SOURCE_BYTES = 30 * 1024 * 1024
ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost"}
SUPPORTED_STYLES = {
    "studio",
    "impact",
    "knowledge",
    "variety",
    "question",
    "quote",
    "clean",
}


class CoverDesignError(ValueError):
    pass


def create_designed_cover(
    *,
    image_source: str,
    title_line_1: str,
    title_line_2: str,
    style: str,
    target_format: str,
    accent_color: str,
    media_root: Path,
) -> dict[str, object]:
    width, height = _parse_target_format(target_format)
    line_1 = _clean_title(title_line_1)
    line_2 = _clean_title(title_line_2)
    if not line_1 and not line_2:
        raise CoverDesignError("请至少输入一行封面文字。")

    source = _load_image(image_source, media_root)
    canvas = ImageOps.fit(
        source.convert("RGB"),
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.42),
    )
    canvas = ImageEnhance.Contrast(canvas).enhance(1.04)
    canvas = ImageEnhance.Color(canvas).enhance(0.96)
    accent = _parse_color(accent_color, (255, 193, 7))
    selected_style = style if style in SUPPORTED_STYLES else "studio"

    if selected_style == "impact":
        _draw_impact_cover(canvas, line_1, line_2, accent)
    elif selected_style == "knowledge":
        _draw_knowledge_cover(canvas, line_1, line_2, accent)
    elif selected_style == "variety":
        _draw_variety_cover(canvas, line_1, line_2, accent)
    elif selected_style == "question":
        _draw_question_cover(canvas, line_1, line_2, accent)
    elif selected_style == "quote":
        _draw_quote_cover(canvas, line_1, line_2, accent)
    elif selected_style == "clean":
        _draw_clean_cover(canvas, line_1, line_2, accent)
    else:
        _draw_studio_cover(canvas, line_1, line_2, accent)

    cover_id = f"designed_cover_{uuid4().hex[:12]}"
    relative_path = Path("library") / "designed_covers" / f"{cover_id}.jpg"
    output_path = media_root / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=94, optimize=True, progressive=True)
    return {
        "id": cover_id,
        "image_url": f"/media/{relative_path.as_posix()}",
        "image_path": str(output_path),
        "style": selected_style,
        "target_format": f"{width}x{height}",
    }


def _draw_studio_cover(
    canvas: Image.Image,
    line_1: str,
    line_2: str,
    accent: tuple[int, int, int],
) -> None:
    width, height = canvas.size
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    gradient_top = int(height * 0.48)
    for y in range(gradient_top, height):
        progress = (y - gradient_top) / max(height - gradient_top, 1)
        alpha = min(255, round(55 + 220 * (progress**0.7)))
        draw.line((0, y, width, y), fill=(8, 12, 18, alpha))

    left = round(width * 0.075)
    baseline = round(height * 0.64)
    draw.rounded_rectangle(
        (
            left,
            baseline - round(height * 0.055),
            left + round(width * 0.26),
            baseline - round(height * 0.018),
        ),
        radius=max(5, width // 160),
        fill=(*accent, 245),
    )
    label_font = _font(max(18, round(width * 0.026)), bold=True)
    draw.text(
        (left + round(width * 0.018), baseline - round(height * 0.052)),
        "数字人口播",
        font=label_font,
        fill=(18, 22, 28, 255),
    )
    y = baseline
    y = _draw_title_line(
        draw,
        line_1,
        x=left,
        y=y,
        max_width=round(width * 0.85),
        preferred_size=round(width * 0.105),
        fill=(255, 255, 255, 255),
        stroke_fill=(8, 10, 14, 230),
    )
    _draw_title_line(
        draw,
        line_2,
        x=left,
        y=y + round(height * 0.012),
        max_width=round(width * 0.85),
        preferred_size=round(width * 0.084),
        fill=(*accent, 255),
        stroke_fill=(8, 10, 14, 230),
    )
    canvas.paste(overlay, (0, 0), overlay)


def _draw_impact_cover(
    canvas: Image.Image,
    line_1: str,
    line_2: str,
    accent: tuple[int, int, int],
) -> None:
    width, height = canvas.size
    blurred = canvas.filter(ImageFilter.GaussianBlur(radius=max(12, width // 55)))
    panel_top = round(height * 0.61)
    canvas.paste(blurred.crop((0, panel_top, width, height)), (0, panel_top))
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, panel_top, width, height), fill=(12, 15, 20, 248))
    bar_x = round(width * 0.07)
    draw.rectangle(
        (
            bar_x,
            panel_top + round(height * 0.055),
            bar_x + max(9, width // 65),
            height - round(height * 0.07),
        ),
        fill=(*accent, 255),
    )
    x = bar_x + round(width * 0.05)
    y = panel_top + round(height * 0.06)
    y = _draw_title_line(
        draw,
        line_1,
        x=x,
        y=y,
        max_width=round(width * 0.80),
        preferred_size=round(width * 0.11),
        fill=(255, 255, 255, 255),
        stroke_fill=(0, 0, 0, 220),
    )
    _draw_title_line(
        draw,
        line_2,
        x=x,
        y=y + round(height * 0.012),
        max_width=round(width * 0.80),
        preferred_size=round(width * 0.082),
        fill=(*accent, 255),
        stroke_fill=(0, 0, 0, 220),
    )
    canvas.paste(overlay, (0, 0), overlay)


def _draw_clean_cover(
    canvas: Image.Image,
    line_1: str,
    line_2: str,
    accent: tuple[int, int, int],
) -> None:
    width, height = canvas.size
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    panel_top = round(height * 0.67)
    draw.rectangle((0, panel_top, width, height), fill=(248, 249, 250, 255))
    left = round(width * 0.075)
    draw.rectangle(
        (
            left,
            panel_top + round(height * 0.048),
            left + round(width * 0.16),
            panel_top + round(height * 0.056),
        ),
        fill=(*accent, 255),
    )
    y = panel_top + round(height * 0.075)
    y = _draw_title_line(
        draw,
        line_1,
        x=left,
        y=y,
        max_width=round(width * 0.85),
        preferred_size=round(width * 0.092),
        fill=(22, 27, 34, 255),
        stroke_fill=None,
    )
    _draw_title_line(
        draw,
        line_2,
        x=left,
        y=y + round(height * 0.006),
        max_width=round(width * 0.85),
        preferred_size=round(width * 0.066),
        fill=(72, 79, 88, 255),
        stroke_fill=None,
    )
    canvas.paste(overlay, (0, 0), overlay)


def _draw_knowledge_cover(
    canvas: Image.Image,
    line_1: str,
    line_2: str,
    accent: tuple[int, int, int],
) -> None:
    width, height = canvas.size
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    panel_top = round(height * 0.62)
    side = round(width * 0.055)
    draw.rounded_rectangle(
        (side, panel_top, width - side, height - round(height * 0.055)),
        radius=max(18, width // 32),
        fill=(248, 250, 252, 246),
    )
    draw.rounded_rectangle(
        (
            side + round(width * 0.035),
            panel_top - round(height * 0.025),
            side + round(width * 0.32),
            panel_top + round(height * 0.028),
        ),
        radius=max(8, width // 90),
        fill=(*accent, 255),
    )
    label_font = _font(max(19, round(width * 0.026)), bold=True)
    draw.text(
        (side + round(width * 0.055), panel_top - round(height * 0.019)),
        "知识拆解",
        font=label_font,
        fill=(20, 28, 36, 255),
    )
    x = side + round(width * 0.055)
    y = panel_top + round(height * 0.07)
    y = _draw_title_line(
        draw,
        line_1,
        x=x,
        y=y,
        max_width=round(width * 0.78),
        preferred_size=round(width * 0.092),
        fill=(18, 25, 33, 255),
        stroke_fill=None,
    )
    _draw_title_line(
        draw,
        line_2,
        x=x,
        y=y + round(height * 0.008),
        max_width=round(width * 0.78),
        preferred_size=round(width * 0.067),
        fill=(61, 71, 82, 255),
        stroke_fill=None,
    )
    for index in range(3):
        radius = max(5, width // 120)
        cx = width - side - round(width * (0.055 + index * 0.035))
        cy = height - round(height * 0.085)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*accent, 230))
    canvas.paste(overlay, (0, 0), overlay)


def _draw_variety_cover(
    canvas: Image.Image,
    line_1: str,
    line_2: str,
    accent: tuple[int, int, int],
) -> None:
    width, height = canvas.size
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    top = round(height * 0.54)
    for y in range(top, height):
        progress = (y - top) / max(height - top, 1)
        alpha = min(250, round(45 + 220 * progress))
        draw.line((0, y, width, y), fill=(7, 10, 16, alpha))
    left = round(width * 0.065)
    tag_y = round(height * 0.60)
    coral = (255, 100, 82)
    cyan = (55, 215, 221)
    draw.polygon(
        [
            (left, tag_y),
            (left + round(width * 0.31), tag_y - round(height * 0.01)),
            (left + round(width * 0.28), tag_y + round(height * 0.055)),
            (left + round(width * 0.02), tag_y + round(height * 0.05)),
        ],
        fill=(*coral, 255),
    )
    label_font = _font(max(20, round(width * 0.028)), bold=True)
    draw.text(
        (left + round(width * 0.03), tag_y + round(height * 0.008)),
        "口播重点",
        font=label_font,
        fill=(255, 255, 255, 255),
        stroke_width=max(1, width // 420),
        stroke_fill=(15, 18, 24, 255),
    )
    y = tag_y + round(height * 0.085)
    y = _draw_title_line(
        draw,
        line_1,
        x=left,
        y=y,
        max_width=round(width * 0.86),
        preferred_size=round(width * 0.112),
        fill=(255, 255, 255, 255),
        stroke_fill=(7, 10, 15, 255),
    )
    _draw_title_line(
        draw,
        line_2,
        x=left,
        y=y,
        max_width=round(width * 0.86),
        preferred_size=round(width * 0.088),
        fill=(*accent, 255),
        stroke_fill=(7, 10, 15, 255),
    )
    dot_radius = max(6, width // 95)
    for index, color in enumerate((cyan, accent, coral)):
        cx = width - round(width * (0.075 + index * 0.045))
        cy = round(height * 0.59)
        draw.ellipse(
            (cx - dot_radius, cy - dot_radius, cx + dot_radius, cy + dot_radius),
            fill=(*color, 255),
            outline=(10, 12, 16, 255),
            width=max(2, width // 360),
        )
    canvas.paste(overlay, (0, 0), overlay)


def _draw_question_cover(
    canvas: Image.Image,
    line_1: str,
    line_2: str,
    accent: tuple[int, int, int],
) -> None:
    width, height = canvas.size
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    top = round(height * 0.50)
    for y in range(top, height):
        progress = (y - top) / max(height - top, 1)
        draw.line((0, y, width, y), fill=(18, 7, 10, min(255, round(42 + 225 * progress))))
    watermark_font = _font(max(120, round(width * 0.32)), bold=True)
    draw.text(
        (width - round(width * 0.30), round(height * 0.54)),
        "?",
        font=watermark_font,
        fill=(255, 255, 255, 35),
    )
    left = round(width * 0.075)
    tag_top = round(height * 0.61)
    tag_color = (237, 66, 69)
    draw.rounded_rectangle(
        (
            left,
            tag_top,
            left + round(width * 0.30),
            tag_top + round(height * 0.052),
        ),
        radius=max(7, width // 90),
        fill=(*tag_color, 255),
    )
    label_font = _font(max(20, round(width * 0.028)), bold=True)
    draw.text(
        (left + round(width * 0.027), tag_top + round(height * 0.009)),
        "你知道吗？",
        font=label_font,
        fill=(255, 255, 255, 255),
    )
    y = tag_top + round(height * 0.09)
    y = _draw_title_line(
        draw,
        line_1,
        x=left,
        y=y,
        max_width=round(width * 0.84),
        preferred_size=round(width * 0.106),
        fill=(255, 255, 255, 255),
        stroke_fill=(22, 5, 8, 255),
    )
    _draw_title_line(
        draw,
        line_2,
        x=left,
        y=y,
        max_width=round(width * 0.84),
        preferred_size=round(width * 0.082),
        fill=(*accent, 255),
        stroke_fill=(22, 5, 8, 255),
    )
    canvas.paste(overlay, (0, 0), overlay)


def _draw_quote_cover(
    canvas: Image.Image,
    line_1: str,
    line_2: str,
    accent: tuple[int, int, int],
) -> None:
    width, height = canvas.size
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    top = round(height * 0.56)
    draw.rounded_rectangle(
        (
            round(width * 0.055),
            top,
            round(width * 0.945),
            round(height * 0.94),
        ),
        radius=max(18, width // 35),
        fill=(12, 18, 24, 218),
        outline=(255, 255, 255, 42),
        width=max(1, width // 400),
    )
    quote_font = _font(max(90, round(width * 0.18)), bold=True)
    draw.text(
        (round(width * 0.075), top - round(height * 0.025)),
        "“",
        font=quote_font,
        fill=(*accent, 210),
    )
    left = round(width * 0.145)
    y = top + round(height * 0.09)
    y = _draw_title_line(
        draw,
        line_1,
        x=left,
        y=y,
        max_width=round(width * 0.72),
        preferred_size=round(width * 0.086),
        fill=(255, 255, 255, 255),
        stroke_fill=None,
    )
    _draw_title_line(
        draw,
        line_2,
        x=left,
        y=y + round(height * 0.005),
        max_width=round(width * 0.72),
        preferred_size=round(width * 0.064),
        fill=(220, 226, 232, 255),
        stroke_fill=None,
    )
    draw.rectangle(
        (
            left,
            round(height * 0.885),
            left + round(width * 0.22),
            round(height * 0.891),
        ),
        fill=(*accent, 255),
    )
    canvas.paste(overlay, (0, 0), overlay)


def _draw_title_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    x: int,
    y: int,
    max_width: int,
    preferred_size: int,
    fill: tuple[int, int, int, int],
    stroke_fill: tuple[int, int, int, int] | None,
) -> int:
    if not text:
        return y
    font = _fit_font(draw, text, preferred_size, max_width)
    box = draw.textbbox((0, 0), text, font=font, stroke_width=max(1, preferred_size // 36))
    line_height = box[3] - box[1]
    stroke_width = max(1, preferred_size // 36) if stroke_fill else 0
    draw.text(
        (x, y - box[1]),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
    return y + line_height + round(preferred_size * 0.18)


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    preferred_size: int,
    max_width: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(24, preferred_size)
    while size > 24:
        font = _font(size, bold=True)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= max(2, preferred_size // 24)
    return _font(24, bold=True)


def _font(size: int, *, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        (
            Path("C:/Windows/Fonts/msyhbd.ttc"),
            Path("C:/Windows/Fonts/simhei.ttf"),
            Path("C:/Windows/Fonts/msyh.ttc"),
        )
        if bold
        else (
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/simsun.ttc"),
        )
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _load_image(source: str, media_root: Path) -> Image.Image:
    value = source.strip()
    parsed = urlparse(value)
    try:
        if parsed.scheme in {"http", "https"}:
            if parsed.hostname not in ALLOWED_LOCAL_HOSTS:
                raise CoverDesignError("封面底图只能来自本机服务或本地文件。")
            with urlopen(value, timeout=30) as response:
                payload = response.read(MAX_SOURCE_BYTES + 1)
            if len(payload) > MAX_SOURCE_BYTES:
                raise CoverDesignError("封面底图文件过大。")
            return Image.open(io.BytesIO(payload)).convert("RGB")

        candidate = Path(value)
        if value.startswith("/media/"):
            candidate = media_root / value.removeprefix("/media/")
        candidate = candidate.resolve()
        allowed_roots = {media_root.resolve(), Path(__file__).resolve().parents[3]}
        if not any(_is_relative_to(candidate, root) for root in allowed_roots):
            raise CoverDesignError("封面底图不在允许的项目目录内。")
        if not candidate.is_file():
            raise CoverDesignError(f"封面底图不存在：{candidate}")
        return Image.open(candidate).convert("RGB")
    except CoverDesignError:
        raise
    except Exception as exc:
        raise CoverDesignError(f"无法读取封面底图：{exc}") from exc


def _parse_target_format(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{2,4})x(\d{2,4})", value.strip().lower())
    if not match:
        raise CoverDesignError("封面尺寸格式无效。")
    width, height = int(match.group(1)), int(match.group(2))
    if width * height > 12_000_000:
        raise CoverDesignError("封面尺寸过大。")
    return width, height


def _parse_color(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    normalized = value.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", normalized):
        return fallback
    return tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))


def _clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:30]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
