"""
parse_paper: PDF → doc_blocks (MySQL) + citations (MySQL) + figures (MinIO).

Pipeline:
  1. MinerU KIE SDK — upload PDF, poll for parse/extract results → blocks
  2. Upload figure images to MinIO figures bucket, backfill image_key
  3. VLM          — figure description (async, per figure block)
  4. Ref parser   — extract citations from references section
       llm mode   : LLM reads references text → structured JSON
       grobid mode: POST PDF to GROBID → TEI XML parse (future)
  5. DB write     — insert doc_blocks, citations; update papers.status
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from common.clients.llm import chat_complete_json, vlm_describe_image
from common.config import settings
from common.logging import logger

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Block:
    block_type: str          # text | table | figure | formula
    content: str             # raw text / HTML / LaTeX / caption
    page_num: int | None = None
    bbox: list | None = None
    image_key: str | None = None  # MinIO key (figures only)
    content_zh: str = ""          # VLM description (figures) or empty

@dataclass
class ParseResult:
    paper_id: int
    user_id: int
    blocks: list[Block] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)  # {title, authors, year, raw_ref}
    title: str = ""
    abstract: str = ""

# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

def _load_prompt(name: str) -> str:
    path = Path(__file__).parents[3] / "prompts" / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    return match.group(1) if match else text


# ---------------------------------------------------------------------------
# Step 1: MinerU KIE SDK parsing
# ---------------------------------------------------------------------------

def _call_mineru_sync(pdf_path: str) -> dict:
    """Synchronous wrapper around MineruKIEClient (SDK is sync). Run via asyncio.to_thread."""
    from mineru_kie_sdk import MineruKIEClient

    client = MineruKIEClient(
        base_url=settings.MINERU_BASE_URL,
        pipeline_id=settings.MINERU_PIPELINE_ID,
        timeout=60,
    )
    file_ids = client.upload_file(pdf_path)
    logger.info(f"[parse] MinerU upload done, file_ids={file_ids}")
    results = client.get_result(file_ids, timeout=300, poll_interval=5)
    return results


async def _call_mineru(pdf_key: str) -> list[dict]:
    """
    1. Download PDF from MinIO to a temp file.
    2. Call MinerU KIE SDK (sync, runs in thread pool).
    3. Normalize the results into a list of raw block dicts.
    4. Clean up the temp file.
    """
    from common.clients.minio import download_to_tempfile

    tmp_path = await asyncio.to_thread(
        download_to_tempfile, settings.MINIO_BUCKET_PDF, pdf_key, ".pdf"
    )
    try:
        results = await asyncio.to_thread(_call_mineru_sync, tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    logger.debug(f"[parse] MinerU raw result keys: {list(results.keys())}")
    return _parse_mineru_results(results)


def _parse_mineru_results(results: dict) -> list[dict]:
    """
    Normalize MinerU parse/extract results into a uniform block list.

    Block dict schema:
      type       : str   — text | table | figure | formula
      content    : str   — plain text / HTML / LaTeX / caption
      page_num   : int | None
      bbox       : list | None
      image_data : bytes | None  — raw image bytes for figure blocks
    """
    blocks: list[dict] = []

    parse_data = results.get("parse") or {}
    # Defensively handle both list-at-root and list-under-"blocks"/"result" key
    if isinstance(parse_data, list):
        raw_items = parse_data
    elif isinstance(parse_data, dict):
        raw_items = parse_data.get("blocks") or parse_data.get("result") or []
    else:
        raw_items = []

    for item in raw_items:
        btype = item.get("type") or item.get("block_type") or "text"
        block: dict[str, Any] = {
            "type": btype,
            "content": item.get("content") or item.get("text") or "",
            "page_num": item.get("page_num") or item.get("page"),
            "bbox": item.get("bbox"),
            "image_data": None,
        }
        if btype == "figure":
            block["image_data"] = _extract_image_data(item)
        blocks.append(block)

    if not blocks:
        logger.warning("[parse] MinerU returned 0 blocks — check pipeline output format")

    return blocks


def _extract_image_data(item: dict) -> bytes | None:
    """Extract image bytes from a MinerU figure block (base64 str or raw bytes)."""
    if b64 := item.get("image_base64") or item.get("img_base64"):
        try:
            return base64.b64decode(b64)
        except Exception:
            return None
    if raw := item.get("image_data") or item.get("image"):
        return raw if isinstance(raw, bytes) else None
    return None


def _mineru_to_blocks(raw_blocks: list[dict]) -> list[Block]:
    return [
        Block(
            block_type=rb["type"],
            content=rb["content"],
            page_num=rb.get("page_num"),
            bbox=rb.get("bbox"),
        )
        for rb in raw_blocks
    ]


# ---------------------------------------------------------------------------
# Step 2: Upload figure images to MinIO, backfill block.image_key
# ---------------------------------------------------------------------------

async def _upload_figures_to_minio(blocks: list[Block], raw_blocks: list[dict]) -> None:
    """
    For each figure block that has image_data, upload to MinIO figures bucket
    and set block.image_key. Runs uploads concurrently.
    """
    from common.clients.minio import upload_bytes, ensure_bucket

    await asyncio.to_thread(ensure_bucket, settings.MINIO_BUCKET_FIG)

    async def _upload_one(block: Block, img_data: bytes) -> None:
        page = block.page_num or 0
        key = f"{page}/{uuid.uuid4().hex}.png"
        try:
            await asyncio.to_thread(upload_bytes, settings.MINIO_BUCKET_FIG, key, img_data, "image/png")
            block.image_key = key
        except Exception as e:
            logger.warning(f"[parse] MinIO figure upload failed: {e}")

    tasks = []
    for block, raw in zip(blocks, raw_blocks):
        if block.block_type == "figure":
            img_data = raw.get("image_data")
            if img_data:
                tasks.append(_upload_one(block, img_data))

    if tasks:
        await asyncio.gather(*tasks)
        logger.info(f"[parse] uploaded {len(tasks)} figure(s) to MinIO")


# ---------------------------------------------------------------------------
# Step 3: VLM figure descriptions (concurrent)
# ---------------------------------------------------------------------------

async def _describe_figures(blocks: list[Block]) -> None:
    """Fill content_zh for figure blocks in-place using VLM."""
    figure_blocks = [b for b in blocks if b.block_type == "figure" and b.image_key]
    if not figure_blocks:
        return

    async def _describe(block: Block) -> None:
        try:
            image_url = (
                f"http://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET_FIG}/{block.image_key}"
            )
            block.content_zh = await vlm_describe_image(image_url, caption=block.content)
        except Exception as e:
            logger.warning(f"[parse] VLM description failed for {block.image_key}: {e}")

    await asyncio.gather(*[_describe(b) for b in figure_blocks])


# ---------------------------------------------------------------------------
# Step 4a: Reference extraction — LLM mode
# ---------------------------------------------------------------------------

async def _extract_refs_llm(blocks: list[Block]) -> list[dict]:
    """Find the references section in text blocks and extract via LLM."""
    full_text = "\n".join(b.content for b in blocks if b.block_type == "text")

    ref_match = re.search(
        r"\b(?:References|Bibliography|参考文献)\b(.*)$",
        full_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not ref_match:
        logger.info("[parse] no references section found")
        return []

    references_text = ref_match.group(1).strip()
    if len(references_text) < 50:
        return []

    references_text = references_text[:8000]
    prompt_template = _load_prompt("extract_references")
    prompt = prompt_template.format(references_text=references_text)

    try:
        result = await chat_complete_json(prompt, system="You are an academic reference parser.")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return v
    except Exception as e:
        logger.warning(f"[parse] LLM reference extraction failed: {e}")

    return []


# ---------------------------------------------------------------------------
# Step 4b: Reference extraction — GROBID mode (future)
# ---------------------------------------------------------------------------

async def _extract_refs_grobid(pdf_bytes: bytes) -> list[dict]:
    """Parse references via GROBID TEI XML. Only used when REFERENCE_PARSER_PROVIDER=grobid."""
    url = f"{settings.GROBID_BASE_URL}/api/processFulltextDocument"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
            data={"consolidateReferences": "0"},
        )
        resp.raise_for_status()

    tei_xml = resp.text
    return _parse_tei_references(tei_xml)


def _parse_tei_references(tei_xml: str) -> list[dict]:
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError as e:
        logger.warning(f"[parse] GROBID TEI parse error: {e}")
        return []

    refs = []
    for bibl in root.findall(".//tei:listBibl/tei:biblStruct", ns):
        title_el = bibl.find(".//tei:title[@level='a']", ns) or bibl.find(".//tei:title", ns)
        title = title_el.text or "" if title_el is not None else ""

        authors = []
        for author in bibl.findall(".//tei:author/tei:persName", ns):
            forename = author.findtext("tei:forename", "", ns)
            surname = author.findtext("tei:surname", "", ns)
            name = f"{forename} {surname}".strip()
            if name:
                authors.append(name)

        year_el = bibl.find(".//tei:date[@type='published']", ns)
        year_text = year_el.get("when", "") if year_el is not None else ""
        year = int(year_text[:4]) if year_text and year_text[:4].isdigit() else None

        raw_ref = ET.tostring(bibl, encoding="unicode")
        refs.append({"title": title, "authors": authors, "year": year, "raw_ref": raw_ref})

    return refs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def parse_paper(
    user_id: int,
    paper_id: int,
    pdf_key: str,
    db: AsyncSession,
    *,
    pdf_bytes: bytes | None = None,  # required only for grobid mode
) -> ParseResult:
    """
    Full parse pipeline for one paper. Called from RQ worker (not request thread).
    Writes doc_blocks and citations to DB, returns ParseResult for indexing.
    """
    logger.info(f"[parse] paper_id={paper_id} user_id={user_id} provider={settings.REFERENCE_PARSER_PROVIDER}")

    try:
        # --- Step 1: MinerU KIE SDK ---
        raw_blocks = await _call_mineru(pdf_key)
        blocks = _mineru_to_blocks(raw_blocks)
        logger.info(f"[parse] MinerU returned {len(blocks)} blocks")

        # --- Step 2: Upload figures to MinIO ---
        await _upload_figures_to_minio(blocks, raw_blocks)

        # --- Step 3: VLM figure descriptions + reference extraction (concurrent) ---
        vlm_task = asyncio.create_task(_describe_figures(blocks))

        if settings.REFERENCE_PARSER_PROVIDER == "grobid":
            if pdf_bytes is None:
                logger.warning("[parse] grobid mode requires pdf_bytes, falling back to llm")
                references = await _extract_refs_llm(blocks)
            else:
                references = await _extract_refs_grobid(pdf_bytes)
        else:
            references = await _extract_refs_llm(blocks)

        await vlm_task
        logger.info(f"[parse] extracted {len(references)} references")

        # --- Step 4: Write to DB ---
        await _write_blocks(user_id, paper_id, blocks, db)
        await _write_citations(paper_id, references, db)
        await _update_paper_status(paper_id, "done", db)
        await db.commit()

    except Exception as e:
        logger.error(f"[parse] paper_id={paper_id} failed: {e}")
        try:
            await _update_paper_status(paper_id, "failed", db)
            await db.commit()
        except Exception:
            pass
        raise

    return ParseResult(
        paper_id=paper_id,
        user_id=user_id,
        blocks=blocks,
        references=references,
    )


# ---------------------------------------------------------------------------
# DB writes
# ---------------------------------------------------------------------------

async def _write_blocks(user_id: int, paper_id: int, blocks: list[Block], db: AsyncSession) -> None:
    from sqlalchemy import text
    for b in blocks:
        await db.execute(
            text("""
                INSERT INTO doc_blocks
                    (paper_id, user_id, block_type, content, content_zh, page_num, bbox, image_key)
                VALUES
                    (:paper_id, :user_id, :block_type, :content, :content_zh, :page_num, :bbox, :image_key)
            """),
            {
                "paper_id": paper_id,
                "user_id": user_id,
                "block_type": b.block_type,
                "content": b.content,
                "content_zh": b.content_zh or None,
                "page_num": b.page_num,
                "bbox": json.dumps(b.bbox) if b.bbox else None,
                "image_key": b.image_key,
            },
        )


async def _write_citations(paper_id: int, references: list[dict], db: AsyncSession) -> None:
    from sqlalchemy import text
    for ref in references:
        await db.execute(
            text("""
                INSERT INTO citations (src_paper_id, dst_title, raw_ref)
                VALUES (:src_paper_id, :dst_title, :raw_ref)
            """),
            {
                "src_paper_id": paper_id,
                "dst_title": ref.get("title", ""),
                "raw_ref": ref.get("raw_ref", ""),
            },
        )


async def _update_paper_status(paper_id: int, status: str, db: AsyncSession) -> None:
    from sqlalchemy import text
    await db.execute(
        text("UPDATE papers SET status = :status WHERE id = :paper_id"),
        {"status": status, "paper_id": paper_id},
    )
