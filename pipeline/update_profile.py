"""One-shot profile refresh for the hormuz-traffic Bluesky account.

Sets a keyword-rich display name + bio (profile text is a real discovery
channel in Bluesky search) and publishes + pins an explainer post. Safe to
re-run: it overwrites the profile fields and pins a fresh explainer each
time, so only run it when the copy below changes.

Run via .github/workflows/update-profile.yml (workflow_dispatch only).

Env:
  BLUESKY_HANDLE         default: hormuz-traffic.bsky.social
  BLUESKY_APP_PASSWORD   required
"""
from __future__ import annotations

import os
import sys

HANDLE = os.environ.get("BLUESKY_HANDLE", "hormuz-traffic.bsky.social")
APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD")

SITE_URL = "https://hormuz-traffic.com"
SITE_LABEL = "hormuz-traffic.com"

DISPLAY_NAME = "Strait of Hormuz Traffic"

# Bio cap is 256 graphemes.
BIO = (
    "Automated daily tracker of Strait of Hormuz shipping. Vessel transits "
    "from IMF PortWatch satellite AIS, charted vs pre-closure norms. Posts "
    "daily, fully automated. Charts & full history: hormuz-traffic.com — "
    "independent, not affiliated with the IMF."
)

PINNED_TEXT = (
    "Daily automated tracking of shipping through the Strait of Hormuz — "
    "vessel transits from IMF PortWatch satellite AIS, charted against "
    "pre-closure norms.\n\n"
    "Interactive charts & full history: "
)

PINNED_TAGS = ["#StraitOfHormuz", "#OOTT", "#Shipping", "#Maritime", "#Iran"]


def main() -> int:
    if not APP_PASSWORD:
        print("ERROR: BLUESKY_APP_PASSWORD env var not set", file=sys.stderr)
        return 2

    from atproto import Client, client_utils, models

    assert len(BIO) <= 256, f"bio is {len(BIO)} chars (max 256)"

    client = Client()
    client.login(HANDLE, APP_PASSWORD)

    # 1. Publish the explainer post (link + tag facets).
    tb = client_utils.TextBuilder()
    tb.text(PINNED_TEXT)
    tb.link(SITE_LABEL, SITE_URL)
    tb.text("\n\n")
    for i, tag in enumerate(PINNED_TAGS):
        if i:
            tb.text(" ")
        tb.tag(tag, tag[1:])
    post_ref = client.send_post(text=tb)
    print(f"Explainer post: {post_ref.uri}")

    # 2. Update the profile record in place, preserving avatar/banner blobs.
    existing = client.com.atproto.repo.get_record(
        models.ComAtprotoRepoGetRecord.Params(
            repo=client.me.did, collection="app.bsky.actor.profile", rkey="self"
        )
    )
    record = existing.value
    record.display_name = DISPLAY_NAME
    record.description = BIO
    record.pinned_post = models.ComAtprotoRepoStrongRef.Main(
        cid=post_ref.cid, uri=post_ref.uri
    )
    client.com.atproto.repo.put_record(
        models.ComAtprotoRepoPutRecord.Data(
            repo=client.me.did,
            collection="app.bsky.actor.profile",
            rkey="self",
            record=record,
            swap_record=existing.cid,
        )
    )
    print(f"Profile updated: name={DISPLAY_NAME!r}, bio {len(BIO)} chars, "
          f"pinned {post_ref.uri}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
