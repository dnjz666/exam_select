# 高考志愿填报智能体（exam_select）

> 面向 3+3 新高考六省市（浙江/上海/北京/山东/天津/海南）的志愿填报辅助系统。
> **定位：决策辅助，仅供参考；最终以各省考试院官方文件与高校招生章程为准。**

- 施工总纲：`AGENTS.md`（唯一权威施工说明）
- 领域规则与算法参数：`docs/DOMAIN_RULES.md`
- 字段口径：`docs/DATA_DICTIONARY.md`
- 架构决策记录：`docs/DECISIONS.md`

## 当前状态

| Phase | 内容 | 状态 |
|---|---|---|
| M0 | 项目骨架与领域模型 | 🚧 进行中 |
| M1 | 数据层与模拟数据生成 | ⬜ |
| M2 | 核心算法引擎 | ⬜ |
| M3 | 后端 API | ⬜ |
| M4 | 前端 | ⬜ |
| M5 | Agent 层与防幻觉 | ⬜ |
| M6 | 真实数据接入 | ⬜（范围另议） |
| M7 | 加固与交付 | ⬜ |

## 快速开始（后端，M0）

```powershell
# 必须用 py -3.11 建虚拟环境（裸 python 是 3.13，禁止）
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -e backend

# 起服务
Push-Location backend
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
Pop-Location

# 健康检查（另开终端）
curl.exe -s http://127.0.0.1:8000/health   # {"status":"ok"}
```

## 合规声明

- 当前所有分数线/位次均为**确定性模拟数据**（`is_synthetic=1`），**严禁用于真实填报**；
- 天津、海南规则仍为转载源（`SECONDARY`），升级 `PRIMARY` 前其推荐结果不得用于真实填报；
- 系统不做录取概率承诺，概率一律以区间 + 证据链呈现。
