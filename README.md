# 素材审核与发布排期 Agent

小影科技 2027 校招 AI Agent 笔试第 1 题实现。系统帮助内容团队读取待处理素材、执行规则审核、检查发布时间冲突，并保存可确认的排期草稿。系统没有真实发布工具，也不会把草稿描述为已发布。

## 一分钟评审入口

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# 运行全部测试
python -m pytest

# 离线运行时段冲突案例：18:00占用，建议19:00并等待确认
python -m src.cli run `
  --mode mock `
  --request-id REVIEW-001 `
  --material-id M01 `
  --requested-slot "2026-11-02T18:00:00+08:00" `
  --earliest-time "17:00:00" `
  --latest-time "21:00:00"
```

直接查看验证材料：

- [八组案例索引](examples/README.md)
- [时段冲突Trace](examples/case-04-slot-conflict/trace.json)
- [重复提交结果](examples/case-05-duplicate/output.json)
- [保存失败Trace](examples/case-06-save-failure/trace.json)
- [测试结果](examples/test-results.txt)
- [评估报告](docs/03-evaluation.md)

## 核心闭环

```text
用户请求
→ 模型选择工具
→ 参数与权限校验
→ 执行业务工具
→ 将观察结果反馈模型
→ 模型调整下一动作或结束
→ 事实一致性审计
→ 保存草稿与Trace
```

Agent不是由固定串行流程直接生成结果。模型每轮可以选择读取素材、检查规则、查询时段、寻找候选时段、保存草稿或结束；Python代码负责工具白名单、安全边界和事实校验。

## 已实现能力

- 素材读取及缺失字段识别
- 确定性规则检查与规则证据
- 指定时段查询和冲突摘要
- 同日候选时段搜索
- 硬性发布时间的确认边界
- 幂等草稿保存
- 并发重复提交保护
- 保存失败和工具异常处理
- 最大决策步数、工具次数及重复调用限制
- OpenAI兼容工具调用适配器
- 可复现离线Mock模型
- JSON Trace、凭据脱敏和结果事实审计
- Windows UTF-8 CLI及结构化退出码

## 安装

要求Python 3.10+。本地验证环境为Python 3.10.9。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

主要依赖：

- `openai>=1.50,<3`：OpenAI兼容工具调用接口
- `pydantic>=2.7,<3`：输入、工具参数和最终输出校验
- `pytest>=7.1,<9`：自动化测试

## 运行方式

### 离线Mock模式

无需API密钥：

```powershell
python -m src.cli run `
  --mode mock `
  --request-id REQ-001 `
  --material-id M01 `
  --requested-slot "2026-11-02T17:00:00+08:00"
```

Mock只证明流程、工具、状态与异常处理正确，不证明真实模型的决策能力。

### 真实模型模式

复制`.env.example`中的变量到本机环境，不要提交真实密钥：

```powershell
$env:OPENAI_API_KEY="<your-key>"
$env:OPENAI_MODEL="<tool-calling-model>"
# 使用兼容服务时可选：
$env:OPENAI_BASE_URL="https://..."

python -m src.cli run `
  --mode live `
  --request-id LIVE-001 `
  --material-id M01 `
  --requested-slot "2026-11-02T18:00:00+08:00" `
  --earliest-time "17:00:00" `
  --latest-time "21:00:00"
```

当前仓库已提交三条DeepSeek `deepseek-flash`真实模型运行记录，覆盖17:00正常路径、18:00冲突后建议19:00待确认路径，以及M03规则风险阻断路径；实际输出与Trace位于`examples/live-model/`。

### JSON文件输入

```powershell
python -m src.cli run `
  --mode mock `
  --input examples/case-04-slot-conflict/input.json `
  --output runtime/result.json
```

### 辅助命令

```powershell
python -m src.cli status
python -m src.cli list-materials
python -m src.cli list-schedule
python -m src.cli show-drafts
```

## 输入格式

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

所有时间必须带时区，并统一规范化为北京时间UTC+8。

## 输出要点

最终结果包含：

- `review_status`：审核状态
- `risk_reasons`：有规则证据支持的风险原因
- `requested_slot`：用户要求时段
- `suggested_slot`：工具返回的候选时段
- `confirmation_status`：是否等待确认
- `pending_items`：待补充或待确认事项
- `draft_status`和`draft_id`：来自真实保存工具观察
- `task_status`：任务状态
- `trace_file`：本次运行Trace

项目中不存在`published`任务状态。保存结果中的`published`始终为`false`。

## CLI退出码

| 退出码 | 含义 |
|---:|---|
| 0 | 完成或正常等待确认 |
| 2 | 输入或模型配置错误 |
| 3 | 业务规则阻断 |
| 4 | 工具或任务失败 |
| 5 | 任务以`incomplete`结束或达到调用上限 |

## 测试与案例

```powershell
python -m pytest
python scripts/generate_examples.py
python scripts/verify_submission.py
```

当前Mock材料共八组：覆盖六个必须验收场景，并补充人工确认型规则和提示词注入安全路径；另有三条真实模型Live运行记录。最终全量测试为133项全部通过。

## 项目结构

```text
src/                 Agent、模型适配、工具、存储和Trace
tests/unit/          数据结构和单模块测试
tests/integration/   Agent路径、限制和Trace测试
tests/e2e/           CLI与交付材料测试
data/                合成素材、规则和已有排期
examples/            输入、实际输出、Trace和测试结果
docs/                需求、方案、评估、AI使用和复盘
scripts/             案例生成与提交前检查
runtime/             本地运行草稿和Trace，不进入Git
```

## 安全边界

- 不提供真实发布工具
- 不擅自修改硬性发布时间
- 替代时段未经确认只能保存候选草稿
- 阻断或信息不足的素材不能保存草稿
- 模型声明不能覆盖工具事实
- 未知工具和`publish`调用会被白名单拒绝
- API密钥、Token和密码不会写入Trace

## 文档

- [需求与成功标准](docs/01-requirements.md)
- [解决方案与技术取舍](docs/02-solution.md)
- [测试、结果与限制](docs/03-evaluation.md)
- [AI辅助使用记录](docs/04-ai-usage.md)
- [复盘与下一步](docs/05-retrospective.md)
- [最终交付清单](DELIVERY.md)

## 已知限制

- 当前业务数据为合成JSON，未连接真实素材库或排期系统。
- Mock模型是确定性流程替身；当前三条Live记录证明代表性正常、冲突和规则阻断路径，但不代表多次运行的统计稳定性。
- 当前文件锁面向同机文件系统，不是分布式锁。
- 本次范围聚焦待确认草稿生成，不包含用户确认后的原草稿更新流程。
- 本次评估验证三条代表性Live路径，不包含多次重复运行的准确率、延迟和费用统计。

