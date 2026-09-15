# 高考志愿填报智能体（exam_select）

> 面向 3+3 新高考六省市（浙江 / 上海 / 北京 / 山东 / 天津 / 海南）的志愿填报辅助系统。
> **定位：决策辅助，仅供参考；最终以各省考试院官方文件与高校招生章程为准。**
>
> **最高原则：宁可不答，不可编造。** 所有分数线、位次、概率一律由确定性算法计算并附证据链；
> LLM 只负责"理解意图、解释结果、追问澄清"三件事（AGENTS.md §0/§3.3）。

- 施工总纲：`AGENTS.md`（**唯一权威施工说明**，动手前必读）
- 领域规则与算法参数：`docs/DOMAIN_RULES.md`
- 字段口径：`docs/DATA_DICTIONARY.md`
- 架构决策记录（ADR）：`docs/DECISIONS.md`

---

## 当前状态

| Phase | 内容 | 状态 |
|---|---|---|
| M0 | 项目骨架与领域模型 | ✅ 完成 |
| M1 | 数据层与模拟数据生成 | ✅ 完成 |
| M2 | 核心算法引擎 | ✅ 完成 |
| M3 | 后端 API | ✅ 完成 |
| M4 | 前端（5 个页面 + 端到端闭环） | ✅ 完成 |
| M5 | Agent 层与防幻觉 | ⬜ **下一轮** |
| M6 | 真实数据接入 | ⬜（范围另议，需确认数据来源授权） |
| M7 | 加固与交付 | ⬜ |

**已交付的实测结果**（可复现，验收记录见 `docs/DECISIONS.md`）

| 项 | 实测 |
|---|---|
| 后端测试 | `201 passed`（其中 API 集成测试 25 项） |
| 算法层覆盖率（`app.core`） | **95.62%**（门槛 ≥90%） |
| 黄金用例 | **38 条**（概率 21 / 过滤 12 / 规则 5） |
| 回测（浙江 2025，811 单位 × 150 考生 × 21,184 样本） | 保底失效率 **0.00%** · 稳档命中率 **86.02%** · 冲档命中率 **31.43%** · Brier **0.0057**（四项全达标） |
| API | `/api/v1` 下 **21 条路由**，OpenAPI 3.1.0 可解析（**69 个 schema，全部强类型**） |
| 前端构建 | `vite build` ✓ 610 modules；`tsc --noEmit` 零错误；vitest 10 项通过 |
| 前端端到端 | `npm run smoke` 闭环全通（建档 → 换算 → 推荐 → 志愿表 → 手改 → 导出 PDF/XLSX） |
| 模拟数据 | 6 省市 · 418 院校 · 528 专业 · 4,645 投档单位 · 16,297 条历史 · 23,225 条计划快照（全部 `is_synthetic=1`） |

---

## 快速开始

### 0. 环境准备（只需做一次）

依赖装在 `backend\.venv` 里，**装在硬盘上，重启电脑不会丢，不需要每次开机重装**。
只有以下情况才需要重装：首次搭建 / 换机器、`backend/pyproject.toml` 新增了依赖、venv 被删或损坏。

```powershell
# 必须用 py -3.11（本机裸 python 是 3.13，禁止使用）
py -3.11 -m venv backend\.venv

# 在线安装（推荐；带镜像、NO_PROXY 与超时保护）
powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1
# 镜像不通时改走本地代理：
# powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1 -ViaProxy
```

自检（5 秒，代替盲目重装）：

```powershell
& 'D:\exam_select\backend\.venv\Scripts\python.exe' -c "import fastapi,scipy,numpy,reportlab,openpyxl,sqlalchemy; print('env OK')"
```

> ⚠️ **两条硬约束**
> 1. pip 相关脚本**必须在真实终端运行**——AI agent 会话的沙箱会拒绝 pip 的 `mkdtemp` 临时目录
>    （ADR-007 追记第 6 条）。
> 2. 一切 Python 命令用 `backend\.venv\Scripts\python.exe` 或 `py -3.11`，**不要用裸 `python`**。

### 1. 生成模拟数据（幂等）

```powershell
# --reset 会清空并重建（同时会清掉已有的考生档案与志愿表）
backend\.venv\Scripts\python.exe scripts\seed.py --reset
# 再跑一次数据量不变 → 幂等
backend\.venv\Scripts\python.exe scripts\seed.py

# 数据质量校验（期望：0 error）
backend\.venv\Scripts\python.exe -m app.etl.validate --report
```

### 2. 启动后端服务

```powershell
Set-Location backend
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

```powershell
curl.exe -s http://127.0.0.1:8000/health                 # {"status":"ok"}
curl.exe -s http://127.0.0.1:8000/api/v1/meta/tiers      # 分层/配额/安全闸门定义
# 交互式文档（Swagger UI）：http://127.0.0.1:8000/docs
```

> 数据库路径已**锚定到仓库根**（ADR-010），从仓库根或从 `backend\` 启动连的都是同一个库。

### 3. 跑测试与回测（每轮验收命令）

```powershell
# M2/M3 验收：单测 + 覆盖率门槛
backend\.venv\Scripts\python.exe -m pytest backend/tests -q --cov=app.core --cov-fail-under=90

# M3 验收：API 集成测试
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_api.py -q

# M2 验收：回测（四项硬指标未达标则 exit 1）
backend\.venv\Scripts\python.exe scripts\run_backtest.py --province zhejiang --year 2025
```

> `pytest backend/tests` 依赖**已播种**的数据库；未播种时会明确失败并提示 `scripts/seed.py --reset`
> （不会静默跳过）。回测报告 `backtest_report.json|md` 是构建产物，已 gitignore。

### 4. 前端（React 18 + TS + Vite + Tailwind，独立工程）

前端与后端**只通过 HTTP 契约通信**（AGENTS.md §4.3）：类型从后端 OpenAPI 生成，
API 基址来自 `VITE_API_BASE_URL`（dev 用 Vite proxy 把 `/api` 转发到 `127.0.0.1:8000`），
**代码里不出现硬编码的 localhost**。

```powershell
Set-Location frontend
pnpm install                     # 依赖装一次即可
pnpm gen:api                     # 从后端 /openapi.json 生成 src/api/schema.d.ts（后端需在跑）
pnpm dev                         # http://127.0.0.1:5173  ← 首屏即建档向导

# M4 验收命令（AGENTS.md §10）
pnpm build                       # prebuild 自动先跑 gen:api
pnpm typecheck                   # tsc --noEmit
pnpm test                        # vitest（纯函数：概率区间格式化等）
pnpm smoke                       # 端到端闭环冒烟（打真后端，断言 §8 的 UI 铁律）
```

> ⚠️ **第三条硬约束**：`pnpm build` / `pnpm dev` / `pnpm test` 依赖 esbuild 的原生二进制，
> 而 esbuild 需要 spawn 子进程并走管道 stdio —— **agent 沙箱会拒绝（spawn EPERM）**，
> 因此这三条命令也要**在真实终端跑**（与 pip 同类限制，见 ADR-011 环境事实）。
> `pnpm typecheck` 是纯 `tsc`，不受影响。
>
> 另注：本机 `curl.exe`/`Invoke-WebRequest` 走 schannel，在 agent 沙箱内会报
> `SEC_E_NO_CREDENTIALS`；**Node 自带的 TLS 栈正常**，所以 `pnpm install` 与 `node scripts/*.mjs`
> 都能联网 —— 排错时别误判成"断网"。

**5 个页面**：`/profile` 建档向导（首屏）· `/recommend` 推荐列表 · `/plan` 志愿表 ·
`/report` 可打印报告 · `/chat` 对话（M3 通道，能力边界如实标注）。

---

## 端到端示例（已实测跑通）

建档 → 换算位次 → 推荐 → 生成志愿表 → 导出报告：

```powershell
$api  = 'http://127.0.0.1:8000/api/v1'
$json = 'application/json; charset=utf-8'

# 1) 建档（允许草稿态：缺字段会在 data.missing_fields 里返回，前端据此追问）
$stu = Invoke-RestMethod -Method Post -Uri "$api/students" -ContentType $json -Body (@{
  province = 'zhejiang'; year = 2026
  subjects = @('物理','化学','生物'); total_score = 640
} | ConvertTo-Json)
$id = $stu.data.id

# 2) 分数 → 位次（返回位次、百分位、近三年等效分与来源）
$rank = Invoke-RestMethod -Method Post -Uri "$api/students/$id/resolve-rank" -ContentType $json -Body '{}'

# 3) 推荐（每项必带非空 evidence + 概率区间；filters/weights 可选）
$rec = Invoke-RestMethod -Method Post -Uri "$api/recommend" -ContentType $json -Body (@{
  student_id = $id; limit = 5; filters = @{ regions = @('zhejiang') }
} | ConvertTo-Json -Depth 5)

# 4) 生成志愿表（浙江 80 个平行志愿；含风险扫描与逐项依据）
$plan = Invoke-RestMethod -Method Post -Uri "$api/plans/generate" -ContentType $json -Body (@{
  student_id = $id
} | ConvertTo-Json)
$planId = $plan.data.plan.id

# 5) 导出报告（含免责声明 + 数据来源清单；PDF 为中文 STSong-Light）
Invoke-WebRequest -Uri "$api/plans/$planId/export?format=pdf"  -OutFile report.pdf
Invoke-WebRequest -Uri "$api/plans/$planId/export?format=xlsx" -OutFile report.xlsx

# 6) 只要风险、不生成志愿表（§6.8 全码 + 可执行建议）
$scan = Invoke-RestMethod -Method Post -Uri "$api/risk/scan" -ContentType $json -Body (@{
  student_id = $id; unit_ids = @($plan.data.plan.items[0..2].unit.unit_id); obey_adjustment = $true
} | ConvertTo-Json)
```

**实测输出**（本机真实结果）

| 步骤 | 结果 |
|---|---|
| 建档 | `stu-439d75f55790`，`missing_fields` 为空 |
| 换算位次 | **17812 / 405912**（百分位 0.0439，等效分 3 年，带 `source_url`） |
| 推荐 | 5 项；首项 `CHONG`，概率 **0.237**，区间 **0.04–0.61**，`evidence` 3 条 |
| 志愿表 | `plan-<uuid>`，**80** 个志愿，分层 `{CHONG 7, WEN 55, DIAN 18}`，风险 35 条 |
| 导出 | PDF **14,253** 字节（`%PDF` 头）· XLSX **23,144** 字节 |
| 风险速查 | 扫描 3 个志愿 → 4 条风险（HIGH 1 / MEDIUM 3） |

> ⚠️ **别用 `curl.exe -d '{"json"}'` 发请求**：PowerShell 会把参数里的双引号吃掉，
> 服务端只会回一个 `422 JSON decode error`（实测踩过）。要么像上面这样用 `Invoke-RestMethod`，
> 要么把 JSON 写进文件后 `curl.exe --data-binary "@body.json"`；只有 `GET` 这类无 body 的请求适合直接用 `curl.exe`。

---

## API 一览（`/api/v1`，21 条路由）

| 分组 | 端点 | 说明 |
|---|---|---|
| 元数据 | `GET /meta/provinces` | 六省批次级规则 + **选考科目池**（含 `source_url`、`source_quote`、核实状态、`current_year`、是否需「规则待核实」横幅） |
| | `GET /meta/provinces/{province}/rule` | 单省规则；未知省份 → 404 |
| | `GET /meta/provinces/{province}/subject-coverage?subjects=物理,化学` | **可报专业覆盖率**（用选考要求真实统计，非估算） |
| | `GET /meta/tiers` | 分层区间、配额、**安全闸门**参数与免责声明文案 |
| 考生档案 | `POST /students` | 建档（草稿态）→ 返回 `missing_fields` |
| | `GET /students/{id}` · `PATCH /students/{id}` | 读取 / 增量补全 |
| | `POST /students/{id}/resolve-rank` | 分数 → 位次（含等效分与来源；表缺失 → 503，不估算） |
| 数据查询 | `GET /colleges/search` · `GET /majors/search` | 院校 / 专业检索 |
| | `GET /units/{unit_id}/history?years=3` | 某投档单位逐年历史（每条带来源） |
| 核心推荐 | `POST /recommend` | 过滤 → 打分 → 概率 → 分层排序；每项带 `college`/`major`、证据链与概率**区间** |
| 志愿表 | `POST /plans/generate` | 生成（配额/借位/排序/去重 + 风险扫描 + 院校索引） |
| | `GET /plans/{id}` · `PATCH /plans/{id}/items` · `POST /plans/{id}/validate` | 读取 / 手改（**生成时候选池内**，移除可逆）/ 重跑校验 |
| | `GET /plans/{id}/export?format=pdf\|xlsx` | 导出报告（免责声明 + 来源清单） |
| 风险速查 | `POST /risk/scan` | 对一组 `unit_id` 直接扫风险（§6.8 全码 + 可执行建议） |
| 对话 | `POST /chat`（SSE）· `GET /chat/{session_id}/history` | M3 仅合规通道：**回复不含数字**、首次回复带免责声明；工具化回答见 M5 |
| 回测 | `GET /backtest/report?province=&year=` | 读取离线回测报告（不匹配 → 404 + 复现命令） |
| 健康 | `GET /health` | `{"status":"ok"}` |

**响应契约**：所有响应为 `{data, evidence, warnings}` 三段；错误为
`{error: {code, message, details}}`（`PROFILE_INCOMPLETE` 409 · `RANK_UNAVAILABLE` 503 ·
`PLAN_NOT_FOUND` 404 · `UNKNOWN_UNITS` 422 · `REPORT_UNAVAILABLE` 404 · `NOT_FOUND` 404）。

**四条契约铁律**（有测试守着）：① 每个推荐项 `evidence` 非空且带 `source_url`；
② `probability is None ⇔ confidence == NO_DATA` 且 `reasons` 说明原因；
③ 不出现无来源的数字；④ OpenAPI 自动生成，前端类型由此生成，不手写重复类型。

> 契约自 M4 起**全部强类型**（69 个 schema）：响应体不再用裸 `dict`，
> 字段改名/漏字段会在测试中直接报 `ResponseValidationError`；
> 前端的 `src/api/schema.d.ts` 即由这份 schema 生成（见 ADR-011）。

---

## 目录结构（关键部分）

```
exam_select/
├── AGENTS.md                  # 施工总纲（唯一权威）
├── docs/                      # DOMAIN_RULES / DATA_DICTIONARY / DECISIONS
├── backend/
│   ├── app/
│   │   ├── core/              # ★ 纯算法层：rank/probability/filters/scoring/planner/risk/backtest/rules
│   │   ├── api/               # L4：schemas(信封) + deps + v1/{meta,students,catalog,recommend,plans,risk,chat,backtest}
│   │   ├── db/                # L2：models(表) + repositories(访问层，供 L4 调用)
│   │   ├── etl/               # 确定性模拟数据生成器 + 数据质量校验
│   │   ├── services/          # L4 编排：查库 → 组装 → 调 core → 存结果
│   │   └── main.py            # 入口（/health + /api/v1 装配 + 领域异常映射）
│   └── tests/                 # 201 项测试 + golden/（38 条黄金用例）
├── frontend/                  # L5：React 18 + TS + Vite + Tailwind + ECharts（独立工程）
│   ├── src/pages/             # Profile(首屏向导) / Recommend / PlanBoard / Report / Chat
│   ├── src/components/        # TierBadge · ProbabilityBar · RankTrendChart · PlanRow · RiskPanel · …
│   ├── src/api/client.ts      # 信封感知的 fetch 封装（类型来自生成的 schema.d.ts）
│   ├── src/lib/               # format(纯函数，有单测) · labels(文案配色) · hooks
│   ├── src/store/             # zustand + persist：向导草稿 / 志愿表与意愿序
│   └── scripts/               # gen-api-types.mjs（生成物 gitignore）· smoke.mjs（端到端冒烟）
├── data/                      # exam_select.db（gitignore）、synthetic/、wheels/（离线依赖缓存）
└── scripts/                   # seed.py、run_backtest.py、calibrate_params.py、pip_online.ps1
```

**分层铁律**：`core/` 是纯函数（禁止 import 数据库/网络/LLM），已由测试与覆盖率守护；
任何"顺手查一下数据库"的写法都会让算法层失去可信度（ADR-003）。

---

## 已知限制（诚实披露）

- **省际边界**：冲档/稳档指标在个别省份正好压在阈值上（山东冲档 41.2%、北京稳档 83.9%）。
  模型各层校准良好（预测均值 ≈ 实际命中率），阈值恰好落在 §6.3 分层边界，建议按跨省容差读；
  **不建议为凑指标继续调参**（会滑向对测试集过拟合）。详见 `docs/DECISIONS.md` ADR-009。
- **`/chat` 不是可用助手**：M3 只交付 SSE 通道、内存会话历史与防幻觉底线；
  工具调用 / System Prompt / guard 输出校验器属 M5，会话历史届时落库（重启即清空）。
- **志愿表手改限"生成时的候选池"**（由同一套评估现场重算，硬约束一条都绕不过；
  池外 `unit_id` → 422）。因此**移除是可逆的**，但候选池 ≠ 全部单位：
  被硬约束剔除或概率 <10% 的单位仍需调整筛选后重新生成。
- **前端无浏览器 E2E**：本轮的闭环验证是 `pnpm smoke`（按 UI 真实调用序列打真后端），
  能证明契约与数据流正确，**不能**证明像素与交互细节无瑕疵；Playwright 视觉回归留 M7。
- **仅有浙江是端到端闭环**，其余五省当前只有规则包（M1 交付 20 个批次级规则）。
- 尚无 alembic 迁移（dev 启动 `create_all` 建表）、无鉴权。
- 回测/敏感度热力图（§3.1）与 §6.8 的两个增量风险码（调剂越界、退档条款命中）仍待补。

---

## 排错

| 症状 | 处理 |
|---|---|
| `sqlite3.OperationalError: unable to open database file` | 已修（SQLite 路径锚定到仓库根）。若你自定义了 `DATABASE_URL` 且用相对路径，注意它以**仓库根**为基准 |
| 测试报"数据库为空" | 先 `backend\.venv\Scripts\python.exe scripts\seed.py --reset` |
| pip 卡住 10 分钟以上 | 用 `scripts\pip_online.ps1`（已 pin 超时 15s / 重试 2 次）；镜像不通加 `-ViaProxy` |
| `无法加载文件 … 因为在此系统上禁止运行脚本` | 用 `powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1` |
| 前端 `spawn EPERM`（`pnpm build` / `dev` / `test`） | esbuild 需要 spawn 子进程，agent 沙箱禁止 → **在真实终端跑**；`pnpm typecheck` 不受影响 |
| `ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION` / `Lockfile failed supply-chain policy check` | pnpm 12 的 24 小时供应链防护挡下了太新的版本。本工程已在 `frontend/pnpm-workspace.yaml` 显式固定 `minimumReleaseAge: 1440` 并据此重建 lockfile。**若再次出现**：先 `pnpm install --frozen-lockfile` 看是哪几个包 → 多半只需等满 24 小时，或把该包加进 `minimumReleaseAgeExclude`（显式豁免，PR 说明理由）。**不要**把 `minimumReleaseAge` 改成 0 |
| 同一份 lockfile 在 A 机器过、B 机器挂 | 两台机器的 pnpm **大版本不同**（pnpm 11 没有该默认策略、pnpm 12 有）。本仓库已显式固定策略值；诊断用 `pnpm config list` 看 `minimumReleaseAge` 的有效值 |
| `curl.exe` 报 `schannel: AcquireCredentialsHandle failed` | 本机 schannel 在 agent 沙箱内不可用；改用 Node（`pnpm install` / `node scripts/*.mjs` 都正常） |
| `pnpm install` 报 `ERR_PNPM_IGNORED_BUILDS` / esbuild postinstall EPERM | 已在 `frontend/pnpm-workspace.yaml` 显式 `allowBuilds: esbuild: false`（原生二进制由可选依赖提供） |
| 前端 `gen:api` 报"无法获取实时 OpenAPI" | 后端没起。启动后重跑；离线时会自动回退 `frontend/openapi.snapshot.json` |
| 中文乱码（终端） | 先 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` |
| 根目录出现 `debug.log` | 非项目产物（DSH Desktop 的 Electron crashpad 日志），已在 `.gitignore` 忽略 |

---

## 合规声明

- 当前所有分数线与位次均为**确定性模拟数据**（`is_synthetic=1`、`verified=0`），
  **严禁用于真实填报**；院校名与专业名为公开信息，但数值是造的。
- **天津、海南**规则仍为转载源（`SECONDARY`），升级 `PRIMARY` 前其推荐结果**不得用于真实填报**，
  UI 必须显示「规则待核实」横幅（接口已在 `meta` 中返回 `requires_banner` 供前端直接使用）。
- **选考科目池**（"从几门里选 3 门"）自 M4 起按同一套来源纪律落码，六省各有官方来源：
  浙江 / 上海 / 北京 / 山东 / 海南 = `PRIMARY`（考试院官网原文）；天津 = `PRIMARY_GOV`
  （市政府门户转述，已降级并写明理由）。浙江独有"技术"科目；官方行文"生物/生物学"并存，
  系统统一用招生计划字段口径"生物"并在 `caveats` 记录差异。未核实到原文的省份**降级为
  "由招生计划反推"**（`origin=DATA_DERIVED` + 前端提示），**绝不编造科目池**。
- 系统**不做录取概率承诺**：概率一律以区间 + 证据链呈现，文案禁止"保证录取""一定能上""百分百"。
- 真实数据接入（M6）前必须确认来源授权与使用条款，不得擅自抓取考试院网站。
- 免责声明必须出现在：报告页、导出 PDF/XLSX、Chat 首次回复（当前均已落实）。
