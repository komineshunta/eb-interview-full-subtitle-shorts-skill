---
name: EB_インタビュー全編字幕・縦動画切り抜き生成
description: Generate both a full-length EB interview telop video and multiple vertical short clips in one run. Use when given an EB interview video or folder and the goal is to produce (1) a horizontal full-video deliverable with top-left brand text, top-right chapter titles, and bottom-center full subtitles, and then (2) short-ready vertical 9:16 clips selected from clean SRT with self-contained/high-hook moments, minimum 8 clips, and additional clips when strong candidates exist.
---

# EB_インタビュー全編字幕・縦動画切り抜き生成

Use this skill for one-pass EB interview delivery: full-length telop video first, then vertical short clip generation.

## Default output

- Full video: `<日本語ベース名>_テロップ付き.mp4`
- Shorts folder: `<日本語ベース名>_縦型ショート切り抜き/`
- Shorts manifest: `<日本語ベース名>_縦型ショート切り抜き/00_切り抜き候補一覧.json`
- Shorts are exported as `NN_日本語テーマ名/NN_日本語テーマ名.mp4` (+ matching `.srt`).
- Use concise Japanese theme names that make the content of each short understandable at a glance.
- Default short count: minimum 8 clips, up to 12 by default when additional strong candidates exist.
- By default, remove `<日本語ベース名>_テロップ素材` after full render and short generation complete.
- Use `--keep-assets` only when you explicitly need the intermediate files to remain on disk.
- Do not leave preview renders or design-check stills unless the user explicitly asked for them.

## Full-video layout rules

- Top left: `格安フィリピン留学EB`
- Top right: current chapter title
- Bottom center: full Japanese subtitles
- Never rely on renderer-side automatic wrapping. Subtitle line breaks must be explicit in the generated subtitle file.
- Each subtitle cue must fit fully inside the visible frame on every machine.
- Subtitle rule: keep each cue to a maximum of 2 lines.
- If a subtitle would exceed 2 lines on screen, split that spoken unit into multiple consecutive subtitle cues and redistribute the cue timing.
- Line-break rule: keep each line within a conservative safe width of about 22 full-width Japanese characters.
- Count half-width Latin letters, digits, and spaces as narrower, but if a line looks borderline, split earlier rather than later.
- Break lines at phrase boundaries when possible, prioritizing punctuation such as `、。！？` and then natural word/space boundaries.
- If one spoken unit would need 3 lines or more even after line breaks, split it into multiple consecutive cues and redistribute the cue timing.
- Final safety rule: if there is any doubt that a subtitle may overflow, force an earlier break or an additional cue split until the whole subtitle is safely on-screen.

## 全編字幕テロップの表示ルール

- 字幕は常に最大2行以内に収める。
- 1行が長くなりすぎて画面左右にはみ出す形にしない。
- 長い発話は自然な意味単位で改行し、2行以内に収める。
- 2行でも長すぎる場合は意味を壊さない範囲で表示単位を分割する。
- 無理に1枚へ詰め込まず、自然な読みやすさを優先する。
- 句読点、読点、助詞、意味のかたまりを意識して改行する。
- 不自然な位置で単語や文節を切らない。
- 1字幕あたりの文字量が多すぎる場合は時間範囲を分割して複数字幕にする。
- 常にスマホ視聴で読みやすい長さを優先する。

## 禁止事項（全編字幕）

- 3行以上の字幕。
- 左右にはみ出す長文テロップ。
- 不自然な改行。
- 一瞬で読み切れない量の文字を1枚に詰め込むこと。

## Short-video layout rules

- Output is always 9:16.
- Background is black.
- Source 16:9 video is never cropped.
- Place the 16:9 source in the center of the vertical canvas.
- Never apply left/right crop or unnatural zoom.
- If source already has telop burned in, keep it as-is.
- If source has no telop, burn subtitles from clean SRT into each short.

## Required process

1. Resolve the target interview video.
2. Decide a clear Japanese delivery base name before rendering.
3. Run Whisper with the `small` model. Execute from repository root:

```bash
python3 scripts/run_whisper_small.py \
  "/path/to/interview.mp4" \
  --delivery-base-name "ケントさんインタビュー"
```

This writes the raw transcript files into `<日本語ベース名>_テロップ素材` as:

- `01_whisper_small_raw.srt`
- `01_whisper_small_raw.txt`
- `01_whisper_small_raw.json`
- `01_whisper_small_raw.tsv`
- `01_whisper_small_raw.vtt`

4. Read the raw transcript and correct it manually in-context:
- Fix obvious ASR errors.
- Preserve what was actually said. Do not rewrite into polished prose.
- Verify proper nouns against the source folder, filenames, speaker names, EB terminology, and any user-provided context.
- If a name is still uncertain, make the least risky correction and state the assumption in the final response.
- While correcting subtitles, proactively insert or adjust line breaks so each cue is already close to the final 2-line on-screen layout.
- Do not leave long single-line cues assuming ffmpeg/libass will wrap them later.
- If a corrected subtitle still looks like it would exceed 2 lines on screen, expect the delivery build step to split it into multiple time-distributed cues rather than letting it overflow.
- Save the corrected subtitle as `02_修正字幕.srt` inside the asset folder.

5. Create chapter boundaries from topic shifts:
- Usually 8 to 15 chapters for one full interview.
- Titles should be short, specific, and useful both on-screen and in YouTube timestamps.
- Save chapters to `04_チャプター.json` as an array of:

```json
[
  {
    "startSec": 0,
    "endSec": 97,
    "title": "EB18年で最年少、13歳で単身留学"
  }
]
```

6. Build the delivery package and render the final video from repository root:

```bash
python3 scripts/build_full_interview_delivery.py \
  --video "/path/to/interview.mp4" \
  --corrected-srt "/path/to/<日本語ベース名>_テロップ素材/02_修正字幕.srt" \
  --chapters-json "/path/to/<日本語ベース名>_テロップ素材/04_チャプター.json" \
  --delivery-base-name "ケントさんインタビュー"
```

This script:

- copies the corrected SRT into the asset folder if needed
- generates `03_2行テロップ字幕.srt`
- rewrites each cue into explicit screen-safe line breaks
- keeps each cue to at most 2 lines
- splits overlong cues into multiple time-distributed cues when 2 lines are not enough
- normalizes and stores `04_チャプター.json`
- generates `05_YouTubeタイムスタンプ.txt`
- generates `06_ffmpeg_filtergraph.txt`
- renders `<日本語ベース名>_テロップ付き.mp4`
- analyzes clean SRT and selects short-ready clip windows
- prioritizes 30-60 second clips (allows up to 90 seconds for strong content)
- exports at least 8 vertical shorts when transcript quality permits
- exports more than 8 when additional strong, non-overlapping candidates are found
- writes short outputs into `<日本語ベース名>_縦型ショート切り抜き/`
- removes the asset folder after a successful final render unless `--keep-assets` is passed
- removes old preview-style junk in the source folder for the same interview

## Short selection policy

- Prioritize moments where EB's appeal comes through as a complete short even without earlier context.
- Prioritize segments that communicate clear EB value, especially class quality, teacher support, learning progress, motivation or confidence gain, daily life, safety, food, comfort, or concrete reasons the stay felt worthwhile.
- Prefer self-contained answer blocks that still make sense without the preceding exchange and have a clear beginning, middle, and conclusion.
- Start clips on the student's own speech whenever possible.
- Keep the interviewer's question only when removing it would make the student's answer confusing.
- Prefer segments with a strong hook in the opening seconds when the surrounding narrative also holds together as one short.
- Prefer segments that include learning, realization, emotion, or surprising points when they remain understandable on their own.
- Exclude greetings, backchannels, filler, and fragments that feel underexplained or depend heavily on missing setup.
- If multiple candidate windows make the same point, keep the cleaner and more compact one.
- Do not pad with weak clips just to hit a number.
- If fewer than 8 valid candidates are available, revise transcript cleanup/chapter assumptions and rerun.

## Delivery rules

- Final user-facing deliverables are:
  - one full-length Japanese-named telop mp4
  - one short-clip folder with multiple vertical clips and clear Japanese names
- Name each short clip folder and exported video after that clip's main theme in concise Japanese so the content is clear from the filename alone.
- By default, no telop asset folder should remain after final render + short export.
- If timestamps are needed after cleanup, rely on the script stdout or the final response, not a kept file.
- Preview mp4/png files, prototype files, and design-check stills should not remain after the final run unless the user asked to keep them.
- The final response must include:
  - full video path
  - short clips folder path
  - number of generated short clips
  - YouTube timestamps text

## Notes

- The bundled renderer uses `ffmpeg`.
- By default, subtitles and drawtext use bundled `assets/fonts/NotoSansJP-wght.ttf`.
- Override `--subtitle-font-name` or `--drawtext-font-name` only when you intentionally switch font families.
- On macOS it prefers `h264_videotoolbox`; otherwise it falls back to `libx264`.
- If you only need to validate chapter/timestamp/filtergraph generation, use `--skip-render` on the build script.
- Use `--skip-shorts` if you intentionally need full-video output only.
- Use `--shorts-min-clips`, `--shorts-max-clips`, `--shorts-min-seconds`, `--shorts-preferred-seconds`, and `--shorts-max-seconds` to tune short export behavior.
- `--skip-render` keeps the asset folder because no final deliverable has been completed yet.
