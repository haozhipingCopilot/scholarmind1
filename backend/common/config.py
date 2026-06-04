import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_ENV: str = "dev"
    APP_PORT: int = 8000
    SECRET_KEY: str = "change-me-in-prod-please"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    RATE_LIMIT_PER_MIN: int = 60

    # LLM
    LLM_PROVIDER: str = "qwen"
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_API_KEY: str = "sk-xxxxxxxx"
    LLM_MODEL: str = "qwen3.7-max"
    LLM_REASON_MODEL: str = "qwen3.7-thinking"
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 4096

    # Embedding
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_MODEL: str = "qwen3-embedding"
    EMBEDDING_BASE_URL: Optional[str] = "http://embedding:80/v1"
    EMBEDDING_API_KEY: Optional[str] = ""
    EMBEDDING_DIM: int = 1024
    EMBEDDING_BATCH: int = 32
    # local_path mode parameters
    EMBEDDING_MODEL_PATH: Optional[str] = "/models/bge-m3"
    EMBEDDING_DEVICE: str = "cpu"

    # Rerank
    RERANK_PROVIDER: str = "local"
    RERANK_MODEL: str = "qwen3-reranker"
    RERANK_BASE_URL: Optional[str] = "http://reranker:80/rerank"
    RERANK_API_KEY: Optional[str] = ""
    RERANK_TOP_N: int = 5
    # local_path mode parameters
    RERANK_MODEL_PATH: Optional[str] = "/models/bge-reranker-v2-m3"
    RERANK_DEVICE: str = "cpu"

    # VLM
    VLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    VLM_API_KEY: str = "sk-xxxxxxxx"
    VLM_MODEL: str = "qwen3-vl"

    # Milvus
    MILVUS_URI: str = "http://milvus:19530"
    MILVUS_TOKEN: str = ""
    MILVUS_COLLECTION: str = "scholarmind_chunks"
    MILVUS_INDEX_TYPE: str = "HNSW"
    MILVUS_METRIC: str = "COSINE"

    # MySQL
    MYSQL_HOST: str = "mysql"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "change-me"
    MYSQL_DB: str = "scholarmind"

    # PostgreSQL
    PG_HOST: str = "postgres"
    PG_PORT: int = 5432
    PG_USER: str = "postgres"
    PG_PASSWORD: str = "change-me"
    PG_DB: str = "scholarmind_memory"

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # MinIO
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_PDF: str = "papers"
    MINIO_BUCKET_FIG: str = "figures"
    MINIO_SECURE: bool = False

    # Ingestion APIs
    MINERU_BASE_URL: str = "http://mineru:8000"
    MINERU_PIPELINE_ID: str = ""

    # Reference parser provider: llm (default, no extra container) | grobid (high accuracy, needs grobid ~4GB image)
    REFERENCE_PARSER_PROVIDER: str = "llm"
    GROBID_BASE_URL: str = "http://grobid:8070"

    # Retrieval
    RETRIEVAL_TOP_K: int = 20
    HYBRID_DENSE_WEIGHT: float = 0.6
    INGEST_MAX_CONCURRENCY: int = 2

    # RAG Optimization switches (from Option A)
    ENABLE_INTENT_ROUTER: bool = True
    ENABLE_QUERY_REWRITE: bool = True
    ENABLE_MULTI_QUERY: bool = False
    ENABLE_HYDE: bool = True
    ENABLE_QUERY_TRANSLATION: bool = True
    ENABLE_RERANK: bool = True
    ENABLE_CORRECTIVE_RAG: bool = False
    ENABLE_SELF_RAG_REFLECT: bool = False

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
