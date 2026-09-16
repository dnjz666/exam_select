# 高考志愿填报智能体 —— 构建总纲（AGENTS.md）

> 本文件是本仓库的**唯一权威施工说明**。任何接手本项目的 AI agent 在动手前必须先读完本文件，
> 再读 `docs/DOMAIN_RULES.md`（领域规则与算法参数库，**必读，不可跳过**）。
> 两者冲突时，以本文件的架构约束为准；涉及算法参数与投档规则时，以 `docs/DOMAIN_RULES.md` 为准。

---

## 0. 角色设定（你这次要扮演谁）

你是一位**有十余年一线经验的高考志愿规划名师**，同时是一名**严谨的资深全栈工程师**。
这两个身份同等重要，且必须同时在线：

- 作为**名师**：你知道位次比分数可靠、知道"大小年"会坑人、知道保底必须真保底、
  知道新高考院校专业组模式下不服从调剂意味着退档。你**不会**为了让家长开心而说"这个稳了"。
- 作为**工程师**：你知道 LLM 会一本正经地编造分数线。所以你把**所有数字的计算权交给确定性算法**，
  把 LLM 限制在"理解意图、解释结果、追问澄清"三件事上。

**贯穿全项目的最高原则：宁可不答，不可编造。** 志愿填报的错误不是"体验问题"，是"人生事故"。

---

## 1. 项目目标与非目标

### 1.1 目标
构建一个面向 **3+3 新高考六省市（浙江、上海、北京、山东、天津、海南）** 的志愿填报智能系统，
能够：

1. 采集考生档案（省份、选考科目、分数/位次、身体条件、偏好）
2. 基于**位次法**给出可解释、可复现、可回测的院校专业组/专业推荐
3. 生成满足冲稳保梯度约束的**完整志愿表**（含顺序优化与风险扫描）
4. 由 LLM 以名师口吻解释推荐理由、回答追问、指出风险
5. 导出可打印的志愿报告（PDF/Excel）

### 1.2 非目标（明确不做，避免范围爆炸）
- ❌ **不做全 31 省**。先做六省市中**一个省的端到端闭环**（默认浙江，因其"专业+院校"模式最复杂，
  跑通后其余省份是配置问题），其余五省只交付规则配置包。
- ❌ **不做实时爬虫**。M0–M5 全部使用**确定性模拟数据**；真实数据接入是 Phase M6 的独立工作项。
- ❌ **不做志愿填报代提交**。系统只输出建议与报告，绝不连接任何省考试院填报接口。
- ❌ **不做录取概率的"承诺"**。任何 UI 文案、API 字段、导出报告中**禁止**出现
  "保证录取""一定能上""百分百"等表述。概率必须以区间和证据呈现。
- ❌ **不做艺体/提前批军警校的专项规则**（结构上预留字段，不实现逻辑）。

### 1.3 成功判据（Definition of Done）
系统建成当且仅当同时满足：

| 判据 | 阈值 |
|---|---|
| 保底失效率（回测：被判为"保/垫"却未投档的比例） | **0%** |
| 稳档命中率（回测：被判为"稳"且实际投档的比例） | ≥ 85% |
| 冲档命中率（回测） | 落在 10%–40% 区间 |
| 概率校准 (Brier score) | ≤ 0.15 |
| 算法层单测覆盖率 | ≥ 90% |
| 幻觉测试（询问库外院校分数线，20 次） | 编造次数 = **0** |
| 端到端流程 | 填档案 → 出推荐 → 生成志愿表 → 导出 PDF 全通 |

---

## 2. 领域硬知识（先记住这些，否则一定做错）

### 2.1 六省市投档规则表（**核心数据，进代码前先落成配置**）

| 省份 | 投档单位 | 平行志愿数 | 组内专业数 | 专业调剂 | 关键特征 |
|---|---|---|---|---|---|
| **浙江** | 专业(类)+院校 | 80 | — | **无调剂概念** | 一段/二段；一个志愿=一个专业，报满即录，无退档调剂问题 |
| **山东** | 专业(类)+院校 | 96 | — | **无调剂概念** | 常规批；同上 |
| **上海** | 院校专业组 | 24 | 4 | 有 | 每组 4 个专业 + 服从调剂 |
| **北京** | 院校专业组 | 30 | 6 | 有 | 本科普通批 |
| **天津** | 院校专业组 | 50（本科A段）/ 25（本科B段） | 组内多个 | 有 | 征询志愿各 25 个；高职专科批 20 个 |
| **海南** | 院校专业组 | 30（本科普通批） | 6 | 有 | 提前普通类 6 个；高职专科批 10 个 |

> **核实状态（2026-02 官方原文核实，原文摘录见 `docs/DOMAIN_RULES.md` §1.2）**：
> 浙江 / 山东 / 上海 ✅ `PRIMARY`；北京 🟡 `PRIMARY-GOV`（市政府门户转述，待考试院原文复核升 PRIMARY）；
> **天津 / 海南 🟡 `SECONDARY`（转载源）——升级为 `PRIMARY` 前，其推荐结果不得用于真实填报，
> UI 必须显示「规则待核实」横幅**。
> **每一条规则必须带 `source_url` 与 `verified_year` 字段。**
> 未标注来源的规则数字视为**不可用**，不得进入推荐结果。
>
> ★ **一个省 ≠ 一套规则，必须建模到批次级**：同一省份不同批次的志愿性质完全不同
>（例：浙江普通类专业平行志愿每段 ≤ 80 是**平行**志愿，而普通类提前录取院校是 5 个院校**顺序**志愿）。
> 规则包按批次级 `BatchRule` 建模（见 §6.6 与 `docs/DECISIONS.md` ADR-006），
> 本表数字均指各省**本科普通批 / 专业平行志愿主批次**。

**"专业+院校" vs "院校专业组"是整个系统的分叉点：**
- 前者一个志愿就是一个具体专业 → 无调剂、无退档、粒度细 → 概率模型直接作用于"专业录取位次"
- 后者一个志愿是一个组 → **组内服从调剂是保命选项** → 概率模型作用于"组投档位次"，
  且必须额外评估"组内专业是否都能接受"（冲进去被调剂到冷门专业是真实事故）

### 2.2 必须内建的十条名师铁律

1. **位次 > 分数**。跨年比较一律用位次，不用分数。分数只用于展示。
2. **考生人数会变**。今年考生比去年多 5%，同样的位次含金量就下降。必须做位次归一化。
3. **大小年必防**。某校某年异常低分，次年大概率反弹。绝不使用单年数据下结论。
4. **保底要"真保底"**。**考生位次必须比该单位近三年最难年份的切线还靠前 ≥ 60%**（`safety_margin`，
   经 M2 回测标定），且计划数不能太小。⚠️ 原表述"单位位次优于考生位次"方向写反（那等于单位更难=不安全），
   已勘误，见 `docs/DECISIONS.md` ADR-009 勘误 2。
5. **计划数是强信号**。计划大幅增加 → 门槛下降；大幅减少 → 门槛上升。这是修正项，不是噪音。
6. **计划数小 = 波动大**。招生 < 5 人的专业，位次历史毫无预测价值，必须降置信度。
7. **顺序决定结果**。平行志愿虽是"平行"，但检索严格按考生填报顺序。**最想去的必须放最前**。
8. **服从调剂是生死线**。院校专业组模式下不服从调剂 = 主动接受退档风险，必须强提示。
9. **无历史 ≠ 不能报**，但必须标注"数据缺失/低置信度"，并用同层次院校做类比，绝不虚构位次。
10. **贵的不一定差，但必须让家长看见**。中外合作/民办/独立学院的学费必须在推荐卡片上明示。

> 完整经验规则库（含风险规则码、偏好打分细则）见 `docs/DOMAIN_RULES.md` §4、§5。

---

## 3. 系统架构

### 3.1 分层图

```
┌─────────────────────────────────────────────────────────────┐
│  L5  交互层  Web前端 (React/TS)  +  Agent对话 (LLM)          │
│      · 档案向导  · 推荐列表  · 志愿表编辑器  · 报告导出         │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST / SSE  (OpenAPI 契约)
┌───────────────────────────▼─────────────────────────────────┐
│  L4  服务层  FastAPI                                         │
│      · 路由/鉴权/会话  · Schema 校验(Pydantic)  · 编排服务    │
└───────────────────────────┬─────────────────────────────────┘
                            │ 纯函数调用（无 IO）
┌───────────────────────────▼─────────────────────────────────┐
│  L3  核心引擎  core/   ★ 全项目可信度所在 ★                   │
│    rank.py  probability.py  filters.py  scoring.py            │
│    planner.py  risk.py  backtest.py  rules/{province}.py      │
│    约束：纯函数、无网络、无DB、无LLM、100%可单测                │
└───────────────────────────┬─────────────────────────────────┘
                            │ Repository 接口
┌───────────────────────────▼─────────────────────────────────┐
│  L2  数据层  SQLAlchemy + SQLite(dev)/PostgreSQL(prod)       │
│    ETL: 解析 → 校验 → 归一化 → 入库（幂等）                    │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  L1  数据源  模拟数据生成器 (M0-M5) → 真实数据适配器 (M6)      │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 铁律：L3 核心引擎必须是纯函数

```
def estimate_probability(
    student: StudentProfile,
    target: AdmissionUnit,
    history: list[AdmissionRecord],
    rule: ProvinceRule,
    params: ModelParams,
) -> ProbabilityResult:   # 不读数据库、不发请求、不调 LLM
```

**理由**：可单测、可回测、可复现。任何"顺手查一下数据库"的写法都会让整个算法层失去可信度。
数据由 L4 查好、组装好，作为参数传进来。

### 3.3 LLM 的边界（防幻觉架构）

LLM **只能**做三件事：
1. **意图解析**：自然语言 → 结构化考生档案（缺字段就追问，不猜）
2. **结果解释**：把算法输出的数字翻译成人话（但数字必须原样引用工具返回值）
3. **澄清追问**：信息不足时提问

LLM **绝对不能**做的事：
- ❌ 生成任何分数线、位次、招生计划数、录取率数字
- ❌ 在没有调用工具的情况下描述某院校的录取情况
- ❌ 对录取结果做绝对承诺

**实现手段**（三重防护，缺一不可）：
1. System Prompt 明令禁止 + 给出正确/错误示例
2. **工具强制**：所有涉及数字的回答必须先经过工具调用（Function Calling）
3. **输出校验器**：对 LLM 回复做后置正则扫描，若出现"疑似分数线数字"但本次会话无对应工具调用记录 → 拦截并重写为"我需要查一下数据"

---

## 4. 技术栈与目录结构

### 4.1 技术栈
| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI + Pydantic v2 | Pydantic 做领域模型**和** API schema，一份定义两处用 |
| ORM | SQLAlchemy 2.x | dev 用 SQLite，prod 切 PostgreSQL 只改连接串 |
| 算法 | numpy + scipy.stats | 正态分布 `scipy.stats.norm.cdf` |
| 数据处理 | pandas | 仅用于 ETL，**不得进入 core/** |
| 前端 | React 18 + TypeScript + Vite + TailwindCSS | |
| 图表 | ECharts | 位次趋势、梯度分布 |
| 测试 | pytest + pytest-cov + hypothesis | hypothesis 用于算法性质测试 |
| LLM | OpenAI 兼容接口，provider 可插拔 | 必须可替换、可 mock |
| 部署 | Docker Compose | |

### 4.2 目录结构（**按此创建，不要自创结构**）

```
exam_select/
├── AGENTS.md                      # 本文件
├── README.md
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── docs/
│   ├── DOMAIN_RULES.md            # ★ 已存在，必读：规则表 + 算法参数 + 经验规则库
│   ├── DATA_DICTIONARY.md         # M0 创建：字段口径（以 DOMAIN_RULES.md §2 为种子）
│   └── DECISIONS.md               # M0 创建：架构决策记录 (ADR)，每轮追加
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI 入口
│   │   ├── config.py
│   │   ├── core/                  # ★ 纯算法层，禁止 import db / requests / openai
│   │   │   ├── models.py          # 领域模型 (Pydantic)
│   │   │   ├── rank.py            # 位次↔分数换算、位次归一化
│   │   │   ├── probability.py     # 录取概率模型
│   │   │   ├── filters.py         # 硬约束过滤（选科/体检/语种/单科）
│   │   │   ├── scoring.py         # 软偏好效用打分
│   │   │   ├── planner.py         # 志愿表生成与优化
│   │   │   ├── risk.py            # 风险扫描
│   │   │   ├── backtest.py        # 回测框架
│   │   │   └── rules/
│   │   │       ├── base.py        # ProvinceRule 抽象基类
│   │   │       ├── zhejiang.py    # 专业+院校，80
│   │   │       ├── shandong.py    # 专业+院校，96
│   │   │       ├── shanghai.py    # 院校专业组，24×4
│   │   │       ├── beijing.py     # 院校专业组，30×6
│   │   │       ├── tianjin.py     # 院校专业组，50/25
│   │   │       └── hainan.py      # 院校专业组，30×6
│   │   ├── api/
│   │   │   ├── deps.py
│   │   │   ├── schemas.py         # 统一响应信封（data/evidence/warnings）与请求模型
│   │   │   └── v1/
│   │   │       ├── students.py
│   │   │       ├── meta.py
│   │   │       ├── catalog.py     # 院校/专业检索、单位历史
│   │   │       ├── recommend.py
│   │   │       ├── plans.py
│   │   │       ├── risk.py
│   │   │       ├── chat.py        # SSE 通道（LLM 工具化回答见 M5）
│   │   │       └── backtest.py
│   │   ├── db/
│   │   │   ├── models.py          # SQLAlchemy 表定义
│   │   │   ├── session.py
│   │   │   └── repositories.py    # 数据访问，供 L4 调用
│   │   ├── etl/
│   │   │   ├── synthetic.py       # ★ 确定性模拟数据生成器（seed 固定）
│   │   │   ├── validate.py        # 数据质量校验
│   │   │   └── loaders/           # M6 真实数据适配器（先留接口）
│   │   ├── agent/                 # L5 agent 层（M5）
│   │   │   ├── tools.py           # ★ 工具定义（严格 schema，只读/绝不写库，数字全带来源）
│   │   │   ├── prompts.py         # System Prompt（含防幻觉条款与正反例）
│   │   │   ├── parser.py          # 自然语言 → 考生档案 + 确定性意图路由
│   │   │   ├── narrator.py        # 工具返回值 → 名师口吻解释（数字原样引用）
│   │   │   ├── guard.py           # ★ 输出校验器（幻觉拦截）
│   │   │   └── llm.py             # provider 可插拔的 LLM 客户端（可替换 / 可 mock / 可缺席）
│   │   └── services/              # 编排：查数据 → 调 core → 存结果
│   │       ├── meta_service.py
│   │       ├── student_service.py
│   │       ├── recommend_service.py
│   │       ├── plan_service.py
│   │       ├── risk_service.py
│   │       ├── report_service.py  # 报告导出（xlsx / 中文 PDF）
│   │       ├── chat_service.py
│   │       ├── backtest_service.py
│   │       └── backtest_data.py   # 回测数据装配（M2 引入）
│   └── tests/
│       ├── golden/                # ★ 黄金用例（输入→期望概率区间）
│       ├── test_rank.py
│       ├── test_probability.py
│       ├── test_filters.py
│       ├── test_planner.py
│       ├── test_risk.py
│       ├── test_backtest.py
│       ├── test_api.py
│       └── test_agent_hallucination.py   # ★ 幻觉测试
├── frontend/
│   ├── src/
│   │   ├── main.tsx               # 入口：路由（/ → /profile，首屏即向导）
│   │   ├── App.tsx                # 外壳：导航 + 档案完成度常驻提示 + 免责声明页脚
│   │   ├── pages/{Profile,Recommend,PlanBoard,Report,Chat}.tsx
│   │   ├── components/            # TierBadge · ProbabilityBar · RankTrendChart · PlanRow ·
│   │   │                          # RiskPanel · EvidenceTable · GradientChart · RuleBanner ·
│   │   │                          # StepIndicator · Disclaimer · Chart(ECharts 容器) · StateBlocks
│   │   ├── api/client.ts          # 信封感知的 fetch 封装；类型全部来自生成的 schema.d.ts
│   │   ├── api/schema.d.ts        # ★ 生成物（gitignore）：openapi-typescript 从 /openapi.json 生成
│   │   ├── lib/                   # format(纯函数，有单测) · labels(文案配色) · hooks
│   │   ├── store/                 # zustand + persist：向导草稿 / 志愿表与意愿序
│   │   └── index.css              # Tailwind 基线 + 组件类 + 打印样式
│   ├── scripts/gen-api-types.mjs  # 在线取 /openapi.json，失败回退 openapi.snapshot.json
│   ├── scripts/smoke.mjs          # 端到端闭环冒烟（按 UI 真实调用序列打真后端）
│   ├── openapi.snapshot.json      # 后端 /openapi.json 的快照（离线构建回退，**进版本库**）
│   ├── pnpm-workspace.yaml        # pnpm 11 的构建脚本白名单（allowBuilds）
│   └── package.json               # 脚本：gen:api / dev / build / typecheck / test / smoke
├── data/
│   ├── raw/{province}/{year}/     # 真实原始数据（M6）
│   ├── synthetic/                 # 生成的模拟数据
│   └── exam_select.db
└── scripts/
    ├── seed.py                    # 生成并载入模拟数据
    ├── run_backtest.py            # 跑回测出报告
    └── smoke.sh                   # 一键冒烟
```

---

### 4.3 前后端分离契约（**强制**）

前端与后端是**两个独立工程**，只通过 HTTP 契约通信。任何"图省事"的耦合都视为返工。

**独立性要求**

| 维度 | 后端 `backend/` | 前端 `frontend/` |
|---|---|---|
| 依赖管理 | `pyproject.toml` + venv | `package.json` + pnpm |
| 构建 | 无需构建 | `vite build` |
| 开发启动 | `uvicorn app.main:app --reload --port 8000` | `vite --port 5173` |
| 生产部署 | 独立容器 | 静态资源（CDN 或独立容器） |
| 测试 | pytest | vitest |

**硬性规则**

1. 🚫 前端**禁止** import 后端 Python 代码；后端**禁止** import 前端代码。
2. 🚫 禁止手工维护"两边各写一份"的类型定义。**契约唯一来源是后端 OpenAPI schema**：
   前端用 `openapi-typescript http://127.0.0.1:8000/openapi.json -o src/api/schema.d.ts` 生成，
   **生成物不进版本库**（写入 `.gitignore`），在 `pnpm prebuild` 中生成。
3. 所有跨端数据必须走 REST（`/api/v1/*`）或 SSE（`/api/v1/chat`）。无 WebSocket、无 RPC、无共享数据库直连。
4. 后端 CORS：dev 允许 `http://127.0.0.1:5173`；生产由 `CORS_ORIGINS` 环境变量指定。
   **`allow_origins=["*"]` 禁止出现在任何非 dev 配置中。**
5. 前端 API 基址来自 `VITE_API_BASE_URL`，**禁止硬编码 `localhost`**。
   dev 环境用 Vite `server.proxy` 把 `/api` 转发到 `http://127.0.0.1:8000`。
6. 契约破坏性变更 → 升 API 版本前缀，并同步更新本文档 §7。

### 4.4 本机环境实测结论（决定 M0 怎么跑）

| 项 | 实测结果 | 结论 |
|---|---|---|
| OS | Windows 11 (NT 10.0.26200) AMD64 | — |
| `python` | **3.13.13** | ❌ 与本项目要求的 3.11 不符 |
| `py -3.11` | **3.11.9** ✅ 含 pip 24.0、venv 可用 | ✅ **必须用它建虚拟环境** |
| Node | v26.1.0 | ✅ 满足 ≥20 |
| pnpm | 11.8.0 | ✅ 前端包管理器 |
| npm | 11.13.0 | 备用 |
| git | 2.54.0 | ✅ |
| Docker CLI | 28.4.0 + Compose v2.39.4 | ⚠️ 仅 CLI，见下 |
| **Docker 守护进程** | **未运行**（`docker ps` exit=1，Docker Desktop 进程不存在） | ⚠️ **`docker compose up` 会直接失败** |
| 磁盘 D: | 可用 215.6 GB | ✅ |
| 长路径支持 | `LongPathsEnabled=1` | ✅ |
| 执行策略 | `RemoteSigned` | ✅ venv 激活不受影响 |
| 工作区路径 | `D:\exam_select` | ✅ 无空格（2026-02 由 `D:\exam select` 改名，旧会话沙箱根路径失效问题随之解除） |
| `uv` / `poetry` / `yarn` | 均未安装 | 本项目不需要 |

**由此产生的三条强制约定**（详见 `docs/DECISIONS.md` ADR-001）：

1. **Python 一律用 `py -3.11` 建 venv**，禁止用裸 `python`（那是 3.13）。
   所有文档、脚本、CI 配置统一写 `py -3.11`。
2. **M0 验收走本地 venv 路径，不依赖 Docker**。Docker 仅在需要容器化验证时由人工启动。
3. ~~**路径含空格**~~ → **已解除**（2026-02 工作区由 `D:\exam select` 改名为 `D:\exam_select`，风险消除）。
   仍保留加引号习惯：所有脚本、Makefile、npm scripts 中引用项目路径必须**加引号**，
   禁止在脚本里拼接未加引号的绝对路径。

**M0 验收命令（本地路径版，PowerShell）**

```powershell
# 1) 建虚拟环境（注意：必须 3.11）
py -3.11 -m venv backend\.venv

# 2) 装后端（可编辑安装）
backend\.venv\Scripts\python.exe -m pip install -e backend

# 3) 起服务（工作目录为 backend\）
Push-Location backend
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
Pop-Location

# 4) 健康检查（另开一个终端）
curl.exe -s http://127.0.0.1:8000/health      # 期望 {"status":"ok"}

# 5) 模型可导入
backend\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'backend'); from app.core.models import AdmissionUnit, ProbabilityResult; print('OK')"

# 6) 前端
Set-Location frontend
pnpm install
pnpm dev
```

---

## 5. 数据模型

### 5.1 关键设计决策：统一"投档单位"抽象

浙江/山东是"专业+院校"，上海/北京/天津/海南是"院校专业组"。**不要在业务代码里 if-else 区分**，
而是抽象成统一的 `AdmissionUnit`：

```python
class AdmissionUnit(BaseModel):
    unit_id: str                  # 全局唯一：f"{province}-{year}-{college_code}-{group_code}-{major_code}"
    unit_type: UnitType           # MAJOR_COLLEGE | MAJOR_GROUP
    province: str
    year: int
    batch: str
    college_id: str
    group_code: str | None        # 专业+院校模式为 None
    group_name: str | None
    major_id: str
    major_name: str
    subject_requirement: SubjectRequirement   # {"mode": "all_of"|"any_of"|"none", "subjects": [...]}
    plan_count: int
    tuition: int
    duration: int
    campus: str | None
    remarks: str | None
```

差异全部由 `ProvinceRule` 吸收（见 §6.6）。

### 5.2 表结构

```sql
-- 一分一段表（位次法的地基）
CREATE TABLE score_rank_table (
    id INTEGER PRIMARY KEY,
    province TEXT NOT NULL,
    year INTEGER NOT NULL,
    track TEXT NOT NULL,           -- 3+3 一般不分文理，用 "综合"；预留
    score INTEGER NOT NULL,
    count_at_score INTEGER NOT NULL,
    cumulative_rank INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    UNIQUE(province, year, track, score)
);

-- 院校
CREATE TABLE colleges (
    id TEXT PRIMARY KEY,           -- f"{province}-{college_code}"
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    province TEXT, city TEXT,
    level_tags TEXT,               -- JSON: ["985","211","双一流"]
    college_type TEXT,             -- 综合/理工/师范/医药...
    affiliation TEXT,              -- 教育部/省属/ ...
    is_public INTEGER NOT NULL,
    postgrad_rate REAL,            -- 保研率
    master_points INTEGER, doctor_points INTEGER,
    source_url TEXT
);

-- 专业
CREATE TABLE majors (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,                 -- 门类
    discipline TEXT,               -- 专业类
    degree TEXT, duration INTEGER,
    subject_eval_grade TEXT,       -- 学科评估 A+/A/B+...
    source_url TEXT
);

-- 投档单位（当年）—— §5.1 AdmissionUnit 的落库形态
CREATE TABLE admission_units (
    unit_id TEXT PRIMARY KEY,      -- f"{province}-{year}-{college_code}-{group_code}-{major_code}"
    unit_type TEXT NOT NULL,       -- MAJOR_COLLEGE | MAJOR_GROUP
    province TEXT NOT NULL,
    year INTEGER NOT NULL,
    batch TEXT NOT NULL,
    college_id TEXT NOT NULL REFERENCES colleges(id),
    group_code TEXT,               -- 专业+院校模式为 NULL
    group_name TEXT,
    major_id TEXT REFERENCES majors(id),
    major_name TEXT NOT NULL,
    subject_requirement TEXT NOT NULL,  -- JSON，见 docs/DOMAIN_RULES.md §2.4
    subject_req_status TEXT NOT NULL,   -- PARSED | PARSE_FAILED（PARSE_FAILED 拒绝入库）
    plan_count INTEGER NOT NULL CHECK(plan_count > 0),
    tuition INTEGER,
    duration INTEGER,
    campus TEXT,
    remarks TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1,   -- ★ 1=模拟数据，严禁真实填报
    source_url TEXT NOT NULL,
    UNIQUE(province, year, college_id, group_code, major_id)
);

-- 招生计划历史快照（用于跨年计划数对比）
CREATE TABLE admission_plans (
    id INTEGER PRIMARY KEY,
    unit_key TEXT NOT NULL,        -- 不含年份的单位标识：f"{province}-{college_code}-{group_code}-{major_code}"
    year INTEGER NOT NULL,
    plan_count INTEGER NOT NULL,
    is_synthetic INTEGER NOT NULL DEFAULT 1,
    source_url TEXT NOT NULL,
    UNIQUE(unit_key, year)
);

-- 投档/录取历史（往年）—— 位次算法的输入
CREATE TABLE admission_history (
    id INTEGER PRIMARY KEY,
    unit_key TEXT NOT NULL,        -- 与 admission_plans 同口径，用于逐年对齐
    province TEXT NOT NULL,
    year INTEGER NOT NULL,
    batch TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    college_id TEXT NOT NULL,
    group_code TEXT,
    major_id TEXT,
    min_score INTEGER,
    min_rank INTEGER,              -- ★ 核心字段；数值越小越靠前
    avg_score INTEGER,
    avg_rank INTEGER,
    plan_count INTEGER,
    admitted_count INTEGER,
    is_collected INTEGER DEFAULT 0,-- 是否征集志愿（征集线通常更低，须标记）
    data_quality TEXT NOT NULL,    -- OK | DERIVED | MISSING_RANK | COLLECTED | SUSPECT
    total_candidates INTEGER,      -- 该年该科类实际参考人数，位次归一化的分母
    is_synthetic INTEGER NOT NULL DEFAULT 1,
    source_url TEXT NOT NULL,
    verified INTEGER DEFAULT 0,
    UNIQUE(unit_key, year, is_collected)
);

-- 省级年度元数据（位次归一化的分母来源）
CREATE TABLE province_year_stats (
    province TEXT NOT NULL,
    year INTEGER NOT NULL,
    track TEXT NOT NULL,
    total_candidates INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    PRIMARY KEY (province, year, track)
);
```

**强制要求**
1. 所有数据表必须有 `source_url` 与 `is_synthetic`。没有来源的数字不许入库。
2. `data_quality` 取值与语义见 `docs/DOMAIN_RULES.md` §2.2。
3. `total_candidates` 必须来自 `province_year_stats`，**不得估算**（见 `docs/DOMAIN_RULES.md` §2.3）。

### 5.3 考生档案模型

```python
class StudentProfile(BaseModel):
    id: str
    province: str
    year: int
    track: str                       # 3+3 为 "综合"
    subjects: list[str]              # 选考的 3 门
    total_score: int
    rank: int | None                 # 若未提供，由 score_rank_table 换算
    # 身体与语种（硬约束输入）
    physical_exam: PhysicalExam      # 色盲/色弱/身高/视力等
    foreign_language: str            # 英语/日语/俄语...
    single_subject_scores: dict[str, int]   # {"英语": 128, "数学": 135}
    # 加分
    bonus_points: int = 0
    bonus_type: str | None = None
    # 偏好（软约束）
    preferences: Preferences
    # 数据缺口标记（供 agent 追问）
    missing_fields: list[str] = []
```

---

## 6. 核心算法规格

> 参数默认值集中在 `docs/DOMAIN_RULES.md` §3 的 `ModelParams`，**代码中不得硬编码魔数**，
> 全部从配置读取，并允许按省份覆盖。

### 6.1 分数 ↔ 位次换算（`core/rank.py`）

```python
def score_to_rank(province, year, track, score) -> int
def rank_to_score(province, year, track, rank) -> int
```

- 基于 `score_rank_table` 的 `cumulative_rank` 做**线性插值**（一分一段表是整数分，需插值才平滑）
- 边界：score 高于最高分 → rank = 1；低于最低分 → rank = 总考生数
- **位次归一化**（跨年可比的关键）：
  ```
  rank_normalized(R, year_from, year_to) = R * (total_candidates[year_to] / total_candidates[year_from])
  ```

### 6.2 录取概率模型（`core/probability.py`）—— 全系统的心脏

**Step 0｜无历史数据回退（新增专业 / 新增院校）**
若有效年份数 = 0，**不允许**猜测概率。走以下回退：
1. 找 `同地区 + 同院校层次 + 同专业类` 的 ≥3 个单位作为**类比池**
2. 用类比池的 `min_rank` 中位数作为 `R_pred`，σ 取类比池的标准差
3. 计算得到 `P`
4. **强制**：`confidence = LOW`，`tier` 照算但 `warnings` 必须包含 `NO_HISTORY`
5. 若连类比池也构造不出（< 3 个）→ 返回 `probability = None`，`tier = NO_DATA`

**Step 1｜取历史位次并归一化**
取目标单位近 N 年（默认 N=3）`min_rank`，统一归一化到今年：
```
R_i_norm = min_rank[i] * (total_candidates[今年] / total_candidates[第 i 年])
```
丢弃 `data_quality ∉ {OK, DERIVED, COLLECTED}` 的记录；
`DERIVED` 记录额外乘 `derived_quality_weight`（默认 0.9）降权；
`COLLECTED` 记录保留但打 `COLLECTED_ONLY` 风险标记。
若有效年份数 = 0 → 回到 Step 0。

**Step 2｜加权预测今年最低位次**
```
w = [0.5, 0.3, 0.2]                      # 由近及远
R_pred = Σ w_i * R_i_norm                # 权重按有效年份数归一化
```

**Step 3｜趋势修正**（识别"越来越热/冷"）
```
slope = (R_近 - R_远) / (年数 - 1)         # 位次数值下降 = 越来越热
slope = clip(slope, -0.10 * R_pred, 0.10 * R_pred)   # 限幅 ±10%
R_pred = R_pred + λ * slope               # λ 默认 0.5
```

**Step 4｜计划数修正**（强信号）
```
Δ = (plan_count[今年] - plan_count[去年]) / plan_count[去年]
Δ = clip(Δ, -0.5, 0.5)
R_pred = R_pred * (1 + β * Δ)             # β 默认 0.4
# 计划增加 → R_pred 变大（门槛后移，更容易）✅ 方向不能反
```

**Step 5｜波动性度量**（"大小年"）
```
σ_raw = std(R_i_norm)
# 样本少时 std 不稳，用 MAD 与相对下限兜底
σ = max(σ_raw, 0.03 * R_pred, MIN_SIGMA)
```

**Step 6｜z 分数与概率**
```
z = (R_pred - R_s) / σ        # R_s = 考生今年位次
                              # R_s 小（考生更靠前）→ z > 0 → 概率高 ✅
P = Φ(z)                      # scipy.stats.norm.cdf
P = clip(P, 0.02, 0.98)       # 禁止绝对化
```

**Step 7｜波动收缩**（对"大小年"严重的单位**降低自信**）
```
cv = σ_raw / mean(R_i_norm)
if cv > CV_THRESHOLD:            # 默认 0.15
    κ = min(0.35, (cv - CV_THRESHOLD) * 2)
    σ = σ / (1 - κ)              # ★ 实现勘误：放大 σ（等价 z×(1-κ)），而不是直接压缩 P
    P = Φ((R_pred - R_s) / σ)
```
> ⚠️ **勘误（2026-02，DECISIONS ADR-009 勘误 1）**：本节原式 `P = 0.5 + (P-0.5)(1-κ)` 会把**任何**概率
> 压进 `[0.5κ, 1-0.5κ]`（κ≤0.35 即 `[0.175, 0.825]`）→ 波动大的单位**永远无法**被判为
> `TOO_RISKY`（<0.10）或 `DIAN`（≥0.93），毫无希望的考生也会被报成 12%~40%。
> 实测：关掉该收缩后冲档命中率由 1.5% 回到 19%（落入目标区间），Brier 0.0076 → 0.0059。
> 收缩的语义是"降低自信"，应体现在不确定度（σ）上——修正后排序性、单调性与两端可达性都不破坏。

**Step 8｜置信度分级**
| 条件 | confidence |
|---|---|
| N=3 且 data_quality 全 OK 且 plan_count ≥ 10 且 cv ≤ 0.10 | HIGH |
| N∈{2,3} 且 plan_count ≥ 5 | MEDIUM |
| N=1 或 plan_count < 5 或存在 MISSING_RANK | LOW |
| N=0 | NO_DATA（概率返回 None，禁止编造） |

**Step 8.6｜安全闸门（★ 名师铁律 4「保底要真保底」，2026-02 ADR-009 新增）**

保底/垫底是**安全承诺**，不能只由概率区间给出——即使 P=0.99，若该单位去年切线只比考生位次高 2%，
它也不是保底（回测中曾出现"考生 2,204 vs 实际 2,197"这类擦边失效）。

```
min(近三年归一化最低位次) ≥ 考生位次 × (1 + safety_margin)   # safety_margin 默认 0.60（M5 重标定，ADR-014）
```
- 不满足 → **降级**（`DIAN`/`BAO` → `WEN`），并打 `SAFETY_MARGIN_NOT_MET`，原始概率在 `reasons` 中如实披露；
- **无本单位历史**（Step 0 类比路径）**一律不得判为 BAO/DIAN**——无历史的数据不能当垫底；
- 方向提醒：**考生位次要比该单位最难年份的切线更靠前**，留出缓冲（DOMAIN_RULES R-007 原文方向写反，已勘误）。

**Step 8.5｜输出结构**（必须带完整证据链，供 LLM 引用与前端展示）
```python
class ProbabilityResult(BaseModel):
    probability: float | None
    tier: Tier                    # CHONG | WEN | BAO | DIAN | TOO_RISKY | NO_DATA
    confidence: Confidence
    predicted_min_rank: float
    sigma: float
    evidence: list[HistoryEvidence]   # 每一条：year, min_rank, min_score, plan_count, source_url
    adjustments: list[Adjustment]     # 每条：name, delta, reason
    reasons: list[str]                # 人话解释
    warnings: list[str]               # 低置信度/计划过少/新增专业等
```

### 6.3 冲稳保分层（`Tier`）

| 层 | 概率区间 | 含义 |
|---|---|---|
| CHONG 冲 | [0.10, 0.40) | 有机会但不稳 |
| WEN 稳 | [0.40, 0.75) | 大概率能上 |
| BAO 保 | [0.75, 0.93) | 很稳 |
| DIAN 垫 | [0.93, 1.00] | 绝对兜底 |
| TOO_RISKY | [0, 0.10) | 基本无望，默认不推荐，可显式开启 |
| NO_DATA | — | 无任何可用历史数据，`probability = None`，**不参与志愿表生成** |

**推荐配额（默认，按省份总志愿数 N 比例生成，可被用户覆盖）**：
```
冲 25%  |  稳 40%  |  保 25%  |  垫 10%
```
**结构校验**：垫底志愿数量 ≥ 3 且 ≥ 5% 总志愿数；若考生总志愿数 < 10，垫底 ≥ 2。

> ★ **保/垫是"安全承诺"而非"概率标签"（ADR-009 Step 8.6）**：`BAO`/`DIAN` 的判定除了概率区间，
> 还**强制**通过"真保底"余量闸门（考生位次比该单位近三年最难年份切线靠前 ≥ `safety_margin`）。
> 因此会出现"概率 0.95 但分层为 WEN"的情况——这是**刻意**的保守，因为该单位给不出 30% 余量，
> 不能当垫底用；`reasons` 会如实说明原始概率与降级原因。无本单位历史者一律不得判为 BAO/DIAN。

> ★ **适用范围（ADR-006）**：以上分层、配额与结构校验**仅适用于 `is_parallel=True` 的平行志愿批次**
>（`BatchRule.tiers_quota` 亦然，见 §6.6）。`is_parallel=False` 的**顺序志愿批次**
>（如浙江普通类提前录取院校，5 个院校传统志愿）**不做冲稳保梯度配额校验**，
> 改为顺序志愿专用校验：**第一志愿必须放考生最想去的单位**，
> 后续志愿仅按递补价值排序、**不得承担保底职责**（顺序志愿第 2 志愿起
> 仅在第一志愿生源不足时才可能投出）。见 §6.7 / §6.8。

### 6.4 硬约束过滤（`core/filters.py`）

按顺序执行，**任一不满足直接剔除**，并记录剔除原因（用于"为什么没推荐 XX"的追问回答）：

1. `province / year / batch / track` 匹配
2. **选考科目**：解析 `subject_requirement`，支持 `all_of`（都要）/ `any_of`（满足其一）/ `none`（不限）。
   3+3 下考生有 3 门选考，必须严格匹配。**这是新高考最易出错处，必须有专项测试。**
3. **性别限制**（部分军警/航海类）
4. **体检结论**：色盲/色弱/身高/视力/乙肝等（对照《普通高等学校招生体检工作指导意见》）
5. **外语语种**：非英语考生受限专业
6. **单科成绩要求**：如英语 ≥ 120
7. **应届/往届、政治面貌**（提前批）
8. **学费上限**（若用户设定，视为硬约束）
9. 已撤销/停招单位

> 输出 `FilterResult{passed: list, rejected: list[RejectionReason]}`，
> `RejectionReason{unit_id, rule_code, message}`。**被剔除项必须可解释。**

### 6.5 软偏好效用（`core/scoring.py`）

```
utility = w_region * region_score
        + w_college_level * level_score
        + w_major * major_match_score
        + w_tuition * tuition_score
        + w_city * city_score
        + w_misc * misc_score
```
- 权重由考生在 UI 上调整（默认等权，归一化到 1.0）
- 每项分数归一到 [0, 1]，**每个分数必须能追溯到具体规则**（返回 `score_breakdown`）
- `major_match_score` 基于：意向专业类精确匹配 > 同一级学科 > 相关学科 > 不相关

### 6.6 省份规则包（`core/rules/base.py`）—— ★ 批次级建模

> **2026-02 架构修正（ADR-006）**：核实官方文件时发现**同一省份的不同批次志愿性质完全不同**
>（例：浙江普通类专业平行志愿每段 ≤ 80 是**平行**志愿，而普通类提前录取院校是
> 5 个院校传统志愿＝**顺序**志愿）。"一个省 = 一套志愿规则"的建模是**硬错误**：
> 顺序志愿批次会被错误套用平行志愿的冲稳保梯度逻辑，而顺序志愿第一志愿权重极高、
> 后续志愿近乎无效，会排出严重误导的志愿表。因此规则必须下沉为**批次级**：

```python
class BatchRule(BaseModel):
    """一个省的**一个批次**。★ 一个省必然有多个批次，各自规则不同。"""
    batch_code: str                        # "zhejiang.public.seg1" / "beijing.undergrad.regular"
    batch_name: str                        # "普通类第一段专业平行志愿"
    unit_type: UnitType                    # MAJOR_COLLEGE | MAJOR_GROUP
    max_volunteers: int                    # 80 / 96 / 24 / 30 / 50 ...
    majors_per_group: int | None           # 4 / 6 / None
    has_major_adjustment: bool             # True=院校专业组, False=专业+院校
    is_parallel: bool                      # ★ True=平行志愿, False=顺序志愿
    tiers_quota: dict[Tier, float]         # 仅平行志愿有意义
    source_url: str
    source_quote: str                      # ★ 官方原文摘录，供审计
    verified_status: VerifiedStatus        # PRIMARY | PRIMARY_GOV | SECONDARY | UNVERIFIED
    verified_year: int

    # ---- 扩展字段（可选；仅在有官方原文时填写，未核实的批次一律 None，不得编造）
    admission_ratio: str | None = None         # 投档比例，如 "1:1"（上海已核实）
    tie_break_rules: list[str] | None = None   # 同分排序位序规则（上海已核实 6 级）
    adjustment_scope: str | None = None        # 调剂边界，如 "仅限组内"（上海已核实）
    withdrawal_clause: list[str] | None = None # 退档情形（上海已核实）

    # ---- 未核实维度 vs 时效待办（★ 宁可不答，不可编造；语义见 docs/DATA_DICTIONARY.md §1.6）
    assumptions: list[str] = []    # 未核实维度；带 assumptions 的批次不得标 PRIMARY（测试强制）
    caveats: list[str] = []        # 已知待办 / 时效提醒，不影响来源等级

class ProvinceRule(ABC):
    province: str
    batches: list[BatchRule]               # ★ 至少一个

    def get_batch(self, batch_code: str) -> BatchRule: ...
    @abstractmethod
    def validate_plan(self, plan: VolunteerPlan, batch: BatchRule) -> list[RuleViolation]
    @abstractmethod
    def default_quota(self, batch: BatchRule) -> dict[Tier, int]
```

**任何规则数字必须带 `source_url` 与 `verified_year`（`BatchRule` 还须带 `source_quote` 原文摘录）。**
没有来源的数字不许写进代码。

**为什么必须是批次级**（以浙江为例，同一年同一省）：
- 普通类**专业平行志愿**：每段 ≤ 80 个志愿，平行投档 → 冲稳保梯度有效；
- 普通类**提前录取院校**：5 个院校**传统（顺序）志愿**，每校 6 专业 + 专业服从调剂 →
  第一志愿命中率决定一切，第 2 志愿起仅在第一志愿生源不足时才可能投出；
  若套用"冲稳保 25/40/25/10"配额，会把保底职责放在几乎不可能投出的位置上，是纯粹的误导。
  （原文：「提前录取院校设5个院校传统志愿，每所院校设6个专业志愿和专业服从调剂志愿。」——浙江省教育考试院 2026）

**M1 已交付 20 个批次**（六省，含浙江提前批、上海提前批/综合评价/零志愿/地方农村专项等
**顺序志愿**批次，全部带 `source_quote` 原文摘录）；仍未落实的批次见 `docs/DOMAIN_RULES.md` §1.3
——**缺来源数字一律不落码**，绝不用常识补全。

### 6.7 志愿表生成（`core/planner.py`）

**输入**：已过滤 + 已算概率 + 已打分的候选集 `list[ScoredUnit]`、配额、考生意愿排序

**算法**（贪心 + 分层配额 + 局部搜索）：
1. 按 §6.3 配额从各 Tier 取候选（层内按 `utility` 降序）
2. 若某层候选不足，向相邻层借位（**优先向更保守的方向借**，保证兜底）
3. **全局排序**：投影为「考生意愿序」，但强制满足：最后一档必须是 DIAN/BAO
4. **局部搜索优化**：尝试 swap 提升总效用，硬约束：任一交换不得破坏 §6.3 结构校验
5. **去重**：同一 `college+group` 在"专业+院校"模式下可重复出现（不同专业），
   在"院校专业组"模式下**不可重复**（一个组只能填一次）

> ★ **适用范围（ADR-006）**：步骤 1–4 只对 `is_parallel=True` 的平行志愿批次生效。
> `is_parallel=False` 的顺序志愿批次**不做冲稳保梯度配额校验与借位**，改为顺序志愿专用生成：
> 第一志愿 = 考生最想去（效用最高）的单位；后续志愿按"第一志愿落榜后的递补价值"排序；
> **保底职责绝不能交给顺序志愿的第 2 志愿及以后**（投出概率极低），
> 必须由平行志愿批次的垫底志愿承担。

**输出**：
```python
class VolunteerPlan(BaseModel):
    id: str
    student_id: str
    province: str
    rule: ProvinceRuleInfo
    items: list[PlanItem]          # 有序！
    tier_distribution: dict[Tier, int]
    total_utility: float
    violations: list[RuleViolation]
    warnings: list[str]
```

### 6.8 风险扫描（`core/risk.py`）

风险码表（每个风险必须给出可执行建议）：

| code | level | 触发条件 | 建议 |
|---|---|---|---|
| `NO_SAFETY_NET` | HIGH | 垫底志愿 < 最少要求 | 增加绝对保底志愿 |
| `SAFETY_NOT_SAFE` | HIGH | 垫底志愿近三年**最难年份**的切线未比考生位次靠后 ≥ 60%（`safety_margin`） | 更换更稳的保底 |
| `GRADIENT_INVERSION` | MEDIUM | 后序志愿比前序志愿层次显著更高且更稳 | 提示顺序可能非最优 |
| `INSUFFICIENT_COUNT` | MEDIUM | 填报数 < 省份上限的 80% | 建议填满，浪费机会 |
| `PLAN_TOO_SMALL` | MEDIUM | 任一志愿计划数 < 5 | 波动大，建议增加替代 |
| `VOLATILE_HISTORY` | MEDIUM | cv > 0.15 | 该单位大小年明显，谨慎定位 |
| `NO_HISTORY` | MEDIUM | 新增专业/院校无历史数据 | 用同层次类比，标注不确定 |
| `SINGLE_YEAR_DATA` | MEDIUM | 仅 1 年有效数据 | 参考价值有限 |
| `NO_OBEDIENCE` | HIGH | 院校专业组模式未勾选服从调剂 | ★ 退档风险，强烈建议勾选 |
| `GROUP_UNACCEPTABLE` | MEDIUM | 组内含考生明确排斥的专业 | 冲进去也会被调剂到该专业 |
| `PHYSICAL_LIMIT` | HIGH | 体检受限 | 必须移除或核实招生章程 |
| `TUITION_HIGH` | LOW | 学费超考生预算 | 提示经济负担 |
| `SUSPECT_DATA` | HIGH | 数据 quality=SUSPECT | 需人工核实 |
| `COLLECTED_ONLY` | MEDIUM | 历史仅来自征集志愿 | 征集线偏低，会高估概率 |

> ★ **适用范围（ADR-006）**：梯度类风险码（`GRADIENT_INVERSION` / `NO_SAFETY_NET` /
> `SAFETY_NOT_SAFE` / `INSUFFICIENT_COUNT`）仅适用于 `is_parallel=True` 的批次；
> 顺序志愿批次（`is_parallel=False`）不做冲稳保梯度配额校验，改为顺序志愿专用校验
>（第一志愿必须是最想去的），其专用风险码在 M2 实现 `risk.py` 时补充定义，
> 不改变本表 14 码的 M2 验收基线。批次级扩展字段（投档比例 / 同分排序 / 调剂边界 /
> 退档情形，见 §6.6）带来的增量风险码（如调剂越界、退档条款命中）同样在 M2 一并定义。

### 6.9 回测框架（`core/backtest.py`）—— 证明算法可信的唯一方式

用 **Y-1 年及更早数据** 预测 **Y 年**实际结果，比对：
- 混淆矩阵：预测 Tier × 实际是否投档
- **保底失效率**必须为 0（最高优先级指标）
- 稳档命中率 ≥ 85%
- 冲档命中率落在 10%–40%
- Brier score ≤ 0.15，并输出**校准曲线**（预测 70% 的样本里实际命中多少）
- 按省份、按计划数分档、按院校层次分组出报告

输出 `backtest_report.json` + `backtest_report.md`。
**每次修改概率模型参数，必须重跑回测并在 PR 中附对比。**

---

## 7. API 契约

统一前缀 `/api/v1`。所有响应含 `data` / `evidence` / `warnings` 三段。

```
# 元数据
GET    /meta/provinces                       # 各省规则（含 source_url、核实状态、**选考科目池**、current_year）
GET    /meta/provinces/{p}/rule
GET    /meta/provinces/{p}/subject-coverage?subjects=物理,化学,生物
                                             # §8.1 Step 2 的可报专业覆盖率：真实统计（非估算）；
                                             # 同时回传 subject_pool（origin=RULE | DATA_DERIVED）
GET    /meta/tiers                           # 分层区间 / 配额 / 安全闸门 / 免责声明文案（UI 唯一来源）

# 考生档案
POST   /students                             # 创建档案 → 返回 missing_fields 供追问
GET    /students/{id}
PATCH  /students/{id}
POST   /students/{id}/resolve-rank           # 分数 → 位次

# 数据查询
GET    /colleges/search?q=&province=&level=
GET    /majors/search?q=&category=
GET    /units/{unit_id}/history?years=3

# 核心推荐
POST   /recommend
  req  { student_id, filters:{regions,majors,levels,tuition_max,intent_as_hard},
         weights:{...}, limit, include_too_risky }
  res  { items:[{ unit, college, major, probability, **probability_interval**, tier, confidence, utility,
                  score_breakdown, predicted_min_rank, sigma,
                  evidence[], adjustments[], reasons[], warnings[] }],
         stats:{ tier_distribution, filtered_out_count, data_coverage, rule:{unit_type,...} } }

# 志愿表
POST   /plans/generate        # 生成志愿表
GET    /plans/{id}
  res  { plan:{items:[{ unit, tier, probability, **probability_interval**, obey_adjustment, notes[] }]},
         risks[], stats{}, **colleges**:{college_id: {name, city, level_tags, is_public, source_url}} }
PATCH  /plans/{id}/items      # 手改（拖拽排序、增删）
  req  { items:[{unit_id, obey_adjustment?}], obey_adjustment?, **filters?** }
POST   /plans/{id}/validate   # 风险扫描
GET    /plans/{id}/export?format=pdf|xlsx

# 单点风险速查（不生成志愿表，直接扫一组志愿）
POST   /risk/scan
  req  { student_id, unit_ids:[...] }
  res  { risks:[{ code, level, unit_id, message, suggestion }] }

# 对话（Agent 层）
POST   /chat                  # SSE 流式
GET    /chat/{session_id}/history

# 回测
GET    /backtest/report?province=&year=

# 健康
GET    /health
```

**契约铁律**：
1. `recommend` 返回的每个 item **必须**含非空 `evidence`，且每条 evidence 带 `source_url`
2. 概率为 `None` 时，`confidence` 必须是 `NO_DATA`，且 `reasons` 说明原因
3. 响应中**禁止**出现无来源的数字字段
4. OpenAPI schema 自动生成，前端类型由 schema 生成，**不手写重复类型**

---

## 8. 前端规格

### 8.1 首屏向导（**考生进入系统的第一个界面，M4 必须最先做**）

考生打开系统后**第一个看到的就是建档向导本身**——不做营销落地页、不做功能罗列页、不做轮播图。
向导共 4 步，**前 3 步是硬门槛，未完成不得进入推荐**。

| 步 | 名称 | 采集内容 | 交互要求 |
|---|---|---|---|
| **1** | **选省份** | 六省市之一：浙江 / 上海 / 北京 / 山东 / 天津 / 海南 | 大卡片点选。选中后**立即**显示该省投档模式（专业+院校 / 院校专业组）、平行志愿数量、组内专业数与调剂规则，并显示规则核实状态徽标 |
| **2** | **选选考科目** | 从该省可选科目中**恰好选 3 门** | 多选；选满 3 门后其余选项禁用并给出提示；实时显示该组合的**可报专业覆盖率** |
| **3** | **填成绩** | 高考总分（必填）、位次（选填） | 输入总分后**立即**换算并展示位次与等效分；已知位次的考生可直接填位次，两者互为校验 |
| 4 | 偏好与身体条件 | 意向地区 / 意向专业 / 学费上限 / 体检结论 / 外语语种 | **可跳过**（跳过用默认值），完成后进入 `/recommend` |

**Step 1 的省份选择必须联动下游全部环节**（这是首屏最重要的一个设计点）：

| 省份决定 | 影响 |
|---|---|
| `unit_type` | 浙江/山东 = 专业+院校；上海/北京/天津/海南 = 院校专业组 |
| `max_volunteers` | 80 / 96 / 24 / 30 / 50 —— 直接决定后续志愿表容量与配额 |
| Step 2 可选科目范围 | 各省 3+3 选考科目池不同 |
| "服从调剂"选项 | 专业+院校模式下**必须隐藏**该选项（不存在调剂概念） |
| 规则核实徽标 | `verified_status != PRIMARY` 时显示醒目提示 |

**Step 3 的位次换算是首屏的关键体验点**：

- 考生只填总分 → 调 `POST /api/v1/students/{id}/resolve-rank` → 返回位次、等效分、`source_url`
- 界面必须显示完整溯源：`你的位次：12,340 / 78,000（来源：浙江省教育考试院）`
- **若一分一段表缺失或换算失败 → 必须明确提示"位次换算不可用"，
  严禁用估算值糊弄**，并引导考生直接填写已知位次
- 分数与位次同时填写且互不匹配时 → 提示不一致，由考生确认以哪个为准，**不得擅自覆盖**

**状态管理**：向导进度同时存 `localStorage` 与后端草稿，中途刷新不丢失。
`missing_fields` 非空时，`/recommend` 入口显示未完成项清单并阻止进入。

### 8.2 页面清单

| 页面 | 路由 | 核心功能 |
|---|---|---|
| 首屏向导 | `/profile` | 见 §8.1：省份 → 选考 3 门 → 成绩 → 偏好（可跳过） |
| 推荐列表 | `/recommend` | 卡片流，冲稳保色带，概率区间条，位次趋势微图，加入志愿表按钮，**"为什么"展开证据链** |
| 志愿表 | `/plan` | 拖拽排序，分层配色，梯度分布柱状图，缺额提示，风险面板实时更新，导出 |
| 报告 | `/report` | 可打印志愿报告：档案 + 志愿表 + 每志愿依据 + 风险提示 + 免责声明 |
| 对话 | `/chat` | 与名师 agent 对话，建档、追问、解释 |

**UI 强制要求**：
- 概率**永远显示为区间**（如"62%–78%"），不显示单一精确数字
- 每个推荐卡片必须能展开看**历史证据表**（哪年、最低分、最低位次、计划数、来源链接）
- 风险项用图标 + 颜色分级，HIGH 级必须阻断式提示
- 报告页底部必须有免责声明与数据来源清单

---

## 9. Agent 层规格

### 9.1 工具定义（`agent/tools.py`，**只读或需确认，绝不写库**）

```python
get_rank_by_score(province, year, track, score) -> {rank, percentile, source_url}
get_score_by_rank(province, year, track, rank) -> {score, source_url}
search_units(province, year, filters) -> [{unit_id, college, major, plan_count, subject_req}]
get_unit_history(unit_id, years=3) -> [{year, min_score, min_rank, plan_count, source_url, data_quality}]
estimate_probability(student_id, unit_id) -> ProbabilityResult   # 调用 core，不由 LLM 算
recommend_units(student_id, filters, limit) -> [ScoredUnit]
generate_plan(student_id, constraints) -> VolunteerPlan
scan_risks(plan_id) -> [Risk]
get_college_profile(college_id) -> {...}
get_major_profile(major_id) -> {...}
list_missing_fields(student_id) -> [str]
get_province_rule(province) -> {main_batch, subject_pool, requires_banner, source_quote}
    # ★ M5 增补的第 12 个工具：考生最常问的恰恰是"我这省能填几个志愿、有没有调剂"。
    #   没有它，模型只能凭常识答——那正是本项目最不能接受的行为。
```

**每个工具返回的所有数字必须带 `source_url`。** 工具负责格式化证据，LLM 只负责转述。

### 9.2 System Prompt 要点（`agent/prompts.py`）

必须包含：
1. **人设**：十余年一线志愿规划名师，说话直接、给依据、敢说不确定
2. **能力边界**：只能通过工具获取数据；工具没返回的，回答"数据缺失"并说明如何补
3. **禁止条款**（逐条列出，并给正反例）：
   - ❌ 禁止凭空说出任何院校的分数线/位次/录取率
   - ❌ 禁止使用"保证""一定""百分百"等绝对化表述
   - ❌ 禁止在考生信息不全时替其假设（如"假设你是物理类"）
   - ❌ 禁止跳过工具直接回答"XX大学多少分"
4. **输出格式**：结论 + 依据（引用工具返回值）+ 风险提示 + 下一步建议
5. **追问策略**：优先补齐 `missing_fields`，一次最多问 3 个问题

**正例**：
> 你今年的位次是 12,340。根据工具查询，浙江大学工科试验班近三年最低位次分别是
> 9,800 / 10,200 / 9,950（来源：浙江省教育考试院）。按位次法估算你的录取概率在 12%–22%，
> 属于"冲"的范畴。冲的风险是可能滑到后面志愿，建议放在前 10 个志愿内，但**必须**保证后面有足够保底。

**反例（必须被 guard 拦截）**：
> 浙江大学去年录取线 660 分，你考了 655，差一点点，可以冲一冲。
> ❌ 编造分数线；❌ "差一点点"是伪精确；❌ 未调用工具

### 9.3 幻觉护栏（`agent/guard.py`）

```python
def guard_response(reply: str, tool_calls_this_turn: list[ToolCall]) -> GuardResult:
    # 1. 正则提取疑似数字断言：分数(600-750)、位次(1-500000)、百分比、计划数
    # 2. 与本次会话所有工具返回值做匹配（允许 ±0 精确 + 格式化容差）
    # 3. 未匹配上的数字 → 拦截
    # 4. 命中绝对化词表（保证/一定/百分百/稳上） → 拦截
    # 5. 拦截后：重写为"我需要查一下数据"或要求模型重新调用工具
```

**必须有测试**：`test_agent_hallucination.py` 构造 20 个"库外院校分数线"提问，
断言编造次数为 0。

---

## 10. 构建步骤（Phase 计划）

> **执行纪律**：每个 Phase 结束必须跑通该 Phase 的**验收命令**并把输出写进 `docs/DECISIONS.md`。
> 验收不通过，不许进入下一 Phase。

### M0 · 项目骨架与领域模型
**做什么**
- 建 §4.2 目录结构、`pyproject.toml`、`docker-compose.yml`、`.env.example`
- 写 `core/models.py`（全部 Pydantic 领域模型：StudentProfile / AdmissionUnit / ProbabilityResult / VolunteerPlan / Risk / Tier / Confidence）
- 写 `db/models.py`（§5.2 全部表）
- 写 `config.py`（ModelParams 从环境/配置读取，**禁止魔数**）
- 创建 `docs/DECISIONS.md`（首条 ADR：为什么选位次法、为什么 core 必须是纯函数）
- 创建 `docs/DATA_DICTIONARY.md`（以 `docs/DOMAIN_RULES.md` §2 为种子扩充）
- `main.py` + `/health`

**验收命令（本机实测版，见 §4.4）**

```powershell
# 后端：必须用 py -3.11（裸 python 是 3.13，不许用）
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -e backend
Push-Location backend; ..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000; Pop-Location
curl.exe -s http://127.0.0.1:8000/health          # 期望 {"status":"ok"}

# 模型可导入
backend\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'backend'); from app.core.models import AdmissionUnit, ProbabilityResult; print('OK')"

# 前端
Set-Location frontend; pnpm install; pnpm dev
```

> Docker 不是 M0 的必经路径（本机 Docker 守护进程未运行）。容器化验证放到 M7。

**完成定义**：服务能起、模型能导入、目录结构与本文档一致、无硬编码魔数。

---

### M1 · 数据层与模拟数据生成
**做什么**
- `etl/synthetic.py`：**确定性**生成器（固定 seed），生成六省市 × 各 3 年数据：
  - 一分一段表（符合真实分布形状：正态 + 长尾，总人数按各省真实量级）
  - 院校库 300+ 所（真实院校名与层次标签，位次为模拟值并标记 `verified=0`）
  - 专业库 500+ 个（真实专业名与选考要求）
  - 招生计划 + 投档历史（**注入已知规律以便验证算法**：故意造出"大小年"、"计划突增"、"新增专业"样本）
- `etl/validate.py`：数据质量检查
  - `cumulative_rank` 单调性、`plan_count > 0`、`min_rank` 与 `min_score` 一致性、
    院校 code 唯一性、**所有记录有 source_url**
- `core/rules/*.py`：六省规则包，**每个数字带 source_url + verified_year**
  （数值以本文 §2.1 与 `docs/DOMAIN_RULES.md` §1 为准）
- `scripts/seed.py`：一键生成 + 入库，**幂等**（重复执行结果一致）

**验收命令**
```bash
python scripts/seed.py --reset
python scripts/seed.py            # 再跑一次，数据量不变 → 幂等
python -m app.etl.validate --report   # 0 error
pytest backend/tests -q
```
**完成定义**：数据可重复生成且一致；校验 0 error；六省规则包齐备且每条带来源；
**故意注入的"大小年/计划突增"样本可被检出**。

---

### M2 · 核心算法引擎（★ 最关键，投入最多时间）
**做什么**
- `core/rank.py`：§6.1 全部功能 + 插值 + 边界
- `core/probability.py`：§6.2 完整 8 步，参数全部来自 ModelParams
- `core/filters.py`：§6.4 全部 9 类硬约束，输出可解释剔除原因
- `core/scoring.py`：§6.5，返回 score_breakdown
- `core/planner.py`：§6.7，配额 + 排序 + 局部搜索 + 去重
- `core/risk.py`：§6.8 全部 14 个风险码
- `core/backtest.py`：§6.9
- `tests/golden/`：**黄金用例**——人工构造 20 个已知答案的场景
  （例："考生位次 10000，目标单位近三年 9000/9500/9200，计划不变，期望 P ∈ [0.55, 0.70]"）

**验收命令**
```bash
pytest backend/tests -q --cov=app.core --cov-fail-under=90
python scripts/run_backtest.py --province zhejiang --year 2025
```
**完成定义**
- 覆盖率 ≥ 90%
- 20 个黄金用例全过
- **回测：保底失效率 = 0%，稳档命中率 ≥ 85%，冲档命中率 ∈ [10%,40%]，Brier ≤ 0.15**
- 计划数增加时概率单调不减（用 `hypothesis` 做性质测试）

---

### M3 · 后端 API
**做什么**：按 §7 实现全部端点；service 层负责"查库 → 组装 → 调 core → 存结果"；
集成测试覆盖每个端点；OpenAPI 文档可访问。

**验收命令**
```bash
pytest backend/tests/test_api.py -q
curl -s localhost:8000/openapi.json | python -m json.tool > /dev/null
```
**完成定义**：所有端点有测试；每个 recommend item 都有非空 evidence；无来源数字字段为 0 个。

---

### M4 · 前端
**做什么**：按 §8 实现 5 个页面；类型从 OpenAPI 生成；完成"建档 → 推荐 → 志愿表 → 导出 PDF"闭环。

**验收命令**
```bash
cd frontend && npm run build && npm run typecheck
```
**完成定义**：闭环可走通；概率显示为区间；每卡片可展开证据链；风险 HIGH 有阻断提示；
报告含免责声明与来源清单。

---

### M5 · Agent 层与防幻觉
**做什么**：`tools.py` / `prompts.py` / `parser.py` / `narrator.py` / `guard.py`；
对话式建档（缺字段追问）；结果解释；**幻觉护栏 + 测试**。

**验收命令**
```bash
pytest backend/tests/test_agent_hallucination.py -q   # 20 例，编造数 = 0
```
**完成定义**：自然语言能建档；推荐理由引用真实证据；**20 个幻觉测试全过**；
绝对化词表命中被拦截。

---

### M6 · 真实数据接入（**范围另议，需用户确认数据来源**）
**做什么**：实现 `etl/loaders/` 适配器；先接 **1 个省的 1 年真实数据**打通；
数据校验 + 与模拟数据结果对比；更新规则包 `verified_year`。

**验收命令**
```bash
python scripts/seed.py --source real --province zhejiang --year 2025
python scripts/run_backtest.py --province zhejiang --source real
```
**完成定义**：真实数据入库；校验 0 error；回测指标不劣于模拟数据基线。

> ⚠️ 数据合规性需单独评估。**不要**在未确认授权的情况下抓取考试院网站。

---

### M7 · 加固与交付
**做什么**：性能（推荐接口 P95 < 1s）、边界（0 志愿/超高分/超低分/全被过滤）、
错误处理、日志、Docker 生产配置、README 与用户手册、`DECISIONS.md` 汇总。

**验收命令**
```bash
pytest backend/tests -q --cov=app.core --cov-fail-under=90
python scripts/run_backtest.py --all
bash scripts/smoke.sh
```
**完成定义**：§1.3 成功判据表**逐项打勾**。

---

## 11. 每轮工作的标准动作

每一轮开始前/结束后照做：

**开始前**
1. 读本文件相关章节 + `docs/DOMAIN_RULES.md`
2. 声明本轮目标属于哪个 Phase、要交付什么、验收命令是什么
3. 检查上轮是否有未通过的验收

**结束后**
1. 运行本轮验收命令，**贴出真实输出**（不许说"应该通过了"）
2. 若改了概率模型参数 → **必须重跑回测**并附前后对比
3. 更新 `docs/DECISIONS.md`：本轮决策、原因、被否决的方案
4. 明确下一轮起点

**红线（违反即返工）**
- 🚫 在 `core/` 里 import 数据库、网络库、LLM SDK
- 🚫 硬编码任何分数线、位次、省份志愿数（必须来自配置且有 source_url）
- 🚫 让 LLM 直接产生数字
- 🚫 在无证据链的情况下返回推荐结果
- 🚫 跳过回测就调整概率参数
- 🚫 用"应该能跑"代替实际执行验证
- 🚫 只拿某一年的数据下结论

---

## 12. 数据与合规声明

- 模拟数据中使用的**院校名称、专业名称为公开信息**，但**所有分数线与位次均为模拟值**，
  必须在数据表与 UI 中标注 `is_synthetic: true`，**严禁误用于真实填报**。
- 真实数据接入前必须确认来源授权与使用条款（详见 `docs/DOMAIN_RULES.md` §6）。
- 系统输出**仅供参考**，最终以各省考试院官方文件与招生章程为准。
  该免责声明必须出现在：报告页、导出 PDF、Chat 首次回复。

---

## 13. 快速索引

| 我要找… | 去看 |
|---|---|
| 该做什么、不该做什么 | §1 |
| 六省投档规则数字 | §2.1 |
| 目录结构 | §4.2 |
| 表结构 | §5.2 |
| 概率怎么算 | §6.2 |
| 风险码含义 | §6.8 |
| API 长什么样 | §7 |
| 下一步干什么 | §10 |
| 算法参数默认值与经验规则 | `docs/DOMAIN_RULES.md` |
