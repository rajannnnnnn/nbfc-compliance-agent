"""Ad-hoc runner (not part of app/ or eval/'s own CLI): paces LLMClient.structured() calls to
stay under the Gemini free tier's 5 requests/minute limit for gemini-2.5-flash, then delegates
to eval.harness.run_suite unchanged. This is a call-site wrapper around the client (the same
pattern tests/integration/eval/test_harness.py's _stub_client uses), not a production retry
loop — CLAUDE.md's "no agents, no open-ended tool loops" concerns control flow inside the
product; proactively pacing a real eval run against a real free-tier quota is neither.
"""

import asyncio
import sys

from app.config import get_settings
from app.corpus.snapshot import get_active_snapshot_id
from app.db.engine import get_sessionmaker
from app.llm.client import LLMClient
from app.schema.registry import FieldRegistry
from eval.harness import run_suite

DELAY_S = 13.0


async def main(suite: str) -> None:
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = LLMClient(settings)

    real_structured = client.structured

    async def _paced_structured(*args, **kwargs):
        await asyncio.sleep(DELAY_S)
        return await real_structured(*args, **kwargs)

    client.structured = _paced_structured  # type: ignore[method-assign]

    async with sm() as session:
        snapshot_id = await get_active_snapshot_id(session)
        if snapshot_id is None:
            raise SystemExit("no active corpus snapshot")
        report = await run_suite(
            suite,
            session=session,
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=client,
        )
    print(f"case_count={report['case_count']}")
    for k, v in report["metrics"].items():
        if k not in ("per_field", "case_count"):
            print(f"{k}: {v}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "extraction_core"))
