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
| **M6.5** | **专业四级分类规则库 + 目录归属回填（用户实测报障）** | ✅ **完成**（ADR-018） |
| **M6.6** | **院校层次判别增强 + 地区维度 + 持久结果缓存 + 配额调整** | ✅ **完成**（ADR-019） |
| **M7** | **加固与交付（进行中：截断方式 ✅ / 会话定序 ✅）** | 🟡 **进行中** |
| M7 剩余 | 回测口径 · 性能 P95<1s · 边界 · Docker · 手册/alembic 等 | ⬜ 待做 |

### M7 已完成项

* ✅ **推荐列表截断方式**（ADR-020）：原"排序取前 N"在 `limit` 小于 CHONG 候选数时
  返回整页"冲"（实测 limit=8/20/60 全部如此，而全池有 BAO 62 / DIAN 7824）。
  改为按分层配额取样：limit=8 → 冲3/稳3/保2；limit=60 → 冲23/稳22/保11/垫4。
  新增 `stats.tier_allocation` / `stats.tier_shortfall` + 保底缺失警告 + 前端展示。
* ✅ **会话历史定序**（ADR-021）：`time.time_ns()` 在 Windows 上粒度约 15.6ms，
  同 tick 内返回相同值 → 同秒消息只能靠随机后缀定序 → **约 50% 概率把一问一答排成"答、问"**
  （会话历史是证据链，顺序错乱=证据链读不通）。已改为 `msg-<ns>-<进程内序号>-<随机>`，
  40 轮真实问答 0 次倒置，全量测试连跑 4 次全绿。

> ⚠️ **`_next_id` 的定序语义别改回去**：只靠纳秒 + 随机后缀在 Windows 上必然偶发倒置。
> 回归用例 `tests/test_chat_ordering.py` 会**冻结时钟**来确定性地守住它。

* ✅ **筛选/偏好并入建档向导 + 意向专业分级 + 删除学费维度**（ADR-022）：
  筛选与偏好只在**向导第 4 步**填一次并持久化到档案，推荐与志愿表都由后端按档案推导
  （`recommend_service.criteria_from_profile`），前端 `/recommend` 与 `/plans/generate`
  都**不再传 `filters`**（该字段降级为可选高级覆盖）。意向专业改为 **门类 → 专业类**
  （新端点 `GET /meta/major-taxonomy`，直接输出规则库的 12 门类 / 93 专业类 + 库中真实专业名数）
  + 第三级「专业名」走 `/majors/search`。**删除**学费预算、学费硬约束、`weight_tuition`、
  `TUITION_HIGH` 风险码（**风险码表 14 → 13**）、`tuition_score`；学费**数据与展示保留**
  （铁律 10 由展示层保证：卡片/志愿表/报告显示学费 + 非公办标记）。

> ⚠️ **`filters` 的默认值不能当成"考生要求不过滤"显式传下去** —— 那会**无声抹掉档案意向**
> （实测踩过：`intent_as_hard=False` 在 API 层覆盖了档案里的硬约束，推荐结果混进非意向专业）。
> 该字段已改为 `bool | None`：`None` = 用档案值。
> ⚠️ **硬约束只认 专业名/专业类/门类 三档，不认"相关门类"**（`RELATED_CATEGORY` 是软偏好概念）；
> 旧写法只比对 `major.category`，考生选「计算机类」会把**全部**候选一票否决（已修）。

### M6.6 交付了什么（一句话版）

① 层次判别不再只看 985/211/双一流：名册 tier 的 `PROV`/`PRIV` 原先没映射，
**231 所省重点只拿 0.45、31 所民办被打成公办** —— 已修（浙工大 0.45 → **0.60**）。
② 地区维度原先对"未填意向"恒为常数：现按**本省认可度 1.00** + **地区高教资源密度**
（数据驱动：各省双一流及以上院校数 / 31）区分；浙工大在同层排名由第 173 → **第 68**。
③ agent 新增第 **13** 个只读工具 `get_college_level_facts`（判据 + `level_score` 的来源规则 +
caveats，**刻意不给排名**）；并补全**意图路由**——原先"XX大学怎么样"落到 `unknown`、
被当成"问分数线"回答，工具**注册了但走不到**（见 ADR-019 补充）。④ `recommend` 结果**持久缓存**
（`result_cache` + `app_meta.data_version`），同位次同筛选可跨考生、跨重启复用。
⑤ 配额改为 **冲+稳 = 75%（冲≈稳）、保+垫 = 25%**（浙江 80 → 冲 30 / 稳 30 / 保 15 / 垫 5）。

**必读**：`docs/DECISIONS.md` **ADR-019**。

> ⚠️ **改了规则库 / 重新播种 / 回填之后，必须推进 `data_version`**（`seed.py` 与
> `backfill_major_taxonomy.py` 已自动调用），否则持久结果缓存会继续返回旧结论。
> 查看概况用 `services.cache_service.stats(session)`。
> ⚠️ **上海 `wen_hit_rate` = 84.30%（< 85%）是 ADR-019 之前就存在的缺陷**，
> 已用改动前的基线库对照确认；配额只影响志愿表生成，不影响分层校准。列入 M7。

### M6.5 交付了什么（一句话版）

浙江真实数据的 `majors.category`/`discipline` 原先**全是 NULL**（官方投档表不发布专业目录归属），
导致推荐页"意向专业"筛选**完全不生效**、概率 Step 0 的类比池**跨专业乱类比**
（实测：拿 985 院校里任意专业类比"社会学"）。
现新增**四级专业分类规则库**（门类 → 专业类 → 专业 → **招生方向**）：
浙江 2026 的 18,543 个投档单位**门类级覆盖 99.84% / 专业类级 99.08%**；
意向"计算机类"时的效用取值数从 3（同院校内恒定）提升到 **124**。

**必读**：`docs/MAJOR_TAXONOMY.md`（规则库唯一权威说明）与 `docs/DECISIONS.md` **ADR-018**。

> ★ **已有数据库不必重新播种**：跑 `scripts/backfill_major_taxonomy.py --apply`
> 即可原地回填（幂等，**不碰考生档案/志愿表/对话**）。
> 若看到"意向专业勾了没反应"，先确认这一步跑过。

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
| **地区筛选（ADR-017）** | "意向地区"取的是**院校所在地**（`College.province`），不是招生省；选项来自 `/recommend` 的 `stats.region_options`（动态，覆盖 31 个省级行政区）。**院校所在地缺失的院校不会被地区硬约束剔除**（不知道就不能否决） |
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

# 专业目录归属回填（ADR-018；已有数据库**不需要**重新播种）
& $py scripts\dedupe_major_taxonomy.py                        # 重复键检测/消解（幂等）
& $py scripts\build_major_taxonomy_data.py                    # JSON → Python 模块 + 守卫 + 不变量校验
& $py scripts\backfill_major_taxonomy.py                      # 预演（只补空值）
& $py scripts\backfill_major_taxonomy.py --apply              # 实际写库（幂等）
& $py scripts\backfill_major_taxonomy.py --reclassify         # ★ 改了规则库后：重算已有行（看 diff）
& $py scripts\backfill_major_taxonomy.py --reclassify --apply

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
3. ✅ **已完成（ADR-020）· 推荐列表截断方式**：原实现"按 `(tier, -utility)` 排序取前 N"
   在 `limit` 小于 CHONG 候选数时返回整页"冲"（实测 limit=8/20/60 全部如此，而全池有 BAO 62 / DIAN 7824）。
   已改为 `recommend_service.allocate_display_slots()` **按分层配额取样**：
   浙江 630 分 limit=8 → 冲3/稳3/保2；limit=60 → 冲23/稳22/保11/垫4。
   新增契约字段 `stats.tier_allocation` / `stats.tier_shortfall`；前端展示"各档取样"与保底缺失提示。
   **注意**：`planner._allocate`（志愿表）仍是"向更保守方向借位"，**与展示层取样刻意不同**，
   别把两者合并。
4. **Step 0 类比池阶梯**（ADR-018 引入）：目录归属回填后，类比池从"任意专业"收紧为
   "同专业类"，覆盖率 **−0.29pp**（15,333 → 15,281 可评估单位），换掉了跨专业编造。
   可考虑加"**保持专业类不变、逐级放宽地区/层次**"的类比阶梯把覆盖率补回来——
   **必须先用回测验证**（AGENTS.md §6.9），且绝不允许跨专业类兜底。
5. 边界：0 志愿 / 超高分 / 超低分 / 全被过滤 / 一次对话内连续建档。
6. 前端视觉回归：引入 Playwright（现在只有 `pnpm smoke` 的契约级验证，不能证明像素与交互）。
7. 敏感度热力图（DOMAIN_RULES §3.1 待补）。
8. §6.8 的两个增量风险码：调剂越界、退档条款命中（上海原文已核实，字段已就位）。
9. Docker 生产配置（本机 Docker 守护进程未运行，需人工启动验证）。
10. 用户手册与 `DECISIONS.md` 汇总；`alembic` 迁移（现在 dev 靠 `create_all`，
    M6 加了两列只能靠 `seed.py --reset`，已在脚本里给出明确指引）。
11. 规则包的 `verified_year` / `verified_status` 复核（天津/海南升 PRIMARY 是长期待办）。
12. 🟡 **"保底志愿缺失"提示 —— 后端已完成，前端待视觉验证**：
    后端现在通过 `stats.tier_shortfall` + `warnings` 明确披露（ADR-020）；
    `Recommend.tsx` 已加醒目提示，但**前端构建/视觉回归需真实终端**（沙箱 esbuild EPERM），
    本机尚未跑过 `pnpm build` / `pnpm smoke`。
    ⚠️ 另注意：**推荐列表里 BAO/DIAN 是有候选的**（全池 BAO 62 / DIAN 7824），
    缺的是**志愿表**侧（2 年窗口 + 安全闸门把保/垫降级为稳，见 ADR-015 缺陷 6）。
13. **首次回复免责声明硬编码"当前数据为模拟数据"**（`chat_service.DISCLAIMER`）——
    对浙江考生是**事实错误**（他们看的是省考试院真实投档数据）。
    正确做法：按 `source_url` 前缀（`real://` vs `synthetic://`）动态生成。
14. **上海 `wen_hit_rate` = 84.30%**（< 85%，ADR-019 之前即存在，已用基线库对照确认）。

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
  ✅ **已修（ADR-017）**：推荐页勾的意向现在会合并进软偏好打分；"意向地区"选项也从
  `/recommend` 的 `stats.region_options` 动态生成（覆盖候选池全部 31 个省级行政区，
  不再只有六省市）。仍未做的是**权重滑块**（`weights` 目前只有 API 层能传）。
- 其余五省仍为**模拟数据**（规则包、科目池、覆盖率、规则展示、agent 查询六省都可用）。

---

## 9. 关键文件索引

| 想找什么 | 去哪 |
|---|---|
| 施工总纲 / 每轮计划与验收命令 | `AGENTS.md` |
| 投档规则、算法参数、经验规则库、黄金用例规范 | `docs/DOMAIN_RULES.md` |
| 字段口径、时间轴、API 口径、`chat_messages`、**真实数据口径（§5bis）** | `docs/DATA_DICTIONARY.md` |
| **专业四级分类规则库（门类→专业类→专业→招生方向）** | `docs/MAJOR_TAXONOMY.md` |
| **专业分类纯函数分类器** | `backend/app/core/major_taxonomy.py`（+ `major_taxonomy_data.py` + `tests/test_major_taxonomy.py`） |
| **专业目录归属原地回填（不碰用户数据）** | `scripts/backfill_major_taxonomy.py`（`--reclassify` 用于规则改动后重算） |
| **规则库 JSON 重复键检测/消解** | `scripts/dedupe_major_taxonomy.py`（详见 ADR-018 补充） |
| **持久结果缓存（相似查询复用）** | `backend/app/services/cache_service.py`（+ `tests/test_cache_service.py`） |
| **院校层次事实工具（agent 第 13 个）** | `backend/app/agent/tools.py::_get_college_level_facts` |
| **层次问答的意图路由与叙述** | `parser.py`（`college_level` 意图）· `chat_service._answer_about_school_level` · `narrator.narrate_college_level`（+ `tests/test_agent_college_level.py`） |
| 全部决策与被否决方案、各轮验收记录 | `docs/DECISIONS.md`（ADR-001…ADR-018） |
| **M6.5 专业目录归属缺陷与四级规则库** | `docs/DECISIONS.md` **ADR-018** |
| **M7 推荐列表截断方式（分层取样）** | `docs/DECISIONS.md` **ADR-020** |
| **M7 会话历史定序缺陷** | `docs/DECISIONS.md` **ADR-021** |
| **M7 筛选/偏好并入向导 + 意向专业分级 + 删学费维度** | `docs/DECISIONS.md` **ADR-022** |
| **专业分类规则库端点（意向专业分级来源）** | `GET /api/v1/meta/major-taxonomy` · `services/meta_service.py::major_taxonomy_meta` |
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
