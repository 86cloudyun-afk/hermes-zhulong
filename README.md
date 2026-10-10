# 烛龙 Zhulong 🐉

**开眼即观测。** Hermes Agent 的观测、校准与自主核心：从授权事实中形成自己的目标，通过 Hermes 执行，再由机械验收和持久账本决定结果、学习及恢复。

> 「钟山之神，名曰烛阴……其瞑乃晦，其视乃明。」——《山海经·大荒北经》

## 这是什么

Zhulong 是 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的插件，包含三个组成部分：

1. **观测（S2）**：订阅 11 个 observer hooks，把每个生命周期事件规范化、脱敏、写入本地日记（JSONL + SQLite）。
2. **校准（S3）**：登记 agent 的预测/声明（工具 `zhulong_predict`），由**机械核验器或人工**结算，产出 Brier / ECE / 命中率 / 弃答统计与历史快照。

3. **自主核心（v0.5）**：观察配置来源、合成可验证目标、持久提交、独立核验及维护有样本分母的自我模型；增加受监督运行与 Docker 执行边界。配置启用后，日常闭环无需逐项人工评分。

这是可测试的功能自我模型，测试不证明主观意识。关键纪律：**agent 永远不能给自己的预测打分**。

## 原则（写死，不妥协）

- **观测 hooks 仅记事实**：原有 11 个 hooks 不修改对话、不发起模型调用；独立自主控制层按配置发起规划和执行。
- **失败开放**：任何回调异常都吞掉，绝不阻塞或影响主循环。
- **数据范围明确**：观测只存元数据；自主账本另存自己形成的最小目标意图、冻结验收和证据，不采集工具正文、原始聊天或私有推理。
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
/zhulong model                        # 证据型自我模型
/zhulong autonomy status              # 自主状态
/zhulong autonomy goals               # 最近目标
/zhulong autonomy tick                # 推进一次有界循环
/zhulong autonomy pause               # 暂停新合成/派发，继续对账
/zhulong autonomy resume              # 恢复配置允许的工作
/zhulong autonomy cancel <id>         # 持久取消意图并跟踪在途状态
```

Agent 侧工具：

```
zhulong_predict(claim, confidence?, verify?)    # 登记预测
zhulong_calibration(action=report|run|list)     # 读账/对账
zhulong_model()                               # 只读自我模型
zhulong_autonomy(action=status|goals|tick)     # 不提供直接评分/改验收入口
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
├── autonomy.db                      # goals/submissions/evidence/预算/模型版本真源
├── self_model.json                   # 原子导出；可由账本重建
└── config.json                       # 配置，见下
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
- ✅ v0.4.0：自主目标闭环、可靠恢复、自我模型和 `/zhulong model`
- ✅ v0.5.0：受监督运行、原生 Docker 边界和恢复测试
- ✅ v0.6.0：失败证据学习、策略复用、独立任务验证晋升和失败自动退役
- ⏳ 后续：周报投递、真实外部事务、控制内核自动晋升与长期测试

## License

MIT © 2026 YG

## 启用自主核心

默认 `autonomy.enabled=false`。将 [示例配置](examples/autonomy-config.json) 改为实际授权路径、事实来源、验收及本地 API 地址，再放到当前 profile 的 `zhulong/config.json`。示例没有秘密或个人资料，路径是占位符。输入来源提供事实，例如失败测试统计、阅读进度、可用时段；模型自行生成候选，不能创建自己的权限或验收规则。

执行端需运行支持持久幂等的 Hermes API server。当前验证宿主固定为 `73162b00eefde3794bed0afb53d84a19c0eed230`；启动方式为该 profile 的 `hermes gateway run`。使用 `API_SERVER_KEY` 环境变量配置 API 认证，它不同于模型凭据 `DEEPSEEK_API_KEY`。模型配置沿用 `deepseek / deepseek-flash`；不要把密钥写进示例或 Git。API 必须宣告 run 提交、状态、stop 及 durable idempotency；缺少支持则受阻。

`api_identity_version` 是部署维护的非秘密版本；认证命名空间、profile 或凭据变化时必须更新。它不自动证明凭据连续性；不能维护该版本的部署无法承诺未决提交的安全重放。`api_profile` 是冻结的执行身份标签，不是自行切换宿主 profile 的 API 参数。

默认每日新 run 8 次、同时 1 个、候选最多 3 个、租约 120 秒、目标期限 600 秒、独立尝试最多 3 次。共享辅助模型调用默认 40 次/日，零表示停用。一次 tick 至多 20 个目标操作和一次新 submission；积压受阻工作轮转，模型、HTTP 和检查在数据库写锁之外。源事实和验收 / 方向的相关变化形成新版本；相同输入不反复规划。`input_fields` 可从 JSON 选取相关字段，避免无关噪声触发工作。

机械验收支持 `file_contains`、`json_equals`、显式可信的 `argv`。文件和输出最多 64 KiB，argv 默认 15 秒且不用 shell。已有产物记为 `already_satisfied`，不派发或计能力成功；要求变化的契约比较初始 hash。研究字段 / 格式验收只覆盖约定范围，不能据此声称论文结论普遍正确；个人场景是本地草案，未接真实日历 / 邮箱。

`pause` 只暂停新工作。相同 submission 的恢复不消耗新尝试或预算；响应丢失在保留窗口内重放原请求。`interrupted`、stop accepted 和缺少产物都不能证明没有迟到副作用；未知在途执行保留名额。审批终止后的旧目标保持受阻，不自动重发；新来源 / 契约版本可以形成新目标。过期重放或身份连续性不明时记录 `unknown_result`，避免盲目重复动作。正常宿主结果与独立验收都完成后才结算可信结果。

自我模型展示领域 / 执行身份范围、可信样本、未知、受阻、首次 / 累计成功、Brier/ECE 及错误置信度。零样本明确未知，单一标签时错误区分指标不可用。历史影响目标选择；反思仍是有来源和适用范围的假设。`SelfModel.restore(version)` 只恢复导出快照，保留原始结果；下一次刷新从最新证据重建。

## 经验学习（v0.6）

自主核心默认启用经验学习，`autonomy.learning_enabled=false` 关闭新生成与新请求检索，既有提交仍使用原冻结请求恢复。停止、暂停、共享预算耗尽时不新增学习模型调用；每 tick 最多一次，每失败 submission 最多两次，预算不足不吃掉生成重试。

机械失败且执行已静止后，`ctx.llm` 生成最多 600 字符的策略假设。账本固定其来源、正文 hash 和 source/domain/contract/执行身份范围；执行请求最多携带两条相关策略。原失败重试成功不算迁移，两项后续独立目标首次机械成功才晋升为 active。可靠的复用失败自动退役，未知结果不晋升、不伪造失败。策略始终是提示经验，不能修改验收、权限或预算。

`/zhulong autonomy experience` 或 `zhulong_autonomy(action="experience")` 查看状态，自我模型也导出经验版本。运行数据仅在 profile 的 `autonomy.db`；原生 skills 目录保持受控。若模型、工具实现或执行策略改变，应更新部署的非秘密 `api_identity_version`，避免误用旧范围证据；受监督部署同时检查固定代码/config hash。

研究、工程路线和局限见 [本轮研究](docs/research/2026-10-10-evidence-learning.md)。真实模型生成与一次新任务复用不证明因果改善、跨领域通用技能或主观意识。

## 强制规则实现

技能文档和提示词负责描述意图。插件的 SQLite 事务、不可变字段触发器、租约代次、原子预算和验收接口负责约束自身状态与派发。模型不能通过公开插件工具直接把任务标成成功、降低验收或绕过预算。所有提交状态写入还比较当前 submission ID，防止旧快照结算新执行；命令验收可能读取 cwd 外的路径，因此同一账本中的 argv 验收执行保守串行，避免跨任务认领成果。

插件所在的 Python 进程与执行器仍需可信部署。Hermes 普通 Runs 没有请求级 workspace 沙箱；profile、cwd、路径检查或审批提示不能替代文件 / 进程 / 网络权限。v0.5 提供 [受监督部署入口](docs/deployment/supervised-runtime.md)：验证实际模型工具权限，把终端动作放入非 root、无网络、只读根、有限资源的原生 Docker worker，保护控制文件和只读源事实。默认插件安装仍不自行创建此部署；可信宿主/插件 Python 与 Docker daemon 处于隔离边界之外。

受监督部署只接受数据型验收，拒绝宿主 `argv` 执行模型生成代码。进程级测试覆盖重复/孤儿锁、持久重启预算、停止顺序、错误 boot 及丢回复后的唯一副作用；有限测试不代表长期可用率。详细命令、资源/磁盘限制及 Linux 常驻示例见部署文档。

## 验证

```bash
python3 -m unittest discover -s tests -v
# 使用固定宿主官方 PM Python；通用 CI 不安装宿主，相关集成测试显式 skip。
python scripts/host_smoke.py --hermes-root /path/to/hermes-agent
HERMES_AGENT_ROOT=/path/to/hermes-agent python -m unittest discover -s tests -p test_host_smoke.py -v
# 下面会产生实际 DeepSeek 消耗，并在临时 profile 中启动/关闭自己的网关。
python scripts/live_autonomy_smoke.py --hermes-root /path/to/hermes-agent --report /tmp/zhulong-live.json
```

GitHub Actions 覆盖 Python 3.11 / 3.12 / 3.14。模拟多领域与故障测试、离线真实宿主 smoke、付费真实模型及工具验证分别报告；长期稳定性只在实际运行后宣称。研究与规格在 [研究正文](docs/research/2026-10-09-cross-disciplinary-autonomy.md)和 [设计规格](docs/superpowers/specs/2026-10-09-autonomous-core-design.md)。当前 v0.5 证据见[验证记录](docs/research/2026-10-10-v0.5-validation.md)及[审查闭环](docs/research/2026-10-10-v0.5-review.md)；v0.4 历史证据保留在 docs/research 中。
