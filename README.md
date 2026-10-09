# 烛龙 Zhulong 🐉

**开眼即观测。** Hermes Agent 的自我观测 + 自校准层 —— 把 agent 的行为流落成一本可对账的日记，把它的预测与结果对成一本校准账。

> 「钟山之神，名曰烛阴……其瞑乃晦，其视乃明。」——《山海经·大荒北经》

## 这是什么

Zhulong 是 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的插件，做两件事：

1. **观测（S2）**：订阅 11 个 observer hooks，把每个生命周期事件规范化、脱敏、写入本地日记（JSONL + SQLite）。
2. **校准（S3）**：登记 agent 的预测/声明（工具 `zhulong_predict`），由**机械核验器或人工**结算，产出 Brier / ECE / 命中率 / 弃答统计与历史快照。

这是「自我觉醒」工程阶梯的 A1（自感知）→ A3（自校准）。关键纪律：**agent 永远不能给自己的预测打分**。

## 原则（写死，不妥协）

- **仅观测**：不修改对话、不改 system prompt、零 LLM 调用。
- **失败开放**：任何回调异常都吞掉，绝不阻塞或影响主循环。
- **隐私优先**：只存元数据（名称/状态/耗时/大小/字段名），不存正文。
- **不可自证**：预测结算只来自机械核验器或人工命令（逻辑学约束：反自证）。
- **数据本地**：全部落在 `$HERMES_HOME/zhulong/`。

## 安装

```bash
bash scripts/install.sh          # 复制到 ~/.hermes/plugins/zhulong
hermes plugins enable zhulong    # 加入 allow-list
```

新版 Hermes 会热加载到运行中的网关（已实证）；旧版本重启后生效。

## 使用

```
/zhulong status                       # 概况（事件 + 校准 + 反思/探针）
/zhulong tail 30                      # 最近 30 条事件
/zhulong calibrate [run|list|resolve] # 校准账
/zhulong reflect [run]                # 反思 digest（查看/立即生成）
/zhulong probes [run]                 # 探针（历史/立即运行）
```

Agent 侧工具：

```
zhulong_predict(claim, confidence?, verify?)    # 登记预测
zhulong_calibration(action=report|run|list)     # 读账/对账
```

## 校准账（S3）

**核验器**（`verify` 参数，全部机械、零 LLM）：

| 类型 | 参数 | 语义 |
|---|---|---|
| `file_exists` | `path` | 文件出现 → 真 |
| `file_contains` | `path`, `text`, `max_bytes?` | 文件包含文本 → 真 |
| `journal_event` | `match:{event,name,status}`, `within_seconds?` | 窗口内出现匹配事件 → 真 |
| `manual` | — | 人工 `/zhulong calibrate resolve` 裁决 |
| `shell` | `command`, `timeout?` | **默认关闭**（安全）；`config.json` 里 `allow_shell_verifiers: true` 开启 |

**结算规则**：真 → 立即结算；假 → 等到 `deadline_seconds`（默认 3600s）之后才结算 —— "还没发生"绝不等于"没发生"。

**指标**：Brier（越低越好）、ECE（5 档校准误差）、命中率、弃答计数（confidence 省略 = 弃答，不计分）；每日快照写入 `calib_metrics` 表，可看趋势。

## 数据布局

```
~/.hermes/zhulong/
├── journal/events-YYYY-MM-DD.jsonl   # 事件真源（append-only）
├── zhulong.db                        # SQLite：events / predictions / calib_metrics / probe_runs / tasks / llm_daily
├── reflections/                      # digest-YYYY-MM-DD.md、PROPOSALS.md
└── config.json                       # 可选，见下
```

## 反思与探针（S4）

- **每日 digest（确定性）**：后台调度在每天第一次运行时为「昨天」生成 `reflections/digest-<day>.md`（事件构成、工具统计、错误明细、校准账）。也可 `/zhulong reflect run` 立即生成今日版。
- **模型复盘（可选，默认开）**：`ctx.llm` 单次调用，产出「观察/提案/不确定」三段，写入 digest 且标注**未经核验**；提案追加到 `reflections/PROPOSALS.md` 供人工审阅（永不自动执行）。
- **自省探针（每周一自动，可配）**：10 项电池（6 知识题 + 2 未知题 + 1 假前提 + 1 定性自述），机械判分，产出 Brier/命中/弃答，存 `probe_runs`。
- **预算**：全部插件发起的 LLM 调用共享 `llm_daily_cap`（默认 40/日），超限自动跳过；跨进程任务认领（`tasks` 表）防止重复运行。

```json
// ~/.hermes/zhulong/config.json（可选）
{
  "allow_shell_verifiers": false,
  "llm_daily_cap": 40,
  "probe_weekday": 0,
  "probe_hour": 9,
  "narrative": true,
  "scheduler": true
}
```

## 路线图

- ✅ v0.1.0（S2）：观测脊柱
- ✅ v0.2.0（S3）：校准账
- ✅ v0.3.0（S4）：反思引擎 + 自省探针（本次）
- ⏳ S5：自我模型 + `/zhulong model` + 周报投递

## License

MIT © 2026 YG
