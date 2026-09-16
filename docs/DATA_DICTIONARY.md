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
| `total_candidates` | **位次归一化使用的分母**（`R_adj = R × (N_今年 / N_当年)`，DOMAIN_RULES §2.3）。口径 = **该年分数段表覆盖的最低分对应的累计人数**；必须与库中历史位次同口径（浙江合编数据覆盖到二段，所以不能只取"一段线上线人数"）。模拟数据里它就是该年考生总数 |
| `segment1_cumulative` | **一段线上累计人数**（M6 新增，ADR-015）。用途：标定无官方分数段表年份的"分数—累计人数"曲线（在官方一段线处精确闭合）。`NULL` 表示模拟数据（无此概念） |
| `segment1_line` | 该年普通类一段线分数（M6 新增）。`NULL` 表示模拟数据 |

> ★ 为什么必须是两列而不是一列（M6 实测教训）：一度把"分数段表最低分累计人数"当分母，
> 浙江 2026 官方表最低 266 分 → 292,753，而 2023 若按一段线 488 分算只有 175,424；
> 同一位次的含金量会被凭空放大 1.7 倍，跨年比较彻底失真。两列分开后：
> **归一化用 `total_candidates`，标定曲线用 `segment1_cumulative`**，各自口径自洽。

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

## 5bis. 真实数据接入口径（M6 · `backend/app/etl/loaders/zhejiang.py`，ADR-015）

当前状态：**浙江 = 真实数据；其余五省 = 模拟数据**（`scripts/seed.py --source hybrid`，默认）。

### 5bis.1 来源与年份（全部为浙江省教育考试院 www.zjzs.net 公开发布物）

| 年份 | 原始文件（`data/raw/zhejiang/`） | 用途 | `is_synthetic` |
|---|---|---|---|
| 2023–2025 | 《浙江省普通高校招生投档及专业录取情况》合编 PDF → `zhejiang_parallel_compilation_YYYY.csv` | **历年投档/录取**（含选考科目要求、录取人数、学制、平均分、一/二段位次） | 0 |
| 2024 | 年度《普通类第一段平行投档分数线表》.xls | 与合编 PDF **交叉校验**（两个独立官方来源） | 0 |
| 2026 | 年度《普通类第一段平行投档分数线表》.xls | **填报年**投档单位 + 计划数 + 专业代号 | 0 |
| 2026 | 《成绩分数段表（总分）》PDF（`zhejiang_score_segment_2026.csv`） | **一分一段表（官方原文）** | 0 |
| 2023–2025 | 无官方分数段表 | 由**当年官方投档记录**（分数↔位次）导出的标定曲线 | **1** |

每个原始文件在 `data/raw/zhejiang/manifest.json` 里登记 `source_url` / `sha256` / `bytes`。

### 5bis.2 必须记住的五条口径

| 项 | 口径 |
|---|---|
| **跨年单位对齐** | 浙江的 `专业代号` **每年重排**（2025 的 001–041 在 2026 对应完全不同的专业），所以 `unit_key` 用「院校代号 + 专业名」：`zhejiang-{院校代号}-NA-{专业链标识}`，标识 = `sha1(归一化基名)[:10]`（同名多链加 `-2` 后缀）。院校代号跨年稳定（实测 6 年 1083 所代号不变） |
| **专业名匹配** | 三级优先：全名精确 → 基名（剥括号）唯一 → 新建链（=当年新增专业，走 Step 0 类比，标 `NO_HISTORY`） |
| **位次为空** | 官方原文：位次栏为空 = 该专业本轮投档人数未满 → `data_quality=MISSING_RANK`，**不参与概率计算**，也不生成历史行 |
| **一段 vs 二段** | 同一院校专业同年出现两条时，**一段有完整位次的优先**；只有二段记录时退到二段，只产生一条历史行（`unit_key` 跨年唯一） |
| **缺口如实披露** | 2021/2022 投档表**没有选考科目要求** → 不导入（宁可少两年历史，也不能放"选考不限"的假数据进去）；无官方分数段表的年份、只存在于历史年而 2026 已停招的专业链，都在 `dataset.gaps` 里列明 |

### 5bis.3 一分一段表的两级质量

| 年份 | 来源 | 构造 | `is_synthetic` |
|---|---|---|---|
| 2026 | 官方分数段表**原文** | 直接读取，累计必须自洽 | 0 |
| 2023–2025 | **标定估计** | `cumulative(s) = max( running_max{ min_rank : min_score >= s }, 官方一段线上线人数 )` —— 观测上界天然单调、与该年官方记录天然自洽；在官方一段线处精确闭合 | 1 |

| 参数 | 值 | 来源 |
|---|---|---|
| 一段线 | 2023=488 / 2024=492 / 2025=490 / 2026=494 | 各年《各类别分数线》 |
| 一段线上线人数 | 2023=175,424（考试院公布）/ 2025=189,111（官方 2026 分数段表 490 分累计，相邻年同分段）/ 2024=178,041（三点拟合保守取值）/ 2026=184,816（官方原文） | 见 `SEGMENT1_SOURCE` |

> 标定表与官方记录的残差（反查分数 ≠ 该专业实际最低分）**必须为 WARNING 而非 ERROR**：
> 它是估计曲线，不是数据错误。校验参数 `ModelParams.rank_score_gap=2`（官方表）、
> `ModelParams.modeled_score_gap=50`（标定表）。实测浙江 2023–2025 最大残差 38 分，
> 99.5% 的记录完全自洽。

### 5bis.4 混装（hybrid）时的剔除规则

`--source hybrid` 时模拟侧必须**整省剔掉浙江**：`colleges` 主键是 `{province}-{代号}`、
`score_rank_table` 有 `UNIQUE(province, year, track, score)`，两边共用同一套 id/唯一键。
不剔干净会出现两类脏数据（M6 实测都踩到过）：

1. 同一 (省, 年, 分数) 撞唯一键 → 入库失败；
2. 同一所院校被算成两所（模拟的"浙江大学"与真实的"浙江大学"并存）。

剔除后还要级联清掉引用已删院校/单位的孤儿行（`admission_units` → `admission_plans` → `admission_history`）。

### 5bis.5 用真实数据后暴露并修掉的六处缺陷

| # | 缺陷 | 现象 | 修法 |
|---|---|---|---|
| 1 | 归一化分母口径不一致 | 一度用"分数段表最低分累计人数"当分母：2026=292,753 而 2023 表只到一段线 → 175,424，同一位次被放大 1.7 倍 | `province_year_stats` 增加 `segment1_cumulative` / `segment1_line` 两列；归一化**只用 `total_candidates`**，标定曲线才用 `segment1_cumulative` |
| 2 | 院校代号被当成全局唯一 | 浙江招生的 0001–9034 是"面向浙江招生的顺序号"（含清华北大），与模拟号段相撞 → 162 条 `COLLEGE_CODE_DUPLICATE` | 校验改为按 `(院校所在地, 代号)` 判唯一（主键本来就是 `{省}-{代号}`） |
| 3 | 分数段表覆盖不到全体考生 | 二段位次（27.7–29.1 万）大于一段线上线人数 → 2934 条 `MIN_RANK_OUT_OF_RANGE` | 同上：分母取含二段的总量 |
| 4 | 模拟/真实混装撞主键 | hybrid 下同一所院校被算成两所；同一 (省, 年, 分数) 撞唯一键 | `seed.py` 整省剔掉浙江模拟行并级联清孤儿行（§5bis.4） |
| 5 | 覆盖率接口 O(n²) | `[u for u in units if u not in matched]` 对 Pydantic 模型做深比较 → 18,543 单位时 **1.7 亿次 `__eq__`，接口 398 秒** | 改按 `unit_id` 集合判定 → **0.9 秒**，数值不变 |
| 6 | 安全闸门缺"历史年数"门槛 | 只有 1–2 年历史时，把某年的一次性低位当长期底线 → 真实数据回测 6 例保底失效 | Step 8.6 增加 `len(历史年数) ≥ min_baodian_years`（默认 3），不足则 `BAO/DIAN → WEN` + `SAFETY_YEARS_NOT_ENOUGH` |

---

## 6. M2 算法输出口径（`app/core/*`）

| 项 | 口径 |
|---|---|
| `tier` 判定 | 概率区间（§6.3）**+ 安全闸门**（Step 8.6），两条闸门都要过：① `min(近三年归一化最低位次) ≥ 考生位次 × (1 + safety_margin)`，不满足 → `SAFETY_MARGIN_NOT_MET`；② **可用历史年数 ≥ `min_baodian_years`（默认 3）**，不满足 → `SAFETY_YEARS_NOT_ENOUGH`。任一不过都降级 `WEN` |
| 为何"概率 0.95 却是 WEN" | 该单位给不出 60% 余量，**或历史年数不足** → 不能当垫底用；`reasons` 会披露原始概率与降级原因（**刻意保守**） |
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

### 7.3 M5 新增：`chat_messages` —— 会话消息（ADR-013）

| 字段 | 口径 |
|---|---|
| `id` | `msg-<纳秒>-<随机后缀>`，**按字典序 = 按时间序**（纯 uuid 会让同一秒内的消息顺序错乱） |
| `session_id` | 会话标识；前端未提供时后端生成 `chat-<uuid12>` |
| `role` | `user` \| `assistant` |
| `content` | 消息正文（首次回复会前置免责声明，§12） |
| `tool_calls` | 本轮调用的工具 `[{name, arguments, result}]`（JSON）——**"数字从哪来"的直接证据**，也是护栏判据 |
| `missing_fields` | 该轮结束时档案仍缺的字段（JSON list） |
| `mode` | `deterministic` \| `llm` \| `deterministic-fallback`（LLM 不可用时退回规则路径） |
| `blocked` | 是否被幻觉护栏拦截过（拦截 = 模型曾试图编造，留痕便于复盘） |
| `source_url` | 固定 `agent://chat`（本表是会话数据，不是外部数据源） |

> 会话历史**落库**而非存内存：它是"我当时问了什么、系统依据什么这么答"的唯一凭据，
> 进程重启就清空等于把证据链丢了。

### 7.4 API 口径

| 项 | 口径 |
|---|---|
| 响应信封 | 所有响应 `{data, evidence, warnings}`；错误体 `{error: {code, message, details}}` |
| 错误码 | `PROFILE_INCOMPLETE` 409 · `RANK_UNAVAILABLE` 503 · `PLAN_NOT_FOUND` 404 · `UNKNOWN_UNITS` 422 · `REPORT_UNAVAILABLE` 404 · `NOT_FOUND` 404 |
| `recommend` 项字段 | `probability / probability_interval / tier / confidence / utility / score_breakdown / evidence / adjustments / reasons / warnings`；`probability is None` 的项**不返回**（数量见 `stats.no_data_count`） |
| 概率区间 | `probability_interval` 按 ±1σ 给出（UI 强制显示区间，§8） |
| `plans` 手改 | PATCH 只接受**生成时候选池内**的 `unit_id`；池外 → 422 `UNKNOWN_UNITS` |
| `export` | `format=pdf`（reportlab，内置 STSong-Light 中文，无需字体文件）或 `xlsx`（openpyxl，四张表）；均含免责声明与来源清单 |
| `/chat` | M5 起是**能查数据的助手**：SSE 帧为 `start` → `delta` → `done`；`done` 里带 `content / tool_calls / mode / blocked / warnings / missing_fields / student_id`。**先算完再流式**：agent 走完工具与护栏才切帧，保证未过护栏的内容不会被吐出去 |
| `/chat` 建档回流 | `done.student_id` 是本轮结束时的档案 id；**前端必须据此更新自己的 studentId**，否则下一条消息会被当成"还没有档案"而重复建档 |
| dev 建表 | `APP_ENVIRONMENT=dev` 时启动 `create_all`；生产不自动建表（M7 alembic） |
| 测试前置 | `pytest backend/tests` 需要已播种数据库；未播种时**明确失败**并提示 `scripts/seed.py --reset`（不静默跳过） |
