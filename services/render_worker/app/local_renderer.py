import math
import re
import statistics
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class LocalRenderError(RuntimeError):
    pass


def _parse_target_format(target_format: str) -> tuple[int, int]:
    try:
        width_text, height_text = target_format.lower().split("x", maxsplit=1)
        width = int(width_text)
        height = int(height_text)
    except ValueError as exc:
        raise LocalRenderError(f"Invalid target format: {target_format}") from exc

    if width <= 0 or height <= 0:
        raise LocalRenderError(f"Invalid target format: {target_format}")

    return width, height


def _audio_duration(audio_path: Path) -> float:
    try:
        with wave.open(str(audio_path), "rb") as audio_file:
            frame_count = audio_file.getnframes()
            frame_rate = audio_file.getframerate()
            if frame_count <= 0:
                raise LocalRenderError(f"WAV file has no audio frames: {audio_path}")
            return frame_count / float(frame_rate)
    except (wave.Error, OSError, ZeroDivisionError) as exc:
        raise LocalRenderError(f"Could not read WAV duration: {audio_path}") from exc


def _sample_value(raw: bytes, sample_width: int) -> int:
    if sample_width == 1:
        return raw[0] - 128
    return int.from_bytes(raw, byteorder="little", signed=True)


def _rms_from_bytes(data: bytes, sample_width: int) -> float:
    if not data:
        return 0.0

    total = 0.0
    count = 0
    for index in range(0, len(data) - sample_width + 1, sample_width):
        sample = _sample_value(data[index : index + sample_width], sample_width)
        total += sample * sample
        count += 1

    return math.sqrt(total / max(count, 1))


def _audio_envelope(audio_path: Path, fps: int, frame_count: int) -> list[float]:
    try:
        with wave.open(str(audio_path), "rb") as audio_file:
            frame_rate = audio_file.getframerate()
            sample_width = audio_file.getsampwidth()
            channels = max(audio_file.getnchannels(), 1)
            frames_per_video_frame = max(1, int(frame_rate / fps))
            energies: list[float] = []

            for _ in range(frame_count):
                data = audio_file.readframes(frames_per_video_frame)
                energies.append(_rms_from_bytes(data, sample_width) / channels)
    except (wave.Error, OSError, ZeroDivisionError) as exc:
        raise LocalRenderError(f"Could not analyze WAV envelope: {audio_path}") from exc

    positive = [value for value in energies if value > 0]
    if not positive:
        return [0.0 for _ in range(frame_count)]

    peak = statistics.quantiles(positive, n=20)[-1] if len(positive) >= 20 else max(positive)
    peak = max(peak, 1.0)

    normalized: list[float] = []
    previous = 0.0
    for value in energies:
        current = min(value / peak, 1.0)
        smoothed = previous * 0.35 + current * 0.65
        normalized.append(smoothed)
        previous = smoothed

    return normalized


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_path in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


def _cover_resize(
    source: Image.Image,
    size: tuple[int, int],
    zoom: float,
    offset_x: float,
    offset_y: float,
) -> Image.Image:
    target_width, target_height = size
    source_width, source_height = source.size
    scale = max(target_width / source_width, target_height / source_height) * zoom
    resized_width = max(target_width, math.ceil(source_width * scale))
    resized_height = max(target_height, math.ceil(source_height * scale))
    resized = source.resize((resized_width, resized_height), Image.Resampling.LANCZOS)

    max_left = resized_width - target_width
    max_top = resized_height - target_height
    left = int(max_left / 2 + offset_x * max_left / 2)
    top = int(max_top / 2 + offset_y * max_top / 2)
    left = max(0, min(max_left, left))
    top = max(0, min(max_top, top))
    return resized.crop((left, top, left + target_width, top + target_height))


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int
) -> list[str]:
    normalized = " ".join(text.replace("\n", " ").split())
    if not normalized:
        return ["等待输入脚本"]

    lines: list[str] = []
    current = ""
    for char in normalized:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = char
            if len(lines) >= max_lines:
                break
        else:
            current = candidate

    if current and len(lines) < max_lines:
        lines.append(current)

    if len(lines) == max_lines and len("".join(lines)) < len(normalized):
        lines[-1] = lines[-1].rstrip("，。,. ") + "..."

    return lines


def _split_subtitle_text(text: str, max_chars: int = 14) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    rows: list[str] = []
    current = ""
    for char in normalized:
        current += char
        visible_length = len(current.replace(" ", ""))
        if (
            visible_length >= max_chars
            or char in "。！？!?；;"
            or (visible_length >= 6 and char in "，,：:")
        ):
            rows.append(current.strip())
            current = ""
    if current.strip():
        rows.append(current.strip())
    return rows


def _subtitle_segments(
    subtitle_text: str,
    supplied_segments: list[dict[str, object]] | None,
    duration: float,
) -> list[dict[str, object]]:
    valid: list[dict[str, object]] = []
    for segment in supplied_segments or []:
        text = str(segment.get("text") or segment.get("content") or "").replace("\n", " ").strip()
        try:
            start = max(0.0, float(segment.get("start") or 0.0))
            end = min(duration, float(segment.get("end") or 0.0))
        except (TypeError, ValueError):
            continue
        if text and end > start:
            valid.append({"start": start, "end": end, "text": text})
    if valid:
        return sorted(valid, key=lambda item: float(item["start"]))

    rows = _split_subtitle_text(subtitle_text)
    if not rows or duration <= 0:
        return []
    weights = [max(1, len(row.replace(" ", ""))) for row in rows]
    total_weight = sum(weights)
    cursor = 0.0
    for index, (row, weight) in enumerate(zip(rows, weights)):
        end = duration if index == len(rows) - 1 else cursor + duration * weight / total_weight
        valid.append({"start": cursor, "end": end, "text": row})
        cursor = end
    return valid


def _active_subtitle(segments: list[dict[str, object]], timestamp: float) -> str:
    for segment in segments:
        if float(segment["start"]) <= timestamp < float(segment["end"]):
            return str(segment["text"])
    return ""


def _fit_single_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    text = text.replace("\n", " ").strip()
    while text and _text_width(draw, text, font) > max_width:
        text = text[:-1].rstrip()
    return text if text else ""


def _draw_caption(
    frame: Image.Image,
    subtitle_text: str,
    subtitle_template: str = "clean",
) -> None:
    if not subtitle_text:
        return
    width, height = frame.size
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    style = (
        subtitle_template
        if subtitle_template
        in {
            "clean",
            "bold_yellow",
            "news_bar",
            "orange_pop",
            "minimal",
            "center_focus",
        }
        else "clean"
    )
    margin = max(28, width // 28)
    font_divisor = 24
    text_fill = (255, 255, 255, 255)
    stroke_fill = (0, 0, 0, 235)
    stroke_width = max(1, width // 540)
    panel_height = max(92, height // 18)
    panel_top = height - panel_height - margin

    if style == "clean":
        draw.rounded_rectangle(
            (margin, panel_top, width - margin, height - margin),
            radius=18,
            fill=(8, 14, 20, 196),
        )
    elif style == "bold_yellow":
        font_divisor = 20
        text_fill = (255, 213, 79, 255)
        stroke_width = max(3, width // 270)
    elif style == "news_bar":
        font_divisor = 22
        panel_height = max(104, height // 16)
        panel_top = height - panel_height - margin
        draw.rectangle(
            (0, panel_top, width, height - margin),
            fill=(9, 17, 24, 222),
        )
        draw.rectangle(
            (0, panel_top, max(12, width // 90), height - margin),
            fill=(228, 59, 68, 255),
        )
        stroke_width = 0
    elif style == "orange_pop":
        font_divisor = 20
        text_fill = (255, 138, 61, 255)
        stroke_width = max(3, width // 270)
    elif style == "minimal":
        font_divisor = 28
        panel_top = height - max(76, height // 22) - margin
        stroke_width = max(1, width // 720)
    elif style == "center_focus":
        font_divisor = 19
        panel_height = max(116, height // 14)
        panel_top = round(height * 0.70)
        draw.rounded_rectangle(
            (margin * 2, panel_top, width - margin * 2, panel_top + panel_height),
            radius=14,
            fill=(8, 14, 20, 168),
        )
        text_fill = (255, 244, 199, 255)
        stroke_width = max(2, width // 360)

    body_font = _font(max(34, width // font_divisor))
    line = _fit_single_line(draw, subtitle_text, body_font, width - margin * 2 - 64)
    text_width = _text_width(draw, line, body_font)
    text_box = draw.textbbox((0, 0), line, font=body_font)
    text_height = text_box[3] - text_box[1]
    text_y = panel_top + (panel_height - text_height) / 2 - text_box[1]
    draw.text(
        ((width - text_width) / 2, text_y),
        line,
        fill=text_fill,
        font=body_font,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )

    frame.alpha_composite(overlay)


def _draw_mouth_motion(frame: Image.Image, energy: float) -> None:
    width, height = frame.size
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    center_x = int(width * 0.5)
    center_y = int(height * 0.365)
    mouth_width = int(width * (0.052 + energy * 0.032))
    mouth_height = int(height * (0.003 + energy * 0.011))

    if energy < 0.08:
        return

    shadow_box = (
        center_x - mouth_width,
        center_y - mouth_height,
        center_x + mouth_width,
        center_y + mouth_height,
    )
    draw.ellipse(shadow_box, fill=(56, 18, 22, int(95 + energy * 120)))

    lip_line_y = center_y - int(mouth_height * 0.35)
    draw.rounded_rectangle(
        (
            center_x - int(mouth_width * 0.9),
            lip_line_y - 2,
            center_x + int(mouth_width * 0.9),
            lip_line_y + 2,
        ),
        radius=3,
        fill=(130, 70, 72, int(80 + energy * 90)),
    )
    frame.alpha_composite(overlay)


def render_talking_video(
    *,
    image_path: Path,
    audio_path: Path,
    subtitle_text: str,
    subtitle_segments: list[dict[str, object]] | None,
    subtitle_template: str,
    burn_subtitles: bool,
    target_format: str,
    output_dir: Path,
    ffmpeg_path: str,
    video_crf: int,
    video_preset: str,
    video_filter_extra: str = "",
) -> tuple[Path, Path]:
    if not image_path.exists():
        raise LocalRenderError(f"Image not found: {image_path}")
    if not audio_path.exists():
        raise LocalRenderError(f"Audio not found: {audio_path}")

    width, height = _parse_target_format(target_format)
    duration_seconds = min(max(_audio_duration(audio_path), 3.0), 90.0)
    fps = 18
    frame_count = max(int(math.ceil(duration_seconds * fps)), fps * 3)
    envelope = _audio_envelope(audio_path, fps, frame_count)
    timed_subtitles = _subtitle_segments(subtitle_text, subtitle_segments, duration_seconds)

    job_dir = output_dir
    frame_dir = job_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    export_path = job_dir / "talking_agent.mp4"
    cover_path = job_dir / "cover.jpg"

    source = Image.open(image_path).convert("RGB")
    for frame_index in range(frame_count):
        progress = frame_index / max(frame_count - 1, 1)
        energy = envelope[frame_index] if frame_index < len(envelope) else 0.0
        breathing = 0.5 + 0.5 * math.sin(progress * math.tau * 1.4)
        zoom = 1.045 + breathing * 0.01 + energy * 0.012
        offset_x = math.sin(progress * math.tau * 1.2) * 0.18
        offset_y = math.sin(progress * math.tau * 1.7 + 0.8) * 0.10

        frame = _cover_resize(source, (width, height), zoom, offset_x, offset_y).convert("RGBA")
        _draw_mouth_motion(frame, energy)
        if burn_subtitles:
            _draw_caption(
                frame,
                _active_subtitle(timed_subtitles, frame_index / fps),
                subtitle_template,
            )
        frame.convert("RGB").save(
            frame_dir / f"frame_{frame_index:05d}.jpg", quality=90, optimize=True
        )

    (frame_dir / "frame_00000.jpg").replace(cover_path)
    Image.open(cover_path).save(frame_dir / "frame_00000.jpg", quality=90, optimize=True)

    frame_pattern = str(frame_dir / "frame_%05d.jpg")
    result = subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            frame_pattern,
            "-i",
            str(audio_path),
            "-c:v",
            "libx264",
            "-preset",
            video_preset,
            "-crf",
            str(video_crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            str(export_path),
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )

    if result.returncode != 0:
        raise LocalRenderError((result.stderr or result.stdout or "ffmpeg render failed.").strip())

    if not export_path.exists() or export_path.stat().st_size < 4096:
        raise LocalRenderError("ffmpeg finished without producing a video file.")

    return export_path, cover_path


def render_lip_synced_video(
    *,
    video_path: Path,
    audio_path: Path,
    subtitle_text: str,
    subtitle_segments: list[dict[str, object]] | None,
    subtitle_template: str,
    burn_subtitles: bool,
    target_format: str,
    output_dir: Path,
    ffmpeg_path: str,
    video_crf: int,
    video_preset: str,
    video_filter_extra: str = "",
) -> tuple[Path, Path]:
    if not video_path.exists():
        raise LocalRenderError(f"Lip-sync video not found: {video_path}")

    width, height = _parse_target_format(target_format)
    job_dir = output_dir
    job_dir.mkdir(parents=True, exist_ok=True)
    export_path = job_dir / "talking_agent.mp4"
    cover_path = job_dir / "cover.jpg"

    filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
    ]
    if video_filter_extra:
        filters.append(video_filter_extra)
    if burn_subtitles:
        duration_seconds = _audio_duration(audio_path)
        timed_subtitles = _subtitle_segments(subtitle_text, subtitle_segments, duration_seconds)
        if timed_subtitles:
            subtitle_path = job_dir / "subtitles.ass"
            _write_ass_subtitles(
                subtitle_path,
                timed_subtitles,
                width,
                height,
                subtitle_template,
            )
            filters.append("ass=subtitles.ass")
    video_filter = ",".join(filters)
    result = subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            video_preset,
            "-crf",
            str(video_crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(export_path),
        ],
        capture_output=True,
        text=True,
        timeout=240,
        cwd=str(job_dir),
    )

    if result.returncode != 0:
        raise LocalRenderError(
            (result.stderr or result.stdout or "ffmpeg lip-sync packaging failed.").strip()
        )

    if not export_path.exists() or export_path.stat().st_size < 64 * 1024:
        raise LocalRenderError("ffmpeg finished without producing a usable lip-sync video file.")

    cover_filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
    ]
    if video_filter_extra:
        cover_filters.append(video_filter_extra)
    cover_result = subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "0.5",
            "-i",
            str(video_path),
            "-vf",
            ",".join(cover_filters),
            "-frames:v",
            "1",
            str(cover_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if cover_result.returncode != 0 or not cover_path.exists():
        raise LocalRenderError(
            (cover_result.stderr or cover_result.stdout or "cover extraction failed.").strip()
        )

    return export_path, cover_path


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _ass_text(value: str) -> str:
    return value.replace("\\", "").replace("{", "（").replace("}", "）").replace("\n", " ").strip()


def _write_ass_subtitles(
    path: Path,
    segments: list[dict[str, object]],
    width: int,
    height: int,
    subtitle_template: str = "clean",
) -> None:
    styles = {
        "clean": {
            "font_size": max(38, round(width / 15)),
            "primary": "&H00FFFFFF",
            "outline": "&H00101010",
            "back": "&H80000000",
            "bold": 0,
            "border": 1,
            "outline_width": 3,
            "shadow": 1,
            "margin_v": max(58, round(height * 0.06)),
        },
        "bold_yellow": {
            "font_size": max(42, round(width / 13)),
            "primary": "&H004FD5FF",
            "outline": "&H00080808",
            "back": "&H90000000",
            "bold": -1,
            "border": 1,
            "outline_width": 4,
            "shadow": 2,
            "margin_v": max(64, round(height * 0.065)),
        },
        "news_bar": {
            "font_size": max(40, round(width / 14)),
            "primary": "&H00FFFFFF",
            "outline": "&H00000000",
            "back": "&H480D1218",
            "bold": -1,
            "border": 3,
            "outline_width": 1,
            "shadow": 0,
            "margin_v": max(52, round(height * 0.055)),
        },
        "orange_pop": {
            "font_size": max(42, round(width / 13)),
            "primary": "&H003D8AFF",
            "outline": "&H00130B05",
            "back": "&H90000000",
            "bold": -1,
            "border": 1,
            "outline_width": 4,
            "shadow": 2,
            "margin_v": max(64, round(height * 0.065)),
        },
        "minimal": {
            "font_size": max(34, round(width / 18)),
            "primary": "&H00FFFFFF",
            "outline": "&H00202020",
            "back": "&HA0000000",
            "bold": 0,
            "border": 1,
            "outline_width": 2,
            "shadow": 0,
            "margin_v": max(50, round(height * 0.05)),
        },
        "center_focus": {
            "font_size": max(44, round(width / 12)),
            "primary": "&H00C7F4FF",
            "outline": "&H00101010",
            "back": "&H70000000",
            "bold": -1,
            "border": 3,
            "outline_width": 2,
            "shadow": 1,
            "margin_v": max(210, round(height * 0.22)),
        },
    }
    style = styles.get(subtitle_template, styles["clean"])
    rows = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        (
            "Style: Main,Microsoft YaHei,"
            f"{style['font_size']},{style['primary']},&H00FFFFFF,"
            f"{style['outline']},{style['back']},{style['bold']},"
            "0,0,0,100,100,0,0,"
            f"{style['border']},{style['outline_width']},{style['shadow']},"
            f"2,40,40,{style['margin_v']},1"
        ),
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    for segment in segments:
        rows.append(
            "Dialogue: 0,"
            f"{_ass_timestamp(float(segment['start']))},"
            f"{_ass_timestamp(float(segment['end']))},"
            f"Main,,0,0,0,,{_ass_text(str(segment['text']))}"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8-sig")
