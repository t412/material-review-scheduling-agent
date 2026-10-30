# 素材审核与发布排期 Agent——完整项目交付文档

> 本文档是项目的独立交付说明，覆盖项目目标、范围、架构、目录、安装、配置、运行、输入输出、测试、验收、风险、验证结论和GitHub提交步骤。`README.md`作为评审人员的快速入口。

## 1. 交付信息

| 项目 | 内容 |
|---|---|
| 笔试题号 | 第1题 |
| 项目名称 | 素材审核与发布排期 Agent |
| 实现语言 | Python 3.10+ |
| 运行形式 | CLI |
| 模型方式 | OpenAI兼容真实模型 + Offline Mock |
| 项目目录 | 任意本地目录；以下命令均从项目根目录执行 |
| GitHub URL | `https://github.com/t412/material-review-scheduling-agent` |
| 最终Commit SHA | 推送后执行`git rev-parse HEAD`，在考试提交页面填写 |
| 仓库可见性 | Public |
| 当前测试结果 | 133项测试全部通过 |
| 项目状态 | 核心实现、本地验证、Live Trace与交付文档均已完成 |
| Live Trace状态 | 已生成3条DeepSeek真实模型Trace，脚本验证与强化提交检查均通过 |
| 人工核查状态 | 已核对核心机制、Live工具顺序、结果状态、确认边界和保存事实 |

## 2. 项目总目标

本项目面向内容运营和审核人员，帮助团队完成以下工作：

1. 根据素材ID读取素材及元数据；
2. 检查标题、类型、来源、版权方等必要信息；
3. 根据审核规则识别内容风险；
4. 查询用户指定的发布时间是否可用；
5. 目标时段冲突时查找合理候选时段；
6. 在不越过用户确认边界的前提下生成排期建议；
7. 将结果保存为排期草稿；
8. 防止重复提交产生重复草稿；
9. 在工具失败、信息不足或达到调用上限时返回明确状态；
10. 生成可审计的运行Trace。

系统只保存草稿，不接入真实发布渠道，不提供真实发布工具，也不把“草稿已保存”描述为“内容已发布”。

## 3. 核心成功标准

项目需要证明的不只是固定流程，而是以下动态闭环：

```text
模型选择动作
→ 校验工具名称和参数
→ 执行业务工具
→ 模型观察工具结果
→ 模型调整下一动作或结束
→ 校验最终结果是否得到工具事实支持
```

必须覆盖：

- 正常排期；
- 素材信息缺失；
- 规则风险；
- 时段冲突；
- 重复提交；
- 草稿保存失败。

## 4. 项目范围

### 4.1 已实现范围

- CLI运行入口；
- 合成素材、审核规则和已有排期；
- 素材读取工具；
- 规则检查工具；
- 指定时段查询工具；
- 候选时段搜索工具；
- 幂等草稿保存工具；
- OpenAI兼容工具调用适配器；
- 无密钥Offline Mock；
- Agent动态决策循环；
- 最大决策步数和工具调用次数；
- 重复工具调用限制；
- 未知工具白名单拦截；
- 原子文件写入和本机并发保护；
- JSON Trace、敏感字段脱敏和结果审计；
- 单元、集成和端到端测试；
- 八组实际Mock验收与安全运行材料；
- 一键生成案例和提交前检查脚本。

### 4.2 不在本次范围

- 真实内容发布；
- 真实企业素材库；
- 真实排期平台；
- Web界面；
- HTTP服务；
- 多Agent系统；
- 线上部署；
- 分布式数据库和分布式锁；
- 完整人工审批工作台。

## 5. 业务约束与安全边界

1. 系统只能保存草稿。
2. 项目中不存在`publish`或类似真实发布函数。
3. `hard`发布时间发生冲突时，不得自动更改，只能建议并等待确认。
4. 候选时段必须标记为`pending_confirmation`。
5. 信息不足的素材不能保存草稿。
6. 命中阻断规则的素材不能保存草稿。
7. 保存失败时不得返回成功或伪造草稿ID。
8. 相同业务请求重复执行只允许产生一条物理草稿。
9. 模型不能调用白名单以外的工具。
10. 最终审核状态、风险原因、建议时段和保存状态必须得到工具观察支持。
11. Trace不能包含API密钥、Token、密码或模型隐藏思维过程。
12. 达到步数或调用次数上限时必须返回明确的`incomplete`状态。

## 6. 系统架构

```text
用户输入 / JSON文件
        ↓
SchedulingRequest校验与北京时间规范化
        ↓
MaterialSchedulingAgent
        ↓
ModelClient.decide(messages, tool_schemas)
        ↓
ToolRegistry白名单与参数校验
        ↓
素材 / 规则 / 时段 / 草稿工具
        ↓
ToolResult观察写回模型
        ↓
模型继续调用工具或生成最终JSON
        ↓
AgentResult结构校验与事实一致性审计
        ↓
草稿 + Trace + CLI结构化输出
```

### 6.1 模型层

- `OpenAICompatibleModel`：连接支持Tool Calling的OpenAI兼容模型；
- `OfflineMockModel`：无密钥条件下稳定复现路径，只用于流程验证；
- `ModelDecision`：要求模型在“调用工具”和“返回最终结果”之间二选一。

### 6.2 Agent层

Agent负责：

- 组织系统提示和用户请求；
- 调用模型获取下一动作；
- 检查工具是否在白名单中；
- 校验工具参数；
- 执行工具并回传观察；
- 检测重复调用；
- 控制模型步数和工具次数；
- 校验最终结果；
- 生成Trace。

### 6.3 工具层

| 工具 | 职责 |
|---|---|
| `get_material` | 读取素材并返回缺失字段 |
| `check_material_rules` | 执行审核规则并返回规则证据 |
| `query_slot` | 查询目标时段是否占用 |
| `find_alternative_slots` | 查询同日可用候选时段 |
| `save_schedule_draft` | 幂等保存排期草稿，不发布 |

## 7. 动态决策示例

### 7.1 正常时段路径

```text
get_material
→ check_material_rules
→ query_slot返回available
→ save_schedule_draft
→ completed
```

### 7.2 时段冲突路径

```text
get_material
→ check_material_rules
→ query_slot返回occupied
→ find_alternative_slots
→ 建议19:00
→ save_schedule_draft为pending_confirmation
→ awaiting_confirmation
```

两条路径的差异来自`query_slot`的实际观察，而不是预先写入的决策日志。

## 8. 项目目录说明

```text
项目根目录/
├── README.md                     # 快速安装、运行与评审入口
├── DELIVERY.md                   # 当前完整交付文档
├── pyproject.toml                # 项目元数据、依赖和pytest配置
├── .env.example                  # 真实模型环境变量示例
├── .gitignore                    # 密钥、缓存、虚拟环境和运行数据排除规则
├── src/
│   ├── agent.py                  # Agent决策循环、限制和事实审计
│   ├── cli.py                    # CLI命令、输入解析和退出码
│   ├── schemas.py                # Pydantic数据结构和业务约束
│   ├── prompts.py                # 真实模型系统提示
│   ├── trace.py                  # Trace生成、脱敏和原子写入
│   ├── exceptions.py             # 稳定异常类型
│   ├── models/
│   │   ├── base.py               # 模型统一接口
│   │   ├── mock_model.py         # 离线Mock模型
│   │   └── openai_compatible.py  # OpenAI兼容模型适配器
│   ├── tools/
│   │   ├── material.py           # 素材读取工具
│   │   ├── review.py             # 审核规则工具
│   │   ├── schedule.py           # 时段查询与候选时段工具
│   │   ├── draft.py              # 草稿保存工具
│   │   └── registry.py           # 工具白名单和JSON Schema
│   └── storage/
│       ├── json_repository.py    # 只读JSON数据仓库
│       ├── idempotency.py        # 稳定幂等键
│       └── draft_repository.py   # 文件锁、原子草稿存储
├── tests/
│   ├── unit/                     # Schema和单模块测试
│   ├── integration/              # Agent路径、限制和Trace测试
│   └── e2e/                      # CLI及交付材料测试
├── data/
│   ├── materials.json            # 合成素材M01-M06
│   ├── review_rules.json         # 审核规则R001-R003
│   ├── schedules.json            # 已有排期
│   └── drafts.seed.json          # 空草稿种子
├── examples/
│   ├── README.md                 # 案例索引
│   ├── test-results.txt          # 实际pytest结果
│   ├── case-01-normal/           # 正常排期
│   ├── case-02-missing-info/     # 信息缺失
│   ├── case-03-rule-risk/        # 规则风险
│   ├── case-04-slot-conflict/    # 时段冲突
│   ├── case-05-duplicate/        # 重复提交
│   ├── case-06-save-failure/     # 保存失败
│   ├── case-07-manual-review/    # 人工确认型规则
│   ├── case-08-prompt-injection/ # 提示词注入安全
│   └── live-model/               # 3条DeepSeek真实模型输出与Trace
├── docs/
│   ├── 01-requirements.md        # 需求、范围和成功标准
│   ├── 02-solution.md            # 架构、动态决策和技术取舍
│   ├── 03-evaluation.md          # 测试结果、失败和限制
│   ├── 04-ai-usage.md            # AI辅助和人工贡献说明
│   └── 05-retrospective.md       # 复盘、学习与后续计划
├── scripts/
│   ├── generate_examples.py      # 重新生成八组Mock案例
│   ├── run_examples.ps1          # Windows案例生成入口
│   ├── generate_live_examples.py # 生成三条真实模型案例
│   ├── generate_live_examples.ps1# 隐藏读取API Key的安全入口
│   ├── verify_submission.py      # 提交前目录、密钥和测试检查
│   └── verify_submission.ps1     # Windows提交检查入口
└── runtime/
    ├── drafts/                   # 本地运行草稿，不提交JSON
    └── traces/                   # 本地运行Trace，不提交JSON
```

## 9. 环境要求

### 9.1 基础环境

- Python 3.10或更高版本；
- Windows PowerShell、PowerShell 7、CMD或兼容Shell；
- 真实模型模式需要网络和支持Tool Calling的模型服务；
- 离线Mock模式不需要API密钥。

本项目实际开发验证环境：

```text
Python 3.10.9
Pydantic 2.14.1
OpenAI SDK 2.54.0
pytest 8.4.2
```

### 9.2 主要依赖

| 依赖 | 用途 |
|---|---|
| `openai` | OpenAI兼容Chat Completions及工具调用 |
| `pydantic` | 输入、工具参数、状态和输出校验 |
| `pytest` | 自动化测试 |
| `pytest-cov` | 可选测试覆盖率 |

## 10. 安装步骤

### 10.1 Windows PowerShell

```powershell
cd "<项目根目录>"

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

以上方式不要求激活虚拟环境，也不受PowerShell脚本执行策略影响。后续命令可以始终使用`.\.venv\Scripts\python.exe`。

如希望激活虚拟环境，可在当前PowerShell窗口临时放行脚本后执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

不激活时运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### 10.2 macOS或Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## 11. 环境变量配置

Offline Mock不需要环境变量。真实模型模式使用：

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_BASE_URL=
AGENT_MAX_STEPS=8
AGENT_MAX_TOOL_CALLS=10
```

字段说明：

| 变量 | 必填 | 说明 |
|---|---:|---|
| `OPENAI_API_KEY` | Live必填 | 模型服务密钥，不得提交 |
| `OPENAI_MODEL` | Live必填 | 支持Tool Calling的模型名 |
| `OPENAI_BASE_URL` | 否 | OpenAI兼容服务地址 |
| `AGENT_MAX_STEPS` | 否 | 计划中的环境配置项，CLI当前可直接传参 |
| `AGENT_MAX_TOOL_CALLS` | 否 | 计划中的环境配置项，CLI当前可直接传参 |

不要把真实密钥写入`.env.example`、文档、案例、Trace或Git提交。

使用DeepSeek API时，环境变量名仍保持不变，因为项目通过OpenAI兼容SDK接入：

```dotenv
OPENAI_API_KEY=<你的DeepSeek API Key>
OPENAI_MODEL=deepseek-flash
OPENAI_BASE_URL=https://api.deepseek.com
```

项目检测到DeepSeek地址后，会按DeepSeek官方工具调用示例关闭思考模式，以兼容当前多轮Chat Completions工具调用流程。官方OpenAI用户应将`OPENAI_BASE_URL`留空。

## 12. 运行方式

### 12.1 查看项目状态

```powershell
python -m src.cli status
```

### 12.2 离线Mock正常排期

```powershell
python -m src.cli run `
  --mode mock `
  --request-id DEMO-001 `
  --material-id M01 `
  --requested-slot "2026-11-02T17:00:00+08:00"
```

预期：

- `review_status: passed`
- `draft_status: saved`
- `task_status: completed`

### 12.3 离线Mock时段冲突

```powershell
python -m src.cli run `
  --mode mock `
  --request-id DEMO-002 `
  --material-id M01 `
  --requested-slot "2026-11-02T18:00:00+08:00" `
  --earliest-time "17:00:00" `
  --latest-time "21:00:00"
```

预期：18:00占用，建议19:00，状态为`awaiting_confirmation`。

### 12.4 JSON文件输入

```powershell
python -m src.cli run `
  --mode mock `
  --input examples/case-04-slot-conflict/input.json `
  --output runtime/result.json
```

### 12.5 故障注入

```powershell
python -m src.cli run `
  --mode mock `
  --material-id M05 `
  --requested-slot "2026-11-02T19:00:00+08:00" `
  --inject-save-failure
```

预期：`draft_status: failed`，不能返回草稿ID。

### 12.6 真实模型模式

推荐使用安全脚本生成三条Live记录：

```powershell
.\scripts\generate_live_examples.ps1
```

脚本会：

1. 隐藏读取API Key；
2. 读取模型名和可选Base URL；
3. 运行17:00空闲路径；
4. 运行18:00冲突路径；
5. 运行M03规则风险阻断路径；
6. 校验结束原因、必要工具、禁止工具和任务状态；
7. 全部成功后才替换`examples/live-model/`，失败不覆盖已有证据；
8. 从当前进程清除密钥。

也可以手动设置当前终端环境变量：

```powershell
$env:OPENAI_API_KEY="<your-key>"
$env:OPENAI_MODEL="<tool-calling-model>"
$env:OPENAI_BASE_URL="<optional-compatible-url>"

python -m src.cli run `
  --mode live `
  --request-id LIVE-001 `
  --material-id M01 `
  --requested-slot "2026-11-02T18:00:00+08:00"
```

不要在Git、截图、聊天或文档中展示真实密钥。

### 12.7 辅助命令

```powershell
python -m src.cli list-materials
python -m src.cli list-schedule
python -m src.cli show-drafts
```

## 13. 输入格式

```json
{
  "request_id": "REQ-001",
  "material_id": "M01",
  "requested_slot": "2026-11-02T18:00:00+08:00",
  "slot_requirement": "hard",
  "user_confirmed_alternative": false,
  "constraints": {
    "allowed_date": "2026-11-02",
    "earliest_time": "17:00:00",
    "latest_time": "21:00:00"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `request_id` | string | 是 | 本次请求标识 |
| `material_id` | string | 是 | 素材ID |
| `requested_slot` | ISO 8601 datetime | 是 | 必须包含时区 |
| `slot_requirement` | `hard/flexible` | 否 | 默认`hard` |
| `user_confirmed_alternative` | boolean | 否 | 是否确认替代时段 |
| `constraints.allowed_date` | date | 否 | 允许排期日期 |
| `constraints.earliest_time` | time | 否 | 最早候选时间 |
| `constraints.latest_time` | time | 否 | 最晚候选时间 |

## 14. 输出格式

```json
{
  "result": {
    "request_id": "REQ-001",
    "material_id": "M01",
    "review_status": "passed",
    "risk_reasons": [],
    "requested_slot": "2026-11-02T18:00:00+08:00",
    "suggested_slot": "2026-11-02T19:00:00+08:00",
    "confirmation_status": "pending_confirmation",
    "pending_items": ["请确认候选时段或审核风险。"],
    "draft_status": "saved",
    "draft_id": "DRAFT-...",
    "task_status": "awaiting_confirmation",
    "summary": "候选排期草稿已保存，等待用户确认；未执行真实发布。",
    "trace_file": "..."
  },
  "completion_reason": "model_finished",
  "model_steps": 6,
  "tool_calls": 5,
  "trace_error": null
}
```

### 14.1 状态枚举

| 字段 | 可选值 |
|---|---|
| `review_status` | `passed`、`needs_information`、`needs_confirmation`、`blocked` |
| `confirmation_status` | `not_required`、`pending_confirmation`、`confirmed` |
| `draft_status` | `saved`、`duplicate`、`not_attempted`、`failed` |
| `task_status` | `completed`、`awaiting_confirmation`、`blocked`、`incomplete`、`failed` |

项目没有`published`状态。

### 14.2 CLI退出码

| 退出码 | 含义 |
|---:|---|
| 0 | 完成或正常等待确认 |
| 2 | 输入或模型配置错误 |
| 3 | 业务规则阻断 |
| 4 | 工具或任务失败 |
| 5 | 任务以`incomplete`结束或达到调用上限 |

## 15. 合成数据说明

### 15.1 素材

| 素材 | 用途 |
|---|---|
| M01 | 信息完整、无规则风险 |
| M02 | 缺少版权方 |
| M03 | 包含“全网第一”等绝对化用语 |
| M04 | 健康类内容，需要人工确认 |
| M05 | 正常教程素材，用于保存失败测试 |
| M06 | 提示词注入文本安全测试 |

### 15.2 规则

| 规则 | 内容 | 动作 |
|---|---|---|
| R001 | 必填元数据完整性 | 请求补充信息 |
| R002 | 禁用绝对化营销用语 | 阻断 |
| R003 | 健康类内容人工复核 | 请求确认 |

### 15.3 已有排期

- 2026-11-02 18:00已占用；
- 2026-11-02 20:00已占用；
- 19:00可作为18:00冲突后的第一候选。

## 16. 幂等与可靠性

幂等键使用规范化业务字段生成SHA-256，包括：

- 素材ID；
- 北京时间发布时间；
- 时间要求类型；
- 用户确认状态；
- 时间范围约束。

`request_id`不参与幂等键，因此同一业务请求使用不同请求ID重试，第二次仍返回原草稿。

草稿写入过程：

1. 获取`O_EXCL`锁文件；
2. 锁内读取已有草稿；
3. 检查幂等键；
4. 写入同目录临时文件；
5. 调用`fsync`；
6. 使用`os.replace`原子替换；
7. 释放锁。

## 17. Agent运行限制

默认值：

| 限制 | 默认值 |
|---|---:|
| 最大模型决策步数 | 8 |
| 最大工具调用次数 | 10 |
| 相同工具和参数重复次数 | 2 |

达到上限后返回`incomplete`，并在`completion_reason`和Trace中说明原因。

## 18. Trace说明

每条Trace包含：

- `run_id`；
- 开始和结束时间；
- 原始输入；
- 运行限制；
- 模型步数和工具调用数；
- 每一步工具名称和参数；
- 工具状态、摘要、错误码和返回数据；
- 下一动作；
- 简短决策依据；
- 最终输出；
- 完成原因。

Trace不会记录模型隐藏思维过程，只记录便于审核的动作依据。

自动脱敏字段包括：

- API Key；
- Authorization；
- Access Token；
- Refresh Token；
- Password；
- Secret。

## 19. 测试与验证

### 19.1 运行测试

```powershell
python -m pytest
```

最近一次记录：

```text
133 passed in 41.99s
```

测试时间主要来自多次独立启动CLI子进程；单元和Agent集成测试通常只需数秒。

### 19.2 测试分层

- `tests/unit/`：Schema、工具、存储、模型适配和Trace；
- `tests/integration/`：完整Agent路径、失败、限制和审计；
- `tests/e2e/`：独立CLI进程、案例材料和Windows编码。

### 19.3 八组验收与安全材料

| 案例 | 任务状态 | 草稿状态 | 关键结果 |
|---|---|---|---|
| case-01-normal | `completed` | `saved` | 17:00空闲并保存 |
| case-02-missing-info | `incomplete` | `not_attempted` | 缺版权方，不保存 |
| case-03-rule-risk | `blocked` | `not_attempted` | 命中禁止词并阻断 |
| case-04-slot-conflict | `awaiting_confirmation` | `saved` | 建议19:00，待确认 |
| case-05-duplicate | `completed` | `duplicate` | 相同草稿ID，物理记录1条 |
| case-06-save-failure | `failed` | `failed` | 明确保存失败 |
| case-07-manual-review | `awaiting_confirmation` | `saved` | 健康类规则需人工确认 |
| case-08-prompt-injection | `completed` | `saved` | 注入文字未改变权限，无发布动作 |

每个普通案例包含：

- `input.json`；
- `output.json`；
- `trace.json`。

重复提交案例包含两次运行输出和两份Trace。

### 19.4 重新生成验收材料

```powershell
python scripts/generate_examples.py
```

## 20. 提交前自动检查

```powershell
python scripts/verify_submission.py
```

检查内容：

- 规定目录和文档是否存在；
- 八组案例文件是否完整；
- 是否存在根目录`.env`；
- 是否出现疑似真实密钥；
- 是否存在至少两条Live Trace；
- 全部pytest是否通过；
- 项目是否启用真实发布。

如果要求Live Trace不足时直接失败：

```powershell
python scripts/verify_submission.py --require-live
```

## 21. 当前完成状态

### 21.1 已完成

- [x] Python项目结构
- [x] 输入输出Schema
- [x] 素材读取工具
- [x] 审核规则工具
- [x] 时段查询工具
- [x] 候选时段工具
- [x] 草稿保存工具
- [x] 幂等机制
- [x] 并发文件锁
- [x] 原子写入
- [x] OpenAI兼容适配器
- [x] Offline Mock
- [x] Agent动态循环
- [x] 工具白名单
- [x] 决策和调用上限
- [x] 最终事实审计
- [x] Trace和脱敏
- [x] 完整CLI
- [x] 单元、集成和端到端测试
- [x] 八组Mock验收与安全材料
- [x] README
- [x] 5份规定文档
- [x] AI辅助记录初稿
- [x] 提交前检查脚本

### 21.2 本地交付验收结果

- [x] 使用DeepSeek生成正常、冲突和规则阻断三条Live Trace；
- [x] 核对三条Live的结束原因、工具顺序、状态、保存事实和确认边界；
- [x] 核对Agent循环、Schema状态约束、五个业务工具及幂等保存逻辑；
- [x] 完成`docs/04-ai-usage.md`中的个人贡献和AI辅助边界记录；
- [x] 完成`docs/05-retrospective.md`中的实际投入时间和复盘；
- [x] 确认仓库没有`.env`、真实密钥或隐私数据；
- [x] 完成133项自动化测试；
- [x] 完成强化提交检查，错误和警告均为空；
- [x] 确认公开GitHub仓库地址。

### 21.3 当前状态说明（2026-10-30）

- `examples/live-model/`已包含3条DeepSeek `deepseek-flash`真实模型记录；
- 正常路径为4次工具调用，结果`completed / saved`；冲突路径为5次工具调用，观察18:00占用后查询19:00并以`pending_confirmation`保存，结果`awaiting_confirmation / saved`；规则风险路径为2次工具调用，命中R002后`blocked / not_attempted`；
- 已运行`python scripts/verify_submission.py --require-live --skip-tests`，结果`passed`，错误与警告均为空；
- 已完成133项单元、集成和端到端测试，结果全部通过；
- 候选人已完成选题、技术栈、交付方式、模块推进、测试策略、Live Trace和交付文档核查；
- GitHub仓库地址已确定；最终Commit SHA在最终推送后生成，并直接填写到考试提交页面，避免在提交内容中形成自引用SHA。

## 22. 已知限制

1. 当前业务数据为合成JSON，不代表真实数据规模和脏数据分布。
2. 八组验收与安全案例由Offline Mock生成；真实模型已验证正常、冲突和规则阻断三条代表性路径。
3. 文件锁适用于同机文件系统，不是分布式锁。
4. 本次范围聚焦待确认草稿生成，不包含用户确认后的原草稿更新流程。
5. 本次使用合成工具和数据，不接入真实素材库、审核平台或发布系统。
6. 本次评估验证代表性路径，不包含多模型、多次重复运行下的准确率、延迟、Token和费用统计。
7. OpenAI兼容服务的工具调用格式需要服务端实际支持。

## 23. 常见问题排查

### 23.1 `ModuleNotFoundError`

确认已激活虚拟环境并安装项目：

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

### 23.2 PowerShell无法激活虚拟环境

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.venv\Scripts\Activate.ps1
```

### 23.3 Live模式提示缺少配置

确认当前进程中存在：

```powershell
$env:OPENAI_API_KEY
$env:OPENAI_MODEL
```

不要把输出截图或写入日志。

### 23.4 模型不支持工具调用

更换支持Tool Calling的模型，或使用正确的OpenAI兼容Base URL。普通文本模型不能完成本项目Live模式。

### 23.5 Live模型返回非JSON最终答案

项目会拒绝无法解析的最终输出。可调整模型、系统提示或工具描述后重新运行，不能手工修改Trace冒充成功。

### 23.6 重复执行返回`duplicate`

这是预期的幂等行为。若要进行独立测试，请更换素材、时段或使用新的运行目录。

### 23.7 看到`awaiting_confirmation`

表示系统找到了候选时段或审核风险需要确认，不代表任务失败，也不代表已经发布。

## 24. AI辅助与个人贡献

AI辅助范围包括：

- 方案拆解；
- 代码实现；
- 测试设计；
- 合成数据；
- 文档初稿；
- 风险和边界检查。

候选人已经完成：

- 选择第1题、Python技术栈和CLI交付方式；
- 明确六个验收场景、分阶段实现与测试要求；
- 持续核对项目进度并要求补齐至少两条Live Trace；
- 要求生成独立交付文档并开始审阅AI使用、复盘和限制说明。

候选人完成的核查包括：

- 核对项目结构、核心机制和交付入口；
- 核对CLI、自动化测试和真实模型运行结果；
- 核对Agent动态决策、用户确认和保存事实边界；
- 如实记录本人修改、验证内容和实际投入；
- 明确区分AI辅助内容与候选人个人贡献。

详细记录见`docs/04-ai-usage.md`。

## 25. GitHub提交步骤

最终发布使用以下命令：

```powershell
git init -b main
git add .
git status
git commit -m "feat: complete material review scheduling agent"
```

连接已创建的GitHub仓库并推送：

```powershell
git remote add origin https://github.com/t412/material-review-scheduling-agent.git
git push -u origin main
```

最终核对：

```powershell
git status
git log -1 --oneline
git rev-parse HEAD
```

提交给评审的信息：

```text
题号：第1题
GitHub URL：https://github.com/t412/material-review-scheduling-agent
最终Commit SHA：粘贴`git rev-parse HEAD`的40位输出
```

仓库设置为Public，评审可直接读取。

## 26. 最终交付检查清单

### 26.1 文件

- [x] `README.md`
- [x] `DELIVERY.md`
- [x] `src/`
- [x] `tests/`
- [x] `examples/`
- [x] `data/`
- [x] `docs/01-requirements.md`
- [x] `docs/02-solution.md`
- [x] `docs/03-evaluation.md`
- [x] `docs/04-ai-usage.md`
- [x] `docs/05-retrospective.md`
- [x] `pyproject.toml`
- [x] `.env.example`
- [x] `.gitignore`

### 26.2 行为

- [x] 正常排期
- [x] 信息缺失
- [x] 规则风险
- [x] 时段冲突
- [x] 重复提交
- [x] 保存失败
- [x] 调用上限
- [x] 未知工具阻断
- [x] 不提供真实发布
- [x] 保存状态事实审计

### 26.3 本地交付确认

- [x] 已生成三条真实模型Live Trace
- [x] 已运行强制Live提交检查，结果通过且无警告
- [x] 已运行`python -m pytest`，133项测试通过
- [x] 已确认没有`.env`、真实密钥和隐私数据
- [x] 已核对核心代码机制与关键边界
- [x] 已更新AI使用说明、个人贡献和实际用时
- [x] 已填写GitHub URL并确认Public权限

## 27. 最终提交信息模板

```text
题号：第1题——素材审核与发布排期Agent

GitHub URL：https://github.com/t412/material-review-scheduling-agent

最终Commit SHA：在考试提交页面粘贴`git rev-parse HEAD`的40位输出

运行入口：
python -m src.cli run --mode mock --input examples/case-04-slot-conflict/input.json

测试命令：
python -m pytest

评审入口：
README.md
DELIVERY.md
examples/README.md
docs/03-evaluation.md

Live Trace状态：
已生成并核对3条DeepSeek真实模型Trace，正常、冲突与规则阻断路径均通过。

已知限制：
使用合成数据；真实模型当前验证3条代表性路径但未做多次统计评测；未接入真实审批和发布系统。
```

