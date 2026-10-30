# 02 解决方案与技术取舍

## 方案概览

项目采用原生Python实现单Agent工具调用循环，使用Pydantic约束输入、工具参数和最终输出。模型负责选择下一动作，确定性Python层负责执行工具、安全控制和事实校验。

```text
SchedulingRequest
  ↓
ModelClient.decide(messages, tools)
  ↓
ToolRegistry白名单与参数Schema
  ↓
业务工具执行并返回ToolResult
  ↓
观察写回messages
  ↓
模型继续决策或返回AgentResult
  ↓
结构校验 + 工具事实校验 + Trace
```

## 为什么不采用工作流框架

本题核心链路较短，限制投入时间内原生实现更容易展示模型决策与安全边界的责任划分。引入LangGraph等框架会增加依赖和解释成本，但不会自动提升业务正确性。

原生方案保留了可替换的`ModelClient`接口，后续可以将循环迁移到框架节点而无需重写业务工具。

## 核心模块

| 模块 | 职责 |
|---|---|
| `src/schemas.py` | 输入、状态、工具结果、草稿和最终结果Schema |
| `src/agent.py` | 模型—工具—观察循环、上限控制和事实校验 |
| `src/models/` | OpenAI兼容适配器和离线Mock |
| `src/tools/` | 素材、规则、排期、草稿与工具注册表 |
| `src/storage/` | JSON读取、幂等键、文件锁和原子草稿存储 |
| `src/trace.py` | Trace脱敏与原子写入 |
| `src/cli.py` | CLI输入、模式选择、退出码和辅助命令 |

## 动态决策

正常时段路径：

```text
get_material
→ check_material_rules
→ query_slot返回available
→ save_schedule_draft
→ 完成
```

时段冲突路径：

```text
get_material
→ check_material_rules
→ query_slot返回occupied
→ find_alternative_slots
→ 建议19:00
→ save_schedule_draft为pending_confirmation
→ 等待确认
```

这两条路径的动作差异来自工具观察，而不是预设的固定日志。离线Mock用确定性规则复现该协议；真实模型模式通过OpenAI兼容工具调用接口完成动作选择。

## 工具设计

### `get_material`

读取指定素材，返回元数据和缺失字段。素材正文始终被当作不可信业务数据，不能改变系统指令。

### `check_material_rules`

支持必填字段、包含词、等值和集合匹配。命中优先级为：

```text
blocked > needs_information > needs_confirmation > passed
```

每条命中包含规则ID、原因和事实证据。

### `query_slot`

查询指定带时区时段。`occupied`是业务观察，不是工具异常。

### `find_alternative_slots`

在同日允许范围内搜索候选。相同距离时优先原时间之后的时段，因此18:00冲突时先推荐19:00。候选统一标记为`pending_confirmation`。

### `save_schedule_draft`

只保存草稿。阻断或信息不足状态在工具输入Schema层即被拒绝。返回`published: false`，项目中不存在发布函数。

## 幂等与存储

幂等键由以下规范化字段计算SHA-256：

- 素材ID
- 北京时间发布时间
- 时间要求类型
- 用户确认状态
- 时间约束

`request_id`不进入幂等键，所以相同业务请求使用不同请求ID重试仍会返回原草稿。

写入过程使用：

1. `O_EXCL`锁文件；
2. 锁内重新读取已有草稿；
3. 临时文件写入与`fsync`；
4. `os.replace`原子替换。

## Agent上限

默认限制：

- 最大模型决策步数：8
- 最大工具调用次数：10
- 相同工具和参数最多重复2次

达到限制后返回明确`incomplete`及完成原因。

## 事实一致性审计

模型输出不能直接成为事实。Agent在结束前核对：

- 请求ID、素材ID和原始时段是否被篡改；
- 审核状态和风险原因是否来自规则工具；
- 替代时段是否存在于候选工具结果；
- 草稿状态和草稿ID是否来自保存工具；
- 保存草稿中的素材和时段是否与原请求一致；
- 保存工具是否明确返回`published: false`；
- 摘要是否包含越权发布声明。

## Trace

每条Trace包含：

- 输入和运行上限
- 步骤与工具参数
- 工具状态、摘要、错误码和数据
- 后续动作
- 简短动作依据
- 最终输出和完成原因

Trace递归脱敏API Key、Authorization、Token、密码和Secret，不记录模型内部思维过程。

## 模型模式

### Offline Mock

用于无密钥测试和稳定复现。它证明系统协议和工程行为，不证明真实模型效果。

### Live

`OpenAICompatibleModel`通过Chat Completions工具调用接口连接支持Tool Calling的模型，环境变量为：

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL`，可选

当前已使用DeepSeek `deepseek-flash`提交三条Live运行记录，保存在`examples/live-model/`。正常路径在时段可用后保存草稿；冲突路径观察18:00占用后新增替代时段查询，并将19:00以待确认状态保存；规则风险路径命中R002后立即阻断，不查询时段、不保存草稿。三条记录均通过强化脚本验证，不包含API Key或模型内部思维过程。

