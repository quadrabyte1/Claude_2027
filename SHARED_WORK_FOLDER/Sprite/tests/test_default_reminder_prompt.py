"""Sprite prompt carries the default-to-reminder rule and matches Herman's list."""

import sys
from pathlib import Path

from sprite.parse import (
    CALENDAR_SIGNAL_WORDS,
    SIGNAL_WORDS_PLACEHOLDER,
    _SYSTEM_PROMPT,
)

HERMAN_BRAIN_SRC = Path("/Volumes/GIT/Claude_2027/SHARED_WORK_FOLDER/Homunculus/brain")
DEFAULT_RULE_PHRASE = "NO such signal is a reminder"


def test_prompt_has_no_unfilled_placeholder():
    assert SIGNAL_WORDS_PLACEHOLDER not in _SYSTEM_PROMPT


def test_prompt_lists_every_signal_word():
    for word in CALENDAR_SIGNAL_WORDS:
        assert f'"{word}"' in _SYSTEM_PROMPT


def test_prompt_states_default_rule():
    assert DEFAULT_RULE_PHRASE in _SYSTEM_PROMPT


def test_signal_list_matches_herman():
    sys.path.insert(0, str(HERMAN_BRAIN_SRC))
    from homunculus_brain.verb_default import CALENDAR_SIGNAL_WORDS as HERMAN_WORDS
    assert tuple(CALENDAR_SIGNAL_WORDS) == tuple(HERMAN_WORDS)
