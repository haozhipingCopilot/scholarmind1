# 任务 1：解析服务对接 — 完整执行计划

> 状态：**待确认，不改代码**
> 当前 parser.py 已写好骨架，但对接的是一个假 HTTP 接口（`MINERU_BASE_URL/parse`），与真实 MinerU KIE SDK 不符。本次任务的核心工作是：**把 4 个功能点的实现细节都补对**。

---

## 一、现状诊断

| 文件 | 现状 | 问题 |
|---|---|---|
| `backend/services/parsing/parser.py` | 骨架完整，逻辑正确 | Step 1 调用了假的 HTTP 接口（`/parse`），不是 MinerU KIE SDK 的真实用法；MinIO 上传图片逻辑缺失；`_write_blocks` 缺 `content_zh` 字段写入 |
| `backend/common/clients/minio.py` | **文件不存在** | MinIO 客户端尚未实现，VLM 图描述依赖 MinIO URL |
| `backend/common/db/mysql.py` | **文件不存在** | AsyncSession 来源不明，parser 调用了 `AsyncSession` 但 DB 会话工厂还没建 |
| `backend/.env` | `MINERU_BASE_URL` 被注释掉 | 需要取消注释并填写真实值（或本地测试值） |
| `backend/common/config.py` | `MINERU_PIPELINE_ID` 缺失 | MinerU KIE SDK 初始化需要 `pipeline_id` |

---

## 二、4 个功能点详解

### 功能点 1：MinerU API 对接

**目标**：把 `_call_mineru()` 从伪 HTTP 调用改为调用已安装的 `mineru-kie-sdk`，完成上传→轮询→取结果→归一化 block。

**MinerU SDK 真实工作流（来自官方文档）**：
```
client = MineruKIEClient(base_url, pipeline_id)
file_ids = client.upload_file(pdf_path)          # 返回 List[int]
results = client.get_result(file_ids, timeout=300)  # 自动轮询
# results["parse"] / results["split"] / results["extract"]
```

**问题**：`parse_paper` 收到的是 `pdf_key`（MinIO 中的路径），SDK 需要本地文件路径。
**解决**：在调用 SDK 之前，先从 MinIO 下载 PDF 到临时文件，再传给 SDK；下载完清理临时文件。

**MinerU 返回结构（推断）**：`results["parse"]` 包含 block 列表。每个 block 的字段结构需要根据实际返回适配，预计包含：`type`（text/table/figure/formula）、`content`（文本/HTML/LaTeX/caption）、`page_num`、`bbox`、以及图片数据或图片存储引用。

**图片处理关键问题**：MinerU 返回的图片是 base64 二进制还是已上传到某处的 URL？根据 SDK 文档的 `extract` 步骤，图片很可能以 base64 或字节形式返回。需要我们自己上传到 MinIO `figures` bucket，再回填 `image_key`。

**改动文件**：
- `backend/services/parsing/parser.py` — 重写 `_call_mineru()` 函数
- `backend/common/clients/minio.py` — 新建，提供 `download_file()` 和 `upload_bytes()` 两个函数
- `backend/common/config.py` — 增加 `MINERU_PIPELINE_ID` 字段
- `backend/.env` — 取消注释 `MINERU_BASE_URL`，增加 `MINERU_PIPELINE_ID=<你的值>`

---

### 功能点 2：参考文献提取（LLM 方式）

**目标**：从 MinerU 解析出的文本 block 中找到参考文献章节，用 LLM + `extract_references.md` 提示词提取结构化列表，写入 MySQL `citations` 表。

**现状**：`_extract_refs_llm()` 和 `_write_citations()` 已写好，逻辑基本正确。

**存在的小问题**：
1. `_write_citations` 只写了 `dst_title` 和 `raw_ref`，缺少 `authors` 和 `year` 字段。`citations` 表虽然没有 `authors/year` 列，但这些字段在 LLM 返回的 JSON 里，可以考虑序列化后存入 `raw_ref`（或直接丢弃，因为表结构不含这两列）——**当前表结构已足够，无需改动**。
2. `extract_references.md` 中提示词使用了双大括号 `{{}}` 转义，这是 Jinja2 风格，但代码里直接用 `.format()` 方法——**双大括号在 Python `str.format()` 中是对 `{` 字面量的转义，输出 `{}`，是正确的**。
3. `json_mode=True` 时 DeepSeek 可能返回 JSON 对象而不是数组，代码已有 fallback 处理，可接受。

**改动文件**：
- `backend/services/parsing/parser.py` — **基本不需要改动**，逻辑已正确
- 如果要补全 `authors` 写入，需在 `citations` 表加列——**暂不改，保持当前 schema**

---

### 功能点 3：VLM 图片描述

**目标**：将 MinerU 抠出的图片上传到 MinIO `figures` bucket，调用 VLM（`qwen3.7-plus` + `figure_caption.md`）生成中文描述，存回 block 的 `content_zh` 字段。

**现状**：`_describe_figures()` 已写好 VLM 调用逻辑，但：
1. 假设图片已经在 MinIO，靠 `block.image_key` 直接拼 URL——**但 MinerU 不会自动上传到我们的 MinIO**，需要我们来做这一步。
2. `_write_blocks()` 目前**没有写 `content_zh`**，VLM 描述产出后会丢失。

**改动文件**：
- `backend/services/parsing/parser.py`：
  - 在 `_call_mineru()` 或新增函数 `_upload_figures_to_minio()` 中，把 MinerU 返回的图片字节上传到 MinIO，回填 `block.image_key`
  - 在 `_write_blocks()` 中增加 `content_zh` 列的写入
- `backend/common/clients/minio.py`（新建）：提供 `upload_bytes(bucket, key, data)` 函数

---

### 功能点 4：数据归一化入库

**目标**：将所有解析结果完整写入 MySQL `doc_blocks` 表，并更新 `papers` 表的 `status` 字段为 `done`（失败时改为 `failed`）。

**现状**：`_write_blocks()` 存在以下问题：
1. **缺少 `content_zh` 字段**（VLM 描述不写入 DB）
2. **缺少 `papers.status` 更新**——解析完成后 `papers` 表 `status` 应从 `pending` 改为 `done`，失败时改为 `failed`
3. `AsyncSession` 来源：`parse_paper` 接收 `db: AsyncSession` 参数，但调用方（RQ worker）目前没有建立数据库会话并传入

**改动文件**：
- `backend/services/parsing/parser.py`：
  - `_write_blocks()` 增加 `content_zh` 列
  - 新增 `_update_paper_status()` 函数，更新 `papers.status`
  - `parse_paper()` 中调用 `_update_paper_status()`，并用 `try/except` 包裹，捕获异常后将状态设为 `failed`
- `backend/common/db/mysql.py`（新建）：AsyncEngine + `get_db_session()` async context manager
- `backend/app/worker/main.py`：接收 RQ job 任务参数，创建 DB 会话后调用 `parse_paper()`

---

## 三、文件改动清单（完整）

### 新建文件（3 个）

| 文件路径 | 说明 |
|---|---|
| `backend/common/clients/minio.py` | MinIO 异步客户端：初始化 bucket、上传 bytes、下载文件到本地临时路径 |
| `backend/common/db/mysql.py` | AsyncEngine 工厂 + `get_db_session()` async context manager |
| `backend/worker/tasks.py` | RQ 任务函数 `do_parse_paper(task_id, paper_id, user_id, pdf_key)`，负责创建 DB 会话并调用 `parse_paper()`，写 `ingest_tasks` 状态 |

### 修改文件（4 个）

| 文件路径 | 改动内容 |
|---|---|
| `backend/services/parsing/parser.py` | ① 重写 `_call_mineru()`：用 SDK 替代 HTTP；② 新增 `_upload_figures_to_minio()`：图片上传并回填 `image_key`；③ `_write_blocks()` 增加 `content_zh` 列；④ 新增 `_update_paper_status()`；⑤ `parse_paper()` 调用新函数，加异常捕获更新 `failed` 状态 |
| `backend/common/config.py` | 增加 `MINERU_PIPELINE_ID: str = ""` 字段 |
| `backend/.env` | 取消注释 `MINERU_BASE_URL`，增加 `MINERU_PIPELINE_ID=xxx` |
| `backend/app/worker/main.py` | 目前是 `worker.work()` 裸监听，需要导入 RQ job 任务模块，确保任务函数可被 worker 找到 |

---

## 四、详细实现逻辑（伪代码级）

### 4.1 `backend/common/clients/minio.py`（新建）

```python
from minio import Minio
from common.config import settings
import tempfile, os

def _get_client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )

def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """上传字节到 MinIO，返回 key"""
    client = _get_client()
    # 用 io.BytesIO 包装，minio 库是同步的
    ...
    return key

def download_to_tempfile(bucket: str, key: str) -> str:
    """下载到本地临时文件，返回路径（调用方负责删除）"""
    client = _get_client()
    tmp = tempfile.mktemp(suffix=".pdf")
    client.fget_object(bucket, key, tmp)
    return tmp
```

> **注意**：`minio` Python SDK 是同步的。在 async 函数中调用时，需要用 `asyncio.to_thread()` 包装，避免阻塞事件循环。

### 4.2 `backend/common/db/mysql.py`（新建）

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager
from common.config import settings

DATABASE_URL = (
    f"mysql+aiomysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
    f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}"
)

engine = create_async_engine(DATABASE_URL, pool_size=settings.MYSQL_POOL_SIZE, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

@asynccontextmanager
async def get_db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 4.3 重写 `_call_mineru(pdf_key)` 核心逻辑

```python
async def _call_mineru(pdf_key: str) -> tuple[list[dict], dict[str, bytes]]:
    """
    1. 从 MinIO 下载 PDF 到临时文件
    2. 用 MineruKIEClient.upload_file() 上传
    3. 轮询 get_result() 拿 parse/extract 结果
    4. 归一化 block，图片数据以 {image_id: bytes} 形式返回
    5. 清理临时文件
    """
    from mineru_kie_sdk import MineruKIEClient
    import asyncio, os
    from common.clients.minio import download_to_tempfile

    # 同步 MinIO 下载放到线程池
    tmp_path = await asyncio.to_thread(
        download_to_tempfile, settings.MINIO_BUCKET_PDF, pdf_key
    )
    try:
        client = MineruKIEClient(
            base_url=settings.MINERU_BASE_URL,
            pipeline_id=settings.MINERU_PIPELINE_ID,
            timeout=60,
        )
        file_ids = await asyncio.to_thread(client.upload_file, tmp_path)
        results = await asyncio.to_thread(client.get_result, file_ids, timeout=300, poll_interval=5)
    finally:
        os.unlink(tmp_path)

    raw_blocks = _parse_mineru_results(results)
    return raw_blocks
```

### 4.4 `_parse_mineru_results()` 归一化逻辑

MinerU `results["parse"]` 的具体字段需要实测，但根据 SDK 文档模式，推断结构为：

```python
def _parse_mineru_results(results: dict) -> list[dict]:
    """
    将 MinerU 的 parse/extract 结果归一化为统一 block 格式。
    block 格式：{type, content, page_num, bbox, image_data(bytes|None)}
    """
    blocks = []
    parse_data = results.get("parse") or {}
    # MinerU 解析结果字段需实测后确认，先做防御性取值
    for item in parse_data.get("blocks", parse_data.get("result", [])):
        btype = item.get("type", "text")   # text | table | figure | formula
        block = {
            "type": btype,
            "content": item.get("content", ""),
            "page_num": item.get("page_num") or item.get("page"),
            "bbox": item.get("bbox"),
            # 图片：可能是 base64 字符串，或 "image_data" 字节字段
            "image_data": _extract_image_data(item) if btype == "figure" else None,
        }
        blocks.append(block)
    return blocks

def _extract_image_data(item: dict) -> bytes | None:
    """从 MinerU block 中提取图片字节，支持 base64 和原始 bytes"""
    import base64
    if b64 := item.get("image_base64"):
        return base64.b64decode(b64)
    if raw := item.get("image_data"):
        return raw if isinstance(raw, bytes) else None
    return None
```

> **⚠️ 关键不确定点**：MinerU KIE SDK 的实际返回字段（`results["parse"]` 的内部结构）在文档中没有给出具体示例，需要实际调用后 `print(results)` 确认字段名，再完善 `_parse_mineru_results()`。**建议在第一次真实调用时加 debug 日志打印原始结果**。

### 4.5 图片上传到 MinIO

```python
async def _upload_figures_to_minio(blocks: list[Block], raw_blocks: list[dict]) -> None:
    """将 MinerU 返回的图片字节上传到 MinIO figures bucket，回填 block.image_key"""
    import asyncio, uuid
    from common.clients.minio import upload_bytes

    for block, raw in zip(blocks, raw_blocks):
        if block.block_type != "figure":
            continue
        img_data = raw.get("image_data")
        if not img_data:
            continue
        # 用 uuid 生成唯一 key，避免碰撞
        key = f"{block.page_num or 0}/{uuid.uuid4().hex}.png"
        await asyncio.to_thread(upload_bytes, settings.MINIO_BUCKET_FIG, key, img_data, "image/png")
        block.image_key = key
```

### 4.6 `_write_blocks()` 增加 `content_zh`

```python
# 在 INSERT 语句中增加 content_zh 列：
INSERT INTO doc_blocks (paper_id, user_id, block_type, content, page_num, bbox, image_key, content_zh)
VALUES (:paper_id, :user_id, :block_type, :content, :page_num, :bbox, :image_key, :content_zh)
# 参数增加：
"content_zh": b.content_zh,
```

### 4.7 新增 `_update_paper_status()`

```python
async def _update_paper_status(paper_id: int, status: str, db: AsyncSession) -> None:
    from sqlalchemy import text
    await db.execute(
        text("UPDATE papers SET status = :status WHERE id = :paper_id"),
        {"status": status, "paper_id": paper_id},
    )
```

### 4.8 `parse_paper()` 增加异常捕获

```python
async def parse_paper(...) -> ParseResult:
    try:
        # ... 现有 Step 1-4 逻辑 ...
        await _update_paper_status(paper_id, "done", db)
        await db.commit()
        return result
    except Exception as e:
        logger.error(f"[parse] paper_id={paper_id} failed: {e}")
        try:
            await _update_paper_status(paper_id, "failed", db)
            await db.commit()
        except Exception:
            pass
        raise
```

### 4.9 `backend/worker/tasks.py`（新建）

```python
"""RQ 任务函数，在 worker 进程中同步运行（RQ 是同步的，用 asyncio.run() 驱动 async 代码）"""
import asyncio
from common.db.mysql import get_db_session
from services.parsing.parser import parse_paper
from common.logging import logger

def do_parse_paper(task_id: int, paper_id: int, user_id: int, pdf_key: str) -> dict:
    """RQ Job 入口（同步函数）"""
    async def _run():
        async with get_db_session() as db:
            result = await parse_paper(
                user_id=user_id,
                paper_id=paper_id,
                pdf_key=pdf_key,
                db=db,
            )
        return {"paper_id": result.paper_id, "block_count": len(result.blocks)}

    return asyncio.run(_run())
```

---

## 五、`.env` 需要补充的配置

```dotenv
# 取消注释并填写：
MINERU_BASE_URL=https://mineru.net/api/kie   # 或本地部署地址
MINERU_PIPELINE_ID=<你在 MinerU 平台创建的 Pipeline ID>
```

---

## 六、`doc_blocks` 表需要新增列

当前表没有 `content_zh` 列，需要在 `mysql_init.sql` 中补充：

```sql
-- 在 doc_blocks 表定义中增加：
content_zh  TEXT NULL,   -- VLM generated Chinese description (figures only)
```

**改动文件**：`backend/common/db/mysql_init.sql`

---

## 七、改动总结（优先级排序）

```
优先级 1（必须，否则跑不起来）：
  1. backend/common/db/mysql.py          新建 — DB 会话工厂
  2. backend/common/clients/minio.py     新建 — MinIO 客户端
  3. backend/common/config.py            修改 — 增加 MINERU_PIPELINE_ID
  4. backend/.env                        修改 — 启用 MINERU_BASE_URL + PIPELINE_ID
  5. backend/common/db/mysql_init.sql    修改 — doc_blocks 增加 content_zh 列

优先级 2（核心逻辑）：
  6. backend/services/parsing/parser.py  修改 — 重写 _call_mineru, 新增图片上传, 补 content_zh, 补 status 更新
  7. backend/worker/tasks.py             新建 — RQ Job 入口函数

优先级 3（联动）：
  8. backend/app/worker/main.py          修改 — 确保 worker 能找到 tasks 模块（import）
```

---

## 八、遗留不确定点（需要实测确认）

1. **MinerU `results["parse"]` 的确切字段结构** — SDK 文档未给出示例，需要打印原始返回值确认。
2. **MinerU 图片返回方式** — base64、bytes、还是已上传的 URL？影响 `_extract_image_data()` 的实现。
3. **`MINERU_PIPELINE_ID` 的值** — 需要用户在 MinerU 平台创建 Pipeline 后填入。
4. **MySQL 端口** — `.env` 中配置的是 `3307`，`config.py` 默认是 `3306`，`get_db_session` 的 DSN 要用 `settings.MYSQL_PORT`（已是如此，无问题）。

---

*确认后开始按优先级逐步改代码。*
