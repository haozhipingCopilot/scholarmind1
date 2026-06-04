"""
RQ job functions. Each function is a synchronous entry point that drives the
async parsing pipeline via asyncio.run().

Enqueue example:
    from rq import Queue
    q = Queue("ingest", connection=redis_conn)
    q.enqueue(do_parse_paper, task_id=1, paper_id=5, user_id=3, pdf_key="abc/paper.pdf")
"""
import asyncio

from common.db.mysql import get_db_session
from common.logging import logger
from services.parsing.parser import parse_paper


def do_parse_paper(
    *,
    task_id: int,
    paper_id: int,
    user_id: int,
    pdf_key: str,
) -> dict:
    """
    RQ job entry point (synchronous).
    Drives the async parse_paper pipeline and returns a summary dict.
    papers.status is updated to 'done' or 'failed' inside parse_paper.
    """
    logger.info(f"[worker] starting do_parse_paper task_id={task_id} paper_id={paper_id}")

    async def _run() -> dict:
        async with get_db_session() as db:
            result = await parse_paper(
                user_id=user_id,
                paper_id=paper_id,
                pdf_key=pdf_key,
                db=db,
            )
        return {
            "paper_id": result.paper_id,
            "block_count": len(result.blocks),
            "ref_count": len(result.references),
        }

    summary = asyncio.run(_run())
    logger.info(f"[worker] done task_id={task_id} summary={summary}")
    return summary
