import os
from redis import Redis
from rq import Queue, Worker, Connection
from common.config import settings
from common.logging import logger

# Import tasks so RQ worker process can deserialize enqueued jobs
import app.worker.tasks  # noqa: F401

def start_worker():
    logger.info("Starting ScholarMind RQ Worker...")
    
    # Establish connection to Redis
    redis_conn = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB
    )
    
    # Listen to the ingest queue
    queue_name = "ingest"
    with Connection(redis_conn):
        worker = Worker([Queue(queue_name)])
        logger.info(f"Worker listening on queue: {queue_name}")
        worker.work()

if __name__ == "__main__":
    start_worker()
