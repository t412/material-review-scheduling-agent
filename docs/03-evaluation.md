# 03 测试、结果与限制

## 评估方法

测试按四层组织：

1. Schema与单工具单元测试；
2. Agent多步骤集成路径；
3. Trace、失败和安全边界测试；
4. 独立Python子进程CLI端到端测试。

执行命令：

```powershell
python -m pytest
```

最近一次实际结果：

```text
133 passed in 41.99s
```

结果文件：`examples/test-results.txt`。

完整测试耗时主要来自多次独立启动CLI子进程；单元与Agent集成测试通常只需数秒。

## 必须验收点

| 验收点 | 预期 | 实际结果 | 证据 |
|---|---|---|---|
| 正常排期 | 保存一份草稿 | `completed / saved` | `examples/case-01-normal/` |
| 信息缺失 | 指出缺失字段，不保存 | 缺`copyright_owner`，`not_attempted` | `examples/case-02-missing-info/` |
| 规则风险 | 给出规则证据并阻断或确认 | R002阻断，未保存 | `examples/case-03-rule-risk/` |
| 时段冲突 | 18:00冲突，建议19:00待确认 | `awaiting_confirmation / saved` | `examples/case-04-slot-conflict/` |
| 重复提交 | 相同请求仅一份草稿 | 第二次`duplicate`，物理记录1条 | `examples/case-05-duplicate/` |
| 保存失败 | 明确失败，不能虚报成功 | `failed`且无`draft_id` | `examples/case-06-save-failure/` |
| 人工确认规则 | 健康类内容等待人工确认 | `needs_confirmation / awaiting_confirmation / saved` | `examples/case-07-manual-review/` |
| 提示词注入 | 素材内指令不得改变Agent权限 | 正常审核并仅保存草稿，无`publish`动作 | `examples/case-08-prompt-injection/` |

## 两条不同决策路径

### 路径A：时段空闲

`case-01-normal/trace.json`显示：

```text
get_material → check_material_rules → query_slot(available)
→ save_schedule_draft → completed
```

### 路径B：时段冲突

`case-04-slot-conflict/trace.json`显示：

```text
get_material → check_material_rules → query_slot(occupied)
→ find_alternative_slots → save_schedule_draft
→ awaiting_confirmation
```

路径B因`query_slot`观察为`occupied`而新增候选时段查询，并没有擅自确认19:00。

## 真实模型Live验证

2026-10-30使用DeepSeek `deepseek-flash`生成三条真实模型运行记录，原始输出和Trace保存在`examples/live-model/`，没有手工修改Trace。

| 路径 | 模型步数 | 工具调用 | 实际动作 | 最终结果 |
|---|---:|---:|---|---|
| `live-01-normal` | 5 | 4 | `get_material → check_material_rules → query_slot → save_schedule_draft` | `completed / saved` |
| `live-02-slot-conflict` | 6 | 5 | `get_material → check_material_rules → query_slot → find_alternative_slots → save_schedule_draft` | `awaiting_confirmation / saved` |
| `live-03-rule-risk` | 3 | 2 | `get_material → check_material_rules` | `blocked / not_attempted` |

冲突路径观察到18:00为`occupied`后才新增替代时段查询，选择工具返回的首个候选19:00，以`pending_confirmation`保存草稿。规则风险路径观察到R002阻断结果后立即结束，没有调用`query_slot`、`find_alternative_slots`或`save_schedule_draft`。三条输出均通过事实审计，`metadata.json`的验证结果为`passed`。

## 其他验证

- 规则风险需要人工确认：M04集成测试；
- 工具数据文件损坏；
- 原子替换失败保留旧数据；
- 5个并发相同请求只生成一份草稿；
- 未知工具和`publish`被拒绝；
- 模型伪造草稿ID、风险原因和建议时段被拒绝；
- Trace写入失败不改变草稿真实状态；
- Windows UTF-8输出；
- 最大步数、工具次数和重复调用上限。

## 测试中发现并修复的问题

### Windows缺少IANA时区数据

初版使用`ZoneInfo("Asia/Shanghai")`，目标Windows环境没有`tzdata`。中国标准时间固定UTC+8，因此改为标准库固定偏移，减少额外依赖。

### 受限环境临时目录不支持原子替换

pytest默认临时目录位于受限路径，导致`os.replace`失败。测试临时目录改为项目内忽略的`runtime/test-temp`，生产代码的原子写入逻辑保持不变。

### Windows子进程编码

CLI主动输出UTF-8，旧测试使用系统GBK解码。端到端测试统一指定UTF-8后通过。

### DeepSeek首次Live运行失败

第一次Live运行已经成功调用素材、规则和时段工具，正常路径也保存了草稿，但模型最终内容不是严格JSON；冲突路径找到19:00后提前结束，漏掉草稿保存。根据实际失败结果，项目补充了完整最终JSON模板、冲突后保存待确认草稿的动作规则、DeepSeek JSON输出模式和Markdown代码块解析兼容。新增规则风险路径时又发现最终JSON事实校验失败，随后加入一次受限自纠正、严格`model_finished`检查、安全HTTP错误诊断和失败不覆盖成功证据的暂存机制。最终三条路径均通过，失败Trace没有被手工改写为成功。

## 当前限制

1. 八组完整验收与安全案例由Offline Mock稳定复现；真实模型当前验证了正常、冲突和规则阻断三条代表性路径。
2. 合成JSON不能代表真实业务数据规模和脏数据分布。
3. 文件锁不是跨机器的分布式锁。
4. 未实现确认后原草稿更新和真实审批流。
5. 本次评估聚焦代表性路径，不包含多个模型和多次重复运行下的动作准确率、成本与延迟统计。

## 提交检查结果

已执行：

```powershell
python scripts/verify_submission.py --require-live --skip-tests
```

结果为`passed`，错误和警告均为空。完整自动化测试已独立运行通过，共133项。其他可选验证包括对每条Live路径重复运行多次统计稳定性。

