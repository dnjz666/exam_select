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

## M4 验收记录（2026-02）

**验收命令与真实输出**（AGENTS.md §10 M4：`cd frontend && npm run build && npm run typecheck`）：

```text
1) npm run build
   prebuild → node scripts/gen-api-types.mjs
     [gen:api] 21 个端点 / 69 个 schema ← http://127.0.0.1:8000/openapi.json
   vite v6.4.3 building for production...
   ✓ 609 modules transformed.
   dist/index.html                    0.77 kB │ gzip:   0.49 kB
   dist/assets/index-*.css           29.27 kB │ gzip:   5.23 kB
   dist/assets/index-*.js            99.71 kB │ gzip:  31.27 kB
   dist/assets/react-*.js           165.56 kB │ gzip:  54.17 kB
   dist/assets/echarts-*.js         554.81 kB │ gzip: 184.98 kB
   ✓ built in 5.50s                                                     （exit=0）✅

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

