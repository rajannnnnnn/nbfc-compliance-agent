"""ingest() and verify() entry points. LLD §6.6.

`make ingest` calls ingest(activate=True); `make corpus-verify` calls verify(), which mutates
nothing.
"""

import argparse
import asyncio
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.config import Settings, get_settings
from app.corpus.chunk import chunk as chunk_nodes
from app.corpus.embed import embed_texts
from app.corpus.fetch import CorpusFetchError, fetch
from app.corpus.parsers.annex_table import AnnexTableParser
from app.corpus.parsers.base import ClauseNode
from app.corpus.parsers.continuous_para import ContinuousParaParser
from app.corpus.references import extract_references
from app.corpus.snapshot import (
    DriftEntry,
    DriftReport,
    IngestReport,
    InstrumentManifestEntry,
    activate_snapshot,
)
from app.corpus.sources import CorpusSourcesConfig, InstrumentSource, load_corpus_sources
from app.db.base import Base  # noqa: F401
from app.db.engine import get_sessionmaker
from app.llm.client import LLMClient

PARSER_VERSION = "continuous_para/1.0+annex_table/1.0"

ANNEX_DELIMITER = "=== ANNEX A ==="


class CorpusIngestError(Exception):
    pass


def _parse_instrument(inst: InstrumentSource, raw_text: str) -> list[ClauseNode]:
    """Strips the placeholder banner lines (leading '⚠ ' comments), then parses the main body
    with continuous_para and, if `has_annex`, the annex block(s) with annex_table — merged
    into one node list with continuing `order`."""
    lines = raw_text.splitlines()
    body_lines = [ln for ln in lines if not ln.lstrip().startswith("⚠")]
    cleaned = "\n".join(body_lines)

    if inst.has_annex and ANNEX_DELIMITER in cleaned:
        main_text, annex_text = cleaned.split(ANNEX_DELIMITER, 1)
        main_parser = ContinuousParaParser(dialect=inst.dialect)
        main_result = main_parser.parse(main_text)
        nodes = list(main_result.nodes)

        # The annex text may contain multiple header-delimited "parts" — a new part starts
        # whenever a line matching the header shape ('Sl No...') recurs after row content.
        annex_blocks = _split_annex_parts(annex_text)
        order_base = len(nodes)
        for part_idx, block in enumerate(annex_blocks, start=1):
            annex_parser = AnnexTableParser(part_number=str(part_idx))
            annex_result = annex_parser.parse(block)
            for n in annex_result.nodes:
                n.order += order_base
            nodes.extend(annex_result.nodes)
            order_base += len(annex_result.nodes)
        return nodes

    parser = ContinuousParaParser(dialect=inst.dialect)
    result = parser.parse(cleaned)
    return result.nodes


def _split_annex_parts(annex_text: str) -> list[str]:
    lines = [ln for ln in annex_text.splitlines() if ln.strip()]
    parts: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip().lower().startswith("sl no") and current:
            parts.append(current)
            current = []
        current.append(line)
    if current:
        parts.append(current)
    return ["\n".join(p) for p in parts]


def _apply_para_overrides(
    nodes: list[ClauseNode], inst: InstrumentSource
) -> dict[str, tuple[date | None, date | None]]:
    """Returns {para_number: (effective_from, effective_to)} for every override, after
    verifying the paragraph exists — an override naming a paragraph the parser did not find
    is a fatal ingest error (LLD §6.4)."""
    resolved: dict[str, tuple[date | None, date | None]] = {}
    known_para_numbers = {n.para_number for n in nodes}
    for para_number, override in inst.para_overrides.items():
        if para_number not in known_para_numbers:
            raise CorpusIngestError(
                f"{inst.code}: para_override for paragraph {para_number!r} but the parser "
                f"did not find that paragraph — parser and configuration disagree"
            )
        resolved[para_number] = (override.effective_from, override.effective_to)
    return resolved


def _effective_window(
    node: ClauseNode, inst: InstrumentSource, overrides: dict[str, tuple[date | None, date | None]]
) -> tuple[date | None, date | None]:
    if node.para_number in overrides:
        return overrides[node.para_number]
    return (inst.effective_from, inst.effective_to)


async def ingest(
    *,
    sources_path: str | Path | None = None,
    activate: bool = False,
    settings: Settings | None = None,
    session: AsyncSession | None = None,
) -> IngestReport:
    settings = settings or get_settings()
    sources_path = sources_path or settings.corpus_sources_path
    cfg = load_corpus_sources(sources_path)

    owns_session = session is None
    if owns_session:
        sessionmaker = get_sessionmaker(settings)
        session = sessionmaker()
    assert session is not None
    db: AsyncSession = session

    try:
        snapshot_id = uuid7()
        # Row must exist before any regulation_instrument/clause references it by FK.
        # Manifest and chunk_count are filled in with an UPDATE once both are known.
        await db.execute(
            text("""
                INSERT INTO corpus_snapshot
                    (id, instrument_manifest, embedding_model, embedding_dimension,
                     parser_version, chunk_count, is_active, notes)
                VALUES (:id, '[]'::jsonb, :model, :dim, :pver, 0, false, :notes)
                """),
            {
                "id": str(snapshot_id),
                "model": settings.embedding_model,
                "dim": settings.embedding_dimension,
                "pver": PARSER_VERSION,
                "notes": "placeholder corpus" if not settings.embedding_api_key else None,
            },
        )
        all_nodes_by_instrument: dict[str, list[ClauseNode]] = {}
        manifest_entries: list[InstrumentManifestEntry] = []
        warnings_by_instrument: dict[str, list[str]] = {}
        para_ranges: dict[str, tuple[str, str]] = {}
        instrument_ids: dict[str, UUID] = {}

        for inst in cfg.instruments:
            fetch_result = await fetch(inst.source_url, settings=settings)
            raw_text = Path(fetch_result.raw_path).read_text()

            if inst.has_annex:
                nodes = _parse_instrument(inst, raw_text)
                warnings: list[str] = []
            else:
                parser = ContinuousParaParser(dialect=inst.dialect)
                cleaned = "\n".join(
                    ln for ln in raw_text.splitlines() if not ln.lstrip().startswith("⚠")
                )
                result = parser.parse(cleaned)
                nodes = result.nodes
                warnings = result.warnings
                para_ranges[inst.code] = result.detected_para_range

            overrides = _apply_para_overrides(nodes, inst)
            all_nodes_by_instrument[inst.code] = nodes
            warnings_by_instrument[inst.code] = warnings

            instrument_id = uuid7()
            instrument_ids[inst.code] = instrument_id
            await db.execute(
                text("""
                    INSERT INTO regulation_instrument
                        (id, snapshot_id, code, official_title, circular_number, notification_id,
                         issued_on, effective_from, effective_to, status, applies_to_entity_types,
                         citable, verification_status, verification_note, source_url,
                         source_sha256, retrieved_at, page_count, parser_version, superseded_by_code)
                    VALUES
                        (:id, :sid, :code, :title, :circular, NULL,
                         :issued, :eff_from, :eff_to, :status, :entity_types,
                         :citable, :verification, :vnote, :source_url,
                         :sha, :retrieved_at, NULL, :pver, NULL)
                    """),
                {
                    "id": str(instrument_id),
                    "sid": str(snapshot_id),
                    "code": inst.code,
                    "title": inst.official_title,
                    "circular": inst.circular_number,
                    "issued": inst.issued_on,
                    "eff_from": inst.effective_from,
                    "eff_to": inst.effective_to,
                    "status": inst.status,
                    "entity_types": inst.applies_to_entity_types,
                    "citable": inst.citable,
                    "verification": inst.verification_status,
                    "vnote": inst.verification_note,
                    "source_url": inst.source_url,
                    "sha": fetch_result.sha256,
                    "retrieved_at": fetch_result.retrieved_at,
                    "pver": PARSER_VERSION,
                },
            )

            manifest_entries.append(
                InstrumentManifestEntry(
                    code=inst.code,
                    official_title=inst.official_title,
                    circular_number=inst.circular_number,
                    issued_on=inst.issued_on,
                    effective_from=inst.effective_from,
                    effective_to=inst.effective_to,
                    status=inst.status,
                    citable=inst.citable,
                    verification_status=inst.verification_status,
                    verification_note=inst.verification_note,
                    source_url=inst.source_url,
                    source_sha256=fetch_result.sha256,
                    retrieved_at=fetch_result.retrieved_at,
                    parser_version=PARSER_VERSION,
                    clause_count=len(nodes),
                )
            )

        # Chunk and write clauses, per instrument, tracking clause_path -> clause_id for
        # reference resolution.
        clause_id_by_path: dict[str, UUID] = {}
        all_texts_for_embedding: list[str] = []
        chunk_meta: list[dict[str, Any]] = []

        for inst in cfg.instruments:
            nodes = all_nodes_by_instrument[inst.code]
            overrides = _apply_para_overrides(nodes, inst)
            chunks = chunk_nodes(nodes)
            for c in chunks:
                node = c.node
                eff_from, eff_to = _effective_window(node, inst, overrides)
                clause_id = uuid7()
                clause_path = node.clause_path
                clause_id_by_path[f"{inst.code}/{clause_path}"] = clause_id
                chunk_meta.append(
                    {
                        "id": clause_id,
                        "instrument_code": inst.code,
                        "instrument_id": instrument_ids[inst.code],
                        "clause_path": f"{inst.code}/{clause_path}",
                        "chapter": node.chapter,
                        "chapter_title": node.chapter_title,
                        "section_letter": node.section_letter,
                        "section_title": node.section_title,
                        "para_number": node.para_number,
                        "para_sort": node.para_sort,
                        "level2_label": node.level2_label,
                        "level3_label": node.level3_label,
                        "heading": node.heading,
                        "text": node.text,
                        "text_with_stem": c.text_with_stem,
                        "token_count": c.token_count,
                        "chunk_kind": node.chunk_kind.value,
                        "chunk_strategy": c.chunk_strategy,
                        "chunk_index": c.chunk_index,
                        "effective_from": eff_from,
                        "effective_to": eff_to,
                        "citable": inst.citable,
                        "borrower_classes": node.applies_to_borrower_classes,
                    }
                )
                all_texts_for_embedding.append(c.text_with_stem)

        embeddings: list[list[float] | None] = []
        if settings.embedding_api_key:
            client = LLMClient(settings)
            embeddings = list(
                await embed_texts(all_texts_for_embedding, client=client, settings=settings)
            )
        else:
            embeddings = [None] * len(all_texts_for_embedding)

        for meta, vec in zip(chunk_meta, embeddings, strict=True):
            await db.execute(
                text("""
                    INSERT INTO clause
                        (id, snapshot_id, instrument_id, instrument_code, clause_path, chapter,
                         chapter_title, section_letter, section_title, para_number, para_sort,
                         level2_label, level3_label, heading, text, text_with_stem, token_count,
                         chunk_kind, chunk_strategy, chunk_index, effective_from, effective_to,
                         citable, applies_to_borrower_classes, embedding)
                    VALUES
                        (:id, :sid, :instrument_id, :instrument_code, :clause_path, :chapter,
                         :chapter_title, :section_letter, :section_title, :para_number, :para_sort,
                         :level2_label, :level3_label, :heading, :text, :text_with_stem, :token_count,
                         :chunk_kind, :chunk_strategy, :chunk_index, :effective_from, :effective_to,
                         :citable, :borrower_classes, :embedding)
                    """),
                {
                    **meta,
                    "sid": str(snapshot_id),
                    "instrument_id": str(meta["instrument_id"]),
                    "id": str(meta["id"]),
                    "embedding": vec,
                },
            )

        # Cross-instrument references.
        reference_edges: list[dict[str, str]] = []
        for inst in cfg.instruments:
            nodes = all_nodes_by_instrument[inst.code]
            other_instrument_patterns = {
                code: patterns
                for code, patterns in cfg.reference_title_patterns.items()
                if code != inst.code
            }
            edges = extract_references(
                nodes,
                other_instrument_patterns,
                instrument_is_amendment="AMD" in inst.code,
            )
            for e in edges:
                from_path = f"{inst.code}/{e.from_clause_path}"
                from_clause_id = clause_id_by_path.get(from_path)
                if from_clause_id is None:
                    continue
                await db.execute(
                    text("""
                        INSERT INTO clause_reference
                            (id, snapshot_id, from_clause_id, to_instrument_code, to_clause_path,
                             reference_text, reference_kind)
                        VALUES (:id, :sid, :from_id, :to_code, :to_path, :rtext, :kind)
                        """),
                    {
                        "id": str(uuid7()),
                        "sid": str(snapshot_id),
                        "from_id": str(from_clause_id),
                        "to_code": e.to_instrument_code,
                        "to_path": e.to_clause_path,
                        "rtext": e.reference_text,
                        "kind": e.reference_kind,
                    },
                )
                reference_edges.append(
                    {
                        "from": from_path,
                        "to_instrument": e.to_instrument_code,
                        "kind": e.reference_kind,
                    }
                )

        # Supersessions.
        for sup in cfg.supersessions:
            superseding_id = instrument_ids.get(sup.superseding_code)
            if superseding_id is None:
                continue
            await db.execute(
                text("""
                    INSERT INTO regulation_supersession
                        (id, snapshot_id, superseding_instrument_id, superseded_circular_number,
                         superseded_title, superseded_on)
                    VALUES (:id, :sid, :sup_id, :circ, :title, :on)
                    """),
                {
                    "id": str(uuid7()),
                    "sid": str(snapshot_id),
                    "sup_id": str(superseding_id),
                    "circ": sup.superseded_circular_number,
                    "title": sup.superseded_title,
                    "on": sup.superseded_on,
                },
            )

        manifest_json = [m.model_dump(mode="json") for m in manifest_entries]
        await db.execute(
            text("""
                UPDATE corpus_snapshot
                SET instrument_manifest = :manifest, chunk_count = :count
                WHERE id = :id
                """),
            {
                "id": str(snapshot_id),
                "manifest": __import__("json").dumps(manifest_json),
                "count": len(chunk_meta),
            },
        )

        if activate:
            await activate_snapshot(db, snapshot_id)

        if owns_session:
            await db.commit()

        return IngestReport(
            snapshot_id=snapshot_id,
            parser_version=PARSER_VERSION,
            embedding_model=settings.embedding_model,
            embedding_dimension=settings.embedding_dimension,
            chunk_count=len(chunk_meta),
            instruments=manifest_entries,
            warnings_by_instrument=warnings_by_instrument,
            reference_edges=reference_edges,
            detected_para_range_by_instrument=para_ranges,
        )
    finally:
        if owns_session:
            await db.close()


async def verify(
    *, sources_path: str | Path | None = None, settings: Settings | None = None
) -> DriftReport:
    """Re-fetches every source of the active snapshot's manifest, recomputes hashes, compares.
    Mutates nothing."""
    settings = settings or get_settings()
    sources_path = sources_path or settings.corpus_sources_path
    cfg = load_corpus_sources(sources_path)

    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        row = await session.execute(
            text("SELECT instrument_manifest FROM corpus_snapshot WHERE is_active = true")
        )
        manifest_json = row.scalar_one_or_none()

    entries: list[DriftEntry] = []
    if manifest_json is None:
        for inst in cfg.instruments:
            entries.append(
                DriftEntry(code=inst.code, status="unreachable", old_sha256="", new_sha256=None)
            )
        return DriftReport(entries=entries)

    import json as _json

    old_by_code = {m["code"]: m for m in _json.loads(manifest_json)}

    for inst in cfg.instruments:
        old = old_by_code.get(inst.code)
        old_sha = old["source_sha256"] if old else ""
        try:
            result = await fetch(inst.source_url, settings=settings)
            status = "unchanged" if result.sha256 == old_sha else "changed"
            entries.append(
                DriftEntry(
                    code=inst.code, status=status, old_sha256=old_sha, new_sha256=result.sha256
                )
            )
        except CorpusFetchError:
            entries.append(
                DriftEntry(
                    code=inst.code, status="unreachable", old_sha256=old_sha, new_sha256=None
                )
            )

    return DriftReport(entries=entries)


def render_corpus_report(report: IngestReport, cfg: CorpusSourcesConfig) -> str:
    lines = [
        "# Corpus Ingest Report",
        "",
        f"Snapshot: `{report.snapshot_id}`",
        f"Parser: `{report.parser_version}`",
        "",
    ]
    for inst_report in report.instruments:
        cfg.get(inst_report.code)
        lines.append(f"## {inst_report.code} — {inst_report.official_title}")
        lines.append("")
        lines.append(f"- Clause count: **{inst_report.clause_count}**")
        lines.append(
            f"- Verification status: **{inst_report.verification_status}**"
            + (f" — {inst_report.verification_note}" if inst_report.verification_note else "")
        )
        rng = report.detected_para_range_by_instrument.get(inst_report.code, ("", ""))
        lines.append(f"- Detected paragraph range: `{rng[0]}` .. `{rng[1]}`")
        warnings = report.warnings_by_instrument.get(inst_report.code, [])
        if warnings:
            lines.append(f"- Parser warnings ({len(warnings)}):")
            for w in warnings:
                lines.append(f"  - {w}")
        else:
            lines.append("- Parser warnings: none")
        lines.append("")

    lines.append("## Cross-reference edges")
    lines.append("")
    if report.reference_edges:
        for e in report.reference_edges:
            lines.append(f"- `{e['from']}` --{e['kind']}--> `{e['to_instrument']}`")
    else:
        lines.append("- none found")
    lines.append("")

    lines.append("## Open questions (PRD §14, Q1–Q5)")
    lines.append("")
    lines.append(
        "1. Recovery amendment circular number/date confirmed against a regulator-hosted page: **UNRESOLVED** — blocked on SQ-01 (network policy) and real source text (ADR-001)."
    )
    lines.append("2. Draft vs final paragraph numbering preserved: **UNRESOLVED** — same blocker.")
    lines.append(
        "3. Leaf-level sub-paragraph identifiers for RBC2025 KFS/penal/property/recovery-agent paragraphs: pinned at paragraph granularity (M1); tightening deferred to M5 per LLD §7."
    )
    lines.append(
        "4. General non-microfinance contact-hour provision before 2027: **UNRESOLVED against real text** — the placeholder corpus asserts none exists (RBC2025/p45 is scoped to microfinance only, RBC-AMD2026/p100W is the general provision but not yet in force), matching the PRD §11 example as written."
    )
    lines.append(
        "5. Amendment to either principal instrument since consolidated text was last stamped: **UNRESOLVED** — same blocker as Q1/Q2."
    )
    lines.append("")
    return "\n".join(lines)


async def _cli_ingest(activate: bool) -> None:
    settings = get_settings()
    cfg = load_corpus_sources(settings.corpus_sources_path)
    report = await ingest(settings=settings, activate=activate)
    md = render_corpus_report(report, cfg)
    Path("docs/CORPUS.md").write_text(md)
    print(
        f"Ingested snapshot {report.snapshot_id}: {report.chunk_count} clauses. docs/CORPUS.md written."
    )


async def _cli_verify() -> int:
    report = await verify()
    for e in report.entries:
        print(f"{e.code}: {e.status}")
    return 1 if report.any_changed else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    ingest_p = sub.add_parser("ingest")
    ingest_p.add_argument("--activate", action="store_true")
    sub.add_parser("verify")
    args = parser.parse_args()

    if args.command == "ingest":
        asyncio.run(_cli_ingest(args.activate))
    elif args.command == "verify":
        exit_code = asyncio.run(_cli_verify())
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
