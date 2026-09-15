# 交接说明（HANDOVER.md）—— 本文件由上一轮对话生成，供下一轮对话接手

> **给接手的 agent 的第一条指令**：先读 `AGENTS.md`（唯一权威施工总纲）与 `docs/DOMAIN_RULES.md`
> （领域规则与算法参数），再读 `docs/DECISIONS.md`（ADR-001…ADR-011 + 各轮验收记录），
> 然后读本文件了解"现在站在哪里"。**不要凭常识补全任何规则数字**。

- 工作区：`D:\exam_select`（无空格）
- 生成时间：M4 完成后
- 下一轮起点：**M5（Agent 层与防幻觉）**

---

## 1. 项目是什么（一句话）

面向 3+3 新高考六省市（浙江/上海/北京/山东/天津/海南）的志愿填报辅助系统：
**所有数字由确定性算法计算并附证据链，LLM 只做"理解意图 / 解释结果 / 追问澄清"**。
最高原则：**宁可不答，不可编造**。志愿填报的错误是人生事故，不是体验问题。

---

## 2. 当前进度与真实状态

| Phase | 内容 | 状态 |
|---|---|---|
| M0 | 项目骨架与领域模型 | ✅ 完成 |
| M1 | 数据层与模拟数据生成（六省 20 个批次级规则包） | ✅ 完成 |
| M2 | 核心算法引擎（rank/probability/filters/scoring/planner/risk/backtest） | ✅ 完成 |
| M3 | 后端 API（§7 全端点 + L2 访问层 + L4 编排 + 报告导出） | ✅ 完成 |
| M4 | 前端（5 个页面 + 强类型契约 + 选考科目池 + 覆盖率统计） | ✅ 完成 |
| **M5** | **Agent 层与防幻觉** | ⬜ **下一轮** |
| M6 | 真实数据接入 | ⬜（范围另议，需用户确认数据来源授权） |
| M7 | 加固与交付 | ⬜ |

### 可复现的实测结果（不是"应该通过"）

| 项 | 实测 |
|---|---|
| 后端测试 | `201 passed`（API 集成 25 项 / 配置 5 项 / 算法与数据其余） |
| 算法层覆盖率 `app.core` | **95.62%**（门槛 ≥90%） |
| 黄金用例 | **38 条**（概率 21 / 过滤 12 / 规则 5） |
| 回测（浙江 2025，811 单位 × 150 考生 × 21,184 样本） | 保底失效率 **0.00%** · 稳档命中率 **86.02%** · 冲档命中率 **31.43%** · Brier **0.0057** |
| API | `/api/v1` 下 **21 条** + `/health`；OpenAPI 3.1.0，**69 个强类型 schema** |
| 前端构建 | `vite build` ✓ 610 modules · `tsc --noEmit` 零错误 · vitest 10 项通过 |
| 前端端到端 | `npm run smoke` 闭环全通（建档→换算→覆盖→推荐→志愿表→手改→导出） |
| 模拟数据 | 6 省市 · 418 院校 · 528 专业 · 4,645 投档单位 · 16,297 条历史 · 23,225 条计划快照 |

### git 状态

- 分支 `main`，远端 `https://github.com/dnjz666/exam_select.git`
- 上一轮末尾提交 `76a9b07`（M3 收尾修复 + README）；**M4 的提交见本轮末尾 `git log`**
- 用户偏好：**提交由我做、推送由用户确认**（"只提交不推送"）
- 推送注意：Git 凭据助手要创建命名管道，agent 会话沙箱默认拒绝
  （`sh.exe: couldn't create signal pipe, Win32 error 5`）
  → 推送需用户批准提权，或让用户在自己终端 `git push`

---

## 3. 环境事实（踩过坑，别再踩）

| 事项 | 事实 |
|---|---|
| Python | **必须用 `backend\.venv\Scripts\python.exe`**（3.11.9）。裸 `python` 是本机 3.13，禁止 |
| venv | `backend\.venv`；依赖装一次即可，只有 pyproject 变更/换机器/venv 损坏才需重装 |
| **pip** | `powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1`。**必须在真实终端跑**（沙箱拒绝 pip 的 mkdtemp） |
| **前端构建 / dev / test** | ★ **必须真实终端跑**：Vite/Vitest 要 spawn esbuild 原生二进制（管道 stdio），**agent 沙箱 `spawn EPERM`**。`pnpm typecheck`（纯 tsc）不受影响 |
| **网络** | ★ 本机 **schannel 在 agent 沙箱内不可用**（curl/Invoke-WebRequest 报 `SEC_E_NO_CREDENTIALS`），但 **Node 自带 TLS 正常** → `pnpm install`、`node scripts/*.mjs` 都能联网。排错时别误判成断网 |
| 数据库 | `data\exam_select.db`（SQLite，约 15 MB）。路径**锚定到仓库根**（`config.anchor_sqlite_url`） |
| 测试前置 | `pytest backend/tests` 依赖**已播种**的数据库；未播种会明确失败（不静默跳过） |
| PowerShell 坑 | **不要用 `curl.exe -d '{"json"}'` 发 POST**（双引号被吃 → 422）；用 `Invoke-RestMethod` + `ConvertTo-Json` |
| 终端中文 | 先 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` |
| pnpm | 工程设置写在 `frontend/pnpm-workspace.yaml`（**不再**读 package.json 的 `pnpm` 字段）：`allowBuilds` + `minimumReleaseAge` |
| **两个 pnpm** | ★ agent 会话里的 `pnpm` 是 **DSH shim（11.8.0，`minimumReleaseAge=0`）**；用户终端里的是**全局 pnpm 12.4.1**（默认 24h 供应链防护）。**凡涉及前端依赖，必须用全局 pnpm 复核**：`node "C:\nvm4w\nodejs\node_modules\pnpm\bin\pnpm.mjs" install --frozen-lockfile`。否则会重犯 ADR-012 的错（生成"本机合规、用户机不合规"的 lockfile） |
| `debug.log` | 根目录若出现，是 DSH Desktop 的 Electron crashpad 日志，非项目产物（已 gitignore） |

---

## 4. 验收命令（每轮结束必须真跑并贴输出）

```powershell
$py = 'backend\.venv\Scripts\python.exe'

# 数据（幂等；--reset 会清空学员档案与志愿表）
& $py scripts\seed.py --reset
& $py -m app.etl.validate --report                     # 期望 0 error

# 后端测试与覆盖率
& $py -m pytest backend/tests -q --cov=app.core --cov-fail-under=90   # 201 passed / 95.62%
& $py -m pytest backend/tests/test_api.py -q           # 25 项

# 回测（四项未达标则 exit 1）
& $py scripts\run_backtest.py --province zhejiang --year 2025

# 起服务
Set-Location backend
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# http://127.0.0.1:8000/docs   http://127.0.0.1:8000/health
```

**前端（M4 验收，必须真实终端）**

```powershell
Set-Location frontend
pnpm install
pnpm build          # prebuild 自动跑 gen:api（后端需在跑，否则回退 openapi.snapshot.json）
pnpm typecheck      # tsc --noEmit
pnpm test           # vitest（纯函数）
pnpm smoke          # 端到端闭环：node scripts/smoke.mjs 打真后端
```

---

## 5. 架构与不可违反的约束

```
L5 frontend/ (React18+TS+Vite+Tailwind+ECharts)   +   Agent对话(M5 未开始)
L4 backend/app/{api,services,main.py}   ← 本层才碰 DB / 网络 / LLM
L3 backend/app/core/**                  ← ★ 纯函数：无 IO、无 DB、无网络、无 LLM（ADR-003）
L2 backend/app/db/**  (models 表 + repositories 访问层)
L1 backend/app/etl/** (确定性模拟数据，seed 固定)
```

- **`core/` 纯函数铁律**：已由测试与覆盖率守护。
- **来源纪律**：任何规则数字必须带 `source_url`；`BatchRule` 还要 `source_quote` + `verified_status`
  + `verified_year`；`SubjectPool`（选考科目池）同受约束。响应里**禁止出现无来源的数字**。
- **契约铁律**（有测试守着）：① 每个推荐项 `evidence` 非空且带 `source_url`；
  ② `probability is None ⇔ confidence == NO_DATA` 且 `reasons` 说明原因；③ 无来源数字为零；
  ④ OpenAPI 是契约唯一来源，**响应体必须强类型**（M4 新增强制，见 ADR-011 决策 1）。
- **响应格式**：所有响应 `{data, evidence, warnings}`；错误 `{error:{code,message,details}}`
  （`PROFILE_INCOMPLETE` 409 · `RANK_UNAVAILABLE` 503 · `PLAN_NOT_FOUND` 404 · `UNKNOWN_UNITS` 422 ·
  `REPORT_UNAVAILABLE` 404 · `NOT_FOUND` 404 · `VALIDATION_ERROR` 422）。
- 红线（违反即返工）：`core/` 里 import DB/网络/LLM；硬编码分数线/位次/志愿数；
  让 LLM 产生数字；无证据链返回推荐；跳过回测改概率参数；用"应该能跑"代替实测。

---

## 6. 本轮（M4）的关键决策与新增契约

### 先补契约、再写界面（ADR-011，务必先读）

动手写界面前发现**照 M3 的契约写不出合格界面**，因此先做了 4 处后端改造：

1. **响应体全部强类型**：M3 的 `Envelope[dict]` 让"类型从 OpenAPI 生成"形同虚设
   （生成出来等价于 `unknown`）。现在 `RecommendItem` / `PlanPayload` / `ProvinceMeta` /
   `SubjectPoolMeta` / `SubjectCoveragePayload` / `TiersPayload` … 逐字段声明并挂到 `response_model`，
   OpenAPI 成了**校验器**（字段改名会 `ResponseValidationError`），共 69 个 schema。
2. **选考科目池（新增 `SubjectPool` + `/meta/provinces/{p}/subject-coverage`）**：
   §8.1 Step 2 需要"从该省 N 门中选 3 门"，M1 没有这个数据。
   六省均取到官方来源（浙江 7选3 含"技术"，其余 6选3；天津为 PRIMARY_GOV）。
   拿不到原文的省份降级为"招生计划反推"（`origin=DATA_DERIVED` + 前端提示），**不编造**。
   覆盖率用 `core.filters.subject_matches` 真实统计（实测可报 640/811）。
3. **`PATCH /plans/{id}/items` 候选池改为"生成时的候选池"**：
   M3 用"当前 items"当池 → **移除一个志愿后无法加回来**（志愿填报里这是危险缺陷，
   且与它自己的 docstring 矛盾）。现在用同一套 `evaluate_candidates` 现场重算，
   硬约束一条绕不过，池外仍 422。回归测试 `test_plan_remove_is_reversible`。
4. **`PlanItem.probability_interval` + `PlanPayload.colleges`**：
   志愿表页也要显示区间（§8），且 `PlanItem` 只有 `college_id`，没有院校名就读不了。

### 前端设计要点（AGENTS §8）

- **首屏即向导**（`/` → `/profile`，无落地页）：省份→选考 3 门→成绩→偏好（可跳过）。
  Step 3 分数换算显示完整溯源；503 时明确提示"位次换算不可用"并引导手填；
  **分数与手填位次冲突时给两个按钮让考生选，绝不擅自覆盖**。
- **概率永远是区间**：`ProbabilityBar` 只画区间带，**刻意不画单点标记**；
  区间过窄自动加小数位，不美化放大；分层刻度来自 `/meta/tiers`，前端不写死 10/40/75/93。
- **证据链可展开**：`EvidenceTable` 把"本单位历史"与"Step 0 类比证据"**分表展示**。
- **HIGH 风险阻断式**：志愿表页出现 HIGH 风险时锁定导出，需勾选"我已理解"才解锁。
- **调剂选项按 `has_major_adjustment` 显隐**（不是按省份名判断）。
- **不引入拖拽库**：原生 HTML5 DnD + 上下移动按钮（键盘可达，DnD 不是唯一路径）。
- **`/chat` 如实标注能力边界**：M3 的对话还不能查数据，界面明说"完整工具化回答在 M5"。

### 前端目录（AGENTS §4.2 已同步更新）

```
frontend/
├── src/{main.tsx,App.tsx,index.css}
├── src/pages/{Profile,Recommend,PlanBoard,Report,Chat}.tsx
├── src/components/  TierBadge · ProbabilityBar · RankTrendChart · PlanRow · RiskPanel ·
│                    EvidenceTable · GradientChart · RuleBanner · StepIndicator ·
│                    Disclaimer · Chart(ECharts 容器) · StateBlocks
├── src/api/{client.ts, schema.d.ts(生成物,gitignore)}
├── src/lib/{format.ts(+单测), labels.ts, hooks.ts}
├── src/store/{profile.ts, plan.ts}         # zustand + persist
├── scripts/{gen-api-types.mjs, smoke.mjs}
├── openapi.snapshot.json                    # ★ 进版本库：离线构建回退
└── pnpm-workspace.yaml                      # pnpm 11 allowBuilds: esbuild:false
```

---

## 7. 下一轮：M5（Agent 层与防幻觉）—— 具体要做的事

**按 AGENTS §9 实现**：`backend/app/agent/{tools.py, prompts.py, parser.py, narrator.py, guard.py}`。

1. **`tools.py`**：§9.1 的 11 个工具（只读或需确认，绝不写库）。
   **每个工具返回的所有数字必须带 `source_url`**；工具负责格式化证据，LLM 只转述。
   可直接复用现有 service 层：`recommend_service` / `plan_service` / `risk_service` /
   `student_service` / `meta_service`（都是"查库 → 组装 → 调 core"的现成编排）。
2. **`prompts.py`**：人设（十余年一线名师，敢说不确定）+ 能力边界 + 逐条禁止条款（含正反例）
   + 输出格式 + 追问策略（一次最多问 3 个）。
3. **`parser.py`**：自然语言 → 考生档案；缺字段就追问，**不猜**（复用 `student_service.compute_missing_fields`）。
4. **`narrator.py`**：算法输出 → 名师口吻解释；**数字必须原样引用工具返回值**。
5. **`guard.py`**：`guard_response(reply, tool_calls_this_turn)` —— 正则提取疑似数字断言
   （分数 600-750 / 位次 / 百分比 / 计划数）→ 与会话内工具返回值匹配 → 未匹配即拦截；
   绝对化词表（保证/一定/百分百/稳上）命中即拦截；拦截后重写为"我需要查一下数据"。
6. **`tests/test_agent_hallucination.py`**：20 个"库外院校分数线"提问，**编造次数必须 = 0**。
7. **`/chat` 升级**：M3 的 `chat_service` 是"不含数字的占位回复"，M5 要接上工具调用；
   会话历史从内存改为落库（见 `docs/DATA_DICTIONARY.md` §7）。

**验收命令**（AGENTS §10 M5）：

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_agent_hallucination.py -q   # 20 例，编造数 = 0
```

**M5 要注意的边界**：
- LLM provider 必须**可插拔、可 mock**（§4.1）——测试不能依赖真实 API。
- 前端 `/chat` 页现在把能力边界写死了（"还不能查数据"），**M5 完成后要同步改这段文案与
  `chat_service` 的回复策略**，否则界面在说谎。
- 现有 `/chat` 测试断言"回复中不得出现三位以上数字、不得出现 %"——M5 接入工具后这些断言
  **必须改成"数字必须能在本次工具返回值中找到"**，而不是简单删掉。

---

## 8. 已知边界（诚实披露，别在下一轮"顺手修掉"）

- **省际阈值压线**：山东冲档 41.2%（略超 40%）、北京稳档 83.9%（略低于 85%）。
  模型各层校准良好（预测均值≈实际命中率），是阈值正好落在 §6.3 分层边界上。
  **不建议为凑指标继续调参**（会滑向对测试集过拟合）。
- **前端无浏览器 E2E / 视觉回归**：本轮的闭环验证是 `pnpm smoke`（按 UI 真实调用序列打真后端），
  能证明契约与数据流正确，**不能**证明像素与交互细节无瑕疵 → M7 引入 Playwright。
- **权重滑块只影响排序**：意向地区的软偏好权重当前取考生档案里的偏好值，
  滑块与后端 `weights` 参数的联动尚未做（不影响概率，概率只由算法决定）。
- **志愿表 PATCH 每次重算候选池**（811 单位量级约 0.3–1s）。本地无感，M7 可加缓存/池快照。
- 尚无 alembic 迁移（dev 启动 `create_all` 建表）、无鉴权。
- 仅浙江是端到端闭环，其余五省只有规则包（但科目池、覆盖率、规则展示六省都可用）。
- 敏感度热力图（DOMAIN_RULES §3.1）与 §6.8 的两个增量风险码（调剂越界、退档条款命中）仍待补。
- 回测报告 `backtest_report.json|md` 是构建产物（gitignore），由 `scripts/run_backtest.py` 生成。

---

## 9. 关键文件索引

| 想找什么 | 去哪 |
|---|---|
| 施工总纲 / 每轮计划与验收命令 | `AGENTS.md` |
| 投档规则、算法参数、经验规则库、黄金用例规范 | `docs/DOMAIN_RULES.md` |
| 字段口径、时间轴、API 口径、用户表 | `docs/DATA_DICTIONARY.md` |
| 全部决策与被否决方案、各轮验收记录 | `docs/DECISIONS.md`（ADR-001…ADR-011） |
| **M4 的契约改造与前端设计决策** | `docs/DECISIONS.md` **ADR-011** + M4 验收记录 |
| 概率模型心脏 | `backend/app/core/probability.py`（§6.2 八步 + Step 0 回退 + Step 8.6 安全闸门） |
| 推荐/志愿表编排 | `backend/app/services/{recommend_service,plan_service}.py` |
| API 响应模型（契约唯一来源） | `backend/app/api/schemas.py` |
| 选考科目池与覆盖率 | `backend/app/core/rules/*.py`（`subject_pool`）+ `services/meta_service.py` |
| 报告导出（xlsx + 中文 PDF） | `backend/app/services/report_service.py` |
| 前端 API 客户端 | `frontend/src/api/client.ts`（类型来自 `schema.d.ts`） |
| 前端端到端冒烟 | `frontend/scripts/smoke.mjs` |
| 运维脚本 | `scripts/{seed,run_backtest,calibrate_params,pip_online,bootstrap_wheels}` |
