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
from dataclasses import dataclass
from pathlib import Path


INVALID_FILENAME_CHARS = r'\/:*?"<>|'
DEFAULT_MIN_CLIPS = 8
DEFAULT_MAX_CLIPS = 12
DEFAULT_MIN_SECONDS = 30.0
DEFAULT_PREFERRED_SECONDS = 45.0
DEFAULT_MAX_SECONDS = 90.0

HOOK_KEYWORDS = (
    "最初",
    "初め",
    "本当に",
    "実は",
    "一番",
    "不安",
    "驚",
    "変わ",
    "できるよう",
)
VALUE_KEYWORDS = (
    "成長",
    "実感",
    "学び",
    "気づ",
    "変化",
    "安心",
    "不安",
    "嬉し",
    "楽しか",
    "TOEIC",
    "発音",
    "文法",
    "表現",
    "使える",
    "留学",
)
INTERVIEWER_LIKE_PATTERNS = (
    "どうですか",
    "教えて",
    "お伺い",
    "聞きたい",
    "思いますが",
    "でしょうか",
)
TITLE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("toeic", "150", "アップ"), "1か月でTOEIC150点アップ"),
    (("toeic",), "TOEIC学習で結果を出した方法"),
    (("発音", "rとl"), "発音が変わった実感"),
    (("発音",), "発音力が伸びた1か月"),
    (("文法", "a と the"), "冠詞を意識できるようになった"),
    (("文法",), "正しい文法で話せるように"),
    (("治安", "不安"), "初めての留学でも安心できた理由"),
    (("eop",), "EOP環境で使える英語が増えた"),
    (("表現", "増え"), "使える表現が増えた体験"),
    (("予習", "復習"), "予習復習を続けた学習習慣"),
    (("留学", "成長"), "留学で成長を実感した瞬間"),
)


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Candidate:
    start_ms: int
    end_ms: int
    start_index: int
    end_index: int
    score: float
    text: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def parse_args() -> argparse.Namespace:
    skill_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Analyze clean SRT and render vertical 9:16 shorts with centered 16:9 video "
            "on black background."
        ),
    )
    parser.add_argument("--video", required=True, help="Source video for clipping.")
    parser.add_argument(
        "--analysis-srt",
        required=True,
        help="Clean SRT used for short candidate detection.",
    )
    parser.add_argument(
        "--subtitle-srt",
        help=(
            "SRT used when burning subtitles onto shorts. Defaults to --analysis-srt. "
            "Ignored when --source-has-telop is set."
        ),
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output folder that will contain short clip folders.",
    )
    parser.add_argument(
        "--source-has-telop",
        action="store_true",
        help="Use this when the source video already has burned subtitles/telops.",
    )
    parser.add_argument(
        "--min-clips",
        type=int,
        default=DEFAULT_MIN_CLIPS,
        help=f"Minimum number of shorts to output (default: {DEFAULT_MIN_CLIPS}).",
    )
    parser.add_argument(
        "--max-clips",
        type=int,
        default=DEFAULT_MAX_CLIPS,
        help=f"Maximum number of shorts to output (default: {DEFAULT_MAX_CLIPS}).",
    )
    parser.add_argument(
        "--min-seconds",
        type=float,
        default=DEFAULT_MIN_SECONDS,
        help=f"Minimum short duration in seconds (default: {DEFAULT_MIN_SECONDS}).",
    )
    parser.add_argument(
        "--preferred-seconds",
        type=float,
        default=DEFAULT_PREFERRED_SECONDS,
        help=f"Preferred short duration in seconds (default: {DEFAULT_PREFERRED_SECONDS}).",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=DEFAULT_MAX_SECONDS,
        help=f"Maximum short duration in seconds (default: {DEFAULT_MAX_SECONDS}).",
    )
    parser.add_argument(
        "--font-file",
        default=str(skill_root / "assets" / "fonts" / "NotoSansJP-wght.ttf"),
    )
    parser.add_argument("--subtitle-font-name", default="Noto Sans JP")
    return parser.parse_args()


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


def parse_srt(path: Path) -> list[Cue]:
    source = path.read_text(encoding="utf-8")
    blocks = [
        block.strip()
        for block in source.replace("\ufeff", "").replace("\r\n", "\n").split("\n\n")
        if block.strip()
    ]
    cues: list[Cue] = []

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        timestamp_line = next((line for line in lines if "-->" in line), None)
        if not timestamp_line:
            continue
        start_raw, end_raw = [part.strip() for part in timestamp_line.split("-->")]
        text = "\n".join(
            line for line in lines if line != timestamp_line and not line.isdigit()
        ).strip()
        if not text:
            continue
        cues.append(
            Cue(
                start_ms=parse_timecode(start_raw),
                end_ms=parse_timecode(end_raw),
                text=text,
            )
        )

    return cues


def dump_srt(cues: list[Cue]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_timecode(cue.start_ms)} --> {format_timecode(cue.end_ms)}",
                    cue.text,
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def normalize_search_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def normalize_display_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_interviewer_like(text: str) -> bool:
    compact = normalize_search_text(text)
    return any(pattern in compact for pattern in INTERVIEWER_LIKE_PATTERNS)


def is_question_like(text: str) -> bool:
    normalized = normalize_display_text(text)
    return normalized.endswith(("?", "？", "ですか", "ますか", "でしょうか"))


def score_candidate(
    cues: list[Cue],
    start_index: int,
    end_index: int,
    preferred_ms: int,
) -> float:
    start_text = cues[start_index].text
    merged_text = normalize_display_text(" ".join(cue.text for cue in cues[start_index:end_index + 1]))
    merged_search = normalize_search_text(merged_text)
    opening_search = normalize_search_text(start_text)[:48]
    score = 0.0

    if is_interviewer_like(start_text):
        score -= 3.5
    else:
        score += 2.5

    if is_question_like(merged_text):
        score -= 2.0

    score += 2.0 if any(keyword in opening_search for keyword in HOOK_KEYWORDS) else 0.0
    score += sum(1.0 for keyword in VALUE_KEYWORDS if keyword.lower() in merged_search)

    duration_ms = cues[end_index].end_ms - cues[start_index].start_ms
    distance = abs(duration_ms - preferred_ms) / 1000.0
    score -= min(3.0, distance * 0.07)

    if len(merged_text) < 25:
        score -= 1.5
    if "..." in merged_text or "えー" in merged_text:
        score -= 0.4

    return score


def generate_candidates(
    cues: list[Cue],
    min_ms: int,
    preferred_ms: int,
    max_ms: int,
) -> list[Candidate]:
    candidates: list[Candidate] = []

    for start_index in range(len(cues)):
        local: list[Candidate] = []
        start_ms = cues[start_index].start_ms
        for end_index in range(start_index, len(cues)):
            end_ms = cues[end_index].end_ms
            duration_ms = end_ms - start_ms
            if duration_ms > max_ms:
                break
            if duration_ms < min_ms:
                continue

            merged_text = normalize_display_text(
                " ".join(cue.text for cue in cues[start_index:end_index + 1])
            )
            if len(merged_text) < 20:
                continue

            local.append(
                Candidate(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    start_index=start_index,
                    end_index=end_index,
                    score=score_candidate(cues, start_index, end_index, preferred_ms),
                    text=merged_text,
                )
            )

        local.sort(key=lambda candidate: candidate.score, reverse=True)
        candidates.extend(local[:3])

    deduped: dict[tuple[int, int], Candidate] = {}
    for candidate in candidates:
        key = (candidate.start_ms, candidate.end_ms)
        previous = deduped.get(key)
        if previous is None or previous.score < candidate.score:
            deduped[key] = candidate

    return list(deduped.values())


def overlap_ratio(left: Candidate, right: Candidate) -> float:
    overlap = max(0, min(left.end_ms, right.end_ms) - max(left.start_ms, right.start_ms))
    shorter = max(1, min(left.duration_ms, right.duration_ms))
    return overlap / shorter


def select_candidates(
    candidates: list[Candidate],
    min_clips: int,
    max_clips: int,
) -> list[Candidate]:
    ranked = sorted(
        candidates,
        key=lambda candidate: (candidate.score, candidate.duration_ms),
        reverse=True,
    )
    selected: list[Candidate] = []

    for candidate in ranked:
        if any(overlap_ratio(candidate, existing) > 0.45 for existing in selected):
            continue
        if candidate.score < 0.3 and len(selected) >= min_clips:
            continue
        selected.append(candidate)
        if len(selected) >= max_clips:
            break

    if len(selected) < min_clips:
        for candidate in ranked:
            if candidate in selected:
                continue
            if any(overlap_ratio(candidate, existing) > 0.80 for existing in selected):
                continue
            selected.append(candidate)
            if len(selected) >= min_clips or len(selected) >= max_clips:
                break

    return sorted(selected, key=lambda candidate: candidate.start_ms)


def build_default_title(text: str) -> str:
    sentence = normalize_display_text(text)
    sentence = re.sub(r"[「」『』【】\[\]（）()]", "", sentence)
    sentence = re.sub(r"[!?！？。、,.]", " ", sentence)
    sentence = re.sub(r"\s+", " ", sentence).strip()
    if len(sentence) > 18:
        sentence = sentence[:18]
    if not sentence:
        sentence = "ショート切り抜き"
    return sentence


def sanitize_file_component(value: str) -> str:
    sanitized = "".join("_" if character in INVALID_FILENAME_CHARS else character for character in value)
    sanitized = sanitized.strip(" .")
    return sanitized or "ショート切り抜き"


def choose_title(candidate: Candidate, used: set[str]) -> str:
    text_search = normalize_search_text(candidate.text)
    base_title = ""
    for keywords, rule_title in TITLE_RULES:
        if all(keyword in text_search for keyword in keywords):
            base_title = rule_title
            break
    if not base_title:
        base_title = build_default_title(candidate.text)

    base_title = sanitize_file_component(base_title)
    if base_title not in used:
        used.add(base_title)
        return base_title

    suffix = 2
    while True:
        candidate_title = f"{base_title}_{suffix}"
        if candidate_title not in used:
            used.add(candidate_title)
            return candidate_title
        suffix += 1


def escape_filter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")


def choose_video_codec() -> list[str]:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise SystemExit("ffmpeg command not found in PATH.")

    encoders = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    if "h264_videotoolbox" in encoders:
        return [
            "-c:v",
            "h264_videotoolbox",
            "-b:v",
            "8M",
            "-maxrate",
            "8M",
            "-bufsize",
            "16M",
        ]

    return [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
    ]


def make_clip_srt(cues: list[Cue], start_ms: int, end_ms: int) -> list[Cue]:
    clipped: list[Cue] = []
    for cue in cues:
        if cue.end_ms <= start_ms or cue.start_ms >= end_ms:
            continue
        clipped_start = max(cue.start_ms, start_ms) - start_ms
        clipped_end = min(cue.end_ms, end_ms) - start_ms
        if clipped_end - clipped_start < 120:
            continue
        clipped.append(Cue(start_ms=clipped_start, end_ms=clipped_end, text=cue.text))
    return clipped


def render_short(
    source_video: Path,
    output_video: Path,
    start_sec: float,
    end_sec: float,
    source_has_telop: bool,
    subtitle_srt: Path | None,
    font_file: Path,
    subtitle_font_name: str,
) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise SystemExit("ffmpeg command not found in PATH.")

    base_layout = "scale=1080:608:flags=lanczos,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
    if source_has_telop:
        video_filter = f"{base_layout},format=yuv420p"
    else:
        if subtitle_srt is None:
            raise SystemExit("subtitle_srt is required when source has no telop.")
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
        escaped_subtitle = escape_filter_value(str(subtitle_srt))
        escaped_font_dir = escape_filter_value(str(font_file.parent))
        subtitle_filter = (
            f"subtitles='{escaped_subtitle}':fontsdir='{escaped_font_dir}':"
            f"force_style='{style}'"
        )
        video_filter = f"{base_layout},{subtitle_filter},format=yuv420p"

    codec_args = choose_video_codec()
    command = [
        ffmpeg_path,
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-to",
        f"{end_sec:.3f}",
        "-i",
        str(source_video),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        video_filter,
        *codec_args,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_video),
    ]
    subprocess.run(command, check=True)


def is_source_telop(video_path: Path, has_telop_flag: bool) -> bool:
    if has_telop_flag:
        return True
    return "テロップ付き" in video_path.stem


def main() -> None:
    args = parse_args()
    video_path = Path(args.video).expanduser().resolve()
    analysis_srt_path = Path(args.analysis_srt).expanduser().resolve()
    subtitle_srt_path = (
        Path(args.subtitle_srt).expanduser().resolve()
        if args.subtitle_srt
        else analysis_srt_path
    )
    output_dir = Path(args.output_dir).expanduser().resolve()
    font_file = Path(args.font_file).expanduser().resolve()

    for path in (video_path, analysis_srt_path):
        if not path.exists():
            raise SystemExit(f"Required path not found: {path}")
    if not args.source_has_telop and not subtitle_srt_path.exists():
        raise SystemExit(f"Subtitle SRT not found: {subtitle_srt_path}")
    if not font_file.exists():
        raise SystemExit(f"Font file not found: {font_file}")
    if args.max_clips < args.min_clips:
        raise SystemExit("--max-clips must be greater than or equal to --min-clips.")
    if args.max_seconds <= args.min_seconds:
        raise SystemExit("--max-seconds must be greater than --min-seconds.")

    min_ms = int(math.floor(args.min_seconds * 1000))
    preferred_ms = int(math.floor(args.preferred_seconds * 1000))
    max_ms = int(math.floor(args.max_seconds * 1000))

    cues = parse_srt(analysis_srt_path)
    if not cues:
        raise SystemExit("Analysis SRT is empty. Cannot select short clips.")

    candidates = generate_candidates(cues, min_ms=min_ms, preferred_ms=preferred_ms, max_ms=max_ms)
    selected = select_candidates(candidates, min_clips=args.min_clips, max_clips=args.max_clips)
    if len(selected) < args.min_clips:
        raise SystemExit(
            f"Only {len(selected)} short candidates were found. "
            f"Need at least {args.min_clips}. Check SRT quality or loosen constraints."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    source_has_telop = is_source_telop(video_path, args.source_has_telop)
    subtitle_cues = parse_srt(subtitle_srt_path)
    used_titles: set[str] = set()
    manifest: list[dict[str, object]] = []

    for index, candidate in enumerate(selected, start=1):
        title = choose_title(candidate, used_titles)
        folder_name = f"{index:02d}_{title}"
        clip_dir = output_dir / folder_name
        clip_dir.mkdir(parents=True, exist_ok=True)

        clip_video = clip_dir / f"{folder_name}.mp4"
        clip_srt = clip_dir / f"{folder_name}.srt"

        clipped_cues = make_clip_srt(
            cues=subtitle_cues,
            start_ms=candidate.start_ms,
            end_ms=candidate.end_ms,
        )
        clip_srt.write_text(dump_srt(clipped_cues), encoding="utf-8")

        render_short(
            source_video=video_path,
            output_video=clip_video,
            start_sec=candidate.start_ms / 1000.0,
            end_sec=candidate.end_ms / 1000.0,
            source_has_telop=source_has_telop,
            subtitle_srt=None if source_has_telop else clip_srt,
            font_file=font_file,
            subtitle_font_name=args.subtitle_font_name,
        )

        manifest.append(
            {
                "rank": index,
                "title": folder_name,
                "startSec": round(candidate.start_ms / 1000.0, 3),
                "endSec": round(candidate.end_ms / 1000.0, 3),
                "durationSec": round(candidate.duration_ms / 1000.0, 3),
                "score": round(candidate.score, 3),
                "videoPath": str(clip_video),
                "srtPath": str(clip_srt),
                "excerpt": candidate.text[:120],
            }
        )

    manifest_path = output_dir / "00_切り抜き候補一覧.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Short clips output: {output_dir}")
    print(f"Short clips count: {len(selected)}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
