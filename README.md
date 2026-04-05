# EB Interview Full Subtitle + Vertical Shorts Skill

EBインタビュー動画を1回の運用で以下まで作るための再利用可能スキルです。

- 全編テロップ動画（16:9）
- 縦型ショート動画群（9:16、最低8本）

## 概要

このリポジトリは、以下の3段階を実行するためのスクリプトと手順を提供します。

1. Whisperで全編文字起こしを生成
2. 修正済み字幕とチャプター定義から全編テロップ動画をレンダリング
3. 同字幕を解析して縦型ショート候補を抽出・書き出し

## 必要環境

- OS: macOS / Linux（Windowsは未検証）
- Python: 3.10以上
- `ffmpeg` がPATHにあること
- `whisper` コマンドがPATHにあること（`openai-whisper`）

## セットアップ方法

### 1. リポジトリを取得

```bash
git clone <YOUR_REPO_URL>
cd eb-interview-full-subtitle-shorts-skill
```

### 2. Python依存をインストール

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 3. システム依存をインストール

- macOS (Homebrew)

```bash
brew install ffmpeg
```

- Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

## 実行方法

### Step 1: Whisper smallで生字幕生成

```bash
python3 scripts/run_whisper_small.py \
  "/path/to/interview.mp4" \
  --delivery-base-name "ケントさんインタビュー"
```

### Step 2: `02_修正字幕.srt` を手修正

Whisper出力（`01_whisper_small_raw.srt`）をベースに、ASR誤り・固有名詞・改行を修正して `02_修正字幕.srt` として保存します。

### Step 3: `04_チャプター.json` を作成

例:

```json
[
  {
    "startSec": 0,
    "endSec": 97,
    "title": "EB18年で最年少、13歳で単身留学"
  }
]
```

### Step 4: 全編+ショートを書き出し

```bash
python3 scripts/build_full_interview_delivery.py \
  --video "/path/to/interview.mp4" \
  --corrected-srt "/path/to/ケントさんインタビュー_テロップ素材/02_修正字幕.srt" \
  --chapters-json "/path/to/ケントさんインタビュー_テロップ素材/04_チャプター.json" \
  --delivery-base-name "ケントさんインタビュー"
```

## 入出力

### 入力

- インタビュー動画（`.mp4` 想定）
- 修正済み字幕（`02_修正字幕.srt`）
- チャプター定義（`04_チャプター.json`）

### 出力

- 全編: `<日本語ベース名>_テロップ付き.mp4`
- ショートフォルダ: `<日本語ベース名>_縦型ショート切り抜き/`
- ショート一覧: `<日本語ベース名>_縦型ショート切り抜き/00_切り抜き候補一覧.json`
- 付随生成（通常は素材フォルダ内）:
  - `03_2行テロップ字幕.srt`
  - `05_YouTubeタイムスタンプ.txt`
  - `06_ffmpeg_filtergraph.txt`

## 注意点

- 字幕は最終的に2行以内になるよう自動調整されますが、`02_修正字幕.srt` 時点で自然な改行にしておくと品質が安定します。
- デフォルトでは処理成功後に `<日本語ベース名>_テロップ素材` は削除されます（`--keep-assets` で保持可能）。
- 全編だけ必要なら `--skip-shorts` を使ってショート生成を無効化できます。
- 速度優先でmacOSでは `h264_videotoolbox`、それ以外では `libx264` を自動選択します。

## テスト

```bash
python3 -m unittest discover -s tests
```
