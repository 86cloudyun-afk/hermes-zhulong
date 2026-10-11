# 烛龙 Zhulong 🐉

**开眼即观测。** Hermes Agent 的观测、校准与自主核心：从授权事实中形成自己的目标，通过 Hermes 执行，再由机械验收和持久账本决定结果、学习及恢复。

> 「钟山之神，名曰烛阴……其瞑乃晦，其视乃明。」——《山海经·大荒北经》

## 这是什么

Zhulong 是 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的插件，包含三个组成部分：

1. **观测（S2）**：订阅 11 个 observer hooks，把每个生命周期事件规范化、脱敏、写入本地日记（JSONL + SQLite）。
2. **校准（S3）**：登记 agent 的预测/声明（工具 `zhulong_predict`），由**机械核验器或人工**结算，产出 Brier / ECE / 命中率 / 弃答统计与历史快照。

3. **自主核心（v0.11）**：观察配置来源、合成可验证目标、持久提交和独立核验；在受监督 Docker 边界内执行可信步骤 DAG、有界干预诊断和派发前复查，维护有样本分母的自我模型。可选认知工作空间进一步支持事前预测和注意力控制，限定语言证书约束准入及实际执行。配置启用后，日常闭环无需逐项人工评分。

这是可测试的功能自我模型，测试不证明主观意识。关键纪律：**agent 永远不能给自己的预测打分**。

## 原则（写死，不妥协）

- **观测 hooks 仅记事实**：原有 11 个 hooks 不修改对话、不发起模型调用；独立自主控制层按配置发起规划和执行。
- **观测回调失败开放**：observer 回调异常不阻塞主循环；生产状态审计失败或不可用时，拒绝新的 admission 和技能正向激活，保留取消、恢复和清理。
- **数据范围明确**：观测只存元数据；自主账本另存最小目标意图、冻结验收和证据。v0.8 可显式授权有限业务 JSON 字段存入私有账本；默认不捕获，不采集工具正文、原始聊天或私有推理。
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
/zhulong autonomy experience          # 策略经验与证据范围
/zhulong autonomy skills              # 可执行技能版本与状态
/zhulong autonomy workflows           # 持久步骤、依赖与效果状态
/zhulong autonomy diagnostics         # 有界干预诊断与证据等级
/zhulong autonomy cognition           # 工作空间配置、帧/绑定数量与交付计数
/zhulong autonomy assurance           # 当前状态对应审计 + 有限模型/轨迹检查
/zhulong autonomy tick                # 推进一次有界循环
/zhulong autonomy pause               # 暂停新合成/派发，继续对账
/zhulong autonomy resume              # 恢复配置允许的工作
/zhulong autonomy cancel <id>         # 持久取消意图并跟踪在途状态
```

Agent 侧工具：

```
zhulong_predict(claim, confidence?, verify?)    # 登记预测
zhulong_calibration(action=report|run|list|reflect|probes|run_probes)
zhulong_model()                               # 只读自我模型
zhulong_autonomy(action=status|goals|tick|experience|skills|workflows|diagnostics|assurance|cognition)
```

仍为 **4 个工具、11 个观测 hooks、1 个命令入口**。`zhulong_autonomy` 有上述 9 个 actions；暂停、恢复和取消由 `/zhulong autonomy` 命令操作。工具不提供直接评分或修改验收入口；`assurance` 运行有限模型、旧轨迹与当前 refinement 审计；普通 `status` 读取当前真实 SQLite 状态并执行新的 refinement 审计，有限模型部分仍展示已有记录。

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
├── autonomy.db                      # goals/submissions/evidence/预算/refinement journal/认知帧真源
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
- ✅ v0.7.0：独立 Docker 可执行程序评测、不可变版本发布、冻结请求复用和失败回退
- ✅ v0.8.0：授权结构化输入冻结、原目标字段回归和严格原生执行证据
- ✅ v0.9.0：完整参考 JSON 验收、持久步骤 DAG/本地 outbox、有界干预诊断、尝试级元认知和有限状态保证
- ✅ v0.10.0：独立生产状态对应与同事务准入/发布门槛、可选限容量认知工作空间；430 项真实宿主/Docker 测试通过，单次 DeepSeek 原生集成验收成功
- v0.11.0：前瞻注意力、工单 DSL 证书及受保护执行、真实配对研究驱动和实际时钟记录；组件审查与部署证据分别记录
- ⏳ 后续：周报投递、真实外部事务、控制内核自动晋升与长期测试

五条研究线和历史证据见 [完整执行、根因、因果提升、意识与正确性](docs/research/2026-10-11-autonomy-frontiers.md)；当前实现、部署入口与未完成项目见 [工程清单](docs/deployment/engineering-closure.md)。v0.11 的[核心研究](docs/research/2026-10-11-core-evidence-research.md)与[独立审查](docs/research/2026-10-11-v0.11-review.md)区分产品实现、实际执行和未知结论。真实配对驱动在 `scripts/native_paired_trial.py`，有限业务 pilot 仍在 `scripts/native_work_acceptance.py`；结果须按冻结协议及实际运行单独记录。v0.10 的[认知与 refinement 研究](docs/research/2026-10-11-cognition-refinement-research.md)及其[证据包](docs/research/evidence/2026-10-11-cognition-refinement/artifact-manifest.json)保留历史结论。

v0.11 的[实际验证](docs/research/2026-10-11-v0.11-validation.md)记录最新 582 项 Hermes／Docker 实机检查全部通过、第三批原生任务六格成功，以及两个先前停止批次的完整未知分母。远程三版本 Python CI 与首次 formal CI 的实际结果分别保留。Lean 已证明形式 typed 检查器的一般行 soundness，并通过独立干净重放；[证明范围](docs/research/evidence/2026-10-11-core-kernel/formal-model-proof.json)明确保留 JSON／Python／列表输出／原生执行的对应缺口。固定证明源码和[可复现入口](formal/ticket-kernel/README.integration.md)已通过独立包装审查及实际干净重建。

## License

MIT © 2026 YG

## 启用自主核心

默认 `autonomy.enabled=false`。将 [示例配置](examples/autonomy-config.json) 改为实际授权路径、事实来源、验收及本地 API 地址，再放到当前 profile 的 `zhulong/config.json`。示例没有秘密或个人资料，路径是占位符。输入来源提供事实，例如失败测试统计、阅读进度、可用时段；模型自行生成候选，不能创建自己的权限或验收规则。

执行端需运行支持持久幂等的 Hermes API server。当前验证宿主固定为 `73162b00eefde3794bed0afb53d84a19c0eed230`；启动方式为该 profile 的 `hermes gateway run`。使用 `API_SERVER_KEY` 环境变量配置 API 认证，它不同于模型凭据 `DEEPSEEK_API_KEY`。模型配置沿用 `deepseek / deepseek-flash`；不要把密钥写进示例或 Git。API 必须宣告 run 提交、状态、stop 及 durable idempotency；缺少支持则受阻。

`api_identity_version` 是部署维护的非秘密版本；认证命名空间、profile 或凭据变化时必须更新。它不自动证明凭据连续性；不能维护该版本的部署无法承诺未决提交的安全重放。`api_profile` 是冻结的执行身份标签，不是自行切换宿主 profile 的 API 参数。

默认每日新 run 8 次、同时 1 个、候选最多 3 个、租约 120 秒、目标期限 600 秒、独立尝试最多 3 次。共享辅助模型调用默认 40 次/日，零表示停用。一次 tick 至多 20 个目标操作和一次新 submission；积压受阻工作轮转，模型、HTTP、Docker 和文件验收在数据库写锁之外；refinement 的纯 SQLite 状态检查与被许可的正向写入在同一事务内。源事实和验收 / 方向的相关变化形成新版本；相同输入不反复规划。`input_fields` 可从 JSON 选取相关字段，避免无关噪声触发工作。

机械验收支持 `file_contains`、`json_equals`、`json_reference`、显式可信的 `argv`。文件和输出最多 64 KiB，argv 默认 15 秒且不用 shell。`json_equals` 使用整文件严格 JSON 解析，拒绝重复键、非有限数及超过 32 层的业务 JSON，比较时区分布尔、整数与浮点类型；检查版本为 2，旧收据保留。

`json_reference` 从已授权冻结输入计算整份期望业务结果，支持 `workload_summary_v1`（工作量汇总）、`ticket_priority_v1`（工单排序）、`source_index_v1`（来源索引）。来源须显式设置 `persist_input_fields`，契约包含 `path`、`reference_id`、`reference_version: 1` 和可选 `require_change`/`safe_retry`；执行请求提供规则和授权输入，私有核验器计算答案。缺少有效输入绑定为 unknown。配置示例和限制见 [工程清单](docs/deployment/engineering-closure.md#部署使用)。

已有产物记为 `already_satisfied`，不派发或计能力成功；要求变化的契约比较初始 hash。研究字段 / 格式验收只覆盖约定范围，不能据此声称论文结论普遍正确；个人场景是本地草案，未接真实日历 / 邮箱。

`pause` 只暂停新工作。相同 submission 的恢复不消耗新尝试或预算；响应丢失在保留窗口内重放原请求。`interrupted`、stop accepted 和缺少产物都不能证明没有迟到副作用；未知在途执行保留名额。审批终止后的旧目标保持受阻，不自动重发；新来源 / 契约版本可以形成新目标。过期重放或身份连续性不明时记录 `unknown_result`，避免盲目重复动作。正常宿主结果与独立验收都完成后才结算可信结果。

自我模型展示领域 / 执行身份范围、可信样本、未知、受阻、首次 / 累计成功、Brier/ECE、AUROC2、confidence gap 和 coverage-risk。旧 `error_discrimination` 字段只表示指标可计算性；质量另由带正负样本数的指标报告。每次派发前冻结同范围历史估计和监控决策，低概率时可按可信配置执行有界前置复查。零样本为 prior_only，单一标签时 AUROC2 不可用。历史影响目标选择；反思仍是有来源和适用范围的假设。`SelfModel.restore(version)` 只恢复导出快照，保留原始结果；下一次刷新从最新证据重建。

## 认知工作空间与生产状态对应

`autonomy.cognition` 可选且默认关闭；省略时保持原规划路径。以下对象放在现有 `autonomy` 对象内，不能替代来源、契约或部署权限配置：

```json
{
  "cognition": {
    "enabled": false,
    "capacity": 3,
    "ttl_seconds": 120,
    "mask_consumer": null,
    "selection_mode": "adaptive"
  }
}
```

capacity 为 1–8 个来源，TTL 为 1–3600 秒；mask 为 null/planner/executor/monitor，selection_mode 为 adaptive/constant。启用后 Planner 只接收选中的 observations，并移除可能泄露未选事实的 experience、commitments、policy hypotheses 和非 source-scoped 聚合。adaptive 使用持久选择历史轮换，constant 稳定取前 K；容量和预测描述软件调度，不构成完整 GWT 或 AST。

帧、goal 绑定和消费收据不可后改，保存来源/revision/input/facts 摘要与机制身份；默认不新增 raw facts、prompt 或 tool body 的长期存储。TTL 限制新规划，已有 goal 的历史绑定用于恢复，不能称为最新事实。消费者收据标记 `delivered_context_only`：它证明具体上下文交付和请求绑定，不证明模型理解或内部注意。mask 随帧冻结，只遮指定消费者的新增工作空间渠道；executor 的固定业务输入、验收契约、source_path 和合法工具权限保留，因此不是全部信息消融。干预/恢复须使用分别声明的匹配帧，不改写旧帧。

新的 refinement checker 从 typed journal 独立重建 covered state，在同一 SQLite snapshot 比较 paused、run_budget、goals/lease/attempt/submission/固定身份和 evidence/final truth。普通 status 展示当前审计；`valid_within_scope`、`counterexample` 和 `unavailable` 与旧有限 BFS／recorded trace 各自独立。检查超限、缺日志或损坏不转换成通过。legacy checkpoint 只是可信观察起点，不证明此前历史。

新 admission、技能发布和正向 fallback activation 在写入事务内执行 gate；counterexample/unavailable 拒绝新正向动作，不新扣预算或启动 run，但 cancel/stop/reconcile/cleanup、旧结果真实结算和负向退役继续。checker/SQLite/保护代码及合法 mutation hooks 仍是可信边界；审计不证明 verifier 正确性、OS 静止、全部 workflow/skill 决策、诊断预算、外部效果或任意 Python 总正确性。`settled` 和 Runs 完成状态也不是独立 quiescence certificate。

v0.10 的[验证记录](docs/research/2026-10-11-v0.10-validation.md)绑定干净代码 `50acabe`：430 项真实宿主/Docker 测试全部通过，单个预登记 DeepSeek 原生任务完成业务、执行审计、结算和清理；[独立审查记录](docs/research/2026-10-11-v0.10-review.md)保留发现与修复。v0.9 结果继续作为历史证据。单次集成验收不建立因果收益，尚未运行长程测试；当前机制不提供主观体验 oracle、意识概率或通用正确性 theorem。

## 经验学习（v0.6）

可执行技能的工程入口见 [部署文档](docs/deployment/executable-skills.md) 和 [v0.8 研究记录](docs/research/2026-10-10-frozen-input-replay.md)。可信清单默认为空；程序从机械失败生成，在独立无网络容器中通过回归和未公开例后发布。启用 `persist_input_fields` 后，在形成目标的同一次观察中冻结授权投影；`replay_origin: true` 要求候选同时通过原目标 `json_equals` 字段条件。普通状态仅显示快照 hash/大小。宿主不执行候选代码，原生 skills 保持空 RO；绑定版本失败时退役并回退。有限测试和目标自主执行不建立主观意识或通用正确性。

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
