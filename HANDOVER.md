# 交接说明（HANDOVER.md）—— 本文件由上一轮对话生成，供下一轮对话接手

> **给接手的 agent 的第一条指令**：先读 `AGENTS.md`（唯一权威施工总纲）与 `docs/DOMAIN_RULES.md`
> （领域规则与算法参数），再读 `docs/DECISIONS.md`（ADR-001…ADR-015 + 各轮验收记录），
> 然后读本文件了解"现在站在哪里"。**不要凭常识补全任何规则数字**。

- 工作区：`D:\exam_select`（无空格）
- 生成时间：M6 完成后
- 下一轮起点：**M7（加固与交付）**；M6 的已知待办见 §7（回测口径、性能、2021/2022 两年历史）

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
| M1 | 数据层与模拟数据生成（六省 20 个批次级规则包） | ✅ 完成（M5 期间修掉一个池截断缺陷，见 ADR-014） |
| M2 | 核心算法引擎 | ✅ 完成（`safety_margin` 在 M5 重标定为 0.60） |
| M3 | 后端 API | ✅ 完成 |
| M4 | 前端（5 个页面 + 强类型契约） | ✅ 完成 |
| M5 | Agent 层与防幻觉（12 个只读工具 + 护栏 + 对话式建档 + 会话落库） | ✅ 完成 |
| **M6** | **真实数据接入（浙江 2023–2026；其余五省仍为模拟数据）** | ✅ **完成**（ADR-015） |
| M7 | 加固与交付 | ⬜ 下一轮 |

### M6 交付了什么（一句话版）

浙江考生现在看到的是**浙江省教育考试院公开发布的真实投档数据**：
2026 年 18,543 个「专业+院校」投档单位（当年计划数、选考要求、最低分与位次）+
2023/2024/2025 三年 38,957 条投档历史 + 官方 2026 一分一段表（494 分累计 184,816 人，原文）。
其余五省继续用模拟数据。两边的行用 `source_url` 前缀区分：`real://` vs `synthetic://`。

**必读**：`docs/DECISIONS.md` **ADR-015**（含五个实测缺陷的复盘与"被否决的方案"）
与 `docs/DATA_DICTIONARY.md` **§5bis**（真实数据口径：跨年对齐、一分一段表两级质量、混装剔除规则）。

### 可复现的实测结果（不是"应该通过"）

| 项 | 实测 |
|---|---|
| 数据装载 | `scripts/seed.py --source hybrid` **幂等**（重复运行计数与 digest 不变） |
| 数据校验 | `python -m app.etl.validate --report` → **0 error / 10 warning** |
| 交叉校验 | 2024 年两个独立官方来源：12,869 条可比对记录中 **12,830 条完全一致（99.7%）** |
| 浙江真实数据 | 1,692 院校 · 18,543 专业 · 18,543 投档单位 · 57,502 计划快照 · 38,957 历史 |
| 三年历史覆盖率 | 18,543 条当年记录中 **10,500 条**能拿到完整 2023–2025 三年历史；3,394 条无历史（走 Step 0 类比） |
| 后端测试 | 见 §4（本轮结束时的真实输出） |
| 幻觉测试 | 20 例 × 2 条防线，**编造次数 = 0** |

### git 状态

- 分支 `main`，远端 `https://github.com/dnjz666/exam_select.git`
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
| **`seed.py --reset` 的连带影响** | 它会让**所有浏览器里已保存的草稿 id 失效**（localStorage 的 `exam-select.profile-draft`）。前端已做自愈（PATCH 404 → 自动重新建档，ADR-015 缺陷 7）；若在推荐页/志愿表页直接刷新看到 404，**回建档向导走一步**即可恢复 |
| **进程内缓存**（ADR-016） | L2 缓存静态参考数据（院校/专业/单位/历史）、L3 缓存概率结果。写库后由 `get_db` 自动 `bump_generation()` 失效；测试/排错可调 `repositories.disable_cache()` 或 `probability.clear_result_cache()`。**改模型参数或直接改库（绕过 API）后必须清缓存**，否则会读到旧结论 |
| PowerShell 坑 | **不要用 `curl.exe -d '{"json"}'` 发 POST**（双引号被吃 → 422）；用 `Invoke-RestMethod` + `ConvertTo-Json` |
| 终端中文 | 先 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` |
| `debug.log` | 根目录若出现，是 DSH Desktop 的 Electron crashpad 日志，非项目产物（已 gitignore） |

---

## 4. 验收命令（每轮结束必须真跑并贴输出）

```powershell
$py = 'backend\.venv\Scripts\python.exe'

# 数据（幂等；--reset 会清空学员档案、志愿表与对话）
#   --source hybrid  = 浙江真实数据 + 其余五省模拟数据（M6 起的默认）
#   --source real    = 只有浙江真实数据
#   --source synthetic = 回到 M5 的"六省全模拟"状态
& $py scripts\seed.py --reset --source hybrid
& $py -m app.etl.validate --report                     # 期望 0 error

# ★ 改了 province_year_stats 的表结构后必须 --reset（create_all 不会给已存在的表加列；
#   seed.py 会提前检测并给出明确指引，不会让 SQLite 报一句看不懂的 "no column named"）

# 数据采集/解析（只在需要重新拉官方文件时跑；data/ 下已有结果）
& $py scripts\collect_zj_score_segment.py fetch --year 2026   # 官方一分一段表 PDF
& $py scripts\collect_zj_score_segment.py parse --year 2026   # → normalized CSV
& $py scripts\collect_zj_scorelines.py build                  # 年度一段表 → CSV
& $py scripts\parse_zj_compilation_pdf.py --year 2024         # 合编 PDF → CSV（含交叉校验）

# 后端测试与覆盖率
& $py -m pytest backend/tests -q --cov=app.core --cov-fail-under=90

# M5/M6 验收：幻觉测试（20 例，编造数 = 0）
& $py -m pytest backend/tests/test_agent_hallucination.py -q

# M6 验收：真实数据适配器（19 项，只读 data/ 下的真实文件）
& $py -m pytest backend/tests/test_loaders_zhejiang.py -q

# 回测（四项未达标则 exit 1）；改了概率参数必须重跑并附前后对比
& $py scripts\run_backtest.py --province zhejiang --year 2025
& $py scripts\calibrate_params.py --province zhejiang --year 2024      # 参数网格标定

# 起服务
Set-Location backend
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

> ⚠️ **真实数据下的回测现状（ADR-015 待办）**：浙江历史只有 2023–2025（2021/2022 的年度表
> 没有选考科目要求，故意不导入）。因此 `--year 2025` 只有 2 年历史窗口，
> 回测报告里的分层校准数字**不能**与 ADR-014 的模拟基线直接对比。
> M7 要做的是：要么补到 2021/2022（需要带选考要求的官方来源），要么把回测口径
> 明确写成"2 年窗口"，并把对比基线一并换成同一窗口下的模拟结果。

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
L1 backend/app/etl/**  synthetic.py（确定性模拟，seed 固定）
                       loaders/zhejiang.py（M6 真实数据适配器，纯读取 + 组装）
                       scripts/ 下的采集与解析脚本（网络只在这里，且必须登记来源与 sha256）
```

- **`core/` 纯函数铁律**：已由测试与覆盖率守护。
- **来源纪律**：任何规则数字必须带 `source_url`；`BatchRule` 还要 `source_quote` + `verified_status`
  + `verified_year`；`SubjectPool`（选考科目池）同受约束；**工具返回的每个数字也必须带来源**。
  真实数据的 `source_url` 前缀是 `real://`，模拟数据是 `synthetic://`——**这是两边的唯一判据**
  （不要用 `province` 判断，真实院校的 `province` 是"院校所在地"，可能任意一个省）。
- **契约铁律**（有测试守着）：① 每个推荐项 `evidence` 非空且带 `source_url`；
  ② `probability is None ⇔ confidence == NO_DATA` 且 `reasons` 说明原因；③ 无来源数字为零；
  ④ OpenAPI 是契约唯一来源，**响应体必须强类型**（ADR-011）。
- **幻觉铁律**（M5 新增）：**LLM/叙述器产出的任何数据型数字，必须能在本次会话的工具返回值里找到**，
  否则整条回复被护栏改写。改 agent 层时不要绕过 `guard_response`。
- **口径铁律**（M6 新增）：位次归一化的分母是 `province_year_stats.total_candidates`
  （= 该年分数段表覆盖的最低分累计人数）；`segment1_cumulative` 只用于标定曲线。
  两列混用会让跨年位次凭空放大 1.7 倍（ADR-015 缺陷 1）。
- 红线（违反即返工）：`core/` 里 import DB/网络/LLM；硬编码分数线/位次/志愿数；
  让 LLM 产生数字；无证据链返回推荐；跳过回测改概率参数；用"应该能跑"代替实测；
  **给缺失字段补一个"看起来合理"的值**（M6 里 2021/2022 没有选考要求就直接不导入）。

---

## 6. 上一轮（M5）的关键决策与实测发现

详见 `docs/DECISIONS.md` **ADR-013**（agent 设计）与 **ADR-014**（数据缺陷 + 重标定）。
本轮（M6）的决策与五个实测缺陷见 **ADR-015** 与 `docs/DATA_DICTIONARY.md` §5bis。

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

---

## 7. 下一轮：M7（加固与交付）

清单（按优先级）：

1. ★ **回测口径**（M6 留下的最大一块）：浙江历史只有 2023–2025，`--year 2025` 只有 2 年窗口，
   分层校准数字**不可**与 ADR-014 的模拟基线直接对比。要么补到 2021/2022（需要带选考要求的
   官方来源），要么把回测口径明确改成"2 年窗口"并换同口径基线。
2. ★ **性能**：`evaluate_candidates` 在浙江真实数据下**热缓存 0.5–1.0s / 冷启动约 4s**
   （模拟侧只要 0.6s）。ADR-016 已把 25s → 0.7s（热）：σ 一次遍历、Φ(z) 有理逼近、
   静态数据与概率结果双层缓存。**仍未达 P95 < 1s**（冷启动要读 5.8 万行 + 算 1.5 万个单位）；
   下一步需要**架构改动**：候选池"粗排 → 精算"，或把单位级中间量预计算落库。
   ⚠️ 改之前先读 ADR-016 的"必须记住的两条"（缓存键必须含目标计划数；不要用 `id()` 做键）。
3. **推荐列表截断方式**（M6 手测发现）：`limit=8` 时返回的 8 条**全是"冲"**
   （候选按分层排序后取前 N）。展示层应按分层配额取样，别让用户以为"一个稳的都没有"。
4. 边界：0 志愿 / 超高分 / 超低分 / 全被过滤 / 一次对话内连续建档。
5. 前端视觉回归：引入 Playwright（现在只有 `pnpm smoke` 的契约级验证，不能证明像素与交互）。
6. 敏感度热力图（DOMAIN_RULES §3.1 待补）。
7. §6.8 的两个增量风险码：调剂越界、退档条款命中（上海原文已核实，字段已就位）。
8. Docker 生产配置（本机 Docker 守护进程未运行，需人工启动验证）。
9. 用户手册与 `DECISIONS.md` 汇总；`alembic` 迁移（现在 dev 靠 `create_all`，
   M6 加了两列只能靠 `seed.py --reset`，已在脚本里给出明确指引）。
10. 规则包的 `verified_year` / `verified_status` 复核（天津/海南升 PRIMARY 是长期待办）。
11. **前端"保底志愿缺失"提示**：浙江真实数据在 2 年窗口下**一条"保/垫"都给不出**
    （ADR-015 缺陷 6）。UI 需要据此明确提示"当前数据不足以给出保底志愿"，
    而不是让用户看到一个没有垫底的志愿表。

**M7 注意**：`safety_margin=0.60` 意味着"保底"标签更稀缺，
`planner` 会更频繁地向更保守方向借位；如果做性能/边界改造，别把这条语义改掉。

---

## 8. 已知边界（诚实披露，别在下一轮"顺手修掉"）

- **真实 LLM 客户端未对真实服务验证过**（本机无 API key）。`llm.py` 的 OpenAI 兼容实现
  由注入的假实现覆盖测试（含"编造必被拦"与"合规必放行"两个方向）。默认关闭。
- **浙江真实数据只有 3 个历史年**（2023/2024/2025）：2021/2022 的官方年度表不含选考科目要求，
  本加载器**故意不导入**（宁可少两年，也不编造"选考不限"）。想补两年必须找到带选考要求的来源。
- **2023–2025 的一分一段表是标定估计**（`is_synthetic=1`），不是官方分数段表；
  官方只有 2026 年那张（已用原文）。反查分数与专业实际最低分有残差，校验器发
  `W_RANK_SCORE_MODELED` 警告（实测最大 38 分，99.5% 完全自洽）。
- **真实数据的学费 / 保研率 / 硕博点留空**（官方投档表不发布）：`tuition=0`、卡片上会显示 0。
  层次标签（985/211/双一流）只在**院校名精确命中**人工名册的 400 所上补齐，
  其余 1,292 所留空——空标签会让 `level_score` 与 Step 0 类比池变粗，这是刻意的取舍。
- **专业名跨年改名会断开历史链**（如"新闻传播学类"→"新闻传播学类(含智能与国际传播创新班)"
  可以靠基名接上，但改成完全不同的名字就接不上）→ 该链当年会被判成"新增专业"走 Step 0。
- **规则式意图路由不认简写**："物化生"不会被拆成三门选考 → 此时会**追问**而不是猜。
- **对话式建档只写可增量字段**；省份不会被一句话覆盖（这是刻意的安全设计）。
- 前端无浏览器 E2E / 视觉回归；`pnpm smoke` 证明契约与数据流，不证明像素。
- 意向地区/门类的权重滑块与后端 `weights` 参数尚未联动（只影响排序，不影响概率）。
- 其余五省仍为**模拟数据**（规则包、科目池、覆盖率、规则展示、agent 查询六省都可用）。

---

## 9. 关键文件索引

| 想找什么 | 去哪 |
|---|---|
| 施工总纲 / 每轮计划与验收命令 | `AGENTS.md` |
| 投档规则、算法参数、经验规则库、黄金用例规范 | `docs/DOMAIN_RULES.md` |
| 字段口径、时间轴、API 口径、`chat_messages`、**真实数据口径（§5bis）** | `docs/DATA_DICTIONARY.md` |
| 全部决策与被否决方案、各轮验收记录 | `docs/DECISIONS.md`（ADR-001…ADR-015） |
| **M6 真实数据接入的设计、五个实测缺陷、性能复盘** | `docs/DECISIONS.md` **ADR-015** |
| **真实数据适配器（浙江）** | `backend/app/etl/loaders/zhejiang.py`（+ `tests/test_loaders_zhejiang.py`） |
| 官方数据采集/解析脚本 | `scripts/collect_zj_scorelines.py` · `parse_zj_compilation_pdf.py` · `collect_zj_score_segment.py` · `zjzs_fetch.py` · `package_zj_data.py` |
| 采集来源登记（URL + sha256） | `data/raw/zhejiang/manifest.json` |
| 数据装载入口（幂等，支持三种 source） | `scripts/seed.py` |
| M5 agent 设计与数据缺陷复盘 | `docs/DECISIONS.md` **ADR-013 / ADR-014** |
| 幻觉护栏 | `backend/app/agent/guard.py`（+ `tests/test_agent_guard.py`） |
| 工具层（12 个只读工具） | `backend/app/agent/tools.py`（+ `tests/test_agent_tools.py`） |
| 对话编排（两条路径 + 建档 + 落库） | `backend/app/services/chat_service.py` |
| 幻觉验收测试 | `backend/tests/test_agent_hallucination.py`（20 例 × 2 条防线） |
| 概率模型心脏 | `backend/app/core/probability.py`（§6.2 八步 + Step 0 回退 + Step 8.6 安全闸门） |
| 模拟数据生成器（含 ADR-014 修复） | `backend/app/etl/synthetic.py::_candidate_colleges` |
| 前端 API 客户端 / 端到端冒烟 | `frontend/src/api/client.ts` · `frontend/scripts/smoke.mjs` |
| 运维脚本 | `scripts/{seed,run_backtest,calibrate_params,pip_online,bootstrap_wheels}` |
