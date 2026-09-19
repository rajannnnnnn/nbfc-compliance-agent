"""Load and validate pinning against the live corpus. LLD §7.

The boot failure here is the important behaviour: it is how the system refuses to run
against a corpus it was not built for, rather than silently retrieving nothing.
"""

from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PinningMismatchError(Exception):
    """Raised with every unresolved path named, not just the first."""


def load_pinning_yaml(path: str | Path) -> dict[str, list[str]]:
    with open(path) as f:
        raw = yaml.safe_load(f)
    pins: dict[str, list[str]] = raw.get("pins", {})
    return pins


async def load_and_validate(
    snapshot_id: UUID, session: AsyncSession, *, pinning_path: str | Path
) -> dict[str, list[str]]:
    pins = load_pinning_yaml(pinning_path)
    all_paths = sorted({p for paths in pins.values() for p in paths})
    if not all_paths:
        return pins

    rows = await session.execute(
        text(
            "SELECT clause_path FROM clause WHERE snapshot_id = :sid AND clause_path = ANY(:paths)"
        ),
        {"sid": str(snapshot_id), "paths": all_paths},
    )
    resolved = {r[0] for r in rows}
    missing = [p for p in all_paths if p not in resolved]
    if missing:
        raise PinningMismatchError(
            f"{len(missing)} pinned clause path(s) not found in snapshot {snapshot_id}: {missing}"
        )
    return pins


def expand_parent_to_descendants(pinned_path: str, all_clause_paths: list[str]) -> list[str]:
    """A pinned parent paragraph (e.g. 'RBC2025/p35') expands to itself plus every clause
    whose path starts with it followed by '/' (its sub-clauses)."""
    result = [pinned_path]
    prefix = pinned_path + "/"
    result.extend(p for p in all_clause_paths if p.startswith(prefix))
    return result
