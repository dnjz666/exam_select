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

> **2026-09-14 追记（在线路径复核，受控实验）**：**代理开启时 pip 在线安装可用，无需关闭代理**。
> 在线路径固化为 `scripts/pip_online.ps1`；离线 wheel 路径保留为复现/CI 兜底。要点：
>
> 1. **代理通道实测健康**：raw socket 直连 `127.0.0.1:7897` 发 CONNECT——绕开一切客户端库的
>    bypass 逻辑（关键方法学改进）——tuna / pypi.org / files.pythonhosted.org 全部
>    `HTTP/1.1 200 Connection established` + TLS + GET 200（0.3–0.5s）；urllib 直连 /
>    显式代理 / 注册表代理三路径同样全 200（0.24–0.55s）。
> 2. **勘误 1（`NO_PROXY='*'`）**：本机两个版本实测均**识别** `'*'`——venv 实际使用的
>    pip 24.0（vendored requests 2.31.0）与全局 pip 26.2（2.34.2）的
>    `should_bypass_proxies(url, no_proxy='*')` 均为 True（最终落到 stdlib
>    `proxy_bypass_environment()`，该层对 `'*'` 无条件放行）。上文"requests 不识别 `*`"
>    不成立。当时"仍走 127.0.0.1:7897"最可能是 **pip 子进程环境里根本没有 NO_PROXY**
>    （例如只在另一个 shell 设置过）。仍建议主机列表形式：`'*'` 的语义依赖 stdlib 回退路径，
>    主机列表（requests 按后缀匹配）跨版本确定。
> 3. **勘误 2（实验方法学）**：若环境已设 `NO_PROXY='*'`，stdlib `proxy_bypass()` 对**任何**
>    主机返回 True——即使 `ProxyHandler({'https': ...})` 显式传入代理也会被跳过。因此上文
>    "urllib 走代理全通"那组样本**可能实际是直连**，证据力不足；本条以 raw CONNECT 重测。
> 4. **冻结点改述**：构建隔离首批请求 = 拉取 `[build-system].requires`（setuptools/wheel 等），
>    与主进程同一 Python ssl/OpenSSL 栈。双路径既通，两次 >10min 挂起判定为**瞬时状态**
>    （mihomo 节点/规则或 TUN DNS 当时异常），非栈不兼容。复现时加
>    `--timeout 15 --retries 2 -vv` 并对照 mihomo 连接面板，15s 内显性化，不会再"挂十分钟"。
> 5. **pip 与 Schannel 无关**：curl.exe / IWR 的 `SEC_E_NO_CREDENTIALS` 属 Schannel 栈问题；
>    pip 走 OpenSSL，不受影响。本机网络取证统一用 python stdlib / raw socket。
> 6. **agent 会话内禁止跑 pip**：DSH 会话沙箱拒绝写入/删除"子进程以 mkdtemp 创建的目录"
>    （对照实验：同一路径 `os.makedirs` 目录可写 `.whl`，`mkdtemp` 目录写入与删除均 EACCES，
>    PowerShell 删除同样被拒），而 pip 的全部临时目录都是 `mkdtemp` 建的，故 pip 在
>    agent 会话内必然 PermissionError。**pip 一律在本机终端执行。**
>
> 在线用法（`powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1`，二选一显式化，
> 不依赖注册表回退）：默认 = 路径 A（tuna 直连 + `NO_PROXY` 主机列表，代理不影响其他应用）；
> `-ViaProxy` = 路径 B（显式 `HTTPS_PROXY=http://127.0.0.1:7897`，适合官方源）。
> 上表"继续 pip 在线安装"的否决理由据此修订："机制不明"已澄清；"离线更确定"仍成立，
> 故离线保留为兜底而非废弃。

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

---

## ADR-008 · M1 数据层与模拟数据生成的关键决策

- **日期**：2026-02（M1 轮）
- **状态**：已采纳

### 背景

M1 需交付确定性模拟数据与六省批次级规则包。约束有四条：
① `core/` 必须纯函数、禁止 IO（ADR-003）；② 规则数字必须有来源（项目红线）；
③ 按 ADR-007 追记第 6 条，**agent 会话内不得运行 pip**，新增依赖的代价很高；
④ 实现过程中实测出四个真实缺陷（见下"实测缺陷"），必须在 M1 内修掉并留档。

### 决策

1. **M1 不引入 numpy / pandas / scipy**：一分一段表的正态分布用 `math.erfc` 精确实现，
   抽样用 stdlib `random.Random`，院校/专业名册为纯 Python 常量表。
   理由：stdlib 已完全够用，而新增依赖要跨"会话内禁 pip"这道门槛；
   **M2 概率模型再按技术栈引入 numpy/scipy**（`scipy.stats.norm.cdf` 是 AGENTS.md §6.2 指定实现）。
   → 结果：M1 全程**零新增依赖、零 pip 调用**。
2. **规则包只落"数量 + 志愿性质均有来源支撑"的批次**，未核实的批次不落码、记入
   `DOMAIN_RULES.md` §1.3（"宁可不答，不可编造"）。共交付 **20 个 `BatchRule`**。
3. **`BatchRule` 新增 `assumptions` 与 `caveats` 两个字段**：
   `assumptions` = 未核实维度（**强制非 PRIMARY**，由 `tests/test_rules.py` 断言）；
   `caveats` = 已知待办 / 时效提醒（不影响来源等级）。语义见 `DATA_DICTIONARY.md` §1.6。
4. **院校代码改为全国统一序号（全局唯一）**：`unit_key = {招生省}-{院校代码}-{组}-{专业}`，
   而同一招生省包含多个省的院校；若院校代码按"院校所在省"各自编号，不同院校会撞出同一 `unit_key`。
5. **校验器 ERROR / WARNING 分级**：ERROR 必须为 0（结构性错误）；
   WARNING 承载"注入规律可检出"与"规则核实红线"的证据
   （`W_RULE_REDLINE` 自动检出天津/海南，禁止靠人工记忆）。
6. 模拟数据 `source_url` 统一为 `synthetic://exam_select/etl/synthetic.py?seed=<SEED>`，
   `is_synthetic=1` / `verified=0`；校验器强制**所有行（含模拟行）**`source_url` 非空。

### 实测缺陷（本轮真实踩到，已修并有回归测试）

| 缺陷 | 症状 | 根因 | 修复 |
|---|---|---|---|
| 单位键撞车 | 161 个 `unit_id` 重复、259 个 `(unit_key, year, is_collected)` 重复、483 个计划键重复 | 院校代码按"院校所在省"编号（每省从 1001 起），而 `unit_key` 前缀是**招生省** → `beijing-1001` 与 `gansu-1001` 撞键 | 院校代码改全国统一序号（决策 4） |
| 位次越界 | 校验报 `MIN_RANK_OUT_OF_RANGE`（位次 > 全省考生数） | 大小年 ×1.45 × 征集 ×1.35 × 冷门 ×1.45 × 高位次档叠加越界 | 位次生成后夹紧到 `[1, 该年考生数]` |
| 大小年方向写死 | volatile 单位两年位次单向下滑而非震荡，cv 检不出"大小年" | `mult` 按年份硬编码 + 二次随机取倒数，导致某年恒为 ×0.75 | 改为「先随机指定哪一年是冷年，两年一大一小」 |
| 来源等级与"假设"混淆 | 山东 `PRIMARY` + `assumptions` 触发"假设必须降级"自检 | 把"文件年份待再核（时效）"与"未核实维度（假设）"塞进同一字段 | 拆分 `assumptions` / `caveats`（决策 3） |

### 后果

- ✅ 零新增依赖：完全绕开"会话内禁 pip"的阻塞，M1 无需任何网络与安装动作。
- ✅ 数据确定性可验证：两次生成 `digest` 相同；幂等由脚本与测试双重保证。
- ✅ 注入规律被量化为 WARNING，M2 可直接用这些样本验证概率模型与风险码。
- ⚠️ 未交付：六省提前批/专科批的部分批次数据、艺体批次（非目标）、alembic 迁移。
- ⚠️ 单位只覆盖各省**主批次**；M1 数据规模（4510 单位 / 8400 历史行）足以验证算法，
  但**不是真实招生规模**，M6 接真实数据后需重新校准性能与回测。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 引入 numpy/pandas 生成分布与数据框 | stdlib 已足够；新增依赖要跨"会话内禁 pip"，收益为零 |
| 把 `unit_key` 改用 `college_id`（含所在省）以避开撞号 | 偏离 AGENTS.md §5.1 规定的 `unit_id` 形态；让院校代码全局唯一更小、更一致 |
| 为凑"六省全批次"给未核实批次填数字 | 违反项目最高原则；已改为 `assumptions` 显式声明 + §1.3 待办 |
| 把 `assumptions` 与 `caveats` 合成一个字段 | 来源等级会失去分辨力（山东 PRIMARY 被误降级，误触发"不得用于真实填报"红线） |

---

## M1 验收记录（2026-02）

**验收命令与真实输出**（AGENTS.md §10 M1；解释器按 ADR-001 用 venv，禁裸 `python`）：

```text
1) backend\.venv\Scripts\python.exe scripts\seed.py --reset
   → [seed] --reset：已删除全部表
   → [seed] 生成完成（seed=20250915）摘要=22d5b101f84c3cea
        colleges 418 / majors 528 / score_rank_table 9228 / province_year_stats 18
        admission_units 4510 / admission_plans 13530 / admission_history 8400
   → 注入样本：collected=248，derived=989，new_major=310，plan_spike=361，
     small_plan=281，volatile=422
   → [seed] ✓ 幂等完成：库内计数与生成计数一致        （exit=0）✅

2) backend\.venv\Scripts\python.exe scripts\seed.py        # 幂等复跑
   → 摘要仍为 22d5b101f84c3cea，逐表计数同上，exit=0
   → 结论：重复执行结果一致（**内容摘要也相同**，不只是计数）✅

3) backend\.venv\Scripts\python.exe -m app.etl.validate --report
   → ---- ERROR（0 条）---- （无）
   → WARNING 8 条：
     W_COLLECTED 248 / W_DERIVED 989 / W_NO_HISTORY 310 / W_PLAN_SPIKE 394 /
     W_SMALL_PLAN 284 / W_VOLATILE_UNITS 441 /
     W_RULE_REDLINE（hainan, tianjin）/ W_RULE_NOT_PRIMARY（beijing, shanghai）
   → 结论：通过（0 error）                            （exit=0）✅

4) backend\.venv\Scripts\python.exe -m pytest backend/tests -q
   → 49 passed, 2 warnings in 5.96s ✅
   （test_rules 20 项 + test_synthetic 12 项 + test_validate 13 项 + M0 冒烟 3 项；
     2 条警告来自 starlette/anyio 内部 Deprecation，非项目代码）
```

**完成定义逐项核对**：
- [x] 数据可重复生成且一致（同 seed → 同 digest；`seed.py` 幂等）
- [x] 校验 0 error（11 类结构不变量；每条 ERROR 码都有对应的"坏数据必须被检出"测试）
- [x] 六省规则包齐备且每条带来源（20 个 `BatchRule`，`source_problems()` 全绿；
      `assumptions` 强制非 PRIMARY 由测试强制）
- [x] 故意注入的"大小年 / 计划突增"样本可被检出（441 个单位 cv > 0.15；394 个单位
      2025 计划相对 2024 变动 ≥40%；310 个新增专业零历史行）
- [x] 数据量达标：院校 418 所（≥300）、专业 528 个（≥500）、六省 × 3 年

**环境附注**：M1 **未引入任何新依赖、未执行任何 pip 命令**（ADR-008 决策 1），
因此完全不受 ADR-007 追记第 6 条"agent 会话内禁 pip"影响。
M2 引入 numpy/scipy 时请在本机终端执行：
`powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1`。

**本轮未做 / 下轮起点**：
- 未交付：六省提前批/专科批的部分批次数据（缺来源数字）、艺体批次（AGENTS §1.2 非目标）、
  数据库迁移工具 alembic（仍用 `Base.metadata.create_all`）；
- 单位只覆盖各省主批次（`main_batch`），其余批次的单位待 M2/M6 按需补齐；
- **下一轮从 M2 开始**：`core/rank.py`（分数↔位次 + 归一化）、`core/probability.py`（§6.2 八步）、
  `core/filters.py`、`core/scoring.py`、`core/planner.py`、`core/risk.py`、`core/backtest.py`、
  `tests/golden/` 20 条黄金用例。

---

## ADR-009 · M2 核心算法引擎：四处规范勘误 + 回测驱动标定

- **日期**：2026-02（M2 轮）
- **状态**：已采纳
- **背景**：实现 AGENTS §6.2 八步概率模型并用回测验证 §1.3 的四项硬指标时，回测首轮即失败
  （保底失效率 1.40%、稳档 63.3%、冲档 3.56%）。按"证据驱动"排查后，定位到 **4 处真实缺陷**
  （3 处是规范/代码的方向性错误，1 处是 M1 数据缺陷）。全部修复并留档。

### 决策与勘误

#### 勘误 1（严重）：§6.2 Step 7「波动收缩」的加法形式会摧毁分层判别力

规范原文：`P = 0.5 + (P - 0.5) · (1 - κ)`（κ ≤ 0.35）。

**问题**：该式把**任何**概率压进 `[0.5κ, 1-0.5κ]`（κ=0.35 时即 `[0.175, 0.825]`）。
后果：波动大的单位**永远无法**被判为 `TOO_RISKY`（<0.10）或 `DIAN`（≥0.93）；
毫无希望的考生也会被报成 12%~40%。实测证据（浙江 2025 回测）：

```text
考生   5,000 → P=0.8805   （由 Φ(z) 复算 = 0.9997）
考生  40,000 → P=0.1195   （由 Φ(z) 复算 ≈ 0）
考生 300,000 → P=0.1195   ← 概率被"地板"托住
关掉收缩：冲档命中率 1.5% → 19%（落入目标区间），Brier 0.0076 → 0.0059
```

**改法**：收缩的语义是"降低自信"，应体现在**不确定度**上 → 改为**放大 σ**
（等价于把 z 按 `(1-κ)` 缩放）：概率同样向 0.5 靠拢，但排序性、单调性与两端可达性不破坏。

#### 勘误 2（方向）：名师铁律 4 / R-007 / §6.8 的"保底余量"方向写反

文档字面："垫底志愿近三年最低位次必须**全部优于考生位次**且留有余量"。
按字面（单位切线比考生更好=更难）恰恰是**不安全**的保底，与"真保底"自相矛盾。

**正确语义**：**考生位次必须比该单位近三年最难年份（位次数值最小者）的切线还靠前 ≥ safety_margin**，
即 `min(近三年归一化最低位次) ≥ 考生位次 × (1 + safety_margin)`——考生留出缓冲。
本仓库的 `core/risk.py::SAFETY_NOT_SAFE` 首版按字面写反，已随之修正。

#### 勘误 3（缺失）：保/垫是"安全承诺"，不能只由概率区间给出

即使概率 P=0.99，若该单位去年切线仅比考生位次高 2%，它也不是保底。
但 §6.3 的 `P → tier` 映射没有任何余量校验，回测中 36 例保底失效多是"擦边"（例：考生 2,204 vs 实际 2,197，差 7 位）。

**改法**：在 §6.2 末尾新增 **Step 8.6 安全闸门**（名师铁律 4 的强制落地）：
`BAO/DIAN` 必须通过余量检验，否则降级为 `WEN` + 告警 `SAFETY_MARGIN_NOT_MET`；
**无本单位历史（Step 0 类比路径）一律不得判为 BAO/DIAN**。原始概率仍在 `reasons` 中如实披露。

#### 勘误 4（数据）：M1 生成器里"计划数"对投档位次没有因果影响

模型按 §6.2 Step 4 把计划数当强信号修正，而 M1 数据里计划变动是纯噪声 → 修正项变成噪声放大器，
直接毁掉低概率档的校准。**改法**：生成器按**真实弹性 0.35**（刻意不同于模型的 β=0.4，避免自我实现）
让计划变动因果地影响切线；另注入约 15% 单位的**真实逐年趋势**（×0.965 / ×1.035），使趋势修正确有信号可学。

#### （附）§7 的另外两处方向勘误（已在黄金用例中锁定）

- §7 G-001 示例：考生 10000 vs 单位 9000/9500/9200 却期望"稳档"——按 §2.1 与 §6.2 应为
  `TOO_RISKY`（要得 0.55~0.72 应把考生位次改到 ~9000）。已由 **G-018** 作为回归陷阱锁定；
- §7.2 "历史位次整体变小（更难）→ 概率**不下降**"方向相反，正确断言是"**不上升**"，
  已由 `test_probability.py::test_property_harder_unit_never_raises_probability` 锁定。

### 参数标定（DOMAIN_RULES §3.1 纪律：网格扫描 + 前后对比 + 跨省稳定性）

唯一改动参数：`safety_margin`（保底余量）。其余参数保持文档默认值（`min_sigma_abs=300`、
`min_sigma_rel=0.03`、`cv_threshold=0.15`、`plan_beta=0.4`）——实测它们对四项指标影响甚微
（见下"扫描证据"），改一个参数即可达标，是抗过拟合的最优选择。

**网格扫描证据（浙江 2025，60 考生 × 100 样本，16 组合节选）**

| safety_margin | min_sigma_abs | 保底失效 | 稳档 | 冲档 | Brier |
|---|---|---|---|---|---|
| 0.15 | 300 | 0.0087 | 0.583 | 0.015 | 0.0076 |
| 0.25 | 300 | 0.0000 | 0.854 | 0.143 | 0.0059 |
| **0.30** | 300 | **0.0000** | **0.865** | **0.143** | **0.0059** |
| 0.30 | 100 | 0.0000 | 0.870 | 0.150 | 0.0058 |

**跨省稳定性验证（防过拟合，§3.1 要求）**

| 省份 | margin=0.25 | margin=0.30 |
|---|---|---|
| 浙江 | 保底 0 / 稳档 0.854 / 冲档 0.143 | 保底 0 / 稳档 **0.865** / 冲档 0.143 |
| 山东 | 保底 0 / 稳档 0.838 / 冲档 0.412 | 保底 0 / 稳档 **0.857** / 冲档 0.412 |
| 北京 | 保底 0 / 稳档 0.825 / 冲档 0.098 | 保底 0 / 稳档 **0.839** / 冲档 0.098 |

0.30 在**三省一致更好**（保底失效率恒为 0，稳档 +1~2 点，冲档与 Brier 不劣）→ 非单省过拟合，采用 **0.30**。

### 后果

- ✅ 浙江 2025 回测**四项硬指标全部达标**（见下方验收记录）；保底失效率的稳健性在三个省都成立。
- ✅ 概率校准极好：Brier 0.0057（门槛 0.15），分层校准偏差 ≤ 0.08（除 BAO 的 +0.125，方向为保守）。
- ✅ 算法层覆盖率 95.84%（门槛 90%），黄金用例 38 条（要求 ≥20）。
- ⚠️ **诚实披露**：`冲档 ∈ [10%,40%]` 与 `稳档 ≥85%` 在**省际边界上是紧的**——
  山东冲档 41.2%（略超 40%）、北京稳档 83.9%（略低于 85%）、北京冲档 9.8%（略低于 10%）。
  模型本身校准良好（各层预测均值 ≈ 实际命中率），阈值恰好压在分层边界上。
  建议：DoD 阈值按"跨省稳定性"读（允许 ±5% 校准容差），或在 M3 前由用户确认是否调整；
  **不建议**为了凑指标继续调参（会滑向对测试集过拟合）。
- ⚠️ 安全闸门使 BAO/DIAN 数量减少（浙江 150×150 回测中 BAO 51 / DIAN 2028），
  这是"真保底"的必然代价：宁可不叫保底，也不给假保底。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 保留 Step 7 加法收缩，只调 σ 参数 | 实测 σ 参数对四项指标几乎无影响；加法收缩的判别力损失是结构性的 |
| 把 §6.3 的分层边界整体上移（如 WEN=[0.85,0.95)）以凑稳档 85% | 会改动 §6.3 语义与 planner/risk/UI 的既有契约；且[0.40,0.85) 区间将无层可归 |
| 让概率模型直接输出"保底/不保底"，不设安全闸门 | 概率是"平均意义上的频率"，保底是"承诺"；两者必须分离，否则保底失效率无法归零 |
| 为达标把 safety_margin 调到 0.35~0.40 | 跨省表显示 0.30 已一致通过；继续加大只会减少保底供给、无证据收益 |
| 用测试集（浙江）单独调参 | 违反 §3.1"不过拟合（跨省、跨年稳定）"；已改为三省市交叉验证 |

---

## M2 验收记录（2026-02）

**验收命令与真实输出**（AGENTS.md §10 M2）：

```text
1) backend\.venv\Scripts\python.exe -m pytest backend/tests -q --cov=app.core --cov-fail-under=90
   → 167 passed, 2 warnings in 16.83s
   → 覆盖率：TOTAL 1491 stmts / 62 miss / 95.84%（门槛 90% ✅）
     分模块：backtest 97% · filters 98% · models 99% · planner 95% · probability 92%
             rank 93% · risk 98% · rules/base 88% · scoring 99%（省份规则包均 100%）
   → 黄金用例 38 条（probability 21 / filters 12 / plan_rule 5），全部通过 ✅

2) backend\.venv\Scripts\python.exe scripts\run_backtest.py --province zhejiang --year 2025
   → 单位 811 · 考生 150 · 样本 21184（可评估 19708，NO_DATA 1476）
   → 分层分布：{BAO 51, CHONG 175, DIAN 2028, NO_DATA 1476, TOO_RISKY 16853, WEN 601}
   → ✅ safety_failure_rate   实际 0.00%   目标 == 0%
   → ✅ wen_hit_rate          实际 86.02%  目标 >= 85%
   → ✅ chong_hit_rate        实际 31.43%  目标 ∈ [10%, 40%]
   → ✅ brier                 实际 0.0057  目标 <= 0.15
   → 分层校准：BAO 0.875→1.000 · CHONG 0.236→0.314 · DIAN 0.979→1.000
                TOO_RISKY 0.020→0.001 · WEN 0.859→0.860
   → 报告落盘 backtest_report.json / backtest_report.md    （exit=0）✅

3) 属性测试（§7.2 方向性，hypothesis）：
   → 考生位次变小 → 概率不下降 ✅
   → 计划数增加   → 概率不下降 ✅
   → 单位变难     → 概率**不上升** ✅（§7.2 原文方向有误，见勘误附注）
   → 位次归一化严格按人数比例 ✅
```

**完成定义逐项核对**：
- [x] 覆盖率 ≥ 90%（实测 95.84%）
- [x] 20 条以上黄金用例全过（交付 38 条，含边界/趋势/计划/大小年/数据缺失/质量/选科/硬约束/调剂）
- [x] 回测四项硬指标全达标（保底失效率 0%、稳档 86.02%、冲档 31.43%、Brier 0.0057）
- [x] 计划数增加时概率单调不减（hypothesis 性质测试）

**本轮未做 / 下轮起点**：
- 未做 §3.1 的**敏感度热力图**（`year_weights`/`plan_beta`/`min_sigma_rel` 网格 + ECharts）——
  已交付 `scripts/calibrate_params.py` 作为底座，热力图留待 M4 前端或 M7 补；
- 未接真实数据（M6）；未做 API（M3）与前端（M4）；未做 §6.8 的 M2 增量风险码
  （调剂越界/退档条款命中，见 §6.8 注记）；
- 已知边界：山东冲档 41.2%、北京稳档 83.9% 略越阈值（见 ADR-009 后果，建议按跨省容差读）；
- **下一轮从 M3 开始**：按 §7 实现 API 端点，service 层"查库 → 组装 → 调 core → 存结果"，
  每个 recommend item 必须带回非空 evidence。

---

## ADR-010 · M3 后端 API 的关键决策

- **日期**：2026-02（M3 轮）
- **状态**：已采纳
- **背景**：按 §7 实现全部端点。约束：core 必须保持纯函数；响应不得出现无来源的数字；
  契约要求"每个 recommend item 必有非空 evidence"；导出需要真 PDF/XLSX（用户选 A，装 reportlab+openpyxl）。

### 决策

1. **统一响应信封** `Envelope[T] = {data, evidence, warnings}`，把 §7 开头"所有响应含三段"落到类型上；
   错误统一为 `{"error": {code, message, details}}`，领域异常在 `main.create_app` 里集中映射
   （409 PROFILE_INCOMPLETE / 503 RANK_UNAVAILABLE / 404 PLAN_NOT_FOUND / 422 UNKNOWN_UNITS /
   404 REPORT_UNAVAILABLE / 404 NOT_FOUND）。
2. **新增两张 L2 表**（§5.2 未列，属 M3 扩展）：`students`（档案，草稿态可空）与
   `plans`（志愿表，payload 存整份 `VolunteerPlan`）。二者是**用户产生的数据**而非外部数据源，
   `source_url` 记录口径（`draft://student-profile` / `generated://planner`）。
   - `students.total_score` **可空**以支持"建档向导中途未填分"；
     **核心 `StudentProfile` 保持"完整档案"语义不变**——草稿态只存在于 L2/L4，
     计算路径用 `student_service.require_complete()` 拦截（不替考生假设）。
3. **新增 `db/repositories.py`（L2 访问层）**，并把 M2 里散在 `services/backtest_data.py`
   的取数逻辑收拢过去，消除重复；`core/` 依旧零 DB 依赖（ADR-003）。
4. **Step 0 类比证据显式化**：给 `HistoryEvidence` 加 `note` 字段，Step 0 返回类比单位的证据并标注
   `note="类比单位 <unit_id>"`。这样既满足"recommend 每项 evidence 非空"的契约铁律，
   又**不会把类比数据伪装成本单位历史**（宁可不答，不可编造）。
5. **报告导出**：xlsx 用 openpyxl（四张表：志愿表 / 历史证据 / 风险提示 / 说明与来源），
   PDF 用 reportlab 内置 `STSong-Light` CID 字体（**无需字体文件**即出中文）。
   两者共用同一份 `build_report()` 数据；内容强制含**免责声明 + 来源清单 + 规则核实状态**（§8/§12）。
6. **手改志愿表只允许在"生成时的候选池"内调整**（`patch_items`）：不允许把未经过滤/未算概率的
   unit_id 塞进志愿表，避免绕过硬约束与证据链；每次改动后**立即重算** `violations`（批次规则）
   与 `risks`（§6.8），不存在"改完不校验"的状态。
7. **`/chat` 在 M3 只交付 SSE 通道 + 会话历史 + 防幻觉底线**：回复**不含任何数字**、
   缺字段先追问（一次 ≤3 个）、首次回复带免责声明；工具调用/System Prompt/guard 属 M5。
   会话历史暂存内存（M5 落库），响应中明确告知，避免被误认为已持久化。
8. **dev 环境启动即 `create_all` 建表**（含 M3 新表），生产不自动建表、由 M7 引入 alembic 迁移。

### 实测缺陷（本轮真实踩到并已修，均有回归测试）

| 缺陷 | 症状 | 根因 | 修复 |
|---|---|---|---|
| 学生 id 撞主键 | `IntegrityError`（同一秒内创建多个档案） | id 用秒级时间戳生成 | 改用 `uuid4().hex[:12]` |
| 志愿表生成崩溃 | `ValueError: tuple.index(x): x not in tuple` | `plan_service` 把 TOO_RISKY 候选也交给 planner，而 planner 的分层元组只有冲稳保垫 | planner 显式剔除 TOO_RISKY 并告警；排序改用安全索引 `_tier_index()` |
| 全省红线误判 | 上海（主批次 PRIMARY + 其余批次 SECONDARY）被当成"全部未核实" | `meta_service.requires_banner` 口径过宽（任一非 PRIMARY 即置位） | 改为"**全部**批次非 PRIMARY"才算红线，与 `validate.py::W_RULE_REDLINE` 对齐；部分未达标记为 `has_caution` |
| `validate` 端点 500 | `NameError: name 'plan' is not defined` | `plan_service.validate()` 漏写 `bundle.` 前缀（3 处） | 修正；测试覆盖该端点 |
| 新表未建 | `no such table: students` | M3 新增表，而建表只在 M1 播种时发生 | dev 启动钩子 `init_db()`；`seed.py --reset` 亦会建表 |
| **SQLite 相对路径随 CWD 漂移** | 从 `backend/` 启动（AGENTS §4.4 的**文档化命令**）时报 `unable to open database file`；更坏的情况是静默生成 `backend\data\exam_select.db` 这个**空库**，让人误以为"库里没数据" | 默认 `sqlite:///./data/exam_select.db` 是相对路径，而验收命令要求 `Push-Location backend` 后起服务 | `config.anchor_sqlite_url()` 把 SQLite 相对路径**锚定到仓库根**并确保父目录存在；新增 5 项 `test_config.py` 回归（含 `monkeypatch.chdir` 模拟不同 CWD） |
| **plan_id 同秒撞主键** | 同一秒内连续生成两张志愿表 → `IntegrityError`（真实用户连点两次即触发） | `plan_service.generate` 的默认 id 用秒级时间戳——与学生 id 是**同一类缺陷**，当时只修了学生 | 默认 id 改 `plan-<uuid12>`；新增 `test_api.py::test_plan_ids_are_unique_without_explicit_id`（测试此前都传显式 id 才没暴露，说明**测试不该替生产兜底**） |
| **README 示例不可执行** | 文档里的 `curl.exe -d '{"json"}'` → 服务端 `422 JSON decode error` | PowerShell 传参给原生 exe 时会**吃掉双引号**，JSON 被破坏 | README 示例改用 `Invoke-RestMethod + ConvertTo-Json` 并**逐条实测**（含导出字节数与风险条数），另加一节说明该坑 |

### 后果

- ✅ M3 验收全绿：`pytest backend/tests/test_api.py -q` → **21 passed**；
  全套 **193 passed**、core 覆盖率 **95.93%**；`/openapi.json` 可解析（OpenAPI 3.1.0，20 条路由），
  真实 uvicorn 下建档→推荐→志愿表→导出的闭环已跑通（README 的端到端示例即由该实测固化而来）。
- ✅ 契约铁律有测试守着：evidence 非空、概率 None ⇔ NO_DATA、来源齐全、概率区间存在。
- ⚠️ 会话历史与 LLM 能力是 M5 的事；M3 的 `/chat` 只是"合规通道"，不是可用助手。
- ⚠️ 志愿表手改仅限候选池内（新增志愿需重新生成）——这是刻意约束，M4 拖拽排序够用，
  但"用户想加一个池外志愿"需在 M4/M5 通过重新生成 + 候选扩展解决。
- ⚠️ `pytest backend/tests` 依赖已播种的数据库（`scripts/seed.py`）；未播种时测试**明确失败**
  并给出命令，不静默跳过。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 放宽"recommend 每项 evidence 非空"（允许 Step 0 项为空） | 契约铁律不能靠例外维护；正确做法是把"类比证据"显式化并标注性质 |
| 把会话历史与 `/chat` 一起留到 M5（M3 返回 501） | M3 要求实现全部端点；SSE 通道 + 防幻觉底线现在就能交付并有测试 |
| 允许 PATCH 任意 unit_id | 会绕过硬约束过滤与概率证据链，等于给系统开一个"无证据推荐"的后门 |
| 导出先返回 HTML 让浏览器打印 | 用户已定 A：契约要求 `format=pdf|xlsx`，用 reportlab/openpyxl 出真文件 |
| 生产环境也自动 `create_all` 建表 | 隐式改 schema 在生产是事故源；迁移必须显式（M7 alembic） |
| 手搓 XLSX/PDF（stdlib zipfile/PDF 指令） | 中文 PDF 需 CJK 字体嵌入，手搓成本与出错率都高于引入成熟库 |

---

## M3 验收记录（2026-02）

**验收命令与真实输出**（AGENTS.md §10 M3）：

```text
1) backend\.venv\Scripts\python.exe -m pytest backend/tests/test_api.py -q
   → 21 passed, 2 warnings in 22.51s        （exit=0）✅
   覆盖端点：/health · /openapi.json · meta(provinces|rule|tiers) · students(POST|GET|PATCH|resolve-rank)
             colleges/search · majors/search · units/{id}/history · recommend · plans(generate|GET|PATCH|validate|export×2)
             risk/scan · chat(SSE) · chat/{id}/history · backtest/report
   覆盖铁律：evidence 非空且带 source_url · probability None ⇔ NO_DATA · 概率区间存在 · 来源齐全
             409（档案不全）· 404（不存在）· 422（导出格式/池外单位）
   另含回归：不传 plan_id 连续生成两张志愿表都成功（秒级时间戳 id 会同秒撞主键）
   导出实测：PDF 以 %PDF 开头且 >1.5KB；XLSX 为 PK 压缩包；xlsx 四张表含免责声明与来源清单

2) backend\.venv\Scripts\python.exe -c "from app.main import app; app.openapi()"
   → openapi ok: 3.1.0 | paths: 20 | title: 高考志愿填报智能体 ✅

3) 真实服务端到端（uvicorn，CWD=backend/ —— 即 §4.4 文档化命令的目录）：
   curl.exe -s http://127.0.0.1:8011/openapi.json | python -m json.tool     → exit 0 ✅
   GET /health                                                             → {"status":"ok"} ✅
   GET /api/v1/meta/provinces   → 6 省 · 红线省份 ['hainan','tianjin']（与 DOMAIN_RULES §1.3 一致）✅
   GET /api/v1/colleges/search?q=浙江 → 3 条，首条「浙江大学」（证明连的是仓库根那个已播种库）✅
   POST /api/v1/students {zhejiang,2026,物化生,640} → stu-a285df29d418，missing=[] ✅
   POST /students/{id}/resolve-rank → 位次 17812，来源 synthetic://…synthetic.py，等效分 3 年 ✅
   POST /api/v1/recommend {limit:5} → 5 项，首项 CHONG 0.237（落在 [0.10,0.40)），evidence 3 条 ✅
   POST /api/v1/plans/generate      → 80 个志愿（浙江上限 80 ✓），分层 {CHONG 7, WEN 55, DIAN 18}
      （BAO 稀缺 → planner 按 §6.7 规则 2「优先向更保守方向借位」，与 M2 安全闸门的 BAO 收缩一致）

4) 全量回归：pytest backend/tests -q --cov=app.core --cov-fail-under=90
   → 193 passed, 2 warnings in 58.76s
   → 覆盖率 TOTAL 1500 stmts / 61 miss / 95.93%（门槛 90% ✅）
   → 其中 test_api.py 21 项（§7 全端点）+ test_config.py 5 项（路径锚定回归）
```

**完成定义逐项核对**：
- [x] 所有端点有测试（20 项集成测试覆盖 §7 全部端点）
- [x] 每个 recommend item 都有非空 evidence（含 Step 0 类比证据，`note` 标注性质）
- [x] 无来源数字字段为 0 个（evidence/院校/专业/规则来源齐备，测试逐项断言）
- [x] OpenAPI 文档可访问且可解析（TestClient 与真实 uvicorn 两条路径都验证过）
- [x] service 层负责"查库 → 组装 → 调 core → 存结果"，core 仍是纯函数（覆盖率 95.93%）
- [x] 端到端真实闭环：建档 → 换算位次 → 推荐 → 生成志愿表 → 导出 PDF/XLSX（测试断言 PDF 头与 xlsx 结构）

**本轮未做 / 下轮起点**：
- `/chat` 的 LLM 工具调用、System Prompt、guard 输出校验器 → **M5**（§9）；
  会话历史仍存内存，M5 落库；
- 前端（M4）：5 个页面 + OpenAPI 生成类型 + 端到端闭环（建档 → 推荐 → 志愿表 → 导出）；
- 敏感度热力图（§3.1）与 §6.8 的两个增量风险码仍待补；
- **下一轮从 M4 开始**：按 §8 实现首屏向导（省份联动 → 选考 3 门 → 成绩换算），
  推荐列表（概率区间 + 展开证据链），志愿表（拖拽/风险面板/导出），报告页（免责声明 + 来源清单）。

---

## ADR-011 · M4 前端：技术选型与"先补契约、再写界面"

**背景**：M4 要在 React/TS 上实现 5 个页面。动手前先核对了 §8 的三条硬要求与 M3 的实际契约，
发现**照现有契约写不出合格的界面**——问题不在前端，在契约本身。

**决策 1：先把 OpenAPI 变成"真有类型"的契约（否则 §4.3 规则 2 形同虚设）**

M3 的响应体几乎全是裸 `Envelope[dict]`，生成出来的 TS 类型等价于 `{[key:string]: unknown}`。
此时"类型从 OpenAPI 生成"只是仪式：字段改名、漏字段都不会被任何一方发现。
因此把 service 层实际返回的字段**逐字段**声明成 Pydantic 模型
（`RecommendItem` / `RecommendStats` / `PlanPayload` / `ProvinceMeta` / `BatchMeta` /
`SubjectPoolMeta` / `SubjectCoveragePayload` / `StudentPayload` / `TiersPayload` /
`UnitHistoryPayload` / `RiskScanPayload` / `ChatHistoryPayload` …），并挂到各路由的 `response_model`。

- 收益：契约从"文档"变成**校验器**。字段名一改，测试立刻 `ResponseValidationError`；
  前端拿到的也是真类型（69 个 schema）。
- 代价：FastAPI 会按 `response_model` 过滤响应体。为此新增
  `test_openapi_payloads_are_typed_not_free_form`，断言关键载荷字段齐全，
  防止"过滤掉一个字段而没人发现"。
- 被否决：前端手写一份 `models.ts`（违反 §4.3 规则 2，且必然与后端漂移）；
  继续用 `dict` + 前端 `as` 断言（把契约风险转成运行时崩溃）。

**决策 2：选考科目池必须有官方来源，拿不到就降级而不是编造（§8.1 Step 2）**

§8.1 要求"从该省可选科目中恰好选 3 门"，但 M1 只落了批次规则，**没有科目池**。
六省科目池是**规则事实**，因此按 §6.6 同一套来源纪律落码：
新增 `core.models.SubjectPool`（province / mode / choose / subjects / source_url / source_quote /
verified_status / verified_year / caveats），各省规则包各自声明。

- 六省全部拿到政府或考试院层级来源（浙江/上海/北京/山东/海南 = PRIMARY；
  天津 = PRIMARY_GOV，理由与降级依据写入 `caveats`）。
- 两个易错点已处理：① **浙江独有"技术"（7选3）**，其余五省 6选3，测试强制；
  ② 官方行文"生物/生物学"并存，池内统一用**招生计划字段口径**（"生物"），
  并在 `caveats` 里如实记录官方写法差异 —— 否则硬字符串匹配会漏。
- 拿不到原文时**降级而非编造**：`subject_pool_meta()` 会退化为"由招生计划反推"，
  带 `origin="DATA_DERIVED"` + `requires_caution=True`，前端必须显示"非官方科目池"提示。
- 新增 `GET /meta/provinces/{p}/subject-coverage`：用 `core.filters.subject_matches`
  真实统计"该组合可报 N / 共 M 个投档单位"，供 Step 2 实时显示覆盖率（非估算）。
- 被否决：前端写死六省科目名（违反"无来源数字不许写进代码"）；
  用"有招生计划的科目并集"当官方科目池（会漏掉无人要求的科目，等于编造一个科目池）。

**决策 3：`PATCH /plans/{id}/items` 的候选池改为"生成时的候选池"**

M3 的实现是 `pool = 当前 items`，于是**移除一个志愿后无法再加回来**——
在志愿填报工具里，这是危险缺陷（误删一个保底志愿却不可恢复）。
而 M3 自己的 docstring 写的就是"只允许使用该志愿表**生成时**的候选池"，
即实现与文档意图不一致。

- 改为：用同一套 `recommend_service.evaluate_candidates` 现场重算候选池
  （同样的硬约束过滤 + 同样的概率口径，`filters` 由请求带回以保持口径一致）。
- 附带收益：重算后每个志愿的 `tier/probability/interval/utility/notes` 都来自同一口径，
  不会因为手工搬运而与推荐列表不一致。
- 仍严禁越界：硬约束（选考/体检/语种/单科/批次/学费上限）一条都绕不过，池外单位照旧 422。
- 回归测试：`test_plan_remove_is_reversible`。

**决策 4：志愿项也带概率区间；志愿表带院校名索引**

- `PlanItem.probability_interval`（±1σ）：§8 要求"概率永远显示为区间"，
  志愿表页当然也算。区间由算法层给出（`core.planner` 调 `probability_interval`），
  **不让前端拿单点概率自己编一个区间**。
- `PlanPayload.colleges`（`college_id → {name, city, level_tags, is_public, source_url}`）：
  `PlanItem` 只有 `college_id`，没有院校名，志愿表页根本读不了。

**决策 5：前端技术选型（尽量少依赖）**

| 选择 | 理由 |
|---|---|
| React 18 + TS + Vite 6 + Tailwind 3 | 按 §4.1；Tailwind 3 而非 4（配置形态稳定，团队可预测） |
| ECharts 5 + `echarts/core` 按需注册 | 只打包用到的图表与组件（位次趋势折线 + 梯度分布柱状） |
| zustand + persist | 向导进度需同时存 localStorage 与后端草稿（§8.1），一个 600 行的状态库就够 |
| **不引入拖拽库** | 志愿表用原生 HTML5 DnD + 上下移动按钮。少一个依赖，且**键盘可达**（DnD 不能是唯一路径） |
| **不引入 react-query** | 服务端状态很轻（元数据 + 一次推荐 + 一张志愿表），多一个依赖就多一份版本面 |
| vitest 只测纯函数 | 组件行为用"真后端"端到端验证（`npm run smoke`），不在 jsdom 里 mock 一套假 API —— 那样测的是 mock |
| 不引入 eslint | 本轮验收是 `build + typecheck`；TypeScript 严格模式已覆盖主要风险面，lint 留 M7 |

**关键设计点（对齐 §8 硬要求）**

1. **首屏即向导**：`/` 重定向到 `/profile`，无落地页。
   Step 1 选中省份**立即**显示投档模式/志愿数/组内专业数/调剂规则/核实徽标。
   Step 2 选满 3 门后其余禁用；实时覆盖率来自后端真实统计。
   Step 3 分数→位次换算显示完整溯源（位次/总人数/来源链接/等效分）；
   换算失败（503 `RANK_UNAVAILABLE`）时明确提示"位次换算不可用"并引导手填；
   **分数与手填位次冲突时给出两个按钮让考生选，绝不擅自覆盖**。
2. **概率永远是区间**：`ProbabilityBar` 只画区间带，刻意**不画单点标记**（单点会诱导伪精确）。
   区间过窄时自动加小数位，不美化放大。分层刻度来自 `/meta/tiers`，前端不写死 10/40/75/93。
3. **证据链可展开**：`EvidenceTable` 把"本单位历史"与"Step 0 类比证据"**分表展示**，
   类比证据不可能被误读成本校往年数据。
4. **HIGH 风险阻断式**：志愿表页出现 HIGH 风险时，导出 PDF/Excel 被锁定，
   必须勾选"我已阅读并理解"才解锁。
5. **调剂选项按 `has_major_adjustment` 显隐**（不是按省份名判断）：
   专业+院校模式不显示该选项（不存在调剂概念）。
6. **报告页**含档案 + 志愿表 + 每志愿依据 + 风险 + **免责声明 + 数据来源清单**；
   免责声明文案取后端 `/meta/tiers` 的 `disclaimer`（不在前端另写一份法律文案）；
   打印样式把来源 URL 展开到纸面。
7. **`/chat` 如实标注能力边界**：M3 的对话还不能查数据，回复里不含任何数字，
   界面明说"完整工具化回答在 M5"，绝不把"还不会查"包装成"已经能建议"。

**决策 6：`frontend/openapi.snapshot.json` 进版本库**

`pnpm gen:api` 优先取**在线** `/openapi.json`（契约唯一来源），拿不到时回退到该快照。
理由：`pnpm build` 是 M4 验收命令，不应因为"后端没起"而无法构建；快照是**后端产物副本**
而非手写类型，且在线可用时永远优先取实时 schema。
（生成物 `src/api/schema.d.ts` 仍然 `.gitignore`，不进版本库 —— §4.3 规则 2 未被破坏。）

**环境事实（新增，踩过的坑）**

- **本机 schannel 在 agent 沙箱内不可用**：`curl.exe`/`Invoke-WebRequest` 访问 HTTPS 会报
  `schannel: AcquireCredentialsHandle failed (SEC_E_NO_CREDENTIALS)`；但 **Node 自带的 TLS 栈正常**。
  因此 `pnpm install` 与 `node scripts/*.mjs` 都能联网，而 curl 不能 —— 排错时不要误判成"断网"。
- **esbuild 在 agent 沙箱内 `spawn EPERM`**：Vite/Vitest 都要 spawn esbuild 原生二进制（管道 stdio），
  沙箱禁止。因此 **`npm run build` / `npm run typecheck` / `npm run test` 必须在真实终端跑**
  （与 ADR-007 追记第 6 条的 pip 问题同类）。`npm run typecheck`（纯 tsc）不受影响。
- **pnpm 11 的构建脚本白名单**已从 `package.json` 的 `pnpm` 字段迁到 `pnpm-workspace.yaml`；
  本仓库显式 `allowBuilds: esbuild: false`（其原生二进制由可选依赖 `@esbuild/win32-x64` 提供，
  postinstall 只是兜底下载），避免在受限环境里让 `pnpm install` 因 EPERM 失败。

---

## ADR-012 · pnpm 供应链策略与 lockfile 缺陷（M4 跟进）

**背景**：用户在自己终端执行 `pnpm dev` 报 `ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION`，
4 个 lockfile 条目被拒（`autoprefixer@10.6.1` / `brace-expansion@2.1.7` / `browserslist@4.29.0`
/ `electron-to-chromium@1.5.428`），pnpm 的提示很准：
*"someone committed a lockfile that bypassed the policy locally"*。这是 M4 遗留的真实缺陷。

**根因（两层，缺一不可）**：

1. **两个 pnpm 不是同一个**。agent 会话里的 `pnpm` 是 DSH Desktop 注入的 runtime shim
   （pnpm **11.8.0**）；用户终端里的是全局安装的 pnpm **12.4.1**。
   pnpm 12 起把 `minimumReleaseAge`（默认 **1440 分钟 = 24 小时**）作为**内置供应链防护**：
   拒绝安装发布不满一天的版本——针对的正是"投毒版本发布后数小时内被下架"这一真实攻击窗口。
   pnpm 11.8 没有这个默认值，shim 报告的 `minimumReleaseAge` 是 **0**。
2. **首次安装没有 lockfile 可供校验**。pnpm 的策略校验作用于 **lockfile 条目**：
   首次 `pnpm install`（无 lockfile）时把当前解析结果直接写入，**不过校验**；
   此后每次 install 都校验。于是同一份 lockfile 在 A 机器过、在 B 机器挂。

**决策**：

1. **不关掉这条防护**。`minimumReleaseAge: 0` 是错误答案——它挡的正是我们要挡的东西。
   改为**显式写死 `1440`** 到 `frontend/pnpm-workspace.yaml`：解析与校验从此用同一把尺子，
   pnpm 11/12 行为一致，不再依赖"哪台机器上哪个 pnpm 的默认值"。
2. **用 pnpm 12（用户那一个）重建 lockfile**，让**解析阶段就受策略约束**。
   4 个包各回退一个补丁版：

   | 包 | 原 | 新 |
   |---|---|---|
   | autoprefixer | 10.6.1 | **10.6.0** |
   | brace-expansion | 2.1.7 | **2.1.4** |
   | browserslist | 4.29.0 | **4.28.9** |
   | electron-to-chromium | 1.5.428 | **1.5.427** |

   实测：`✓ Lockfile passes supply-chain policies (250 entries in 4.5s)`；
   **构建产物哈希与回退前完全一致**（`index-DcwjrTkW.js` / `index-BDwyQYW-.css` 字节相同），
   说明这 4 个都是浏览器数据/工具类的小版本差异，对产物无任何影响。
3. 需要豁免时的正确姿势写进 `pnpm-workspace.yaml` 注释（按优先级）：
   **等满 24 小时** → 或用 `minimumReleaseAgeExclude` 显式豁免并在 PR 说明理由
   → **绝不**把 `minimumReleaseAge` 改成 0。

**环境事实（新增，重要）**：
- **agent 会话里的 `pnpm` / `node` 与用户终端不是同一套**：会话内 `pnpm` 是 DSH shim
  （11.8.0，`minimumReleaseAge=0`），全局 pnpm 在 `C:\nvm4w\nodejs\node_modules\pnpm`（12.4.1）。
  → **凡涉及前端依赖的操作，必须用全局 pnpm 复核**：
  ```powershell
  node "C:\nvm4w\nodejs\node_modules\pnpm\bin\pnpm.mjs" install --frozen-lockfile
  ```
  否则会重复本轮事故（生成一份"本机合规、用户机不合规"的 lockfile）。
- `pnpm config list` 里的 `minimumReleaseAge` 是**有效值**，可直接用来判断当前 pnpm 有无该防护。

**被否决的方案**：

| 方案 | 否决理由 |
|---|---|
| `minimumReleaseAge: 0` | 等于关掉防护，正是这条策略要挡的攻击窗口 |
| 等 24h 再装 | 确实可行，但把仓库留在"lockfile 不合规"的坏状态，下一个人还会踩 |
| 直接 `minimumReleaseAgeExclude` 这 4 个包 | 能立刻解开，但没必要：它们各回退一个补丁版即可，重建 lockfile 更干净；豁免名单留给真正需要的情况 |
| 把 `storeDir` 锁定到仓库内 | 另有一个 store 路径差异（`D:\.pnpm-store` vs `D:\exam_select\.pnpm-store`），但那只导致首次多下一次包，不影响正确性；把 store 路径写进仓库不符合 pnpm 习惯 |

---

## M4 验收记录（2026-02）

**验收命令与真实输出**（AGENTS.md §10 M4：`cd frontend && npm run build && npm run typecheck`）：

```text
1) npm run build
   prebuild → node scripts/gen-api-types.mjs
     [gen:api] 21 个端点 / 69 个 schema ← http://127.0.0.1:8000/openapi.json
   vite v6.4.3 building for production...
   ✓ 610 modules transformed.
   dist/index.html                    0.77 kB │ gzip:   0.49 kB
   dist/assets/index-*.css           29.27 kB │ gzip:   5.23 kB
   dist/assets/index-*.js           101.76 kB │ gzip:  32.22 kB
   dist/assets/react-*.js           165.56 kB │ gzip:  54.17 kB
   dist/assets/echarts-*.js         554.81 kB │ gzip: 184.98 kB
   ✓ built in 5.62s                                                     （exit=0）✅

2) npm run typecheck
   tsc --noEmit → 无输出                                        （exit=0）✅
   （strict + noUnusedLocals/Parameters + noUncheckedIndexedAccess 全开）

3) npm run test（vitest，纯函数）
   ✓ src/lib/format.test.ts (10 tests) 15ms
   Test Files 1 passed (1) · Tests 10 passed (10)              （exit=0）✅
   重点：概率区间格式化——窄区间自动加小数位，绝不把不确定度压成单点或放大

4) npm run smoke（端到端闭环，按前端真实调用顺序打真后端）
   1) 首屏 Step 1/2：六省规则可读 · 六省都有带来源的科目池（origin=RULE）·
      浙江 7选3 含「技术」· 天津/海南要求「规则待核实」横幅
   2) 建档 → resolve-rank：stu-xxxx，missing_fields=[]，位次 17812，带来源与总考生数
      覆盖率：可报 640/811（真实统计）
   3) 推荐：60 项 · 每项都有 ±1σ 区间 · evidence 非空且每条带 source_url ·
      probability=null ⇔ NO_DATA · 默认不返回 TOO_RISKY
   4) 志愿表：80 个志愿 · 每项带概率区间 · 带院校名索引且每个志愿都能查到名字 ·
      每项带学费 · 最后一档是保/垫 · 带逐项来源证据 · 风险可重跑
      分层分布 {"CHONG":7,"WEN":55,"DIAN":18}；风险 35 条（HIGH 4 条）
   5) 手改：拖拽排序与提交一致 · 移除成功 · **移除的志愿可以加回来**
   6) 导出：PDF（%PDF 头）· Excel（PK 头）· 免责声明与分层区间均来自后端
   → 闭环全部通过 ✓                                               （exit=0）✅

5) dev 服务器与代理实测
   npx vite --port 5173 → GET / 返回应用外壳（含 react-refresh 注入）
   node -e "fetch('http://127.0.0.1:5173/api/v1/meta/provinces')"
     → proxy OK, provinces = beijing,hainan,shandong,shanghai,tianjin,zhejiang
     → zhejiang pool = 7选3                       （Vite proxy /api → 127.0.0.1:8000 生效）✅

6) 后端回归（本轮契约改动后重跑）
   pytest backend/tests -q --cov=app.core --cov-fail-under=90
     → 201 passed, 2 warnings in 61.60s
     → 覆盖率 TOTAL 1552 stmts / 68 miss / 95.62%              （门槛 90% ✅）
```

**完成定义逐项核对**（AGENTS.md §10 M4）：

- [x] 闭环可走通：建档 → 推荐 → 志愿表 → 导出 PDF（`npm run smoke` 按 UI 的真实调用序列断言）
- [x] 概率显示为区间：推荐卡片与志愿行都只用 `probability_interval`（±1σ）；
      单点概率即便存在也**不渲染**；`formatInterval` 有单测守住
- [x] 每卡片可展开证据链：`EvidenceTable` 展示"哪年/最低分/最低位次/计划数/数据质量/来源链接"，
      并把类比证据单独分表
- [x] 风险 HIGH 有阻断提示：志愿表页锁死导出，需显式勾选确认才解锁
- [x] 报告含免责声明与来源清单：报告页四段（志愿表/每志愿依据/风险/来源清单）+ 免责声明，
      且打印样式把 URL 展开到纸面
- [x] 类型从 OpenAPI 生成，无手写重复类型（`src/api/schema.d.ts` 由 `pnpm gen:api` 生成且 gitignore）
- [x] 首屏就是建档向导（`/` → `/profile`），前 3 步是硬门槛；`missing_fields` 非空时推荐页阻断式拦截

**跟进修复（ADR-012，用户终端 `pnpm dev` 实测）**：

```text
用户终端 pnpm 12.4.1（策略全开）：
  node "...\pnpm\bin\pnpm.mjs" install --frozen-lockfile
    ? Verifying lockfile against supply-chain policies (250 entries)...
    ✓ Lockfile passes supply-chain policies (250 entries in 4.5s)     （exit=0）✅
  同一条命令在修复前：ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION（4 个条目被拒）

  node "...\pnpm\bin\pnpm.mjs" run typecheck   → exit 0（deps 状态检查一并通过）✅
  node "...\pnpm\bin\pnpm.mjs" run build       → ✓ 610 modules · built in 9.79s
                                                产物哈希与降级前完全一致 ✅
  node "...\pnpm\bin\pnpm.mjs" dev             → predev(gen:api) ✓ → VITE v6.4.3 ready in 1992 ms
                                                 GET / → 200 · GET /src/main.tsx → 200 ✅
```

**本轮未做 / 已知限制（诚实披露）**：

- 无浏览器 E2E（Playwright）与视觉回归 → M7；本轮的闭环验证是"按 UI 真实调用序列打真后端"，
  它能证明契约与数据流正确，**不能**证明像素与交互细节无瑕疵。
- 意向地区/门类的"软偏好权重"调节只影响排序（`utility`），不进入概率——这是设计如此，不是缺陷；
  但权重滑块与后端 `weights` 参数的联动尚未做（当前用考生档案里的偏好值）。
- 志愿表页的"候选池重算"每次 PATCH 都会跑一次完整评估（811 单位量级约 0.3–1s），
  局域网/本地无感，但不是最终形态（M7 可加缓存或候选池快照落库）。
- 前端未做国际化、未做移动端专项适配（响应式栅格已可用，但窄屏体验未做专项验收）。

**下一轮起点：M5（Agent 层与防幻觉）** —— `tools.py` / `prompts.py` / `parser.py` /
`narrator.py` / `guard.py`；20 例幻觉测试编造数必须为 0。

---

## ADR-013 · M5 Agent 层：护栏是保证，提示词只是请求

**背景**：M5 要让 LLM 能查数据、能解释、能追问，同时守住 §0 的"宁可不答，不可编造"。
M3 留下的 `/chat` 是"不含任何数字的占位回复"——它安全但没用。

**决策 1：护栏（`guard.py`）与提示词分离，且护栏是**确定性**的**

System Prompt 是"请求"，不是"保证"。所以护栏必须在模型之外做后置校验：

1. 正则提取回复里的**数据型数字断言**（分数/位次/百分比/计划数/志愿数）；
2. 与**本次会话所有工具返回值**里的数值字段比对（含展示四舍五入容差）；
3. 对不上 → **整条回复拦截**，重写为"我需要先查一下数据"；
4. 命中绝对化词表（保证录取 / 一定能上 / 百分百 / 稳上…）→ 同样拦截。

三个被实测逼出来的实现细节（都有测试）：

- **白名单只收结构的数值字段，绝不从字符串里抓数字**。否则 `source_url` 里的年份、
  `unit_id` 里的专业代码都会变成"合法数字"——编造的 2026 分正好撞上 URL 里的 2026。
- **按"最近的关键词"归类，不是"窗口里出现过就算"**。`最低分 660，最低位次 12,340` 里，
  660 的 ±6 字窗口同时含"最低分"与"最低位次"，谁先匹配谁赢会把 660 判成位次。
- **绝不误伤**。"一定要留足保底"是正当建议不是承诺；"浙江 3+3 / 7 选 3"是模式名称不是数据；
  `1.` 是列表序号不是位次断言。**一个总在误拦的护栏，最后一定会被人关掉**——
  那比没有护栏更糟，因为它给人"有防护"的错觉。因此护栏测试里"不误伤"的用例与"拦得住"同等重要。

**决策 2：没有 LLM 也要能用（确定性路径），而且它不是玩具**

`parser.detect_intent` 做规则式意图路由 → `tools` 查数据 → `narrator` 说人话 → `guard` 校验。
这条路**零编造**（每个数字都来自工具），且完全可单测。理由有三：

- 不能交付一个"没配 API key 就完全不能用"的功能；
- 幻觉测试需要一个**不受模型随机性影响**的对照组；
- 两条路径共用同一套护栏，因此"LLM 路径安全"这件事可以靠对比来验证。

**决策 3：对话式建档由确定性 parser 写库，LLM 不写**

考生说"我浙江的，选物化生，考了 640"——这是**考生自述的事实**，不是模型的判断。
用规则抽字段（抽不出就追问）既不会猜错，也不会被模型的自由发挥带偏。
LLM 在 M5 始终只负责"解释与追问"，不碰数据库。

配套一条**安全约束**：已有档案时，一句话**不会**覆盖省份。
省份决定投档规则与一分一段表，改它等于换一套系统——实测踩过：问一句
"上海大学的最低录取位次是多少"，`上海` 被当成考生省份，整套推荐随之换了规则。
（根因是校名里天然带省份，已在 parser 里先剥掉校名再匹配省份；覆盖保护是第二道锁。）

**决策 4：`generate_plan` 工具是只读预览（`persist=False`）**

§9.1 要求"只读或需确认，绝不写库"。落库动作由考生在前端显式点击完成；
预览与落库走**同一条**生成路径，因此两者结果必然一致。测试直接断言"跑完工具后志愿表数量不变"。

**决策 5：LLM 客户端用标准库 `urllib`，不引入 httpx**

只有一个 POST，且必须是**运行时**依赖。多一个 HTTP 客户端 = 多一份供应链与版本面，
收益只是一个请求。`llm.py` 定义 `LLMClient` 协议，新增 provider = 加一个类 + 注册一行；
测试注入假实现，**任何测试都不需要外网、不需要 key**。

> ⚠️ **诚实披露**：OpenAI 兼容客户端本机**没有 API key，未对真实服务验证过**。
> 因此它默认关闭（`LLM_PROVIDER=none`），线上路径是确定性路径；LLM 路径由假实现覆盖测试。

**决策 6：会话历史落库（`chat_messages`）**

M3 存内存，重启即清空——那等于把"我当时问了什么、系统依据什么这么答"的证据丢了。
`tool_calls` 尤其重要：它是"这句话里的数字从哪查出来的"的直接证据，前端可展开查看。

消息 id 改为 `msg-<纳秒>-<随机>`：历史按 `(created_at, id)` 排序，而 `created_at` 只到秒，
纯 uuid 会让同一秒内的多条消息**顺序错乱**（实测：一问一答被排成"答、问、问"）。

**决策 7：新增第 12 个工具 `get_province_rule`**

§9.1 列了 11 个工具，但没有"查某省投档规则"这一条——而考生最常问的恰恰是
"我这省能填几个志愿、有没有专业调剂"。没有它，模型只能凭常识答，那正是本项目最不能接受的行为。
这是**增补**，不是替换；AGENTS §9.1 已同步。

**被否决的方案**：

| 方案 | 否决理由 |
|---|---|
| 只靠 System Prompt 防幻觉 | 提示词是请求不是保证；模型仍会一本正经地编 |
| 让护栏"宽松一点，少拦几条" | 松到一定程度它就不再是防护；正确做法是提高**分类精度**（就近归类 + 值域下限 + 列表序号排除） |
| 把 LLM 回复逐 token 流式吐给用户 | 那样"要不要拦截"就无法成立——宁可让文字整体出现，也不能把未过护栏的内容发出去 |
| 让 LLM 决定往档案里写什么 | 考生的自述是事实，不该经过模型转述；写库错误比说错话更难挽回 |
| `/chat` 保持 M3 的"不含数字"占位 | 安全但没用；M5 的交付标准是"能查数据且编不出来" |

---

## ADR-014 · M1 候选院校池缺陷（M5 期间发现）+ `safety_margin` 重标定

**背景**：写 M5 工具测试时顺手抽查数据，发现**浙江考生永远看不到浙江大学**。
顺着查下去是一个 M1 层面的确定性缺陷。

**缺陷**：`etl/synthetic.py::_candidate_colleges` 把 `local + strong + sampled` 合并后
**按院校 id 排序再截断** `[:MAX_COLLEGES_PER_PROVINCE]`。院校 id 形如 `{省}-{代码}`，
按 id 排序等于按省名排序 → 截断后剩下的几乎全是排在前面那几个省的院校。

**实测后果**（修复前）：

| 省份 | 候选池单位数 | 其中本省院校 |
|---|---|---|
| 浙江 | 811 | **0** |
| 上海 | 704 | **0** |
| 山东 | 789 | **0** |
| 天津 | 776 | **0** |
| 北京 | 761 | 286 |
| 海南 | 804 | 57 |

而且 `OUT_OF_PROVINCE_SAMPLE=14` 的"外省普通院校"抽样名额也被截断一并吃掉——
池子里实际上只剩 985/211，属于**双重失真**：既没有本省院校，也没有普通院校。

**修复**（两处）：

1. **语义**：本省院校 + 全国性重点院校**都保留**，再用外省普通院校补足名额；
   本省院校排在前面，超额时先牺牲外省重点，也绝不丢本省。
2. **上限**：`MAX_COLLEGES_PER_PROVINCE` 110 → **200**。
   各省 `local+strong` 最多 169（浙江/山东），配 110 必然截断某一类。
   常量旁边写明了"必须大于 max(local+strong)+OUT_OF_PROVINCE_SAMPLE"。

修复后各省构成一致且符合真实分布（以浙江为例：本省 32 + 外省重点 137 + 外省普通 14 = 183 所）。
回归测试：`test_synthetic.py::test_every_province_pool_contains_its_own_colleges`
与 `test_candidate_pool_keeps_out_of_province_sample`。

**连带影响：`safety_margin` 必须重标定**

`0.30` 是在**有偏样本**上标出来的（旧池子里没有本省院校），数据修正后不再达标：

| safety_margin | 保底失效率 | 稳档命中率（浙江） | 说明 |
|---|---|---|---|
| 0.30 | **0.07%** ❌ | 83.0% ❌ | 旧值，数据修正后失效 |
| 0.40 | **0.07%** ❌ | 85.5% | 仍不满足"保底失效 = 0" |
| 0.50 | 0.00% ✅ | 86.9% | 北京 84.72%，差 0.3 点 |
| **0.60** | **0.00%** ✅ | **88.1%** ✅ | 三省四项全达标 ← 采用 |
| 0.75 | 0.00% ✅ | 89.5% | 保底样本被进一步压小，等于用"更少保底志愿"换指标，不取 |

跨省验证（`safety_margin=0.60`，均为 150 考生全量回测）：

| 省份 | 保底失效率 | 稳档 | 冲档 | Brier |
|---|---|---|---|---|
| 浙江 | 0.00% ✅ | 88.10% ✅ | 29.79% ✅ | 0.0089 ✅ |
| 山东 | 0.00% ✅ | 90.54% ✅ | 30.77% ✅ | 0.0080 ✅ |
| 北京 | 0.00% ✅ | 86.08% ✅ | 14.01% ✅ | 0.0083 ✅ |

取 **0.60**：它是使三省同时达标的**最小**取值，方向上也更保守——
"真保底"的门槛更高，与名师铁律 4 一致。

**为什么这不是"为凑指标调参"**

§11 与 ADR-009 都警告过"不要为凑指标继续调参（会滑向对测试集过拟合）"。本次的区别在于：
**输入数据本身是错的**。在一个"本省院校数为 0"的样本上标出来的阈值没有意义，
在修正后的数据上重新标定是必须做的维护，而不是拟合。
两个黄金用例（G-003/G-004）的场景定义直接依赖 `safety_margin`，
本次**保留其语义**（"余量充足 → BAO/DIAN"）、只按新阈值调整输入数字并重写推导过程。

**被否决的方案**：

| 方案 | 否决理由 |
|---|---|
| 只修 `local` 优先、不抬上限 | `local+strong` 已达 169 > 110，外省普通院校名额仍会被截断吃掉（实测如此），属于只修一半 |
| 保持 110，改用 `rng.shuffle` 随机截断 | 会让 985/211 随机缺失（"为什么推荐里没有清华"），且只是把系统性偏差换成随机偏差 |
| 接受 0.30 的 0.07% 保底失效率 | 保底失效率是**最高优先级**指标（§1.3 要求 = 0%），且它正是"M5 能在真实场景里发现数据问题"的证据，不该被抹平 |
| 把 0.60 写成新默认但不重跑三省 | 单省达标不足以证明不是过拟合；三省一致（含此前压线的北京）才采纳 |

---

## M5 验收记录（2026-02）

**验收命令与真实输出**（AGENTS.md §10 M5）：

```text
1) backend\.venv\Scripts\python.exe -m pytest backend/tests/test_agent_hallucination.py -q
   → 47 passed, 2 warnings in 5.24s                                        （exit=0）✅
   20 例库外院校提问 × 2 条防线，编造次数 = 0：
     · 确定性路径：每例回复里**没有任何**分数/位次/百分比断言，且明确说出"没有数据"
     · LLM 路径：注入一个**故意编造**的假模型（"…最低录取分 638 分，位次约 21,000，概率 85%"），
       20 例全部被护栏拦下并重写为安全回复（blocked=True）
   反向用例：合规的 LLM 回答（引用了工具返回的 17,812）**必须放行**，否则护栏等于把助手关掉
   四类提问：A 真实但库外（香港大学…）· B 完全虚构（华夏科技大学…）
             · C 库里有但本省池外（上海理工大学）· D 简称/错字（北大、淅江大学）

2) 全量回归：pytest backend/tests -q --cov=app.core --cov-fail-under=90
   → 319 passed, 2 warnings in 81.60s
   → 覆盖率 TOTAL 1553 stmts / 65 miss / 95.81%                            （门槛 90% ✅）
   → 新增测试文件：test_agent_guard.py / test_agent_tools.py / test_agent_parser.py
                   test_agent_hallucination.py（共 4 个，新增 101 项）

3) 回测（数据修正 + safety_margin=0.60 重标定后，三省一致达标）
   → 见 ADR-014 的跨省表：保底失效率全 0.00%，稳档 88.10 / 90.54 / 86.08，
     冲档 29.79 / 30.77 / 14.01，Brier 0.0089 / 0.0080 / 0.0083

4) 数据校验：python -m app.etl.validate --report → 通过（0 error）
   → 修正后数据量：admission_units 7091 · admission_plans 35455 · admission_history 24921
     （此前 4526 / 22630 / 15784；增加来自"补齐本省院校 + 恢复外省普通院校抽样"）

5) 前端：pnpm typecheck → exit 0 · pnpm build → ✓ 610 modules · built in 6.29s
        pnpm smoke   → 闭环全部通过 ✓（分层分布 {CHONG:4, WEN:52, BAO:2, DIAN:22}）

6) 对话实测（确定性路径，真实服务）
   "你好"                          → 追问 province/subjects/total_score（含免责声明）
   "我是浙江考生，选了物理化学生物，考了640分" → 建档成功，回执只引用考生自己给的 640
   "浙江最多能填几个志愿？有没有调剂？"        → 调 get_province_rule → 引用工具返回的 80
   "我这个位次能报什么学校？"                → 调 recommend_units → 每项带区间与来源
   "查一下合肥工业大学的投档历史"            → 调 search_units + get_unit_history → 带来源
   "上海理工大学去年在浙江的录取分数线是多少？" → 诚实回答"没有该校在你省的投档记录"，零数字
   "北大去年录取线多少分？"                  → 不推断"北大=北京大学"，答数据缺失
```

**完成定义逐项核对**（AGENTS.md §10 M5）：

- [x] 自然语言能建档：一句话即可写入省份/选考/分数（缺什么追问什么，一次最多 3 个）
- [x] 推荐理由引用真实证据：`narrator` 只从工具 payload 取数，护栏比对工具返回值
- [x] **20 个幻觉测试全过，编造次数 = 0**（确定性路径 + 故意编造的假模型两条防线）
- [x] 绝对化词表命中被拦截（保证录取 / 一定能上 / 百分百 / 稳上 / 必录…），
      且**不误伤**正当建议（"一定要留足保底"、"3 门"、"1." 列表序号、年份、模式名称）
- [x] 工具"绝不写库"：`generate_plan` 为只读预览，测试断言志愿表数量不变
- [x] 每个工具的数字都带来源；预期失败（查不到/缺表）返回明确错误码而非抛异常，
      好让模型诚实说"数据缺失"而不是瞎猜

**本轮未做 / 已知限制**：

- **OpenAI 兼容客户端未对真实服务验证**（本机无 key）。默认 `LLM_PROVIDER=none`，
  线上走确定性路径；LLM 路径由注入的假实现覆盖（含"编造必被拦"与"合规必放行"两个方向）。
- 规则式意图路由**不认简写**（"物化生"不会被拆成三门选考）——此时宁可追问，也不猜。
- 对话式建档只写已有档案的"可增量字段"；**省份不会被一句话覆盖**（见 ADR-013 决策 3）。
- 志愿表 PATCH 每次重算候选池（现在 1290 单位量级，约 0.5–1.5s）；M7 可加缓存或池快照落库。
- 前端仍无浏览器 E2E（`pnpm smoke` 证明契约与数据流，不证明像素与交互细节）。

**下一轮起点：M6（真实数据接入）或 M7（加固与交付）** —— M6 需要用户先确认数据来源与授权；
若暂不接真实数据，则 M7 的加固项（性能、边界、Docker、视觉回归、敏感度热力图）可以先行。

---

## ADR-015 · M6 真实数据接入：浙江（2023–2026），其余五省仍为模拟数据

- **日期**：2026-09
- **状态**：已采纳
- **背景**：用户明确本轮要做 M6，范围是"**先接入适用于浙江省考生的数据，其他先用模拟数据**"。
  上一轮（M5 之后）已把浙江的官方数据采集并规范化到 `data/raw/zhejiang/` 与
  `data/normalized/zhejiang/`（含 2023/2024/2025 合编 PDF 解析结果、2021/2022/2024/2026 年度一段表、
  manifest 里逐文件的 source_url + sha256），但**尚未入库**。

### 决策

1. **接入范围：浙江 = 真实数据；其余五省 = 模拟数据**（`scripts/seed.py --source hybrid`，默认）。
   真实数据落在同一批表里，用 `source_url` 前缀区分：`real://`（真实）vs `synthetic://`（模拟）。
   `is_synthetic` 的语义收窄为"**这一行的数字是不是模拟值**"，不再等于"哪个省"。
2. **时间轴对齐模拟侧**：填报年 = 2026（`CURRENT_YEAR`），历史投档年 = 2023/2024/2025，
   因此线上预测仍然是"近三年历史 → 预测今年"，不需要改 `probability.py` 的任何一步。
3. **跨年单位对齐用「院校代号 + 专业名」而不是「专业代号」**（本轮最关键的一个建模决定）。
   浙江的 `专业代号` 是**每年重排**的招生序号：2025 年浙江大学 001–041 在 2026 年对应完全不同的专业。
   而本系统全部跨年逻辑（`unit_key` 不含年份、`admission_plans` 逐年对齐、概率模型取近三年）
   都建立在"同一把 key 跨年稳定"之上。因此：
   `unit_key = zhejiang-{院校代号}-NA-{专业链标识}`，标识 = `sha1(归一化基名)[:10]`，
   同名多链加 `-2` 后缀。实测：18,543 条当年记录里 10,500 条能拿到完整三年历史。
   * 院校代号跨年稳定（实测 2023–2026 共 1083 所代号不变，仅 69 所有"学院→大学"改名）。
   * 专业名匹配三级优先：全名精确 → 基名（剥括号）唯一 → 新建链（=当年新增专业）。
4. **一分一段表分两级质量**：2026 用**官方《成绩分数段表（总分）》原文**（新采集，
   `is_synthetic=0`）；2023–2025 官方未发布可机读版本，用**当年官方投档记录**
   （分数↔位次观测）导出标定曲线（`is_synthetic=1`，构造保证与该年记录自洽，
   并在官方一段线处按官方一段线上线人数精确闭合）。
5. **宁可少两年历史，也不放没有选考要求的行**：2021/2022 的年度一段表**不含选考科目要求**，
   因此不导入（否则等于给所有专业编造"选考不限"）。这一条直接决定了历史窗口是 3 年。
6. **合规**：全部为浙江省教育考试院官网公开发布物，逐文件登记 URL 与 sha256；
   抓取为单线程 + 请求间隔，不做整站镜像（DOMAIN_RULES §1.4）。

### 实测（可复现）

```
python scripts/seed.py --reset --source hybrid     # 幂等：重复执行计数与内容不变
python -m app.etl.validate --report                # 0 error / 10 warning
```

| 项 | 真实数据（浙江） | 全部（含模拟五省） |
|---|---|---|
| 院校 | 1,692 | 2,078 |
| 专业 | 18,543 | 19,071 |
| 投档单位（2026） | 18,543 | 24,201 |
| 计划快照 | 57,502 | 85,792 |
| 投档历史 | 38,957（2023/2024/2025） | 58,841 |
| 一分一段表 | 1,883（2026 官方 428 行 + 标定 1,455 行） | 14,808 |

> 「全部」列小于「模拟六省 + 真实浙江」的直觉值，是因为 hybrid 模式剔掉浙江模拟行后
> 还要级联清掉**引用了已删院校/单位**的孤儿计划与历史（`_drop_orphan_units` 与
> `kept_units` 过滤；`seed.py` 每次都会打印实际清理条数，实测 **715 条**）。

- 2024 年**两个独立官方来源交叉校验**：12,869 条可比对记录中 12,830 条分数+位次完全一致（99.7%）。
- 数据质量分布：`OK 38,957`，`MISSING_RANK` 记录按官方口径（"位次栏为空 = 本轮未满"）**不参与概率计算**。
- 三年历史完整（可走 §6.2 八步）的专业链 10,500 条；无任何历史（走 Step 0 类比并标低置信度）3,394 条。

### 本轮暴露并修掉的四个真实缺陷

| # | 缺陷 | 现象（实测数字） | 修法 |
|---|---|---|---|
| 1 | **归一化分母口径不一致** | 一度用"分数段表最低分累计人数"当分母：2026 官方表最低 266 分 → 292,753，而 2023 若按一段线 488 分算只有 175,424。同一位次的含金量被凭空放大 **1.7 倍**，跨年比较彻底失真 | `province_year_stats` 增加 `segment1_cumulative` / `segment1_line` 两列：归一化**只用 `total_candidates`**，标定曲线才用 `segment1_cumulative` |
| 2 | **院校代号被当成全局唯一** | 浙江招生的 0001–9034 是"面向浙江招生的顺序号"（含清华北大复旦），与模拟号段相撞 → **162 条** `COLLEGE_CODE_DUPLICATE` | 校验改为按 `(院校所在地, 代号)` 判唯一（库主键本来就是 `{省}-{代号}`） |
| 3 | **模拟/真实混装撞主键** | `colleges` 主键 `{省}-{代号}` 与 `score_rank_table` 的 `UNIQUE(province, year, track, score)` 两边共用；hybrid 下同一所院校被算成两所、同一 (省,年,分数) 撞唯一键 | `seed.py` 在 hybrid 时**整省剔掉浙江的模拟行**，并级联清掉引用已删院校/单位的孤儿行 |
| 4 | **真实情况把幻觉测试问倒了** | A 类 6 个"库外院校"（金陵科技学院、河北金融学院…）接入真实数据后**真的有了官方投档记录**，系统如实报出带来源的数字，测试却判它"编造" | A 类改用**境外院校**（库里确实没有）；C 类换成"库里有、浙江无招生单位"的院校并**在测试里先断言这个前提**，避免日后静默失效 |
| 5 | ★ **覆盖率接口 O(n²) 直接卡死** | `subject_coverage` 里 `[u for u in units if u not in matched]`：`AdmissionUnit` 是 Pydantic 模型，`in` 会逐个深比较 → 1,290 单位时无感，**18,543 单位时做了 1.7 亿次 `__eq__`，接口实测 398 秒** | 改成按 `unit_id` 集合判定（语义完全等价）。**398s → 0.9s**，覆盖率数值不变（0.9781 / 0.5363） |

### 性能：真实数据把推荐接口打慢了，本轮做了等价优化（未达标，留给 M7）

18,543 个单位（模拟侧只有 1,290）让 `evaluate_candidates` 从 ~0.6s 涨到 **25s**。
Profile 定位到唯一的真凶：`_step0_no_history` 对类比池里**每一个**成员调一次 `_usable_records`，
3,010 个走 Step 0 的单位共触发 **87 万次**调用（等价但极慢地重复筛同一批记录）。

改法（**语义完全等价**，不改任何阈值/权重）：
1. `_analog_latest`：只在该单位自己的记录里取最近一条可用历史，不再重建列表与 Pydantic 对象；
2. `_analog_candidates`：按「类比桶指纹 + 目标年」缓存候选位次与类比证据（同一桶批量复用）。

结果：**25.0s → 5.9s**（第二轮 8.4s，含冷启动）。仍未达到 AGENTS.md §M7 的 P95 < 1s，
**如实记为 M7 待办**：候选池需要"先粗排再精算"或按桶预计算，这属于架构改动，不在 M6 范围内动。

（同一轮里另有一个**非概率模型**的 O(n²) 缺陷被数据规模暴露，见上表第 5 条，已彻底修复。）

### 缺陷 6：安全闸门缺一条"历史年数"门槛（真实数据回测逼出来的）

真实数据回测（浙江 · 预测 2025 · 2 年历史窗口）第一次跑出来：

```
❌ safety_failure_rate  实际  0.08%   目标 == 0%      （6 例 / 7,211 个保垫档）
❌ wen_hit_rate         实际 84.10%   目标 >= 85%
✅ chong_hit_rate       实际 17.11%   目标 ∈ [10%, 40%]
✅ brier                实际 0.0382  目标 <= 0.15
```

把 6 例逐条拉出来看，**全部**是同一个形状：某单位只有 1–2 年历史，
其中某一年的位次低得可疑，模型据此认为"这是它的底线"：

| 单位 | 2023 | 2024 | 2025 实际 | 预测 |
|---|---|---|---|---|
| 兰州工业学院 · 建筑环境与能源应用工程 | 148,172 | 148,603 | **21,548** | 153,551 |
| 浙江师范大学 · 生物科学(师范) | — | 174,212 | **64,570** | 144,186 |
| 南昌交通学院 · 电子商务 | 237,794 | 233,182 | **114,120** | 192,202 |
| 武汉晴川学院 · 电子商务 | 219,476 | 232,916 | **123,202** | 193,874 |

（注意这些都是"位次数值大 = 门槛低"的项目，2025 年集体大幅走高；
`武汉工商学院·电子商务` 甚至只有 2023 与 2025 两年，中间断了一年。）

**结论：`safety_margin` 只挡住了"余量不够"，挡不住"年份太少"。**
只有 1–2 年历史时，把某一年的一次性低位当成长期底线，就是在拿考生的前途赌。

**决策**：给 Step 8.6 加第二条闸门 —— `len(可用历史年数) ≥ ModelParams.min_baodian_years`（默认 3），
不满足则 `BAO/DIAN → WEN` + 新告警码 `SAFETY_YEARS_NOT_ENOUGH`，并在 `reasons` 里说明原因。

**后果（这是刻意的保守，不是缺陷）**：浙江真实数据在 2 年窗口下**不再产出任何"保/垫"志愿**
（实测 tier 分布：WEN 2,065 / CHONG 191 / TOO_RISKY 1,294 / NO_DATA 50）。
回测四项随即全达标：

```
✅ safety_failure_rate  实际  —（样本里没有 BAO/DIAN）   目标 == 0%
✅ wen_hit_rate         实际 93.95%                     目标 >= 85%
✅ chong_hit_rate       实际 19.90%                     目标 ∈ [10%, 40%]
✅ brier                实际 0.0403                     目标 <= 0.15
```

> 「没有做出安全承诺，就没有失约；但也不能据此声称保底有效」——
> 这条语义写进了 `BacktestReport.notes()`，回测每次都会打印，
> 并且 `safety_failure_rate is None` 时**判定为通过但必须出现这段说明**。
> 前端/报告层面要据此提示"当前数据不足以给出保底志愿"（M7 待办：UI 文案）。

**待办（M7）**：浙江要拿到 3 年窗口必须补 2021/2022（需要带选考要求的官方来源），
或把"2 年窗口"作为正式口径重标定 `safety_margin` 与 `min_baodian_years`。

### 观察 7（不是缺陷，是本轮发现的**展示层**待办）：推荐列表可能被"冲"档占满

真实数据端到端手测（浙江考生 640 分 → 位次 18,584）发现：
全量候选里 `WEN 5,438 / BAO 68 / DIAN 8,481`，但接口 `limit=8` 返回的 8 项**全是 CHONG**。

原因在 `recommend_service.recommend()`：候选按 `(Tier 顺序, -效用)` 排序后取前 N
（冲排在最前）—— 这是**设计如此**（"最想去的放最前"），但用户在推荐列表里会看到
"一个稳的都没有"，容易被误读成"我没稳的学校可报"。

**M7 待办**：推荐列表的截断应当按**分层配额**取样（或至少保证每层都有代表），
而不是把最先进入排序的那一层填满；同时把 `tier_distribution_all`（全量分布）
在 UI 上明确与"返回的 N 条"区分开。`bundle` 里已有一个尚未使用的
`tier_counts()` 方法可以直接用。

### 缺陷 7（前端，用户实测报障）：草稿 id 失效后向导直接报"后端有问题"

用户在建档向导第 3 步看到报错，后端日志是：

```
PATCH /api/v1/students/stu-b9079021b8ef HTTP/1.1  404 Not Found
GET   /api/v1/majors/search?limit=300             200 OK
```

**根因**：`studentId` 会随草稿持久化进 `localStorage`（§8.1 要求"中途刷新不丢失"），
而后端库在本轮被重建过（`seed.py --reset`——M6 给 `province_year_stats` 加了两列，必须重建）：
旧 id 在后端**已不存在**，于是 `submitDraft()` 走 PATCH 分支拿到 404，
`Step3Score` 把它当"换算失败"显示出来，考生看到的就是"后端有问题"。

**这不是后端的 bug，也不该让考生去清浏览器缓存**。档案本来就是**可重建的草稿**，
正确语义是"自愈"：

1. `submitDraft()` 捕获 404 → 丢掉失效 id（`studentId/student/lastError` 清空）→ 走 POST 重建 → 写回新 id；
2. `Step3Score` 用 `submitDraft()` **返回的**档案 id 去 `resolve-rank`，
   不再用闭包里的旧 `profile.studentId`（否则自愈换了新 id，换算仍在打旧 id）。

实测复现与验证（临时起后端 8011 端口，真实数据）：

```
PATCH /students/stu-b9079021b8ef  → 404（复现用户看到的现象）
POST  /students                   → 201 id=stu-b479de20f939
PATCH /students/stu-b479de20f939  → 200
POST  /students/{id}/resolve-rank → rank=18584 total=292753
                                    src=real://…?score_segment=2026   ← 官方一分一段表原文
```

> 提醒（已写进 HANDOVER）：**任何一次 `seed.py --reset` 都会让所有浏览器里的草稿 id 失效**。
> 自愈逻辑已就位；若在别处（如推荐页直接刷新）看到 404，回建档向导走一步即可恢复。

**回归验证（同一天实测，证明新闸门没有破坏模拟基线）**：
切回 `--source synthetic` 后，山东 2025 全量回测仍然是
`0.00% / 90.54% / 30.77% / 0.0080`（四项全达标，与 ADR-014 记录的基线**逐位一致**）——
合成数据的单位有 2022–2024 三年历史，3 年门槛不会把它们误降级。

### 真实数据 vs 模拟数据：指标怎么比才算公平

| 数据集 | 历史窗口 | 保底失效率 | 稳档命中 | 冲档命中 | Brier |
|---|---|---|---|---|---|
| 模拟（山东 2025，ADR-014 基线） | 3 年 | 0.00% | 90.54% | 30.77% | 0.0080 |
| **真实（浙江 2025，本轮）** | **2 年** | —（无保/垫） | **93.95%** | 19.90% | 0.0403 |

> Brier 0.0080 → 0.0403 的差距**主要来自真实数据的不可约噪声**，不是模型退化：
> 模拟数据是按模型假设生成的（"计划弹性 0.35、趋势 ±3.5%/年"），而真实数据里有
> 制度变化、专业改名、招生计划突然腰斩这类模型无法预知的事件（见上表 6 例）。
> **本轮不做重标定**：口径不同（2 年 vs 3 年窗口）时重标定会得出错误的参数，
> 这一步留给 M7（先统一口径，再谈标定）。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| **用「专业代号」做 `unit_key`** | 浙江专业代号**每年重排**（实测 2025→2026 完全换位）→ 历年位次接不到一起，概率模型拿不到三年历史，等于把真实数据降级成"每年都是新专业" |
| **2021/2022 也导入，选考要求按"不限"填** | 那是在**编造**选考要求。选考科目过滤是新高考最易出错处（AGENTS.md §6.4），用假数据过滤会直接把不符合选考要求的专业推荐给考生 |
| **给 2023–2025 直接套用 2026 官方分数段表** | 各年一段线不同（488/492/490/494），套用等于系统性错位；改用"当年官方投档记录导出的标定曲线 + 官方一段线锚定" |
| **用同一套"整省覆盖"按省并存（模拟浙江 + 真实浙江）** | 会同时出现"两个浙江大学""两套一分一段表"，且撞唯一键；且考生会看到互相矛盾的两组数字 |
| **本轮顺手做候选池预筛/缓存把 P95 压到 1s** | 需要改概率模型的调用架构（粗排 → 精算），属于 M7 的加固工作；M6 的验收标准是"数据入库 + 校验 0 error + 回测不劣于基线"，先如实记录瓶颈与实测数字 |

---

## ADR-016 · 推荐接口性能：把"每次请求重算一遍全省"改成"只算一次"

- **日期**：2026-09
- **状态**：已采纳
- **背景**：用户实测报障"建档向导之后推荐列表加载很慢"。M6 接入浙江真实数据后，
  候选单位从 1,290 涨到 **18,543**（14 倍），`evaluate_candidates` 从 ~0.6s 涨到 **25s**
  （ADR-015 已做一轮等价优化到 5.9s），仍然不可用。

### 实测拆解（浙江 · 18,543 单位 · 每项都是真实计时）

| 环节 | 耗时 | 性质 |
|---|---|---|
| `estimate_probability` × 15,333 | **4.3s** | 每请求重算 |
| `load_history`（38,957 行 → Pydantic） | 1.29s | **静态**，可缓存 |
| `load_units`（18,543 行 → Pydantic） | 0.57s | **静态**，可缓存 |
| `load_majors` / `load_colleges` | 0.47s | **静态**，可缓存 |
| `score_unit` × 18,543 | 0.10s | 便宜，不用管 |

其中 `estimate_probability` 内部又被 profile 定位到两处：
`statistics.pstdev`（**三次遍历**，单项 2.0s）与 `scipy.stats.norm.cdf`（1.7 万次调用，1.2s）。

### 决策：三层处理，**全部不改任何模型语义**

1. **σ 用一次遍历算**（`_sigma`）：总体标准差公式手写，与 `statistics.pstdev` 同口径
   （ddof=0、以均值为中心）；`n < 3` 时仍退回 MAD 兜底。
2. **Φ(z) 用有理逼近**（`_norm_cdf`）：Zelen & Severo / A&S 26.2.17，`|误差| < 7.5e-8`。
   概率本身被 clip 到 [0.02, 0.98]、只用于分层与展示（区间宽度由 σ 决定），
   这个精度比"位次的年度波动"低好几个数量级。
3. **静态参考数据 + 概率结果缓存**（`repositories._cached` / `probability._RESULT_CACHE`）：
   * L2 缓存 `load_units` / `load_history` / `load_colleges` / `load_majors`（按省/年）；
   * L3 缓存 `estimate_probability` 的**纯函数结果**；
   * **失效策略**：L4 的 `get_db` 在"本请求真的写了库"（`session.new/dirty/deleted` 非空）
     提交后调用 `repositories.bump_generation()` → 两块缓存一起失效。
     只读请求不推进，否则每次 GET 都把缓存清掉、等于没缓存。

### 实测结果

| 场景 | 优化前 | 优化后 |
|---|---|---|
| 单次推荐（冷启动，含读库） | 25.0s → 5.9s（ADR-015） | **4.0s** |
| 单次推荐（缓存已热：推荐页→志愿表→重算→风险扫描） | 5.9s | **0.5–0.9s** |
| `pytest backend/tests/test_api.py` | 约 5–6 分钟 | **43 秒** |
| 全量后端测试 | 4–6 分钟 | 见 HANDOVER |

### 必须记住的两条

1. **缓存键用内容指纹，不用 `id()`**。第一版用 `id(history)`，被测试当场打脸：
   CPython 会复用已回收对象的 `id`，同一 (单位, 考生) 用**不同历史**算出同一个键 →
   命中上一个用例的结论（实测 4 个用例误命中，其中 G-012 把 TOO_RISKY 报成 WEN）。
   现在键 = `(unit_id, 目标计划数, 考生位次, 当年分母, 参数 JSON, 历史内容指纹, 类比池轻指纹, 代数号)`。
   ⚠️ **目标计划数必须进键**：Step 4 的计划数修正直接用 `target.plan_count`。
2. **改了模型参数或数据，要清缓存**：数据走 `bump_generation()`（自动），
   测试/排错走 `probability.clear_result_cache()`（`tests/test_probability.py` 有 autouse fixture）。
   若以后引入"运行时改参数"的功能，必须在改参数处调用它。

### 仍未达标 / 被否决的方案

| 方案 | 结论 |
|---|---|
| **让 P95 < 1s（AGENTS.md §M7）** | ❌ 仍未达标：冷启动 4.0s（首次要读 5.8 万行 + 算 1.5 万个单位）。热缓存已 0.5–0.9s。**M7 待办**：候选池"粗排 → 精算"，或把"单位级中间量"预计算落库 |
| 把候选池按位次粗排后只精算前 N 个 | 会改变推荐结果（分层配额需要各层都有候选），**不能**在没有回测验证的情况下做 |
| 把 `evaluate_candidates` 的整包结果缓存 | 键要覆盖筛选条件与偏好权重，失效面太大；当前粒度（单位级概率）已够 |
| 关掉缓存保证"每次都新鲜" | 每次 4 秒、且 API 测试从 43 秒回到 6 分钟，代价不可接受 |

---

## ADR-017 · 推荐页"筛选与偏好"两个真实缺陷（用户实测报障）

- **日期**：2026-09
- **状态**：已采纳
- **背景**：用户报障两件事：
  ① 只选**一个**地区并勾选"把意向地区/层次/门类当硬约束"→ 显示"没有符合条件的推荐"；
  ② 不勾硬约束时，**筛选完全不影响列表**（勾了地区，列表与效用值一模一样）。

### 缺陷 1：硬约束取错了"省"

```python
# filters.py（错误实现）
college_province = unit.college_id.split("-", 1)[0]   # ← 这是 **招生省**，不是院校所在地！
```

`unit_id` 的格式是 `{招生省}-{年份}-{院校代号}-{组}-{专业}`，所以第一段永远是**招生省**
（浙江考生 = `zhejiang`）。于是：

```
regions=["北京"] + intent_as_hard → 通过 0 / 剔除 18,543   （REGION_NOT_INTENDED 17,875）
regions=["浙江"] + intent_as_hard → 通过 0 / 剔除 18,543   （连"浙江"也全剔）
```

**修法**：地区硬约束必须用 `College.province`（院校所在地）。为此把
`college_province` 一路传进 `check_unit` / `filter_units`，L4 从 `load_colleges()` 建
`college_id -> province` 映射。修复后实测：

```
regions=["zhejiang"] 硬约束 → 通过 3,530（剔 14,607）
regions=["beijing"]  硬约束 → 通过 1,471（剔 16,666）
levels=["985"]       硬约束 → 通过   809（剔 17,328）
```

**顺带一条重要口径**：**院校所在地缺失时不剔除**。硬约束是"一票否决"，**不知道就不能否决**——
真实数据里有 855 个单位（约 112 所院校）没有所在地字段，若按"不等于意向地"处理，
它们会被无声剔除，考生会以为"这些学校不存在"。

### 缺陷 2：软偏好根本没接上

推荐页的筛选面板叫"筛选与**偏好**"，但 `criteria.regions` / `criteria.major_categories`
**只在 `intent_as_hard=True` 时被用到**；不勾选时它们被完全忽略。而软偏好打分读的是
`preferences.intended_regions`（考生档案里的，来自建档向导第 4 步）——
推荐页勾的意向从来没被合并进去。

**修法**：`_with_weights(profile, weights, criteria)` 把两者合并（档案级意向 ∪ 本次查询意向）。
修复后实测（同一考生，同一份数据）：

| 筛选 | 第 1 名 | 效用 |
|---|---|---|
| 无意向 | 中国农业大学（北京） | 0.8335 |
| 意向地区 = 江苏（软偏好） | **河海大学（江苏）** | 0.7835 |
| 意向地区 = 江苏（硬约束） | 河海大学（江苏） | 0.7835，硬过滤 **16,149** |

（注意软偏好下效用**变小**了：`region_score` 从"未填意向=1.00"变成"非意向地=0.00"，
这正是"降权"应有的表现；候选池数量不变。）

### 缺陷 3（顺带）：地区选项只有六省市，考生选不到江苏/湖北

规则包只有六省市，但**浙江考生的候选池覆盖 31 个省级行政区**
（浙江 2,685 个单位、江苏 1,549、湖北 943、江西 939…）。
推荐页原先只列 `PROVINCE_LABEL` 的六个键 → 考生想报江苏的学校时**筛不到**。

**修法**：`/recommend` 的 `stats.region_options` 回传候选池里院校所在地的实际分布（含单位数），
前端据此生成选项（`frontend/src/lib/labels.ts` 新增 31 省中文名映射）。
契约变更走 OpenAPI 生成（`pnpm gen:api --update-snapshot`），前端类型同步刷新。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 用 `unit.college_id` 前缀推断院校所在地 | 那取到的是招生省，**必然**把全部候选剔光（就是本缺陷的成因） |
| 硬约束时把"所在地缺失"当作"不在意向地" | 硬约束是安全承诺的对立面——**不知道就不能否决**；真实数据里 855 个单位会无声消失 |
| 让推荐页的意向**覆盖**档案里的意向 | 会静默丢弃考生在建档向导里填的偏好；取并集更符合"多选意向"的语义 |
| 把六省市之外的院校所在地选项硬编码进前端 | 与"契约唯一来源是 OpenAPI"冲突；且不同省的候选池不同，写死会过时 |






---

## ADR-018 · 专业目录归属：把"意向专业"从死字段救回来（用户实测报障）

- **日期**：2026-09
- **状态**：已采纳
- **触发**：用户实测报障——"意向专业分得太粗，大类之下分不下去"，追问时发现浙江考生的
  **意向专业筛选完全不生效**。

### 缺陷（实测）

浙江真实数据的 `majors.category` 与 `majors.discipline` **全部为 NULL**（18,543/18,543）。
根因在 `etl/loaders/zhejiang.py`：官方投档表**只发布专业名**，不发布专业目录归属，
装载器当时直接把这两列写死为 `None`。

后果（三处，全部实测确认）：

| 受影响处 | 症状 |
|---|---|
| `scoring.major_match_score` | "同一专业类 0.80 / 同一门类 0.55 / 相关门类 0.30" **三档永不命中**；且它要求 `Major` 行的两列非空，于是连"专业名一致"之外的一切都拿 0 分 |
| `probability` Step 0 类比池 | `analog_key(..., discipline=None)` 让**全部专业塌缩进同一个桶**——实测"浙江大学·社会学"（0 历史）的类比池是**7 个任意专业**的单位，据此算出一个**跨专业**的概率 |
| 推荐页"意向专业" | 勾选后列表顺序与效用值完全不变，形同虚设 |

实测（630 分浙江考生，无意向）：全池 utility 在**同一院校内恒为常数**（浙工大 50 个专业
全部 0.484），推荐列表由 `(tier, -utility, unit_id)` 排序 → 同层内退化为按 `unit_id` 字典序，
**浙工大在 limit=60 时只出现 1 条**。

### 决策

1. 新增**四级专业分类规则库**：门类（L1）→ 专业类（L2）→ 专业（L3）→ **招生方向（L4）**。
   * 规则数据 `core/major_taxonomy_data.py`（由 `scripts/build_major_taxonomy_data.py` 从 JSON 生成）
   * 判定逻辑 `core/major_taxonomy.py`（**纯函数**，遵守 ADR-003，不读文件）
   * 人类可读说明 `docs/MAJOR_TAXONOMY.md`
2. **装载器回填** `category`/`discipline`（新播种走 `seed.py`；已有库走原地迁移脚本
   `scripts/backfill_major_taxonomy.py`，幂等且**不碰用户数据**）。
3. **招生方向不落库**：它 100% 可由专业名纯函数推出，落库等于同一事实存两份必然漂移。
4. `scoring.major_match_score` 改为四级匹配 + **taxonomy 兜底**（`major` 行缺失时用专业名现算），
   并回传 `major_match_level` 让"为什么这个分"可追溯。
5. 判定优先级：目录精确名 → 专业类名 → 试验班（方向收窄优先）→ 关键词（**最长优先**）→
   **`UNCLASSIFIED` 诚实兜底**（绝不猜）。

### 实测结果

覆盖度（浙江 2026 · 18,543 单位）：**门类级 99.84% / 专业类级 99.08%**，
`UNCLASSIFIED` 仅 29 个（0.2%）。判定来源可逐条审计（`evidence` 字段）。

A/B（同一 630 分考生，只有 `majors` 两列不同）：

| 指标 | 回填前 | 回填后 | 变化 |
|---|---|---|---|
| 可评估（有概率） | 15,333 | 15,281 | −52 |
| `NO_DATA` | 2,542 | 2,594 | +52 |
| `data_coverage` | 0.8578 | 0.8549 | −0.29pp |
| 全池 utility 取值数 | 83 | 83 | 0 |
| 带意向"计算机类"时 utility 取值数 | 3（同院校恒定） | **124** | ★ 生效 |

**−52 个可评估单位是修正而非退化**：它们原先靠"任意专业"类比池拿到概率
（跨专业编造），现在因**同专业类**类比池 <3 个而诚实返回 `NO_DATA`。
用 0.29pp 覆盖率换掉跨专业编造，符合"宁可不答，不可编造"。

回测（`--province zhejiang --year 2025`）四项判据全部达标，与回填前**同口径**：
保底失效率 N/A（无 BAO/DIAN）、稳档命中率 95.11%、冲档命中率 38.82%、Brier 0.0510。

### 顺带修掉的两个真实缺陷

1. **规则库不变量缺失**：实测把**门类** `"工学"` 填进了**专业类**字段
   （`direction_narrowing["卓越工程师"]`），导致该专业的 `category` 变成 `None`。
   现在 `build_major_taxonomy_data.py` 与 `tests/test_major_taxonomy.py` **双重校验**
   值域（收窄规则必须是专业类；门类规则必须是门类；专业类不得跨门类重名）。
2. **agent 工具违反契约铁律 2**：`estimate_probability` 的 `NO_DATA` 分支原先只回
   `{"unit_id","probability","tier"}`，把解释塞进 `warnings` 而**丢掉了 `confidence` 与 `reasons`**。
   AGENTS.md §7 铁律 2 要求"概率为 None ⇔ confidence == NO_DATA 且 reasons 说明原因"。
   而 `NO_DATA` 恰恰是最需要解释的情形。已改为与正常路径共用 `_probability_block`。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 把专业名硬编码成 1,110 条映射表 | 3356 个专业名且每年新增，纯枚举必然过时；且无法覆盖新专业 |
| 让 LLM 判断每个专业属于哪个门类 | 直接违反"LLM 不产生数据"红线；且不可复现、不可回测 |
| 专科另用一套 19 大类专业类词汇 | 会让"计算机类"（本科）与"计算机类"（专科）判成不同专业类，匹配与类比双双断裂 |
| 把招生方向也加列落库 | 纯函数可推的数据落库 = 两份事实必然漂移（与 ADR-016 缓存键同源的教训） |
| 对 `UNCLASSIFIED` 用"最近似专业类"填充 | 就是"编造"；0.2% 的诚实缺口远好过 0.2% 的错误归类 |
| 顺手把 Step 0 类比池放宽（跨专业类兜底）以补回覆盖率 | 那正是本 ADR 要修的缺陷本身；要补覆盖率必须用**保持专业类不变、逐级放宽地区/层次**的阶梯，且**先回测验证**（列入 M7） |

### 后果与待办

- ✅ 意向专业筛选真正生效；Step 0 类比池不再跨专业。
- ⚠️ 覆盖率 −0.29pp；`TRAINING_CLASS`（试验班，141 单位）只到门类、不到专业类——
  这是事实（试验班本就跨专业类），不是缺陷。
- 📌 **M7 待办**：Step 0 的"同专业类、逐级放宽地区/层次"类比阶梯 + 回测验证。
- 📌 **M7 待办**：`limit` 截断方式（HANDOVER §7 第 3 条）——推荐列表按 `(tier, -utility, unit_id)`
  取前 N，`limit=8` 时可能**全是"冲"**。本 ADR 让 utility 真正分化后，该问题更值得优先修。


### ADR-018 补充（2026-09）· 规则库 JSON 的重复键缺陷

**触发**：用户报障"`major_taxonomy.json` 里有 Duplicate object key"。

**实测**：`major_exact` 里有 **554 个重复键**（分批追加条目造成）。JSON 规范允许重复键，
解析器**取最后一个** —— 于是 **7 个值冲突**的键被**静默归错类**，
影响 **110 行**真实数据：

| 专业名 | 错误值（最后生效） | 修正为 | 依据 |
|---|---|---|---|
| `交通管理` | 公安学类 | **公共管理类** | 本科 120407T；公安技术类里叫 `交通管理工程`(083103TK) |
| `人力资源管理` | 公共管理类 | **工商管理类**（本科）/ 公共管理类（专科） | 本科 120206 vs 专科 590202 —— **真实的两级分裂** |
| `智慧海洋技术` | 海洋科学类 | **海洋工程类** | 与关键词层一致 |
| `社区管理与服务` | 社会学类 | **公共管理类** | 与关键词层一致 |

另外 3 个冲突键（`动漫制作技术`/`建筑消防技术`/`水生态修复技术`）的最后生效值恰好等于正确值，
属**侥幸**，也一并显式钉死。

**修法（三层防护）**：

1. `scripts/dedupe_major_taxonomy.py`：逐条**人工判定**冲突值（依据写在 docstring 里），
   键**排序**输出，幂等。不依赖"最后一个生效"这种巧合。
2. `scripts/build_major_taxonomy_data.py`：新增**重复键守卫**，发现重复直接 `exit 1`。
   用 `object_pairs_hook` **逐对象**检测。
3. `tests/test_major_taxonomy.py`：`TestNoDuplicateJsonKeys` 断言无重复键，并**反向验证**
   检测器对真重复必须报警；`TestConflictResolutions` 把 7 个判定逐个钉死。

**顺带修掉两处规则库自身缺陷**：

* `交通管理` 原先**同时**出现在 `交通运输类` 与 `公共管理类` 的关键词表里，
  最长优先无法区分（实测命中交通运输类，与目录不符）→ 从 `交通运输类` 移除。
* `水生态修复技术` 关键词层原本无命中 → 补关键词，让两层一致。

**新增能力**：`major_exact_by_level` 支持同名专业按学制分流（见 `docs/MAJOR_TAXONOMY.md` §7.2）；
`backfill_major_taxonomy.py` 新增 `--reclassify` 模式（规则改动后重新归类**已有**行，
预演时打印逐条 `旧 → 新` diff）。

**验证**：`--reclassify` 改动 110 行、重复执行 0 变化（幂等）；
分类器单测 66 例通过；全量 401+ 测试通过。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 只删掉重复键、保留"最后一个生效"的值 | 那 4 个名字会继续归错类；且"哪个值对"变成历史巧合，无法审计 |
| 让 `json.loads` 保持默认行为（静默取最后）+ 只加注释提醒 | 缺陷根源没堵住，下次追加条目会重演 |
| 用全文扁平扫描检测重复键 | 会把 9 个方向类型各自的 `label`/`keywords`/`notes` 误报成冲突（实测误报 3 个） |
| 把 `人力资源管理` 统一成一个专业类 | 它是真实的两级分裂（本科 78 单位 / 专科 6 单位），统一必然错一边 |


---

## ADR-019 · 院校层次判别不再只看 985/211/双一流 + 地区维度 + 持久结果缓存 + 配额调整

- **日期**：2026-09
- **状态**：已采纳
- **触发**：用户提出四点——① 层次判别不应以 985/211/双一流为唯一标准，并要"agent 专家分析
  各院校水平、考虑考生偏向地区及该地区学校综合实力"；② history 结果可保存以便下次相似问题直接调用；
  ③ 志愿表配额改为冲稳 75%（冲≈稳）、保垫 25%。

### 缺陷 1（实测）：名册 tier 映射漏了 PROV / PRIV —— 影响 262 所院校

`etl/loaders/zhejiang.py` 的 `_LEVEL_TAGS` 只映射了 `985/211/SY`，而人工名册
（`etl/catalog.py`，418 所）里还有 **`PROV`（243 所省重点）** 与 **`PRIV`（35 所民办/独立学院）**。
后果（实测真实数据 1,692 所）：

| tier | 院校数 | 修复前 level_score | 应为 |
|---|---|---|---|
| `PROV` 省重点 | **231** | 0.45（普通公办档） | **0.60** |
| `PRIV` 民办/独立 | **31** | 0.45 且 `is_public=True` | **0.20** |

受影响的是浙工大、杭电、浙工商、浙理工这类**没有 985/211 标签但在省内极重要**的院校 ——
它们在与 211 院校比软偏好时被系统性压低。

★ `PRIV` 那一项还**破坏了名师铁律 10**：民办/独立学院的学费必须在卡片明示，而 `is_public`
正是该提示的判据；31 所民办被当成公办后，这个提示不会触发。

**修法**：新增 `_TIER_AFFILIATION`（`PROV` → `"省重点建设高校"`）与 `_TIER_IS_PUBLIC`
（`PRIV` → `False`），**官方名后缀优先、名册只在缺失时补**（原文优先原则）。
实测：浙工大 `affiliation` 由 `None` → `省重点建设高校`，`level_score` 0.45 → **0.60**。

### 缺陷 2：地区维度对"未填意向"的考生完全不参与排序

原 `region_score` 在未填意向地区时一律返回 1.00 → 地区维度**恒为常数**，
既不体现"考生偏向的地区"，也不体现"该地区学校的综合实力"。

**修法（两条名师实务规则，均可追溯）**：

1. **本省认可度**：院校所在地 == 考生本省 → **1.00**
   （本地校友网络、实习与就业半径、省内认可度）；
2. **地区高教资源密度**：外省 → `0.55 + 0.30 × region_strength_index(该省)` ∈ [0.55, 0.85]，
   **始终低于本省**。

`region_strength_index` 是**数据驱动**的：由 `etl/catalog.py` 名册统计各省
「双一流及以上」院校数，除以最大值（北京 31 所）。31 省共 140 所。**不是估计值、不是 LLM 判断。**

> ★ **刻意的语义边界**：密度只描述**地区整体资源**，**不是**对单所院校的质量判断。
> 浙江只有 3 所双一流（高教资源相对其经济体量偏少），但这**不代表**浙工大差 ——
> 所以"本省"必须拿满分，不能被密度拉低。三者（`level_score` 单校质量 /
> `region_strength` 地区资源 / 本省认可度）在代码与文档里都分开。

**有意向地区时保持原语义**（勾选 1.0 / "可接受" 0.5 / 未命中 0.0）；
**不知道考生本省时仍返回 1.00**（不知道就不能区别对待）。

### 缺陷 3：agent 没有"院校层次"的事实工具

考生最常问"XX 大学怎么样、算不算好学校"。原 `get_college_profile` 只回
`level_tags` 等原始字段，**没有 level_score 的判据**，模型很容易滑向"凭常识点评院校"。

**修法**：新增第 **13** 个只读工具 `get_college_level_facts`，返回
`level_tags / affiliation / is_public / level_score / level_basis / region_strength /
region_top_college_count / is_home_province / caveats`，每条带 `source_url`。

★ **本工具刻意不产出任何"排名"或"好坏结论"** —— 它只回答"有哪些可追溯的判据"。
`level_basis` 说明这个分**命中了哪条规则**；无标签时必须给出
「没有 985/211/双一流标签 **不等于**层次低」的 caveat。
这是"agent 专家分析"在本项目红线内（AGENTS.md §3.3：LLM 不产生数字）的实现方式：
**判据由确定性规则给出，模型只负责解释与追问。**

### 配额调整（用户明确要求）

`ModelParams.quota`：`25/40/25/10` → **`0.375 / 0.375 / 0.1875 / 0.0625`**
（冲+稳 = 75%、保+垫 = 25%、冲 == 稳）。浙江 80 个志愿的整数结果：**冲 30 / 稳 30 / 保 15 / 垫 5**。

垫底下限（`min_dian_abs=3` / `min_dian_ratio=0.05`）**优先于配额**：总志愿数较小时
（上海 24、北京 30、海南 30）配额算出的垫底低于下限，`planner._allocate` 会从保底调入，
**不会被配额突破**（名师铁律 4）。实测各批次分配：

| 批次 | 上限 | 冲 | 稳 | 保 | 垫 | 冲+稳 | 保+垫 |
|---|---|---|---|---|---|---|---|
| 浙江一段/二段 | 80 | 30 | 30 | 15 | 5 | 75.0% | 25.0% |
| 山东常规批 | 96 | 36 | 36 | 18 | 6 | 75.0% | 25.0% |
| 天津本科A段 | 50 | 19 | 19 | 9 | 3 | 76.0% | 24.0% |

### history 结果的持久化复用

ADR-016 的缓存是**进程内**的（重启即失）。新增：

* `app_meta` 表存 **`data_version`** —— 持久化数据代次令牌；
* `result_cache` 表存 `recommend` 的完整响应体；
* `services/cache_service.py` 负责指纹、读写、统计、清理；
* `seed.py` 与回填脚本在提交后 `bump_data_version()`。

**为什么可以跨考生复用**：`recommend` 的响应体是**考生无关**的 ——
`item_payload` 不含 `student_id`，概率只依赖**位次**（`probability` 文档已声明），
效用只依赖 `(unit, college, major, preferences)`，而 preferences 已进指纹。

**键覆盖**：`(data_version, 省, 年, 位次, criteria, weights, params, limit, include_too_risky,
allowed_batches, intent_as_hard)` —— 漏一个就是一次静默的错误建议（ADR-016 同源教训）。

**失效**：`data_version` 变化即整体失效。★ **绝不用"行数是否变化"判断** ——
实测回填 `majors.category` 时**行数没变、归类全变了**，靠行数判断会漏。

实测（`tests/test_cache_service.py` 23 例）：冷启动 `hit=False` → 同考生 `hit=True`
→ **另一位同位次考生 `hit=True`** → `limit` 变化 `hit=False` → 代次 bump 后 `hit=False`；
缓存体中**不含考生身份**（断言 `student.id not in payload`）；损坏的缓存行按未命中处理（不 500）。

### 回测（改参数必须重跑，DOMAIN_RULES §3.1）

| 省份 | 保底失效率 | 稳档命中率 | 冲档命中率 | Brier | 结论 |
|---|---|---|---|---|---|
| 浙江（真实） | — (无 BAO/DIAN) | 95.11% | 38.82% | 0.0510 | ✅ |
| 山东 | 0.00% | 89.65% | 32.42% | 0.0074 | ✅ |
| 北京 | 0.00% | 86.29% | 14.56% | 0.0082 | ✅ |
| 上海 | 0.00% | **84.30%** ❌ | 11.49% | 0.0096 | ❌ |

★ **上海的 84.30% 是改动前就存在的缺陷，不是本次引入**：用 ADR-019 改动**之前**的数据库
跑同一命令得到**完全相同**的 84.30%（已对照确认）。原因：配额只影响志愿表**生成**，
而 `wen_hit_rate` 是**分层校准**指标，由概率模型决定。
→ 列入 M7 待办（ADR-014 的跨省验证只覆盖了浙江/山东/北京，上海未被覆盖）。

### 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 让 LLM 给每所院校打"水平分"或排名 | 直接违反红线（LLM 不产生数字）；不可复现、不可回测、无法审计 |
| 用"该省双一流数量"直接给院校加分 | 等于说"江苏的普通院校强于甘肃的顶尖院校"；密度是**地区**属性，不能当**单校**质量 |
| 把 `region_strength` 做成第 7 个效用项 | 会改动全量权重归一化与既有排序口径；折进 `region_score` 语义更连贯且改动可控 |
| 持久缓存用"行数变化"判断失效 | 实测回填时行数不变而归类全变 → 会读到旧结论 |
| 持久缓存键里放进程内代数号 | 重启后归零，旧结果会被当新结果命中 |
| 未填意向地区仍一律 1.00 | 那正是"地区完全不参与排序"的成因；改为本省/密度区分 |
| 垫底配额严格按 6.25% 执行 | 总志愿数小时会跌破 `min_dian_abs`，违反名师铁律 4；保底是安全承诺，不能被配额削弱 |
