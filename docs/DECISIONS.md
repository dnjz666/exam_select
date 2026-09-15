# 架构决策记录（ADR）

> 每轮工作结束后在此追加。格式：编号 / 日期 / 状态 / 背景 / 决策 / 后果 / 被否决的方案。
> **被否决的方案必须写下来**，否则下一轮会有人（或某个 agent）重新提出来。

---

## ADR-001 · 本机开发环境与工具链固定

- **日期**：2026-02（首次环境勘察）
- **状态**：已采纳
- **背景**：M0 需要在开发机上起后端与前端。开工前对开发机做了完整工具链勘察，发现三处会直接影响施工的问题。

### 勘察结果

| 项 | 实测 | 判定 |
|---|---|---|
| OS | Windows 11 (NT 10.0.26200) AMD64 | — |
| `python`（PATH 默认） | **3.13.13**（`D:\develop\python\python.exe`） | ❌ 与项目要求的 3.11 不符 |
| `py -3.11` | **3.11.9**，pip 24.0，venv 可用 | ✅ 可用 |
| `python3` | 不存在 | ⚠️ 脚本里禁止写 `python3` |
| Node | v26.1.0（nvm4w 管理，`C:\nvm4w\nodejs`） | ✅ 满足 ≥20 |
| pnpm / npm | 11.8.0 / 11.13.0 | ✅ |
| yarn / uv / poetry | 均未安装 | 不需要 |
| git | 2.54.0.windows.1 | ✅ |
| Docker CLI | 28.4.0 + Compose v2.39.4 | ⚠️ 仅 CLI |
| **Docker 守护进程** | **未运行**：`docker ps` 返回 exit=1 且无输出，`Docker Desktop` / `com.docker.backend` 进程均不存在 | ⚠️ **阻塞** |
| D: 可用空间 | 231,461,900,288 B ≈ **215.6 GB** | ✅ |
| `LongPathsEnabled` | 1 | ✅ |
| PowerShell 执行策略 | CurrentUser / LocalMachine 均为 `RemoteSigned` | ✅ 本地生成的 `Activate.ps1` 不受限 |
| 工作区路径 | `D:\exam_select`（2026-02 由 `D:\exam select` 改名，原名含空格） | ✅ 无空格；仍保留加引号习惯 |

> 注：`Get-Volume` / `fsutil volume diskfree` 在受管沙箱下返回"拒绝访问"（HRESULT 0x80041003 / Error 5），
> 这是沙箱对 CIM 与原始卷访问的限制，**不是磁盘或系统故障**。磁盘容量改用
> `[System.IO.DriveInfo]::new('D').AvailableFreeSpace` 取得。

### 决策

1. **Python 版本固定为 3.11，且一律用 `py -3.11` 调用。**
   禁止在任何文档、脚本、CI 配置中写裸 `python` 或 `python3`。
   虚拟环境路径固定为 `backend\.venv`。
2. **M0–M6 的开发与验收走本地进程路径（venv + uvicorn + pnpm dev），不依赖 Docker。**
   容器化验证推迟到 M7，届时由人工先启动 Docker Desktop。
3. ~~路径含空格~~ → **已解除**（2026-02 工作区由 `D:\exam select` 改名为 `D:\exam_select`）。
   改名后风险消除，**仍保留加引号习惯**：所有脚本、npm scripts、PowerShell 命令中引用项目路径
   **必须加引号**。禁止拼接未加引号的绝对路径。

### 后果

- ✅ 开发者不需要先装/启动 Docker 就能跑通全流程——降低上手门槛。
- ✅ Python 版本确定，`scipy` / `numpy` / `pandas` 的 wheel 兼容性风险消除。
- ⚠️ 本地进程路径意味着"在我机器上能跑"的风险更高，M7 的容器化验证**不能省**。
- ⚠️ 路径含空格一旦被忽略，会在 shell 脚本、Makefile、部分 C 扩展编译处零散报错，
  排查成本远高于一开始就加引号。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 用默认的 Python 3.13 | 与 AGENTS.md §4.1 技术栈声明冲突；3.13 下部分科学计算依赖的既有版本组合未验证，M2 阶段暴露问题代价太高 |
| 升级项目到 Python 3.13 | 会让技术栈声明、CI 镜像、依赖锁定全部返工，收益为零 |
| 强制所有环节用 Docker | 本机守护进程未运行，M0 会被环境问题阻塞，掩盖真正的开发工作 |
| 把工作区改名为无空格路径（如 `D:\exam-select`） | 需要用户决策且影响工作区绑定；先按"加引号"约定推进，若后续真踩坑再提 |

> **2026-02 追记**：上表最后一项后来被采纳——工作区确由用户改名为 `D:\exam_select`。
> 改名前旧会话已因"路径含空格 + 会话沙箱根路径绑定"出现 `pwsh` / `glob` / `grep` / `write` 全面失效，
> 只能重启会话（结论以交接件落盘，已并入 `docs/DOMAIN_RULES.md` §1.2 与 ADR-005/006），
> 印证该风险是真实事故源而非洁癖。改名后以上工具全部恢复（本次会话已实测）。

---

## ADR-002 · 推荐算法采用位次法而非线差法

- **日期**：2026-02
- **状态**：已采纳
- **背景**：志愿推荐有两条主流技术路线——线差法（考生分数 − 批次线）与位次法（考生位次 vs 历史录取位次）。

### 决策
采用**位次法**为主，分数仅用于展示。核心概率模型见 `AGENTS.md` §6.2。

### 理由
1. 线差法的隐含假设是"批次线到考生分数的距离"跨年可比，但**批次线本身随招生计划与考生人数浮动**，
   该假设在考生人数波动大的年份直接失效。
2. 位次由一分一段表直接给出，是考生在全省的相对位置，**跨年可比性显著优于分数**。
3. 位次法天然支持"考生人数变化归一化"（`R_adj = R × N_今年 / N_当年`），线差法无法表达。

### 后果
- ✅ 需要维护完整的一分一段表与 `province_year_stats.total_candidates`，数据准备工作量更大。
- ✅ 换算链路多一环（分数→位次→归一化→概率），每环都必须可测。
- ⚠️ 对考生解释时要额外做"位次→等效分"的回译，否则家长听不懂。首屏必须展示等效分（见 `AGENTS.md` §8.1）。

### 被否决的方案
| 方案 | 否决理由 |
|---|---|
| 纯线差法 | 跨年可比性差，考生人数波动年份会系统性偏移 |
| 线差法与位次法加权融合 | 两个信号高度相关，融合权重无实证依据，只会增加不可解释的自由度 |
| 直接用 LLM 估计录取概率 | 不可复现、不可回测、会编造数字，直接违反项目最高原则 |

---

## ADR-003 · `core/` 算法层强制纯函数

- **日期**：2026-02
- **状态**：已采纳

### 决策
`backend/app/core/**` 内**禁止** import 数据库、网络库、LLM SDK。
所有外部数据作为参数传入，结果作为返回值传出。见 `AGENTS.md` §3.2。

### 理由
1. **可回测**：回测要用 `Y-1` 年数据预测 `Y` 年，若算法层自己连库取"当前年"数据，回测无法构造历史快照。
2. **可单测**：纯函数不需要 fixture、不需要 mock 数据库，覆盖率 ≥90% 才可能达成。
3. **可复现**：给定同一组输入必然得到同一输出，这是"回测指标可信"的前提。

### 后果
- ✅ 算法层测试极快（无 IO），可以在 CI 里跑大量黄金用例与 hypothesis 性质测试。
- ⚠️ L4 服务层需要写更多"取数 → 组装 → 调用"的样板代码。这是**刻意付出的成本**。

### 被否决的方案
| 方案 | 否决理由 |
|---|---|
| 允许 core 直接查库，用依赖注入在测试时替换 | 边界会被逐步侵蚀，"就这一次"最终导致回测不可用 |
| 把算法做成 Service 类持有 session | 同为边界侵蚀，且让纯函数性质测试无法进行 |

---

## ADR-004 · 前后端分离，OpenAPI 为唯一契约来源

- **日期**：2026-02
- **状态**：已采纳

### 决策
`backend/` 与 `frontend/` 为两个独立工程，仅通过 REST（`/api/v1/*`）与 SSE（`/api/v1/chat`）通信。
前端类型由后端 OpenAPI schema 生成，**不手工维护重复类型**。详见 `AGENTS.md` §4.3。

### 理由
1. 志愿填报的数据结构（`AdmissionUnit`、`ProbabilityResult`）字段多且带证据链，
   手写两份必然漂移，而漂移在"证据链字段丢失"这种地方最难被发现。
2. 后端 Pydantic 模型已经是 schema 的单一来源，`FastAPI` 自动产出 OpenAPI，再生成 TS 类型是零额外成本的。
3. 前后端独立部署能力，为后续把算法层单独服务化留出空间。

### 后果
- ✅ 契约变更会立刻在前端类型检查中暴露，而非运行时才炸。
- ⚠️ 首次配置需要跑通 `openapi-typescript` 生成链路，M0/M4 各有一小段设置成本。
- ⚠️ 后端未启动时前端无法生成类型，开发时需先起后端（或提交一份快照用于 CI，但**不进版本库**）。

### 被否决的方案
| 方案 | 否决理由 |
|---|---|
| 后端渲染模板（Jinja2）单体应用 | 志愿表编辑器需要拖拽排序、实时风险面板等重交互，模板方案体验做不好 |
| 手工维护 TS 类型 | 必然漂移，且漂移点在证据链字段上最难察觉 |
| 引入 tRPC 类共享类型的方案 | 跨语言（Python ↔ TS）不适用 |

---

## ADR-005 · 四省投档规则官方原文核实（浙江/山东/上海/北京）

- **日期**：2026-02（上一会话核实；因工作区改名致会话沙箱失效，结论以交接件落盘，本会话并入）
- **状态**：已采纳

### 背景

`docs/DOMAIN_RULES.md` §1.1 中浙江 / 山东 / 上海 / 北京四项数值（80 / 96 / 24×4 / 30×6）
此前来自行业普遍引用，`verified_status = UNVERIFIED`，触碰项目红线
"没有来源的规则数字不得进入推荐结果"，阻塞 M1 规则包落码。

### 来源等级定义

| 等级 | 含义 |
|---|---|
| `PRIMARY` | 考试院官方文件原文，可直接引用数字 |
| `PRIMARY-GOV` | 政府门户网站转述官方文件，数字可信但非考试院一手页面 |
| `SECONDARY` | 转载源（教育媒体等），必须回官方原文复核 |
| `UNVERIFIED` | 无来源，数字不得进入代码 |

### 结论

1. **80 / 96 / 24 / 30 四个数字与行业普遍引用完全一致，无需纠正**，核实状态升为：
   浙江 ✅ PRIMARY、山东 ✅ PRIMARY、上海 ✅ PRIMARY、北京 🟡 PRIMARY-GOV。
2. 新增两条先前无出处的硬约束：**上海每个院校专业组内设 4 个专业志愿**、
   **北京每个志愿设 6 个专业 + 1 个"是否服从专业组内调剂"选项**。
3. 上海文件额外提供：投档比例 1:1、同分排序 6 级位序、调剂仅限组内、退档情形
   → 已纳入 `BatchRule` 扩展字段（`AGENTS.md` §6.6）。
4. 全部原文摘录与 URL 存于 `docs/DOMAIN_RULES.md` §1.2.3。

### 遗留（M1 待办，详见 `DOMAIN_RULES.md` §1.3）

| 项 | 现状 | 动作 |
|---|---|---|
| 北京 | `PRIMARY-GOV` | 取《北京市2026年普通高等学校招生工作规定》原文升 PRIMARY |
| 天津 | `SECONDARY` | 回天津市教育招生考试院原文核实 |
| 海南 | `SECONDARY` | 回海南省考试局原文核实 |
| 六省 | 仅核实本科普通批 | 补齐提前批/专科批 `BatchRule` |
| 山东 | 依据为 2020/2021 官网问答 | 取当年《录取工作意见》再核年份 |

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 直接采信行业引用而不查原文 | 违反项目红线；行业引用无 `source_url`、无 `verified_year`，回测与审计无从追溯。本次核实恰好发现行业引用缺了"组内专业数 / 调剂选项"两条硬约束，证明不查原文必有遗漏 |
| 以教育媒体聚合站作为来源 | 同为转载源，满足不了 `PRIMARY` 要求，等于把红线洗白 |

---

## ADR-006 · `ProvinceRule` 下沉为批次级 `BatchRule`

- **日期**：2026-02
- **状态**：已采纳

### 背景

ADR-005 核实官方文件时发现，**同一省份的不同批次志愿性质完全不同**：
浙江普通类专业平行志愿每段 ≤ 80（平行），而普通类提前录取院校是 5 个院校传统志愿（**顺序**）；
上海本科普通批 24（平行）而提前批 4（顺序）；北京专科普通批 20（平行，1 校 1 专业）。
原 `AGENTS.md` §6.6 的 `ProvinceRule` 只有单一 `max_volunteers`，
且 §6.3 冲稳保梯度校验与 §6.7 Planner 均建立在平行志愿假设上。

### 决策

1. 规则建模下沉到**批次级**：`ProvinceRule.batches: list[BatchRule]`，
   每个 `BatchRule` 携带 `is_parallel: bool`、`source_quote`（官方原文摘录）、
   `verified_status` / `verified_year`（完整骨架见 `AGENTS.md` §6.6）。
2. `tiers_quota` 从规则级移至**批次级**；`ModelParams.quota` 仅保留为全局缺省值。
3. `is_parallel=False` 的顺序志愿批次**不做**冲稳保梯度配额校验，
   改为顺序志愿专用校验（第一志愿必须是最想去的）；
   `planner.py` / `risk.py` 按 `is_parallel` 分支（`AGENTS.md` §6.3 / §6.7 / §6.8 已同步）。

### 后果

- ✅ 顺序志愿批次不会再被错误套用平行志愿梯度逻辑，消除一类"系统性误导志愿表"的事故源。
- ✅ `source_quote` 让每个规则数字可回溯到官方原文，审计成本趋近于零。
- ⚠️ `planner.py` / `risk.py` / 规则包 / M1 数据都要增加批次维度，M1/M2 工作量增加。
- ⚠️ 六省提前批/专科批的 `BatchRule` 数据尚未核实（`DOMAIN_RULES.md` §1.3），
  M1 补齐前规则包不算完整。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 在 `ProvinceRule` 上加 `secondary_max_volunteers` 字段打补丁 | 只能补数量、补不了志愿性质；顺序/平行之别最终会以 `if province == ...` 渗进 planner/risk，比一次性下沉更贵 |
| 只做本科普通批，提前批/专科批暂不支持 | 提前批结构已核实（浙江 5 顺序、上海 4 顺序），预留成本极低；不做会让数据层字段与业务层能力脱节 |
| 顺序志愿也套冲稳保配额、仅调小数量 | 直接产生误导性志愿表：顺序志愿第 2 志愿起几乎投不出去，把"保底"放那里等于没有保底，违反名师铁律 4 |

---

## ADR-007 · 本机网络探测结论与离线 wheel 引导方案

- **日期**：2026-02（M0 验收期间实测）
- **状态**：已采纳

### 背景

M0 验收需 `pip install -e backend`。本机安装先后两次挂起（>10 分钟无进展），需要定位根因并给出可复现的安装路径。

### 实测结论（证据驱动）

| 探测 | 结果 |
|---|---|
| 系统代理 | WinINET 指向 `127.0.0.1:7897`（clash-verge / verge-mihomo，**进程在运行**，端口可 TCP 连通） |
| curl.exe | TLS 全部失败：`schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`——**沙箱内 curl 不可用于 HTTPS**，据此否定了两轮基于 curl 的探测结论 |
| PowerShell IWR / HttpClient | HTTPS 同样不可用（ connection closed / 状态码异常），两个客户端栈都不可信 |
| **python stdlib urllib** | **直连与走代理全通**（baidu / tuna / aliyun / pypi.org 全部 200，直连 tuna 0.19s）——与 pip 同栈，证明网络本身无碍 |
| pip 冻结点（`-vv` 日志落盘取证） | 卡在 PEP 517 **构建隔离子进程**的第一次 HTTP 请求；requests 的 `NO_PROXY='*'` 不生效（requests 不识别 `*` 通配），仍走 127.0.0.1:7897，具体冻结机制未再深究 |
| setuptools ≥69 | **拒绝** `readme = "../README.md"` 指向项目根之外的路径（DistutilsOptionError）——已从 `backend/pyproject.toml` 移除 |

### 决策

1. 提供 `scripts/bootstrap_wheels.py`：stdlib urllib 直连清华镜像，抓取全部依赖 wheel（含
   `pydantic-core==2.46.5` 这类上游精确 pin，`EXACT_VERSIONS` 维护）到 `data/wheels/`。
2. 安装一律走离线路径：
   `pip install --no-index --find-links data/wheels -e backend[dev]`。
3. `data/wheels/` 仅作本机引导缓存，不进版本库（已入 `.gitignore`）。

### 后果

- ✅ 安装完全确定化：33+ wheel 约 10 秒抓完，安装秒级完成，不再受代理/沙箱网络栈影响。
- ✅ 镜像、直连、代理三条路径全部保留在脚本内可切换，后续机器可复用。
- ⚠️ 新增依赖（如 M1/M2 引入 numpy/scipy/pandas）时需重跑脚本，并视上游 pin 更新 `EXACT_VERSIONS`。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 继续 pip 在线安装（配镜像/配代理） | 两次 >10 分钟无进展；requests 子进程冻结机制不明，修复成本高于绕开 |
| 用系统 Python 3.13 直接装包跑 | 违反 ADR-001（必须 3.11），且未验证 |
| 改用 uv/poetry | 本机未安装，引入新工具链违反"本项目不需要"结论 |

---

## M0 验收记录（2026-02）

**验收命令与真实输出**（AGENTS.md §4.4 本机实测版）：

```text
1) py -3.11 -m venv backend\.venv
   → python 3.11.9 ✅

2) pip install -e backend
   → 走离线路径：pip install --no-index --find-links data/wheels -e backend[dev]
   → Successfully installed ... fastapi-0.141.1 pydantic-2.13.5 sqlalchemy-2.0.52
     uvicorn-0.53.0 pydantic-settings-2.15.0 exam-select-backend-0.1.0 ✅
   （在线安装两次挂起 >10 分钟，根因与替代方案见 ADR-007）

3) uvicorn app.main:app --port 8000（后台）
   → 服务启动 ✅

4) curl.exe -s http://127.0.0.1:8000/health
   → {"status":"ok"}（exit=0）✅
   python 交叉验证：200 {"status":"ok"}；OpenAPI paths: ['/health'] ✅

5) python -c "from app.core.models import AdmissionUnit, ProbabilityResult; print('OK')"
   → OK ✅
   扩展验证：core+db+config 全部可导入；Base.metadata 注册 7 张表
   （admission_history, admission_plans, admission_units, colleges, majors,
    province_year_stats, score_rank_table）✅

6) pytest backend/tests -q
   → 3 passed, 2 warnings in 1.92s（警告来自 starlette/anyio 内部 Deprecation，非项目代码）✅
```

**完成定义逐项核对**：
- [x] 服务能起（uvicorn + /health）
- [x] 模型能导入（core 8 组领域模型 + db 7 表 + config）
- [x] 目录结构与 AGENTS.md §4.2 一致（backend / docs / frontend 占位 / data / scripts；frontend 工程文件留待 M4）
- [x] 无硬编码魔数（ModelParams 唯一来源 DOMAIN_RULES.md §3，pytest 断言其默认值）

**交接件执行附注**：`docs/RULE_VERIFICATION.md` §4 清单 12 项已全部执行并交叉验收；
其中"新增 §1.4 遗留待办"与"原 §1.3 顺延为 §1.4"两条在编号上互斥（原文疑有笔误），
按"§1.3 遗留待办、§1.4 官方核实入口"落位；交接件自身已按其指令删除。

**本轮未做 / 下轮起点**：
- frontend 工程文件（package.json 等）按 Phase 归属 M4，本目录仅保留 §4.2 骨架；
- 数据库迁移工具（alembic）与 seed 脚本属 M1；
- **下一轮从 M1 开始**：`etl/synthetic.py` 确定性数据生成器 + 六省批次级规则包（`BatchRule`，
  提前批/专科批数据补齐见 `DOMAIN_RULES.md` §1.3）。
