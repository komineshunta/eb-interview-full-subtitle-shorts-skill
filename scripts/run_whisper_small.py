#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


RAW_FILE_MAP = {
    ".srt": "01_whisper_small_raw.srt",
    ".txt": "01_whisper_small_raw.txt",
    ".json": "01_whisper_small_raw.json",
    ".tsv": "01_whisper_small_raw.tsv",
    ".vtt": "01_whisper_small_raw.vtt",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Whisper small and store raw transcript files in the EB telop asset folder.",
    )
    parser.add_argument("video", help="Path to the interview video.")
    parser.add_argument(
        "--delivery-base-name",
        help="Japanese base name used for the asset folder, e.g. ケントさんインタビュー.",
    )
    parser.add_argument(
        "--asset-dir",
        help="Optional explicit asset folder. Defaults to <delivery-base-name>_テロップ素材 beside the video.",
    )
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="Japanese")
    parser.add_argument("--task", default="transcribe", choices=["transcribe", "translate"])
    return parser.parse_args()


def resolve_asset_dir(video_path: Path, delivery_base_name: str | None, asset_dir_arg: str | None) -> Path:
    if asset_dir_arg:
        return Path(asset_dir_arg).expanduser().resolve()

    folder_base = delivery_base_name or video_path.stem
    return video_path.parent / f"{folder_base}_テロップ素材"


def run_whisper(video_path: Path, asset_dir: Path, model: str, language: str, task: str) -> None:
    whisper_path = shutil.which("whisper")
    if not whisper_path:
        raise SystemExit("whisper command not found in PATH.")

    asset_dir.mkdir(parents=True, exist_ok=True)

    command = [
        whisper_path,
        str(video_path),
        "--model",
        model,
        "--language",
        language,
        "--task",
        task,
        "--output_dir",
        str(asset_dir),
        "--output_format",
        "all",
        "--verbose",
        "False",
    ]

    subprocess.run(command, check=True)


def rename_outputs(video_path: Path, asset_dir: Path) -> None:
    stem = video_path.stem
    for extension, target_name in RAW_FILE_MAP.items():
        source = asset_dir / f"{stem}{extension}"
        if not source.exists():
            continue
        target = asset_dir / target_name
        if target.exists():
            target.unlink()
        source.replace(target)


def main() -> None:
    args = parse_args()
    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")

    asset_dir = resolve_asset_dir(video_path, args.delivery_base_name, args.asset_dir)
    run_whisper(video_path, asset_dir, args.model, args.language, args.task)
    rename_outputs(video_path, asset_dir)

    print(f"Raw Whisper outputs written to {asset_dir}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
