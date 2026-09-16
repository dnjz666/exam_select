# 交接说明（HANDOVER.md）—— 本文件由上一轮对话生成，供下一轮对话接手

> **给接手的 agent 的第一条指令**：先读 `AGENTS.md`（唯一权威施工总纲）与 `docs/DOMAIN_RULES.md`
> （领域规则与算法参数），再读 `docs/DECISIONS.md`（ADR-001…ADR-014 + 各轮验收记录），
> 然后读本文件了解"现在站在哪里"。**不要凭常识补全任何规则数字**。

- 工作区：`D:\exam_select`（无空格）
- 生成时间：M5 完成后
- 下一轮起点：**M6（真实数据接入，需用户先确认来源与授权）**；若暂不接真实数据，先做 **M7 加固**

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
| M1 | 数据层与模拟数据生成（六省 20 个批次级规则包） | ✅ 完成（**M5 期间修掉一个池截断缺陷**，见 ADR-014） |
| M2 | 核心算法引擎 | ✅ 完成（`safety_margin` 在 M5 重标定为 0.60） |
| M3 | 后端 API | ✅ 完成 |
| M4 | 前端（5 个页面 + 强类型契约） | ✅ 完成 |
| M5 | Agent 层与防幻觉（12 个只读工具 + 护栏 + 对话式建档 + 会话落库） | ✅ 完成 |
| **M6** | **真实数据接入** | ⬜ **需用户先确认数据来源与授权** |
| M7 | 加固与交付 | ⬜（M6 未启动时可先行） |

### 可复现的实测结果（不是"应该通过"）

| 项 | 实测 |
|---|---|
| 后端测试 | `319 passed`（含 agent 层 101 项） |
| 算法层覆盖率 `app.core` | **95.81%**（门槛 ≥90%） |
| 幻觉测试 | 20 例 × 2 条防线，**编造次数 = 0** |
| 回测（safety_margin=0.60，150 考生全量） | 浙江 `0.00% / 88.10% / 29.79% / 0.0089` · 山东 `0.00% / 90.54% / 30.77% / 0.0080` · 北京 `0.00% / 86.08% / 14.01% / 0.0083`（四项全达标） |
| API | `/api/v1` 21 条 + `/health`；OpenAPI 3.1.0，69 个强类型 schema |
| 前端 | `tsc --noEmit` 0 错 · `vite build` ✓ 610 modules · `vitest` 10 项 · `pnpm smoke` 闭环全通 |
| 模拟数据 | 418 院校 · 528 专业 · **7,091** 投档单位 · 24,921 条历史 · 35,455 条计划快照 |

### git 状态

- 分支 `main`，远端 `https://github.com/dnjz666/exam_select.git`
- M4 的两个提交（`2d4f74f`、`d3852a2`）**用户已推送**；本轮 M5 的提交见 `git log`
- 用户偏好：**提交由我做、推送由用户确认**（"只提交不推送"）
- 推送注意：Git 凭据助手要创建命名管道，agent 会话沙箱默认拒绝
  （`sh.exe: couldn't create signal pipe, Win32 error 5`）

---

## 3. 环境事实（踩过坑，别再踩）

| 事项 | 事实 |
|---|---|
| Python | **必须用 `backend\.venv\Scripts\python.exe`**（3.11.9）。裸 `python` 是本机 3.13，禁止 |
| **pip** | `powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1`。**必须在真实终端跑**（沙箱拒绝 pip 的 mkdtemp） |
| **前端构建 / dev / test** | ★ **必须真实终端跑**：Vite/Vitest 要 spawn esbuild 原生二进制，**agent 沙箱 `spawn EPERM`**。`pnpm typecheck`（纯 tsc）不受影响 |
| **两个 pnpm** | ★ 会话里的 `pnpm` 是 **DSH shim（11.8.0，`minimumReleaseAge=0`）**；用户终端是**全局 pnpm 12.4.1**（默认 24h 供应链防护）。**凡涉及前端依赖，必须用全局 pnpm 复核**：`node "C:\nvm4w\nodejs\node_modules\pnpm\bin\pnpm.mjs" install --frozen-lockfile`（详见 ADR-012） |
| **网络** | ★ 本机 **schannel 在 agent 沙箱内不可用**（curl/Invoke-WebRequest 报 `SEC_E_NO_CREDENTIALS`），但 **Node 自带 TLS 正常**。排错时别误判成断网 |
| 数据库 | `data\exam_select.db`（SQLite，约 45 MB）。路径**锚定到仓库根**（`config.anchor_sqlite_url`） |
| 测试前置 | `pytest backend/tests` 依赖**已播种**的数据库；未播种会明确失败（不静默跳过） |
| PowerShell 坑 | **不要用 `curl.exe -d '{"json"}'` 发 POST**（双引号被吃 → 422）；用 `Invoke-RestMethod` + `ConvertTo-Json` |
| 终端中文 | 先 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` |
| `debug.log` | 根目录若出现，是 DSH Desktop 的 Electron crashpad 日志，非项目产物（已 gitignore） |

---

## 4. 验收命令（每轮结束必须真跑并贴输出）

```powershell
$py = 'backend\.venv\Scripts\python.exe'

# 数据（幂等；--reset 会清空学员档案、志愿表与对话）
& $py scripts\seed.py --reset
& $py -m app.etl.validate --report                     # 期望 0 error

# 后端测试与覆盖率
& $py -m pytest backend/tests -q --cov=app.core --cov-fail-under=90   # 319 passed / 95.81%

# M5 验收：幻觉测试（20 例，编造数 = 0）
& $py -m pytest backend/tests/test_agent_hallucination.py -q           # 47 passed

# 回测（四项未达标则 exit 1）；改了概率参数必须重跑并附前后对比
& $py scripts\run_backtest.py --province zhejiang --year 2025
& $py scripts\calibrate_params.py --province zhejiang --year 2025      # 参数网格标定

# 起服务
Set-Location backend
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
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
L5 frontend/ (React18+TS+Vite+Tailwind+ECharts)  +  agent/ (tools/prompts/parser/narrator/guard/llm)
L4 backend/app/{api,services,main.py}   ← 本层才碰 DB / 网络 / LLM
L3 backend/app/core/**                  ← ★ 纯函数：无 IO、无 DB、无网络、无 LLM（ADR-003）
L2 backend/app/db/**  (models 表 + repositories 访问层)
L1 backend/app/etl/** (确定性模拟数据，seed 固定)
```

- **`core/` 纯函数铁律**：已由测试与覆盖率守护。
- **来源纪律**：任何规则数字必须带 `source_url`；`BatchRule` 还要 `source_quote` + `verified_status`
  + `verified_year`；`SubjectPool`（选考科目池）同受约束；**工具返回的每个数字也必须带来源**。
- **契约铁律**（有测试守着）：① 每个推荐项 `evidence` 非空且带 `source_url`；
  ② `probability is None ⇔ confidence == NO_DATA` 且 `reasons` 说明原因；③ 无来源数字为零；
  ④ OpenAPI 是契约唯一来源，**响应体必须强类型**（ADR-011）。
- **幻觉铁律**（M5 新增）：**LLM/叙述器产出的任何数据型数字，必须能在本次会话的工具返回值里找到**，
  否则整条回复被护栏改写。改 agent 层时不要绕过 `guard_response`。
- 红线（违反即返工）：`core/` 里 import DB/网络/LLM；硬编码分数线/位次/志愿数；
  让 LLM 产生数字；无证据链返回推荐；跳过回测改概率参数；用"应该能跑"代替实测。

---

## 6. 本轮（M5）的关键决策与实测发现

详见 `docs/DECISIONS.md` **ADR-013**（agent 设计）与 **ADR-014**（数据缺陷 + 重标定）。

**agent 层的三条要点**：

1. **护栏是保证，提示词只是请求**。`guard.py` 在模型之外做确定性后置校验：
   提取数据型数字断言 → 与工具返回值比对 → 不匹配就整条改写。
   三个被实测逼出来的细节：白名单只收结构的数值字段（否则 URL 里的年份会成为后门）；
   按键词**就近**归类（否则"最低分 660，最低位次 12,340"里的 660 会被判成位次）；
   **绝不误伤**（"一定要留足保底"是建议不是承诺，`1.` 是列表序号不是位次断言）。
2. **没有 LLM 也能用**：默认 `LLM_PROVIDER=none`，走 `parser` 规则路由 + `tools` + `narrator` + `guard`。
   零编造、完全可单测，也是幻觉测试的对照组。
3. **对话式建档由确定性 parser 写库，LLM 不写**；且**已有档案的省份不会被一句话覆盖**
   （实测踩过：问"上海大学的最低录取位次"把考生省份改成了上海）。

**M5 期间发现并修复的两个真实缺陷（都在 M1/M2 层面）**：

- **候选院校池按 id 排序后截断** → 浙江/上海/山东/天津的考生候选池里**本省院校数为 0**
  （浙江考生永远看不到浙江大学），外省普通院校的抽样名额也被一并吃掉。
  修复：本省 + 全国重点都保留、上限 110→200；补了回归测试。
- **`safety_margin` 在修正后的数据上失效** → 0.30 时保底失效率 0.07%（≠0）、稳档 83.0%。
  全量网格扫描后取 **0.60**（使保底失效率回到 0 且三省稳档全部 ≥85% 的最小值）。
  两个黄金用例（G-003/G-004）的场景定义直接依赖该参数，已按新阈值调整输入并重写推导。

---

## 7. 下一轮建议：M6 或 M7

### 若做 M6（真实数据接入）——**必须先找用户确认数据来源与授权**

1. `etl/loaders/` 下的适配器（目录已留空）；先接 **1 个省的 1 年真实数据**打通。
2. 数据合规性单独评估；**未确认授权不得抓取考试院网站**（DOMAIN_RULES §1.4）。
3. 真实数据入库后要跑 `validate` 与回测，并与模拟数据基线对比（ADR-014 的跨省表即基线）。
4. 规则包的 `verified_year` 与 `verified_status` 需随之更新（天津/海南升 PRIMARY 是长期待办）。

### 若做 M7（加固与交付）——可立即开工，清单如下

- **性能**：推荐接口 P95 < 1s。当前瓶颈是每次请求都要 `load_units` 全省单位
  （浙江 1290 个单位）；志愿表 PATCH 每次重算候选池约 0.5–1.5s。可加缓存或候选池快照落库。
- **边界**：0 志愿 / 超高分 / 超低分 / 全被过滤 / 一次对话内连续建档。
- **前端视觉回归**：引入 Playwright（现在只有 `pnpm smoke` 的契约级验证，
  不能证明像素与交互细节）。
- **敏感度热力图**（DOMAIN_RULES §3.1 待补）。
- **§6.8 的两个增量风险码**：调剂越界、退档条款命中（上海原文已核实，字段已就位）。
- **Docker 生产配置**（本机 Docker 守护进程未运行，需人工启动验证）。
- **用户手册**与 `DECISIONS.md` 汇总；`alembic` 迁移（现在 dev 靠 `create_all`）。

**M7 注意**：`safety_margin=0.60` 意味着"保底"标签更稀缺，
`planner` 会更频繁地向更保守方向借位；如果做性能/边界改造，别把这条语义改掉。

---

## 8. 已知边界（诚实披露，别在下一轮"顺手修掉"）

- **真实 LLM 客户端未对真实服务验证过**（本机无 API key）。`llm.py` 的 OpenAI 兼容实现
  由注入的假实现覆盖测试（含"编造必被拦"与"合规必放行"两个方向）。默认关闭。
- **规则式意图路由不认简写**："物化生"不会被拆成三门选考 → 此时会**追问**而不是猜。
- **对话式建档只写可增量字段**；省份不会被一句话覆盖（这是刻意的安全设计）。
- 前端无浏览器 E2E / 视觉回归；`pnpm smoke` 证明契约与数据流，不证明像素。
- 意向地区/门类的权重滑块与后端 `weights` 参数尚未联动（只影响排序，不影响概率）。
- 仅浙江是端到端闭环，其余五省只有规则包（但科目池、覆盖率、规则展示、agent 查询六省都可用）。
- 模拟数据的院校-专业搭配有随机成分（例如会出现"清华 · 食品卫生与营养学"这类不常见组合），
  这是合成数据的固有噪声，不是推荐逻辑的问题；真实数据接入后自然消失。

---

## 9. 关键文件索引

| 想找什么 | 去哪 |
|---|---|
| 施工总纲 / 每轮计划与验收命令 | `AGENTS.md` |
| 投档规则、算法参数、经验规则库、黄金用例规范 | `docs/DOMAIN_RULES.md` |
| 字段口径、时间轴、API 口径、`chat_messages` | `docs/DATA_DICTIONARY.md` |
| 全部决策与被否决方案、各轮验收记录 | `docs/DECISIONS.md`（ADR-001…ADR-014） |
| **M5 agent 设计与数据缺陷复盘** | `docs/DECISIONS.md` **ADR-013 / ADR-014** |
| 幻觉护栏 | `backend/app/agent/guard.py`（+ `tests/test_agent_guard.py`） |
| 工具层（12 个只读工具） | `backend/app/agent/tools.py`（+ `tests/test_agent_tools.py`） |
| 对话编排（两条路径 + 建档 + 落库） | `backend/app/services/chat_service.py` |
| **M5 验收测试** | `backend/tests/test_agent_hallucination.py`（20 例 × 2 条防线） |
| LLM provider 接口 | `backend/app/agent/llm.py`（协议 + OpenAI 兼容实现 + 工厂） |
| 概率模型心脏 | `backend/app/core/probability.py`（§6.2 八步 + Step 0 回退 + Step 8.6 安全闸门） |
| 模拟数据生成器（含 ADR-014 修复） | `backend/app/etl/synthetic.py::_candidate_colleges` |
| 前端 API 客户端 / 端到端冒烟 | `frontend/src/api/client.ts` · `frontend/scripts/smoke.mjs` |
| 运维脚本 | `scripts/{seed,run_backtest,calibrate_params,pip_online,bootstrap_wheels}` |
