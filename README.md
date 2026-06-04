# ScholarMind（文渊）— 跨语言学术文献智能调研系统

**学术文献智能调研 Copilot**：支持双栏 PDF、公式及图表深度解析，提供精准的中文溯源问答，并基于引用网络实现跨文献对比与自动化综述生成。

## 能力

- 多论文问答 + 角标溯源（定位页码 / 回显原图）
- 单篇深读（讲清方法 / 解释公式 / 看懂图表）
- 跨论文对比（多跳，基于引用图谱）
- 自动文献综述（Agentic，带引用）
- 多轮对话 + 记忆
- 意图识别：闲聊不走检索，知识问题走 RAG，复杂走 Agent

## 技术栈

FastAPI · Vue3 · LlamaIndex · Milvus · MySQL · PostgreSQL · Redis · MinIO · GROBID · Qwen3 系列

## 快速开始

```bash
# 1. 复制环境配置文件
cp backend/.env.example backend/.env      # 填模型 API Key

# 2. 启动基础设施与后端 API
# 方式 A：直接构建并启动所有容器
docker compose up -d --build

# 方式 B：如遇网络中断，可以分步拉取依赖镜像，然后再启动
docker compose pull
docker compose up -d --build

# 3. 前端本地跑（方便联调）
cp frontend/.env.example frontend/.env
cd frontend
npm install
# 本地启动
npm run dev
# 打包
npm run build
```

- 后端 API：http://localhost:8008/docs
- 前端 UI：http://localhost:5173
- MinIO 控制台：http://localhost:9001

## 文档

- 架构：[docs/architecture.md](docs/architecture.md)
- 数据契约（schema 真相源）：[docs/data-contracts.md](docs/data-contracts.md)
- RAG 优化点：[docs/rag-pipeline.md](docs/rag-pipeline.md)
- API：[docs/api.md](docs/api.md) ｜ 部署：[docs/deploy.md](docs/deploy.md)
- 给 AI 协作的指引：[CLAUDE.md](CLAUDE.md)

---

## 🛠️ 项目成员开发任务指南 (2日周期 TodoList)

当前**项目基础设施编排**、**前后端代码骨架**以及**数据库初始化 SQL** 均已全部开发完成，并经语法和配置验证通过。

项目成员需完成以下任务，完成核心业务逻辑对接：

### 🏁 基础设施准备 (全员/运维)
- [ ] 复制 `backend/.env.example` 为 `backend/.env`，填写实际的 `LLM_API_KEY`（如通义千问/DeepSeek 等 OpenAI 兼容接口键值）和 MEMBEDDING_API_KEY 和 RERANK_API_KEY 。
- [ ] 启动本地 Docker 编排：`docker compose up -d --build`，确认全部容器正常运行。
- [ ] 在 `frontend/` 目录下执行 `npm install` 安装新增 of `axios`, `pinia`, `vue-router` 依赖。

### 📁 任务 1：解析服务对接 (`backend/services/parsing`)
- [ ] **MinerU API 对接**：在 `parsing` 逻辑中，使用已安装的 `mineru-kie-sdk` 中的 `MineruKIEClient`，上传 PDF，轮询获取双栏正文、公式 (LaTeX)、表格 (HTML) 和抠出的图。
- [ ] **参考文献提取（LLM 方式）**：使用 LLM 配合 `prompts/extract_references.md` 提示词从论文文本中提取参考文献列表，写入 MySQL `citations` 表。
- [ ] **VLM 图片描述**：将抠图上传至 MinIO `figures` bucket，调用 `qwen3.7-plus` (配合 `figure_caption.md` 提示词) 生成中文图像描述。
- [ ] **数据归一化入库**：将 MinerU 解析出的全部 block 写入 MySQL `doc_blocks` 表，并更新 `papers` 状态。

### 📁 任务 2：切分与向量化入库 (`backend/services/indexing`)
- [ ] **智能切分**：编写切分器，读取 `doc_blocks` 文本内容并按章节/语义切分（重叠度 15-20%），大表格和公式块整体保留不切分。
- [ ] **双语增强**：调用 LLM，配合 `prompts/enrich_zh_summary.md` 提示词为英文文本块生成中文摘要及关键词，写入 `content_zh`。
- [ ] **向量化写入 Milvus**：调用 Embedding 获取 dense+sparse 向量。使用 Milvus 客户端初始化 collection（配置 HNSW 索引与 Partition Key），将分块批量（Bulk）写入 Milvus。

### 📁 任务 3：混合检索服务 (`backend/services/retrieval`)
- [ ] **查询优化**：使用 `asyncio.gather` 并发调用 LLM 对 Query 进行改写、翻译 (中译英) 和 HyDE 假设文档生成。
- [ ] **检索与重排**：构造 Milvus 的 `user_id` 和作用域（如 `paper_id` / `folder_id`）过滤表达式，进行 `dense + sparse` 混合检索。获取结果后使用 RRF (互惠排名融合) 算法合并，并调用 Reranker 模型进行 Top-N 重排。
- [ ] **自适应过滤**：实现 Corrective RAG 对检索质量打分，决定是否重写检索或拒绝回答。对接 Redis 缓存层，对相似问题实现秒级返回。

### 📁 任务 4：对话与 Agent 综述 (`backend/services/chat_agent`)
- [ ] **意图路由**：在 `chat_agent` 中使用 `intent_router` 提示词进行分类分流，过滤闲聊。
- [ ] **多轮记忆**：连接 PostgreSQL `scholarmind_memory` 库，读取/保存会话历史 (`conversations`/`messages` 表)。
- [ ] **Agent 综述生成**：使用 LlamaIndex Agent，接收复杂综述/对比请求，分解子查询并检索多篇论文，使用 `review_generation` 提示词输出带引用的综述。
- [ ] **SSE 流式输出**：通过 FastAPI EventSourceResponse 流式推送生成的文本，并在引用处推送 `cite` 结构化事件。

### 📁 任务 5：前端页面与 API 联调 (`frontend/src`)
- [ ] **接口联调**：将各页面的 Mock 方法替换为真实的 Axios 请求（如注册/登录、文献上传进度轮询、设置保存）。
- [ ] **流式对话与引用溯源**：在 `Chat.vue` 中解析 SSE 事件流，实时渲染文本。点击 `[n]` 角标或底部引用卡片时，向右侧 Preview 区域传递并渲染出对应的段落原文、HTML 表格或者插图图片。
- [ ] **可观测可视化**：在 `Observability.vue` 中获取并展示真实的导入进度 and Query 历史日志。
