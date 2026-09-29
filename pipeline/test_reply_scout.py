"""Tests for the reply bot's pure parts: validation, parsing, eligibility.

Run:  python -m pytest pipeline/test_reply_scout.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reply_scout import (  # noqa: E402
    MAX_REPLY_CHARS, Candidate, ineligible_reason, parse_draft, replies_today, validate_reply,
)

NOW = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)


def _cand(uri="at://did:plc:x/app.bsky.feed.post/abc", author="someone.bsky.social"):
    return Candidate(uri=uri, cid="bafy", author_handle=author, author_display=author,
                     text="A post about Hormuz shipping", likes=40, reposts=2, replies=1,
                     created_at="", web_url="https://bsky.app/x")


def _entry(ts, uri, author, reply_uri="at://did:plc:us/app.bsky.feed.post/r1"):
    return {"ts": ts.isoformat(timespec="seconds"), "target_uri": uri,
            "target_author": author, "reply_uri": reply_uri}


def test_good_reply_passes():
    assert validate_reply("Transits are at 4% of the pre-closure norm, "
                          "3.1 ships a day on the 7-day average.") is None


def test_skip_and_empty():
    assert validate_reply("SKIP") == "skip"
    assert validate_reply("  skip ") == "skip"
    assert validate_reply("") == "skip"
    assert validate_reply("SKIP This post is political commentary, not shipping.") == "skip"


def test_rejects_without_a_number():
    assert validate_reply("Traffic through the strait is a fraction of what it was.") == "no concrete number"


def test_rejects_links_mentions_hashtags():
    assert validate_reply("See hormuz-traffic.com, 4% of normal") == "contains a link"
    assert validate_reply("As @someone said, 4% of normal") == "contains an @-mention"
    assert validate_reply("4% of normal #OOTT") == "contains a hashtag"


def test_rejects_em_dash_emoji_quotes_length():
    assert validate_reply("4% of normal — and falling") == "em dash"
    assert validate_reply("4% of normal 🚢") == "emoji"
    assert validate_reply('"4% of normal today"') == "wrapped in quotes"
    assert validate_reply("4 " + "x" * MAX_REPLY_CHARS).startswith("too long")


def test_banned_words_match_whole_words_only():
    assert validate_reply("Traffic remains at 4% of normal") == "banned phrase 'remains'"
    # 'navigate' is banned; 'navigation' is not
    assert validate_reply("Navigation warnings now cover 12 vessels") is None
    assert validate_reply("In the wake of the strikes, 3 ships") == "banned phrase 'in the wake of'"
    assert validate_reply("Only 3 ships today. Thoughts?") == "banned phrase 'thoughts?'"


def test_parse_draft_strips_numbering_and_newlines():
    assert parse_draft("1. Only 3 ships\ntransited today.") == "Only 3 ships transited today."
    assert parse_draft("- 3 ships") == "3 ships"
    assert parse_draft("  SKIP\n") == "SKIP"


def test_parse_draft_turns_em_dashes_into_commas():
    assert parse_draft("3.1 ships daily through Hormuz—4% of normal.") == \
        "3.1 ships daily through Hormuz, 4% of normal."
    assert validate_reply(parse_draft("Day 200 — 3 ships.")) is None


def test_never_reply_to_same_post_twice():
    c = _cand()
    log = [_entry(NOW - timedelta(days=30), c.uri, "other.bsky.social")]
    assert ineligible_reason(c, log, NOW) == "already replied to this post"


def test_author_cooldown():
    c = _cand(uri="at://new")
    recent = [_entry(NOW - timedelta(days=3), "at://old", c.author_handle)]
    assert "within 7 days" in ineligible_reason(c, recent, NOW)
    old = [_entry(NOW - timedelta(days=8), "at://old", c.author_handle)]
    assert ineligible_reason(c, old, NOW) is None


def test_unposted_entries_do_not_trigger_cooldown():
    c = _cand(uri="at://new")
    log = [_entry(NOW - timedelta(days=1), "at://old", c.author_handle, reply_uri=None)]
    assert ineligible_reason(c, log, NOW) is None


def test_replies_today_counts_only_today_and_posted():
    log = [_entry(NOW - timedelta(hours=2), "at://a", "x"),
           _entry(NOW - timedelta(hours=3), "at://b", "y", reply_uri=None),
           _entry(NOW - timedelta(days=1), "at://c", "z")]
    assert replies_today(log, NOW) == 1
