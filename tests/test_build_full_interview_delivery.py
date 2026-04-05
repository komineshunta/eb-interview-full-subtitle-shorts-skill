#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_full_interview_delivery.py"
)
SPEC = importlib.util.spec_from_file_location(
    "build_full_interview_delivery",
    SCRIPT_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SubtitleWrappingTests(unittest.TestCase):
    def test_long_cue_splits_into_multiple_time_distributed_cues(self) -> None:
        cues = [
            {
                "startMs": 0,
                "endMs": 4000,
                "text": (
                    "これはとても長い字幕テキストで、二行では収まりきらないので"
                    "時間で安全に分割されるべき内容です。さらに続きます。"
                ),
            }
        ]

        split_cues = MODULE.split_long_cues(cues)

        self.assertGreater(len(split_cues), 1)
        self.assertEqual(split_cues[0]["startMs"], 0)
        self.assertEqual(split_cues[-1]["endMs"], 4000)

        previous_end = 0
        for cue in split_cues:
            self.assertEqual(cue["startMs"], previous_end)
            self.assertGreater(cue["endMs"], cue["startMs"])
            previous_end = cue["endMs"]

    def test_split_cues_never_exceed_two_lines(self) -> None:
        cues = [
            {
                "startMs": 1000,
                "endMs": 8000,
                "text": (
                    "英語力を伸ばすには授業だけではなく、寮生活や買い物の時間でも"
                    "自分から英語を使うことが大切だと実感しました。"
                ),
            }
        ]

        split_cues = MODULE.split_long_cues(cues)

        for cue in split_cues:
            lines = str(cue["text"]).split("\n")
            self.assertLessEqual(len(lines), MODULE.MAX_SUBTITLE_LINES)

    def test_each_wrapped_line_stays_within_safe_display_width(self) -> None:
        wrapped_lines = MODULE.wrap_subtitle_text(
            (
                "フィリピン留学の最初の一週間は不安もありましたが、"
                "先生やスタッフの支えで徐々に慣れていきました。"
            ),
            MODULE.MAX_LINE_WIDTH_UNITS,
        )

        self.assertGreater(len(wrapped_lines), 1)
        for line in wrapped_lines:
            self.assertLessEqual(
                MODULE.display_width(line),
                MODULE.MAX_LINE_WIDTH_UNITS,
            )

    def test_each_split_cue_keeps_readable_text_amount(self) -> None:
        cues = [
            {
                "startMs": 0,
                "endMs": 15000,
                "text": (
                    "留学初日はとても緊張していましたが、授業と生活を通して少しずつ慣れて、"
                    "自分の言いたいことを言えるようになった実感が生まれました。"
                    "さらに発音や文法への意識も高まりました。"
                ),
            }
        ]

        split_cues = MODULE.split_long_cues(cues)
        self.assertGreater(len(split_cues), 1)

        for cue in split_cues:
            self.assertLessEqual(
                MODULE.measure_page_weight(str(cue["text"])),
                MODULE.MAX_CUE_DISPLAY_UNITS,
            )

    def test_split_cues_get_enough_duration_when_total_time_allows(self) -> None:
        cues = [
            {
                "startMs": 1000,
                "endMs": 26000,
                "text": (
                    "最初は英語で話すのが怖かったのですが、毎日の授業と復習を続けることで"
                    "自分の中で使える表現が増えて、前よりも会話が続くようになりました。"
                    "その変化を実感できたことで学習のモチベーションがさらに上がりました。"
                ),
            }
        ]

        split_cues = MODULE.split_long_cues(cues)
        self.assertGreater(len(split_cues), 1)

        total_duration = split_cues[-1]["endMs"] - split_cues[0]["startMs"]
        minimum_segment = max(
            1,
            min(MODULE.MINIMUM_SEGMENT_MS, total_duration // len(split_cues)),
        )
        page_weights = [MODULE.measure_page_weight(str(cue["text"])) for cue in split_cues]
        required_durations = MODULE.compute_required_durations_ms(
            page_weights,
            minimum_segment_ms=minimum_segment,
            max_units_per_second=MODULE.MAX_READING_UNITS_PER_SECOND,
        )

        self.assertLessEqual(sum(required_durations), total_duration)
        for cue, required in zip(split_cues, required_durations):
            actual = int(cue["endMs"]) - int(cue["startMs"])
            self.assertGreaterEqual(actual, required)


if __name__ == "__main__":
    unittest.main()
