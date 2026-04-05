#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_short_clips.py"
)
SPEC = importlib.util.spec_from_file_location("build_short_clips", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ShortClipSelectionTests(unittest.TestCase):
    def test_make_clip_srt_rebases_to_zero(self) -> None:
        cues = [
            MODULE.Cue(start_ms=1_000, end_ms=5_000, text="最初は不安でした。"),
            MODULE.Cue(start_ms=5_500, end_ms=9_000, text="でも成長を実感しました。"),
        ]

        clipped = MODULE.make_clip_srt(cues, start_ms=2_000, end_ms=8_000)

        self.assertEqual(clipped[0].start_ms, 0)
        self.assertEqual(clipped[0].end_ms, 3_000)
        self.assertEqual(clipped[1].start_ms, 3_500)
        self.assertEqual(clipped[1].end_ms, 6_000)

    def test_interviewer_like_opening_gets_lower_score(self) -> None:
        cues = [
            MODULE.Cue(start_ms=0, end_ms=10_000, text="どうですか、感想を教えてください。"),
            MODULE.Cue(start_ms=10_000, end_ms=22_000, text="最初は不安でしたが成長を実感しました。"),
            MODULE.Cue(start_ms=22_000, end_ms=35_000, text="学びが多くて驚きました。"),
        ]

        interviewer_start = MODULE.score_candidate(cues, 0, 2, preferred_ms=45_000)
        student_start = MODULE.score_candidate(cues, 1, 2, preferred_ms=45_000)

        self.assertLess(interviewer_start, student_start)

    def test_choose_title_ensures_uniqueness(self) -> None:
        used: set[str] = set()
        candidate = MODULE.Candidate(
            start_ms=0,
            end_ms=40_000,
            start_index=0,
            end_index=1,
            score=1.0,
            text="TOEICの学習方法で1か月150点アップできました。",
        )

        first = MODULE.choose_title(candidate, used)
        second = MODULE.choose_title(candidate, used)

        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith(first))


if __name__ == "__main__":
    unittest.main()
