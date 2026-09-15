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
| `unit_key`（派生） | `f"{province}-{college_code}-{group_code}-{major_id}"`，**不含年份**，用于跨年对齐 |
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
| `BatchRule` | 批次级规则 | 必带 `source_url` + `source_quote` + `verified_status/year`；扩展字段未核实一律 `None`（ADR-006） |
| `ModelParams` | 模型参数 | 默认值唯一来源 DOMAIN_RULES §3；改动必须重跑回测 |

---

## 4. 命名与编码约定

- `unit_id` / `unit_key` 的拼接顺序固定为 `province-college_code-group_code-major(_code)`（`unit_id` 额外带 `year`），禁止其他顺序；
- 批次编码 `batch_code` 形如 `zhejiang.public.seg1` / `beijing.undergrad.regular`（ADR-006）；
- 所有 JSON 文本列（`level_tags` / `subject_requirement`）入库前必须可 `json.loads`，否则视为校验失败；
- 金额字段（`tuition` / 预算）单位统一为 **元/年**，禁止混用万元。
