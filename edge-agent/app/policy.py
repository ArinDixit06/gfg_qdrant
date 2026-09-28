"""Local vs. cloud data-placement policy.

This is the "dynamic decision" the problem statement asks for. It is evaluated
at WRITE TIME in the edge agent, not bolted on later. Given a data item's
category and flags, it decides:
  - keep_local:  always stored in the mutable edge shard (searchable offline)
  - sync_to_cloud: whether it is eligible to be pushed to the server

Rules (see design doc section 6):
  | Data type                          | local | cloud |
  | raw high-frequency (sensor/log)    |  yes  |  no   |  (volume/privacy)
  | derived summaries                  |  ---  |  yes  |
  | user notes/queries                 |  yes  |  yes  |
  | anything flagged private           |  yes  |  no   |
"""
from __future__ import annotations

from dataclasses import dataclass

RAW_CATEGORIES = {"sensor", "log", "raw"}
DERIVED_CATEGORIES = {"summary", "derived", "embedding"}


@dataclass(frozen=True)
class PlacementDecision:
    keep_local: bool
    sync_to_cloud: bool
    reason: str


def decide_placement(category: str, private: bool = False) -> PlacementDecision:
    category = (category or "note").lower()

    if private:
        return PlacementDecision(
            keep_local=True,
            sync_to_cloud=False,
            reason="flagged private — never leaves the device",
        )

    if category in RAW_CATEGORIES:
        return PlacementDecision(
            keep_local=True,
            sync_to_cloud=False,
            reason="raw high-frequency data — stays local (volume/privacy)",
        )

    if category in DERIVED_CATEGORIES:
        return PlacementDecision(
            keep_local=True,
            sync_to_cloud=True,
            reason="derived summary — synced to cloud",
        )

    # Default: user-generated notes/queries — local now, cloud after sync.
    return PlacementDecision(
        keep_local=True,
        sync_to_cloud=True,
        reason="user content — local immediately, synced to cloud",
    )
