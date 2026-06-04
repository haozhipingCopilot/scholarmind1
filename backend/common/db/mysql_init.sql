-- MySQL schema initialization for ScholarMind

CREATE TABLE IF NOT EXISTS users (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  username      VARCHAR(64)  NOT NULL UNIQUE,
  email         VARCHAR(128) NOT NULL UNIQUE,
  password_hash VARCHAR(128) NOT NULL,            -- bcrypt
  role          VARCHAR(16)  NOT NULL DEFAULT 'user',  -- user | admin
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS folders (
  id         BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id    BIGINT NOT NULL,
  name       VARCHAR(128) NOT NULL,
  parent_id  BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_folders_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS papers (
  id           BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id      BIGINT NOT NULL,
  folder_id    BIGINT NULL,
  title        VARCHAR(512) NOT NULL,
  authors      JSON NULL,
  abstract     TEXT NULL,
  year         INT NULL,
  doi          VARCHAR(128) NULL,
  arxiv_id     VARCHAR(64)  NULL,
  source       VARCHAR(16)  NOT NULL DEFAULT 'upload',
  lang         VARCHAR(8)   NULL,
  file_hash    CHAR(16)     NOT NULL,
  pdf_key      VARCHAR(256) NOT NULL,
  num_pages    INT NULL,
  chunk_count  INT NOT NULL DEFAULT 0,
  status       VARCHAR(16)  NOT NULL DEFAULT 'pending', -- pending|done|failed
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_filehash (user_id, file_hash),
  INDEX idx_papers_user (user_id),
  INDEX idx_papers_folder (folder_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS doc_blocks (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT,
  paper_id    BIGINT NOT NULL,
  user_id     BIGINT NOT NULL,
  block_type  VARCHAR(16) NOT NULL,               -- text|table|figure|formula
  content     LONGTEXT NULL,                       -- table->HTML, formula->LaTeX, figure->caption
  content_zh  TEXT NULL,                           -- VLM generated Chinese description (figures only)
  page_num    INT NULL,
  bbox        JSON NULL,                           -- [page,left,top,right,bottom]
  image_key   VARCHAR(256) NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_blocks_paper (paper_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS citations (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  src_paper_id  BIGINT NOT NULL,
  dst_paper_id  BIGINT NULL,
  dst_title     VARCHAR(512) NULL,
  raw_ref       TEXT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_cit_src (src_paper_id),
  INDEX idx_cit_dst (dst_paper_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ingest_batches (
  id         BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id    BIGINT NOT NULL,
  total      INT NOT NULL DEFAULT 0,
  done       INT NOT NULL DEFAULT 0,
  failed     INT NOT NULL DEFAULT 0,
  status     VARCHAR(16) NOT NULL DEFAULT 'running', -- running|done
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_batch_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ingest_tasks (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT,
  batch_id    BIGINT NULL,
  user_id     BIGINT NOT NULL,
  paper_id    BIGINT NULL,
  file_name   VARCHAR(256) NOT NULL,
  file_hash   CHAR(16) NOT NULL,
  stage       VARCHAR(16) NOT NULL DEFAULT 'queued', -- queued|parsing|indexing|done|failed
  progress    TINYINT NOT NULL DEFAULT 0,
  error_msg   TEXT NULL,
  retry_count INT NOT NULL DEFAULT 0,
  started_at  DATETIME NULL,
  finished_at DATETIME NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_task_batch (batch_id),
  INDEX idx_task_user_stage (user_id, stage)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS query_logs (
  id                 BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id            BIGINT NOT NULL,
  conversation_id    BIGINT NULL,
  question           TEXT NOT NULL,
  rewritten_query    TEXT NULL,
  retrieved_chunk_ids JSON NULL,
  top_k              INT NULL,
  latency_ms         INT NULL,
  prompt_tokens      INT NULL,
  completion_tokens  INT NULL,
  feedback           TINYINT NULL,                 -- 1: up, -1: down, NULL: none
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_qlog_user (user_id),
  INDEX idx_qlog_time (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS access_logs (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id     BIGINT NULL,
  method      VARCHAR(8) NOT NULL,
  path        VARCHAR(256) NOT NULL,
  status_code INT NOT NULL,
  ip          VARCHAR(45) NULL,
  latency_ms  INT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_alog_time (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
