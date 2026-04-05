#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path


RAW_PREFIX = "01_whisper_small_raw"
CORRECTED_SRT_NAME = "02_修正字幕.srt"
TWO_LINE_SRT_NAME = "03_2行テロップ字幕.srt"
CHAPTERS_NAME = "04_チャプター.json"
YOUTUBE_TIMESTAMPS_NAME = "05_YouTubeタイムスタンプ.txt"
FILTERGRAPH_NAME = "06_ffmpeg_filtergraph.txt"
MINIMUM_SEGMENT_MS = 900
MAX_SUBTITLE_LINES = 2
MAX_LINE_WIDTH_UNITS = 44
MAX_CUE_DISPLAY_UNITS = 60
MAX_READING_UNITS_PER_SECOND = 14.0
READING_PADDING_MS = 150
PREFERRED_BREAK_CHARS = "、。！？!?)]）】」』,，.． "
SENTENCE_BREAK_CHARS = "、。！？!?;；,，.． "


def parse_args() -> argparse.Namespace:
    skill_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Build reusable telop assets, YouTube timestamps, and render the final EB full interview video.",
    )
    parser.add_argument("--video", required=True, help="Path to the interview video.")
    parser.add_argument("--corrected-srt", required=True, help="Corrected subtitle SRT path.")
    parser.add_argument("--chapters-json", required=True, help="Chapter JSON path.")
    parser.add_argument(
        "--delivery-base-name",
        required=True,
        help="Japanese delivery base name, e.g. ケントさんインタビュー.",
    )
    parser.add_argument("--asset-dir", help="Optional explicit asset folder.")
    parser.add_argument("--brand-title", default="格安フィリピン留学EB")
    parser.add_argument(
        "--font-file",
        default=str(skill_root / "assets" / "fonts" / "NotoSansJP-wght.ttf"),
    )
    parser.add_argument("--subtitle-font-name", default="Noto Sans JP")
    parser.add_argument("--drawtext-font-name", default="Noto Sans JP")
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--keep-assets", action="store_true")
    parser.add_argument("--keep-previews", action="store_true")
    parser.add_argument(
        "--skip-shorts",
        action="store_true",
        help="Skip short clip generation.",
    )
    parser.add_argument(
        "--shorts-output-dir",
        help=(
            "Optional output folder for short clips. "
            "Defaults to <delivery-base-name>_縦型ショート切り抜き beside the source video."
        ),
    )
    parser.add_argument(
        "--shorts-source-video",
        help=(
            "Optional source video for short clips. "
            "Defaults to <delivery-base-name>_テロップ付き.mp4 when available; otherwise the original source video."
        ),
    )
    parser.add_argument(
        "--shorts-source-has-telop",
        action="store_true",
        help="Force short clip generation to treat shorts source as already telop-burned.",
    )
    parser.add_argument("--shorts-min-clips", type=int, default=8)
    parser.add_argument("--shorts-max-clips", type=int, default=12)
    parser.add_argument("--shorts-min-seconds", type=float, default=30.0)
    parser.add_argument("--shorts-preferred-seconds", type=float, default=45.0)
    parser.add_argument("--shorts-max-seconds", type=float, default=90.0)
    return parser.parse_args()


def parse_srt(source: str) -> list[dict[str, object]]:
    blocks = [block.strip() for block in source.replace("\ufeff", "").replace("\r\n", "\n").split("\n\n") if block.strip()]
    cues: list[dict[str, object]] = []

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        timestamp_line = next((line for line in lines if "-->" in line), None)
        if not timestamp_line:
            raise ValueError(f"Invalid SRT block:\n{block}")

        start_raw, end_raw = [part.strip() for part in timestamp_line.split("-->")]
        text = "\n".join(
            line for line in lines if line != timestamp_line and not line.isdigit()
        ).strip()
        cues.append(
            {
                "startMs": parse_timecode(start_raw),
                "endMs": parse_timecode(end_raw),
                "text": text,
            }
        )

    return cues


def parse_timecode(value: str) -> int:
    hours, minutes, seconds_ms = value.split(":")
    seconds, milliseconds = seconds_ms.split(",")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(milliseconds)
    )


def format_timecode(value: int) -> str:
    hours = value // 3_600_000
    minutes = (value % 3_600_000) // 60_000
    seconds = (value % 60_000) // 1_000
    milliseconds = value % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def normalize_text(text: str) -> str:
    return "".join(text.split())


def display_width(text: str) -> int:
    width = 0
    for character in text:
        if character == "\n":
            continue
        if character.isspace():
            width += 1
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"F", "W", "A"} else 1
    return width


def clean_subtitle_text(text: str) -> str:
    normalized_lines = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        collapsed = re.sub(r"\s+", " ", raw_line).strip()
        if collapsed:
            normalized_lines.append(collapsed)
    return "\n".join(normalized_lines)


def find_wrap_index(text: str, max_line_width_units: int) -> int:
    width = 0
    last_fit = 0
    break_candidates: list[tuple[int, int]] = []

    for index, character in enumerate(text):
        char_width = display_width(character)
        if width + char_width > max_line_width_units:
            break
        width += char_width
        last_fit = index + 1

        next_character = text[index + 1] if index + 1 < len(text) else ""
        if character in PREFERRED_BREAK_CHARS:
            break_candidates.append((index + 1, 0))
        elif character.isspace() or next_character.isspace():
            break_candidates.append((index + 1, 1))

    if last_fit >= len(text):
        return len(text)
    if not break_candidates:
        return max(1, last_fit)

    window_start = max(1, last_fit - 8)
    nearby_candidates = [
        candidate for candidate in break_candidates if candidate[0] >= window_start
    ]
    search_space = nearby_candidates or break_candidates
    best_index, _ = min(
        search_space,
        key=lambda candidate: (candidate[1], last_fit - candidate[0]),
    )
    return best_index


def wrap_paragraph(text: str, max_line_width_units: int) -> list[str]:
    remaining = text.strip()
    lines: list[str] = []

    while remaining:
        if display_width(remaining) <= max_line_width_units:
            lines.append(remaining)
            break

        split_index = find_wrap_index(remaining, max_line_width_units)
        current_line = remaining[:split_index].rstrip()
        remaining = remaining[split_index:].lstrip()

        if not current_line:
            current_line = remaining[:1]
            remaining = remaining[1:].lstrip()

        lines.append(current_line)

    return lines


def wrap_subtitle_text(text: str, max_line_width_units: int) -> list[str]:
    cleaned = clean_subtitle_text(text)
    if not cleaned:
        return []

    wrapped_lines: list[str] = []
    for paragraph in cleaned.split("\n"):
        wrapped_lines.extend(wrap_paragraph(paragraph, max_line_width_units))
    return wrapped_lines


def paginate_subtitle_lines(lines: list[str], max_lines: int) -> list[str]:
    if not lines:
        return []
    return [
        "\n".join(lines[index:index + max_lines])
        for index in range(0, len(lines), max_lines)
    ]


def measure_page_weight(text: str) -> int:
    return max(1, display_width(normalize_text(text)))


def find_sentence_split_index(text: str, max_units: int) -> int:
    width = 0
    last_fit = 0
    punctuation_split = -1
    whitespace_split = -1

    for index, character in enumerate(text):
        char_width = display_width(character)
        if width + char_width > max_units:
            break
        width += char_width
        last_fit = index + 1
        if character in SENTENCE_BREAK_CHARS:
            punctuation_split = index + 1
        elif character.isspace():
            whitespace_split = index + 1

    if last_fit >= len(text):
        return len(text)

    near_end = max(1, last_fit - 12)
    if punctuation_split >= near_end:
        return punctuation_split
    if whitespace_split >= near_end:
        return whitespace_split
    return max(1, last_fit)


def split_page_by_readability(page_text: str, max_units: int) -> list[str]:
    normalized = clean_subtitle_text(page_text).replace("\n", " ").strip()
    if not normalized:
        return []

    segments: list[str] = []
    remaining = normalized
    while remaining and measure_page_weight(remaining) > max_units:
        split_index = find_sentence_split_index(remaining, max_units)
        if split_index >= len(remaining):
            split_index = max(1, len(remaining) // 2)
        segment = remaining[:split_index].strip()
        if not segment:
            split_index = max(1, split_index)
            segment = remaining[:split_index].strip()
        segments.append(segment)
        remaining = remaining[split_index:].strip()

    if remaining:
        segments.append(remaining)
    return segments


def enforce_page_readability(
    pages: list[str],
    *,
    max_page_units: int,
    max_line_width_units: int,
    max_lines: int,
) -> list[str]:
    refined: list[str] = []
    queue = list(pages)

    while queue:
        current = queue.pop(0)
        if measure_page_weight(current) <= max_page_units:
            refined.append(current)
            continue

        split_segments = split_page_by_readability(current, max_page_units)
        if len(split_segments) <= 1:
            refined.append(current)
            continue

        next_pages: list[str] = []
        for segment in split_segments:
            wrapped = wrap_subtitle_text(segment, max_line_width_units)
            if not wrapped:
                continue
            next_pages.extend(paginate_subtitle_lines(wrapped, max_lines))
        queue = next_pages + queue

    return refined


def compute_required_durations_ms(
    page_weights: list[int],
    *,
    minimum_segment_ms: int,
    max_units_per_second: float,
) -> list[int]:
    required: list[int] = []
    for weight in page_weights:
        reading_ms = int(math.ceil((weight / max_units_per_second) * 1000.0))
        required.append(max(minimum_segment_ms, reading_ms + READING_PADDING_MS))
    return required


def allocate_durations_ms(
    *,
    total_duration_ms: int,
    page_weights: list[int],
    minimum_segment_ms: int,
) -> list[int]:
    if not page_weights:
        return []
    if len(page_weights) == 1:
        return [total_duration_ms]

    required_durations = compute_required_durations_ms(
        page_weights,
        minimum_segment_ms=minimum_segment_ms,
        max_units_per_second=MAX_READING_UNITS_PER_SECOND,
    )
    required_total = sum(required_durations)

    if required_total <= total_duration_ms:
        durations: list[int] = []
        remaining_total = total_duration_ms
        remaining_required = required_total
        remaining_weight = sum(page_weights)

        for index, (required_ms, weight) in enumerate(
            zip(required_durations, page_weights)
        ):
            is_last = index == len(page_weights) - 1
            if is_last:
                duration = remaining_total
            else:
                extra_pool = remaining_total - remaining_required
                proportional_extra = round(
                    extra_pool * (weight / max(1, remaining_weight))
                )
                duration = required_ms + proportional_extra
                max_current = remaining_total - sum(required_durations[index + 1 :])
                duration = max(required_ms, min(max_current, duration))

            durations.append(duration)
            remaining_total -= duration
            remaining_required -= required_ms
            remaining_weight -= weight
        return durations

    durations = []
    remaining_weight = sum(page_weights)
    remaining_total = total_duration_ms
    for index, weight in enumerate(page_weights):
        is_last = index == len(page_weights) - 1
        if is_last:
            duration = remaining_total
        else:
            remaining_pages_after = len(page_weights) - index - 1
            raw_duration = round(remaining_total * (weight / max(1, remaining_weight)))
            min_current = minimum_segment_ms
            max_current = remaining_total - (minimum_segment_ms * remaining_pages_after)
            duration = max(min_current, min(max_current, raw_duration))
        durations.append(duration)
        remaining_total -= duration
        remaining_weight -= weight

    return durations


def split_long_cues(
    cues: list[dict[str, object]],
    max_line_width_units: int = MAX_LINE_WIDTH_UNITS,
    max_lines: int = MAX_SUBTITLE_LINES,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []

    for cue in cues:
        text = str(cue["text"])
        wrapped_lines = wrap_subtitle_text(text, max_line_width_units)
        if not wrapped_lines:
            continue

        pages = paginate_subtitle_lines(wrapped_lines, max_lines)
        pages = enforce_page_readability(
            pages,
            max_page_units=MAX_CUE_DISPLAY_UNITS,
            max_line_width_units=max_line_width_units,
            max_lines=max_lines,
        )
        if len(pages) == 1:
            output.append(
                {
                    "startMs": int(cue["startMs"]),
                    "endMs": int(cue["endMs"]),
                    "text": pages[0],
                }
            )
            continue

        start_ms = int(cue["startMs"])
        end_ms = int(cue["endMs"])
        total_duration = max(1, end_ms - start_ms)
        page_weights = [measure_page_weight(page) for page in pages]
        minimum_segment_ms = (
            max(1, min(MINIMUM_SEGMENT_MS, total_duration // len(pages)))
            if total_duration >= len(pages)
            else 0
        )
        durations = allocate_durations_ms(
            total_duration_ms=total_duration,
            page_weights=page_weights,
            minimum_segment_ms=minimum_segment_ms,
        )
        current_start = start_ms

        for index, (page_text, duration) in enumerate(zip(pages, durations)):
            current_end = min(end_ms, current_start + max(1, duration))
            is_last = index == len(pages) - 1
            if is_last:
                current_end = end_ms

            output.append(
                {
                    "startMs": current_start,
                    "endMs": current_end,
                    "text": page_text,
                }
            )
            current_start = current_end

    return output


def dump_srt(cues: list[dict[str, object]]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_timecode(int(cue['startMs']))} --> {format_timecode(int(cue['endMs']))}",
                    str(cue["text"]),
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def load_and_validate_chapters(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Chapter JSON must be a non-empty array.")

    normalized: list[dict[str, object]] = []
    previous_end = -1.0

    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each chapter must be an object.")

        start_sec = float(item["startSec"])
        end_sec = float(item["endSec"])
        title = str(item["title"]).strip()

        if not title:
            raise ValueError("Chapter title must not be empty.")
        if end_sec <= start_sec:
            raise ValueError(f"Invalid chapter range: {title}")
        if start_sec < previous_end:
            raise ValueError("Chapters must be sorted and non-overlapping.")

        normalized.append(
            {
                "startSec": start_sec,
                "endSec": end_sec,
                "title": title,
            }
        )
        previous_end = end_sec

    return normalized


def format_timestamp(start_sec: float) -> str:
    total_seconds = max(0, int(math.floor(start_sec)))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def build_youtube_timestamps(chapters: list[dict[str, object]]) -> str:
    return "\n".join(
        f"{format_timestamp(float(chapter['startSec']))} {chapter['title']}"
        for chapter in chapters
    ) + "\n"


def escape_drawtext(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def escape_filter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", r"\'")


def build_filtergraph(
    chapters: list[dict[str, object]],
    subtitle_path: Path,
    font_file: Path,
    subtitle_font_name: str,
    drawtext_font_name: str,
    brand_title: str,
) -> str:
    escaped_font = escape_filter_value(str(font_file))
    escaped_subtitle = escape_filter_value(str(subtitle_path))
    escaped_font_dir = escape_filter_value(str(font_file.parent))
    drawtext_font_arg = f"fontfile='{escaped_font}'"
    style = (
        f"FontName={subtitle_font_name},"
        "Fontsize=26,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=3,"
        "Shadow=1,"
        "Alignment=2,"
        "WrapStyle=0,"
        "MarginL=80,"
        "MarginR=80,"
        "MarginV=40"
    )

    filter_lines = [
        (
            f"drawtext={drawtext_font_arg}:text='{escape_drawtext(brand_title)}':"
            "fontsize=60:fontcolor=white:borderw=6:bordercolor=0x5A9EE8@0.96:"
            "shadowcolor=black@0.28:shadowx=0:shadowy=8:x=42:y=34"
        ),
    ]

    for chapter in chapters:
        filter_lines.append(
            (
                f"drawtext={drawtext_font_arg}:text='{escape_drawtext(str(chapter['title']))}':"
                f"enable='between(t,{chapter['startSec']},{chapter['endSec']})':"
                "fontsize=56:fontcolor=white:borderw=6:bordercolor=0x4A4A4A@0.92:"
                "shadowcolor=black@0.35:shadowx=0:shadowy=8:x=w-tw-42:y=34"
            )
        )

    filter_lines.append(
        (
            f"subtitles='{escaped_subtitle}':fontsdir='{escaped_font_dir}':"
            f"force_style='{style}'"
        )
    )

    return "[0:v]\n" + ",\n".join(filter_lines) + "\n[v]\n"


def choose_video_codec() -> list[str]:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise SystemExit("ffmpeg command not found in PATH.")

    result = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
    )

    if "h264_videotoolbox" in result.stdout:
        return [
            "-c:v",
            "h264_videotoolbox",
            "-b:v",
            "12M",
            "-maxrate",
            "12M",
            "-bufsize",
            "24M",
        ]

    return [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
    ]


def remove_preview_artifacts(directory: Path, base_name: str, video_stem: str) -> list[Path]:
    removed: list[Path] = []
    preview_tokens = (
        "preview",
        "prototype",
        "design_check",
        "first10s",
        "first1min",
        "first2min",
    )

    candidates = [path for path in directory.iterdir() if path.name not in {f"{base_name}_テロップ付き.mp4", f"{base_name}_テロップ素材"}]
    for path in candidates:
        name_lower = path.name.lower()
        if video_stem.lower() not in name_lower and base_name.lower() not in name_lower:
            continue
        if not any(token in name_lower for token in preview_tokens):
            continue

        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        removed.append(path)

    return removed


def ensure_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == destination.resolve():
        return
    shutil.copy2(source, destination)


def remove_asset_dir(asset_dir: Path) -> None:
    shutil.rmtree(asset_dir, ignore_errors=True)


def render_video(video_path: Path, filtergraph_path: Path, output_path: Path) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise SystemExit("ffmpeg command not found in PATH.")

    codec_args = choose_video_codec()
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-filter_complex_script",
        str(filtergraph_path),
        "-map",
        "[v]",
        "-map",
        "0:a:0?",
        *codec_args,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]

    subprocess.run(command, check=True)


def resolve_shorts_source_video(
    shorts_source_arg: str | None,
    output_video_path: Path,
    original_video_path: Path,
) -> Path:
    if shorts_source_arg:
        return Path(shorts_source_arg).expanduser().resolve()
    if output_video_path.exists():
        return output_video_path
    return original_video_path


def run_shorts_pipeline(
    args: argparse.Namespace,
    *,
    original_video_path: Path,
    output_video_path: Path,
    corrected_srt_path: Path,
    subtitle_srt_path: Path,
    font_file: Path,
) -> tuple[Path, int]:
    shorts_script = Path(__file__).resolve().parent / "build_short_clips.py"
    if not shorts_script.exists():
        raise SystemExit(f"Short clips script not found: {shorts_script}")

    shorts_source_video = resolve_shorts_source_video(
        args.shorts_source_video,
        output_video_path,
        original_video_path,
    )
    if not shorts_source_video.exists():
        raise SystemExit(f"Short clips source video not found: {shorts_source_video}")

    shorts_output_dir = (
        Path(args.shorts_output_dir).expanduser().resolve()
        if args.shorts_output_dir
        else original_video_path.parent / f"{args.delivery_base_name}_縦型ショート切り抜き"
    )

    command = [
        sys.executable,
        str(shorts_script),
        "--video",
        str(shorts_source_video),
        "--analysis-srt",
        str(corrected_srt_path),
        "--subtitle-srt",
        str(subtitle_srt_path),
        "--output-dir",
        str(shorts_output_dir),
        "--min-clips",
        str(args.shorts_min_clips),
        "--max-clips",
        str(args.shorts_max_clips),
        "--min-seconds",
        str(args.shorts_min_seconds),
        "--preferred-seconds",
        str(args.shorts_preferred_seconds),
        "--max-seconds",
        str(args.shorts_max_seconds),
        "--font-file",
        str(font_file),
        "--subtitle-font-name",
        args.subtitle_font_name,
    ]

    source_has_telop = (
        args.shorts_source_has_telop
        or shorts_source_video == output_video_path
        or "テロップ付き" in shorts_source_video.stem
    )
    if source_has_telop:
        command.append("--source-has-telop")

    subprocess.run(command, check=True)

    manifest_path = shorts_output_dir / "00_切り抜き候補一覧.json"
    if not manifest_path.exists():
        return shorts_output_dir, 0

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return shorts_output_dir, 0
    if isinstance(manifest_data, list):
        return shorts_output_dir, len(manifest_data)
    return shorts_output_dir, 0


def main() -> None:
    args = parse_args()

    video_path = Path(args.video).expanduser().resolve()
    corrected_srt_path = Path(args.corrected_srt).expanduser().resolve()
    chapters_json_path = Path(args.chapters_json).expanduser().resolve()
    font_file = Path(args.font_file).expanduser().resolve()

    for path in (video_path, corrected_srt_path, chapters_json_path, font_file):
        if not path.exists():
            raise SystemExit(f"Required path not found: {path}")

    asset_dir = (
        Path(args.asset_dir).expanduser().resolve()
        if args.asset_dir
        else video_path.parent / f"{args.delivery_base_name}_テロップ素材"
    )
    asset_dir.mkdir(parents=True, exist_ok=True)

    corrected_srt_target = asset_dir / CORRECTED_SRT_NAME
    two_line_srt_target = asset_dir / TWO_LINE_SRT_NAME
    chapters_target = asset_dir / CHAPTERS_NAME
    youtube_timestamps_target = asset_dir / YOUTUBE_TIMESTAMPS_NAME
    filtergraph_target = asset_dir / FILTERGRAPH_NAME
    output_video_path = video_path.parent / f"{args.delivery_base_name}_テロップ付き.mp4"

    ensure_copy(corrected_srt_path, corrected_srt_target)

    cues = parse_srt(corrected_srt_target.read_text(encoding="utf-8"))
    two_line_cues = split_long_cues(cues)
    two_line_srt_target.write_text(dump_srt(two_line_cues), encoding="utf-8")

    chapters = load_and_validate_chapters(chapters_json_path)
    chapters_target.write_text(
        json.dumps(chapters, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    youtube_timestamps = build_youtube_timestamps(chapters)
    youtube_timestamps_target.write_text(youtube_timestamps, encoding="utf-8")

    filtergraph_target.write_text(
        build_filtergraph(
            chapters=chapters,
            subtitle_path=two_line_srt_target,
            font_file=font_file,
            subtitle_font_name=args.subtitle_font_name,
            drawtext_font_name=args.drawtext_font_name,
            brand_title=args.brand_title,
        ),
        encoding="utf-8",
    )

    shorts_output_dir: Path | None = None
    shorts_count = 0

    if not args.skip_render:
        render_video(video_path, filtergraph_target, output_video_path)

    if not args.skip_shorts:
        shorts_output_dir, shorts_count = run_shorts_pipeline(
            args,
            original_video_path=video_path,
            output_video_path=output_video_path,
            corrected_srt_path=corrected_srt_target,
            subtitle_srt_path=two_line_srt_target,
            font_file=font_file,
        )

    removed = []
    if not args.keep_previews:
        removed = remove_preview_artifacts(video_path.parent, args.delivery_base_name, video_path.stem)

    removed_asset_dir = False
    if not args.skip_render and not args.keep_assets:
        remove_asset_dir(asset_dir)
        removed_asset_dir = True

    if args.skip_render:
        print(f"Asset folder: {asset_dir}")
        print(f"Corrected SRT: {corrected_srt_target}")
        print(f"Two-line SRT: {two_line_srt_target}")
        print(f"Chapters JSON: {chapters_target}")
        print(f"YouTube timestamps file: {youtube_timestamps_target}")
        print(f"Filtergraph: {filtergraph_target}")
        print("Final video: skipped")
    else:
        print(f"Final video: {output_video_path}")
        if removed_asset_dir:
            print(f"Asset folder: removed ({asset_dir})")
        else:
            print(f"Asset folder: {asset_dir}")
            print(f"YouTube timestamps file: {youtube_timestamps_target}")
    if args.skip_shorts:
        print("Short clips: skipped")
    elif shorts_output_dir is not None:
        print(f"Short clips: {shorts_output_dir}")
        print(f"Short clips count: {shorts_count}")
    print("YouTube timestamps:")
    print(youtube_timestamps.rstrip())
    if removed:
        print("Removed preview artifacts:")
        for path in removed:
            print(f"- {path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
