# 数据字典（DATA_DICTIONARY.md）

> 本文件是字段口径的**唯一权威定义**，以 `docs/DOMAIN_RULES.md` §2 为种子扩充（M0 建立，M1 随表结构演进追加）。
> 与代码冲突时：字段语义以本文件为准，字段清单以 `backend/app/db/models.py` 与 `backend/app/core/models.py` 为准。

---

## 0. 全局口径

| 约定 | 定义 |
|---|---|
| **位次方向** | `min_rank` 数值越小 = 越靠前 = 越难考。全系统统一，注释必须写清（DOMAIN_RULES §2.1） |
| **来源纪律** | 所有数据表必须有 `source_url` 与 `is_synthetic`；没有来源的数字不许入库（AGENTS.md §5.2 强制要求 1） |
| **归一化分母** | `total_candidates` 必须来自 `province_year_stats`，不得估算（DOMAIN_RULES §2.3） |
| **模拟数据红线** | `is_synthetic = 1` 的数据严禁用于真实填报；UI 常驻提示（DOMAIN_RULES §6） |
| **省份代码** | `zhejiang` / `shandong` / `shanghai` / `beijing` / `tianjin` / `hainan`（小写拼音） |
| **track 口径** | 3+3 六省不分文理，统一填 `"综合"`；字段保留以便扩展 |

---

## 1. 枚举取值

### 1.1 `data_quality`（DOMAIN_RULES §2.2）

| 值 | 含义 | 参与概率计算 |
|---|---|---|
| `OK` | 官方直接公布，字段完整 | ✅ |
| `DERIVED` | 由最低分 + 一分一段表反查 | ✅（权重 ×0.9 = `derived_quality_weight`） |
| `MISSING_RANK` | 有分数无位次且无法反查 | ❌ |
| `COLLECTED` | 数据来自征集志愿 | ⚠️ 参与，但打 `COLLECTED_ONLY` 风险 |
| `SUSPECT` | 校验不通过（位次与分数明显矛盾） | ❌ 且触发 `SUSPECT_DATA` 高风险 |

### 1.2 `verified_status`（DOMAIN_RULES §1.2 / DECISIONS ADR-005）

| 值 | 含义 |
|---|---|
| `PRIMARY` | 考试院官方文件原文 |
| `PRIMARY_GOV` | 政府门户转述官方文件（北京现状） |
| `SECONDARY` | 转载源（天津/海南现状，升级前不得用于真实填报） |
| `UNVERIFIED` | 无来源，数字不得进入代码 |

### 1.3 `unit_type`

| 值 | 省份 | 语义 |
|---|---|---|
| `MAJOR_COLLEGE` | 浙江 / 山东 | 专业(类)+院校；无调剂概念 |
| `MAJOR_GROUP` | 上海 / 北京 / 天津 / 海南 | 院校专业组；组内调剂是保命选项 |

### 1.4 `subject_req_status`

| 值 | 含义 |
|---|---|
| `PARSED` | 选科要求解析成功，可入库 |
| `PARSE_FAILED` | 无法可靠解析（"物理和化学"vs"物理或化学"类陷阱），**拒绝入库**（DOMAIN_RULES §2.4） |

### 1.5 `tier` / `confidence`

见 `docs/DOMAIN_RULES.md` §3（`tier_bounds`）与 AGENTS.md §6.2 Step 8 / §6.3。
`probability = None` ⇔ `confidence = NO_DATA` ⇔ `tier = NO_DATA`（契约铁律，禁止编造）。

### 1.6 `assumptions` 与 `caveats`（`BatchRule` 的两个"诚实字段"）

| 字段 | 语义 | 对来源等级的影响 | 例 |
|---|---|---|---|
| `assumptions` | **未核实维度**：该批次的某个属性没有官方原文支撑，只能按惯例/同类建模 | ★ **强制降级**：带 `assumptions` 的批次不得标 `PRIMARY`（`tests/test_rules.py` 强制） | 天津专科批「志愿性质未核实，按院校专业组模式建模」；海南提前普通类「按提前批惯例（顺序志愿）建模」 |
| `caveats` | **已知待办 / 时效提醒**：来源本身可信，但有后续动作待做 | 不影响等级 | 山东「依据 2020/2021 官网问答，未取当年《录取工作意见》再核年份」 |

> **为什么拆两个字段**：把"我不知道"（assumptions）和"我知道但还没补"（caveats）混在一起，
> 会让来源等级失去分辨力——山东的来源是考试院官网原文（PRIMARY），只是年份待再核；
> 若因此降级为 SECONDARY，就会误触发"不得用于真实填报"的红线。
> 规则：**宁可少落一个批次，也不给未核实维度编一个数字**（未核实维度一律写进 `assumptions` 并显式降级）。

**`verified_year` 口径**：指**规则核实年份**（本项目为 2026，即规则适用的招生年）；
引用文件的发表年份写在 `source_quote` 内，两者不得混用（山东即为此例）。

---

## 2. 表字段字典

### 2.1 `score_rank_table` —— 一分一段表

| 字段 | 类型 | 口径 |
|---|---|---|
| `province` / `year` / `track` / `score` | — | 联合唯一键 |
| `count_at_score` | int | 该分数考生人数 |
| `cumulative_rank` | int | 该分数及以上的累计人数；`score_to_rank` / `rank_to_score` 的插值基准（AGENTS.md §6.1） |
| `source_url` | text | 必填 |
| `is_synthetic` | bool | 按 §0 全局口径补齐（DDL 草图未画出，强制要求 1 补） |

### 2.2 `colleges` / `majors` —— 院校 / 专业库

| 字段 | 口径 |
|---|---|
| `colleges.id` | `f"{province}-{college_code}"` |
| `level_tags` | JSON 数组文本：`["985","211","双一流"]`；`scoring.py` 的 `level_score` 依据（DOMAIN_RULES §5.1） |
| `is_public` | 公办 = true；民办/独立学院学费须在卡片明示（名师铁律 10） |
| `majors.category` / `discipline` | 门类 / 专业类；`major_match_score` 的匹配层级依据（DOMAIN_RULES §5.2） |
| `subject_eval_grade` | 学科评估 A+/A/B+…；`misc_score` 输入 |

### 2.3 `admission_units` —— 投档单位（当年）

| 字段 | 口径 |
|---|---|
| `unit_id` | `f"{province}-{year}-{college_code}-{group_code}-{major_code}"`，全局唯一 |
| `unit_key`（派生） | `f"{province}-{college_code}-{group_code}-{major_code}"`，**不含年份**，用于跨年对齐；`group_code` 为 `None`（专业+院校模式）时用占位符 `NA` |
| `college_code` | ★ **必须全局唯一**（M1 起用全国统一序号 1001…）。同一招生省的单位来自多省院校，若代码按院校所在省各自编号，不同院校会撞出相同 `unit_key`（M1 实测缺陷，见 ADR-008） |
| 单位覆盖范围 | M1 只生成各省**主批次**（`ProvinceRule.main_batch()`）的单位；其余批次单位按需在 M2/M6 补齐 |
| `subject_requirement` | JSON：`{"mode":"all_of"|"any_of","subjects":[...]}`（DOMAIN_RULES §2.4） |
| `subject_req_status` | `PARSE_FAILED` 拒绝入库 |
| `plan_count` | 必须 > 0（CHECK）；< 5 触发 `PLAN_TOO_SMALL` 风险 |
| `tuition` | 元/年；推荐卡片必须明示 |
| `batch` | 批次编码，与 `BatchRule.batch_code` 对齐（ADR-006） |

### 2.4 `admission_plans` —— 招生计划历史快照

| 字段 | 口径 |
|---|---|
| `unit_key` + `year` | 联合唯一 |
| `plan_count` | 概率模型 Step 4 的 Δ 输入：计划大幅增减是强信号（AGENTS.md §6.2） |

### 2.5 `admission_history` —— 投档/录取历史

| 字段 | 口径 |
|---|---|
| `min_rank` | ★ 核心字段；该单位当年投档最低分对应位次；官方只公布分数时必须用一分一段表反查并标 `DERIVED` |
| `min_score` | 与 `min_rank` 必须经一分一段表互相印证；矛盾 → `SUSPECT` |
| `is_collected` | 征集志愿记录；与正常投档分开建行（联合唯一键含 `is_collected`） |
| `total_candidates` | 该年该科类实际参考人数；**必须等于 `province_year_stats` 同键值，禁止就地估算** |
| `data_quality` | 见 §1.1 |
| `verified` | 人工核对标记；模拟数据恒为 false |

### 2.6 `province_year_stats` —— 省级年度元数据

| 字段 | 口径 |
|---|---|
| `total_candidates` | 实际参加高考人数（非报名人数、非计划数）；位次归一化 `R_adj = R × (N_今年 / N_当年)` 的分母（DOMAIN_RULES §2.3） |

---

## 3. 核心领域模型（`app/core/models.py`，纯函数层语言）

| 模型 | 用途 | 关键契约 |
|---|---|---|
| `StudentProfile` | 考生档案 | `missing_fields` 非空 → 前端阻止进入推荐；`rank` 缺失时只能由一分一段表换算 |
| `AdmissionUnit` | 统一投档单位抽象 | 浙江/山东与沪京津琼差异由规则包吸收，业务代码禁 if-else |
| `AdmissionRecord` | 历史输入 | `data_quality` 决定是否参与概率计算 |
| `ProbabilityResult` | 概率输出 | 必带 `evidence`（每条含 `source_url`）；`probability=None` ⇔ `NO_DATA` |
| `HistoryEvidence` | 证据链 | `year / min_rank / min_score / plan_count / data_quality / source_url` |
| `Adjustment` | 修正项 | `name / delta / reason`，每条可解释 |
| `ScoredUnit` / `ScoreBreakdown` | 打分候选 | 每项分值 [0,1] 且可追溯（DOMAIN_RULES §5） |
| `PlanItem` / `VolunteerPlan` | 志愿表 | `items` 有序；`obey_adjustment` 仅 `MAJOR_GROUP` 有意义 |
| `Risk` | 风险项 | 每个 code 必须带 `suggestion`（AGENTS.md §6.8） |
| `BatchRule` | 批次级规则 | 必带 `source_url` + `source_quote` + `verified_status/year`；扩展字段未核实一律 `None`；未核实维度入 `assumptions`（强制非 PRIMARY）、时效待办入 `caveats`（见 §1.6，ADR-006/008） |
| `ModelParams` | 模型参数 | 默认值唯一来源 DOMAIN_RULES §3；改动必须重跑回测 |

---

## 4. 命名与编码约定

- `unit_id` / `unit_key` 的拼接顺序固定为 `province-college_code-group_code-major(_code)`（`unit_id` 额外带 `year`），禁止其他顺序；
- **院校代码全局唯一**（§2.3）：`unit_key` 用院校代码而非 `college_id`，代码撞号会直接产生重复单位键；
- 批次编码 `batch_code` 形如 `zhejiang.public.seg1` / `beijing.undergrad.regular`（ADR-006）；
- 所有 JSON 文本列（`level_tags` / `subject_requirement`）入库前必须可 `json.loads`，否则视为校验失败；
- 金额字段（`tuition` / 预算）单位统一为 **元/年**，禁止混用万元；
- **模拟数据来源标记**：`source_url` 统一为 `synthetic://exam_select/etl/synthetic.py?seed=<SEED>`，
  且 `is_synthetic=1` / `verified=0`；校验器强制所有行 `source_url` 非空（含模拟行）。

---

## 5. 模拟数据生成器口径（M1 · `backend/app/etl/synthetic.py`）

| 项 | 口径 |
|---|---|
| 确定性 | 单一种子 `SEED = 20250915`；生成顺序由**排序后的名册**决定（不依赖 dict/set 遍历序）；两次运行 `SyntheticDataset.digest()` 必须相同（验收项） |
| 名册来源 | `app/etl/catalog.py`：**418 所真实院校名**（层次码 985 / 211 / SY / PROV / PRIV）+ **528 个真实专业名**（门类/专业类/选考要求），均为公开信息 |
| 考生规模量级 | 浙江 39 万 / 山东 70 万 / 上海 5.4 万 / 北京 6.7 万 / 天津 7 万 / 海南 7.4 万（**量级**参照真实公告，数值本身为模拟值） |
| 分数满分 | 上海 660、海南 900（标准分）、其余 750（按各省计分规则量级模拟） |
| 一分一段表 | 正态分布（分段 σ：下尾 ×1.25~1.32 加长）+ 整数分；`count_at_score`/`cumulative_rank` 累加自洽；最低分累计位次 **必须等于** `province_year_stats.total_candidates` |
| 单位生成 | 每省取本地院校 + 全国 985/211/双一流 + 外省抽样（上限 110 所）；院校专业组按**选考要求相同**打包，组内专业数受 `majors_per_group` 约束 |
| 位次生成 | 层次档比例 × 该年考生数；冷门专业 ×1.45、热门专业 ×0.62 修正；**夹紧到 [1, 该年考生数]**（位次不可能大于考生总数） |
| 注入规律 | 大小年 10%、计划突增/突减 8%、新增专业 7%（零历史行）、小计划 6%、征集志愿 3%、`DERIVED` 12% |
| 合规 | 全部行 `is_synthetic=1`、`verified=0`、`source_url` 前缀 `synthetic://`；**严禁用于真实填报** |

### 5.1 时间轴与回测地面真值（ADR-009）

| 概念 | 值 | 说明 |
|---|---|---|
| 填报年 | **2026** | `admission_units.year`；"今年计划"所在年 |
| 历史投档年 | 2022–2025 | `admission_history`；其中 **2025 同时是回测地面真值年** |
| 计划快照年 | 2022–2026 | `admission_plans` |
| 防泄漏 | `year < target.year` | **预测时必须过滤**；模型内部强制，校验器以 `W_GROUND_TRUTH` 提示 |

> 因此：线上（2026 考生）用 2023–2025 预测；回测（Y=2025）用 2022–2024 预测再与 2025 实际比对。

---

## 6. M2 算法输出口径（`app/core/*`）

| 项 | 口径 |
|---|---|
| `tier` 判定 | 概率区间（§6.3）**+ 安全闸门**（Step 8.6）：`BAO`/`DIAN` 还须满足 `min(近三年归一化最低位次) ≥ 考生位次 × (1 + safety_margin)`；否则降级 `WEN` 并打 `SAFETY_MARGIN_NOT_MET` |
| 为何"概率 0.95 却是 WEN" | 该单位给不出 30% 余量 → 不能当垫底用；`reasons` 会披露原始概率与降级原因（**刻意保守**） |
| 无本单位历史 | Step 0 类比路径：`confidence=LOW` 且**一律不得判为 BAO/DIAN** |
| `sigma` | 报告值为**最终生效**的 σ（含 Step 7 波动放大后的值），`probability_interval` 的 ±1σ 区间即基于它 |
| `probability_interval` | UI 必须显示区间（§8）；由报告概率按 σ 尺度展开 ±1，仍受 `prob_clip_*` 约束 |
| 警告码 | `NO_HISTORY` / `SINGLE_YEAR_DATA` / `PLAN_TOO_SMALL` / `COLLECTED_ONLY` / `VOLATILE_HISTORY` / `DERIVED_DATA_DOWNWEIGHTED` / `SUSPECT_DATA_IGNORED` / `MISSING_RANK_IGNORED` / `NO_NORMALIZATION_BASIS` / `ANALOG_POOL_FALLBACK` / `UNKNOWN_BATCH` / **`SAFETY_MARGIN_NOT_MET`** |
| `evidence` | 每条必带 `source_url`；预测只用 `year < target.year` 且 `data_quality ∈ {OK, DERIVED, COLLECTED}` 的行 |
| 回测 `admitted` | `考生位次 <= 该单位目标年实际最低位次`（非征集行优先） |

---

## 7. M3 新增：用户数据表与 API 口径（ADR-010）

### 7.1 `students` —— 考生档案（草稿态可空）

| 字段 | 口径 |
|---|---|
| `id` | `stu-<uuid12>`（**不可用时间戳**：同一秒会撞主键，M3 实测缺陷） |
| `subjects` / `single_subject_scores` / `physical_exam` / `preferences` / `missing_fields` | JSON 文本列 |
| `total_score` | **可空**：建档向导中途未填分；核心 `StudentProfile` 仍要求完整，计算路径用 `require_complete()` 拦截（不替考生假设） |
| `rank` | 可空；由 `POST /students/{id}/resolve-rank` 换算，或推荐前自动换算 |
| `rank_source_url` | 位次来源（`score_rank_table.source_url` 或 `manual://student-provided`）——保证位次可追溯 |
| `source_url` | 固定 `draft://student-profile`（本表是考生自述数据，不是外部数据源） |

### 7.2 `plans` —— 志愿表

| 字段 | 口径 |
|---|---|
| `payload` | 整份 `VolunteerPlan` 的 JSON（有序 items、分层分布、违规、逐项 `notes` 依据） |
| `risks` | 最近一次风险扫描结果 JSON（§6.8 的 `Risk` 列表） |
| `batch_code` / `is_parallel` | 批次规则快照，导出与报告据此复现 |
| `source_url` | 固定 `generated://planner` |

> 逐项**证据链不落库**：导出/读取时由 `admission_history` 重算（证据是派生数据，
> 存副本会与历史脱节）。见 `plan_service._plan_evidence`。

### 7.3 API 口径

| 项 | 口径 |
|---|---|
| 响应信封 | 所有响应 `{data, evidence, warnings}`；错误体 `{error: {code, message, details}}` |
| 错误码 | `PROFILE_INCOMPLETE` 409 · `RANK_UNAVAILABLE` 503 · `PLAN_NOT_FOUND` 404 · `UNKNOWN_UNITS` 422 · `REPORT_UNAVAILABLE` 404 · `NOT_FOUND` 404 |
| `recommend` 项字段 | `probability / probability_interval / tier / confidence / utility / score_breakdown / evidence / adjustments / reasons / warnings`；`probability is None` 的项**不返回**（数量见 `stats.no_data_count`） |
| 概率区间 | `probability_interval` 按 ±1σ 给出（UI 强制显示区间，§8） |
| `plans` 手改 | PATCH 只接受**生成时候选池内**的 `unit_id`；池外 → 422 `UNKNOWN_UNITS` |
| `export` | `format=pdf`（reportlab，内置 STSong-Light 中文，无需字体文件）或 `xlsx`（openpyxl，四张表）；均含免责声明与来源清单 |
| `/chat` | M3 仅 SSE 通道 + 内存会话历史 + 防幻觉底线（回复**不含数字**、首次回复带免责声明）；工具化回答见 M5 |
| dev 建表 | `APP_ENVIRONMENT=dev` 时启动 `create_all`；生产不自动建表（M7 alembic） |
| 测试前置 | `pytest backend/tests` 需要已播种数据库；未播种时**明确失败**并提示 `scripts/seed.py --reset`（不静默跳过） |
