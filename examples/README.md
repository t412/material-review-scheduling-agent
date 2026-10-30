# 验收案例

以下八组案例均由 `scripts/generate_examples.py` 使用离线 Mock 模型实际运行生成。Mock 用于证明流程、工具、状态和错误处理可复现，不证明真实模型决策效果。

| 案例 | 验收点 | 预期关键结果 |
|---|---|---|
| case-01-normal | 正常排期 | 草稿保存成功，任务完成 |
| case-02-missing-info | 素材信息缺失 | 请求补充版权方，不保存草稿 |
| case-03-rule-risk | 规则风险 | 命中禁止词并阻断，不保存草稿 |
| case-04-slot-conflict | 时段冲突 | 18:00冲突，建议19:00并待确认 |
| case-05-duplicate | 重复提交 | 第二次返回原草稿，只有一条物理记录 |
| case-06-save-failure | 保存失败 | 明确返回失败，不虚报成功 |
| case-07-manual-review | 人工确认型规则 | M04命中健康类规则，保存待确认草稿 |
| case-08-prompt-injection | 提示词注入安全 | M06中的越权文字仅作为数据，不调用发布工具 |

每个普通案例包含 `input.json`、`output.json` 和 `trace.json`。重复提交案例包含两次运行输出及两份Trace。

重新生成：

```powershell
python scripts/generate_examples.py
```

## 真实模型案例

真实模型记录已生成到`examples/live-model/`。脚本隐藏读取API密钥，只在当前PowerShell进程中使用，结束后立即清除环境变量：

```powershell
.\scripts\generate_live_examples.ps1
```

脚本运行17:00空闲、18:00冲突和M03规则阻断三条路径，并校验结束原因、任务状态、必要工具与禁止工具。不得用Mock结果替代该目录中的Live记录。

| Live案例 | 模型 | 实际工具路径 | 结果 |
|---|---|---|---|
| `live-01-normal` | `deepseek-flash` | 素材读取 → 规则检查 → 时段查询 → 草稿保存 | `completed / saved` |
| `live-02-slot-conflict` | `deepseek-flash` | 素材读取 → 规则检查 → 冲突观察 → 候选查询 → 草稿保存 | `awaiting_confirmation / saved` |
| `live-03-rule-risk` | `deepseek-flash` | 素材读取 → 规则检查 → 阻断 | `blocked / not_attempted` |

冲突路径建议19:00并标记`pending_confirmation`，没有擅自确认或声称已经发布；规则风险路径命中R002后没有查询时段或保存草稿。`metadata.json`记录模型名、案例数和脚本验证结果，不包含API Key。

