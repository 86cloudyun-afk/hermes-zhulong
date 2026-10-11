# 五专题工程与历史问题清单（v0.11）

这份清单区分已实现接口、实际验收和仍需外部条件的目标。v0.11 的研究依据、冻结判据及理论限制见 [核心内核研究](../research/2026-10-11-core-evidence-research.md)与[独立审查](../research/2026-10-11-v0.11-review.md)。v0.10 的[认知与 refinement 研究](../research/2026-10-11-cognition-refinement-research.md)及[证据索引](../research/evidence/2026-10-11-cognition-refinement/artifact-manifest.json)保留历史结论。真实 Hermes 的能力证据见版本对应的验证记录；本地夹具、Docker 程序评测、有限模型检查和付费原生任务分别计数。

## 已实现的工程机制

| 研究线/问题 | 产品实现 | 验收入口 | 保证范围 |
|---|---|---|---|
| 主 JSON 验收与严格回放不一致 | `autonomy_checks.py` check_version=2 | JSON 重复键、NaN/Infinity/指数溢出、布尔/数值、深度回归 | 整文件严格解析，旧收据不重写；深度 32 是本版明确限制 |
| 固定答案可伪装完成 | `work_reference.py` / `json_reference` | 三种变量业务输入及原生执行审计 | 私有参考计算整份结果；不保证任意自然语言任务 |
| 步骤依赖、崩溃重做 | `workflow.py` + Controller | DAG/事务/并发/重启/取消测试 | 可信有界 DAG、每步 Hermes 子目标、局部 safe_retry；没有自由生成无限重规划 |
| 外部效果与 run 幂等混淆 | `workflow_effects` / `workflow_outbox` | 双意图冲突、事务回滚、重复恢复 | 本地 outbox 一次写入；远程效果与投递继续明确 unknown/unavailable |
| 解释文字被当作根因 | `diagnostics.py` | 独立 Docker 双因素、负对照、原输入重放 | 配置干预的有限支持；模型叙述只是假设 |
| 未知实验无限重试/关闭配置丢恢复 | 持久实验 reservation/quiescence | 三次尝试、零额度清理、配置移除恢复 | 实际评测次数计预算；清理未知阻止新派发，旧代码/收据保留 |
| 把相关成功当作因果提升 | `causal_trial.py` + `native_trial.py`／配对 CLI | 冻结单机制、全分配顺序、独立 oracle、实际 Planner／请求／工具／产物／结算资格 | N=3 三对六格用于集成；统一 180 秒端点与另行冻结清理宽限，全部分母保留；因果收益需足量可信配对样本，经济收益另需完整成本 |
| 仅离线测试冒充 Hermes 工作能力 | `scripts/native_work_acceptance.py` | `--paid` 真实 LLM 发现目标、Runs、Docker terminal、业务产物审计 | 三个有限业务样例；不证明所有用户任务或长期收益 |
| availability 被当成错误识别能力 | `self_model.py` | 正序/反序/常数 AUROC2、类别与 coverage-risk | 保留兼容 availability 字段，另报告质量、分母和范围 |
| 重试复用旧目标预测 | `metacognition.py` + Ledger | 派发前冻结/陈旧捕获/后验绑定拒绝 | 同范围尝试的历史估计、真实前置复查；不声称内省体验 |
| 暂停与技能发布竞争 | SkillStore 同事务 pause 守卫 | 两种双连接次序、退役与备用恢复 | pause 返回后无新正向激活；旧有效结果和安全负向结算保留 |
| 状态转换可伪造终态 | Ledger 终态守卫 + assurance | unknown→failed/succeeded 反例 | 新终态只由机械收据产生；已有真值的运行跟踪允许 |
| 仅布尔守卫枚举冒充整体正确性 | `assurance.py` | 独立 BFS、八种错误变体、真实事务轨迹 | 显式有限界内不变量；不覆盖诊断预算、任意外部副作用或无限运行 |
| valid recorded trace 被当成真实 SQL state 对应 | `refinement.py` 独立 typed replay + authoritative projection | 当前 audit、合法生命周期、未 journal 修改、双连接和 rollback 验证入口 | 当前 covered state 对应；不是所有未来路径 theorem，legacy checkpoint 前历史不证明 |
| 检查与正向写入之间发生状态漂移 | Ledger / SkillStore 同事务 refinement gate | admission、发布及 fallback 激活拒绝／恢复入口 | 不一致或不可用阻断新正向动作；cancel/reconcile/cleanup 和负向退役保留 |
| 全量上下文绕过输入容量 | 可选 `cognition.py` + Controller selected-only Planner | 实际 Planner 输入、来源资格、上下文旁路与轮换检查入口 | capacity 限来源数，选择是框架级功能；不证明专业模块并行或完整 GWT |
| packet 交付被当作体验或全部信息消融 | immutable frame/goal/consumer receipts + 单消费者 mask | TTL、revision、restart、历史绑定和独立 packet 干预入口 | `delivered_context_only`；executor 固定任务输入和合法工具权限保留；不证明内部注意／体验 |
| 静态选择排序被当作事前预测或注意力控制 | `attention.py` + Controller 全来源观察、不可变 forecast/outcome | 独立后续观测、全部分母、Brier、范围返回／首次启用／空选择与实际路由回归 | adaptive/constant/permuted 可选；等待界限限固定来源、容量和持续资格；历史训练复用不保证平稳性 |
| 有限例测试被当作程序证明 | `certified_ticket.py` 有限 typed AST 与完整区间证书 | 严格解析、覆盖、guard/min、独立 score/priority、变形及篡改检查 | 工单规则内 876,010 数值行的经审阅数学论证；不是机器形式化 Python 证明或任意程序正确性 |
| 检查通过却准入／执行不同代码 | `certified_bindings.py` + 原写事务准入 + 受保护 runner | 当前权威、冻结 goal/input、实际 canonical request 与 native 前台执行关联检查 | 工单证书显式启用，新的单 attempt 部署；同 AST 重查执行；普通契约保持兼容 |
| 重启／迟到结果被当成按时完成或长期稳定 | `cohort.py` + durable launch intent／单端点记录 | journal 身份、不可变收据、认领、时钟／boot 连续性、重启不补发、迟到不升级 | 实际时钟 0/6/24/48/72 小时记录与有界零 provider watch；未到期／错过／未知保留，不证明持续服务或长期收益 |
| 大旧账本被单一快照上限阻塞 | 分页初始 checkpoint | 6500 目标、超过 1 MiB、漏页拒绝 | 不遗漏历史投影；没有以截断来制造有效轨迹 |
| 业务 JSON 与 manifest 封套深度混淆 | skill_evaluator 业务/封套分离 | 深度 32 业务与传输包装 | 各业务值单独验证；封套不压缩业务有效深度 |
| 已验收但未静止的 run 不响应取消 | Controller 取消先于真值跟踪 | 产物成功/执行 interrupted 的取消回归 | 发送停止，保留成功真值与未知 quiescence，不能冒充即时消除副作用 |

## 部署使用

先按 [受监督部署](supervised-runtime.md) 安装固定宿主、官方 PM Python、Docker 和摘要固定镜像，再创建独立授权目录。插件安装不会自动开启自主运行；必须有真实来源、任务方向和契约。`json_reference` 来源显式设置 `persist_input_fields`，业务内容只冻结到私有账本。

以下是 `autonomy.sources` 中单个来源的配置示例；路径需位于预先授权的 `workspace_roots`。`input_fields` 用于观察变化，`persist_input_fields` 明确允许冻结的顶层字段。

```json
{
  "id": "business-facts",
  "domain": "personal",
  "path": "/absolute/authorized/work/tasks.json",
  "direction": "依据任务数据生成完整工作量汇总",
  "input_fields": ["tasks"],
  "persist_input_fields": ["tasks"],
  "contracts": {
    "business-report": {
      "type": "json_reference",
      "path": "/absolute/authorized/work/report.json",
      "reference_id": "workload_summary_v1",
      "reference_version": 1,
      "require_change": true,
      "safe_retry": true
    }
  }
}
```

该来源文件的业务结构是 `{"tasks":[{"id":"a","team":"ops","minutes":20,"done":false}]}`。其他内置规则为 `ticket_priority_v1`（`tickets`）和 `source_index_v1`（`sources`）；完整字段、类型和算法见 [可信参考函数](../../work_reference.py)。每份冻结业务输入最多 4096 UTF-8 字节、32 层，每个列表最多 64 条记录。规则 ID 不能指定任意代码或自然语言评分。执行请求携带规则与授权输入；核验器在私有侧计算整份答案，严格检查字段和类型。缺少有效冻结输入、绑定不符或版本不支持时保留 unknown。

工作流清单示例（位于 `autonomy` 对象内，需为该来源另行配置所引用的全部契约）：

```json
{
  "workflows": [{
    "id": "report-pipeline", "source_id": "business-facts", "contract_id": "final-report",
    "steps": [
      {"id": "prepare", "contract_id": "prepared", "objective": "生成约定的准备产物", "effect_mode": "opaque_nonretryable"},
      {"id": "report", "contract_id": "business-report", "objective": "计算并生成业务报告", "depends_on": ["prepare"], "effect_mode": "local_outbox"}
    ]
  }],
  "monitoring": {"enabled": true, "mode": "normal", "threshold": 0.6, "max_rechecks": 1},
  "diagnostic_daily_evaluations": 2
}
```

所有 contract ID 必须在同一来源预先配置。`opaque_nonretryable` 不自动重试；`local_outbox` 记录完成通知元数据而不发信。`read_only` 是可信计划对效果的分类，不是单独的 OS 只读权限；实际权限仍来自受监督部署，不能用标签代替隔离。内部步骤契约不会交给规划器作为可跳过依赖的独立目标。

诊断需要 `diagnostics` 可信清单：关联已配置 skill_id，1–3 个因素，各非空组合一份冻结代码，另有负对照。该代码只能在已有隔离评测器运行，不能变成宿主 argv。没有可信原失败、原输入或原回归时，显示 unavailable，不靠模型补造。

```text
/zhulong autonomy status
/zhulong autonomy experience
/zhulong autonomy skills
/zhulong autonomy workflows
/zhulong autonomy diagnostics
/zhulong autonomy assurance
/zhulong autonomy cognition
```

`assurance` 命令运行固定界模型检查、旧 recorded trace 验证及新的当前 refinement 审计；`cognition` 查看配置、帧/绑定数量和交付通道计数。普通 status 执行当前 refinement audit，有限模型部分仍展示已有结果。v0.9 历史默认模型取 2 个目标、2 个租约代次、预算 2、深度 8、同时 1 个 run，历史枚举为 1236 个状态、3811 个转移，在该界内未发现反例；历史八种守卫错误变体均有反例。有限模型不覆盖任意文件/网络/外部效果、诊断预算或无限执行。

插件保持 11 个 hooks、4 个工具和 1 个命令入口。`zhulong_autonomy` 的 9 个 actions 是 `status`、`goals`、`tick`、`experience`、`skills`、`workflows`、`diagnostics`、`assurance`、`cognition`，没有直接评分或改验收接口。`/zhulong autonomy` 另提供 `pause`、`resume` 和 `cancel <id>`。

### 认知工作空间默认值与覆盖边界

工作空间通过现有 `autonomy` 配置中的可选对象启用，默认关闭；以下示例只列新增字段：

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

capacity 范围 1..8，TTL 1..3600 秒；mask 只能是 null/planner/executor/monitor，selection_mode 为 adaptive/constant。未知字段、bool/int 混用或非有限值拒绝。Planner 从全部当前可用、input 可用且可获得 source claim 的来源中选择，不能先按配置顺序截断；未获得 claim 的来源不能记为实际规划曝光。事实正文不能改变配置、权限、验收或预算。启用时裁剪未选事实的 self-model/experience 旁路，移除不具有 source scope 的 domain/identity 聚合。

v0.11 另提供 `attention_mode: off|adaptive|constant|permuted`，默认 `off`；可配 `attention_constant_probability`（0..1，默认 0.5）、`attention_max_wait`（1..1024，默认 8）和 `attention_switch_penalty`（0..1，默认 0）。预测先冻结，再与后续独立全来源观察对账，最后学习和排序；无法建立顺序或连续性的历史样本保留排除原因。启用控制会改变实际选择。尚无历史时，默认关闭不新增注意力记录；已有历史后的关闭观察可保存顺序标记，以免重新启用时恢复旧焦点。确定性控制 panel 的 Planner 返回空候选，因此只测曝光与新鲜度，不能当作业务收益样本。

工单契约可显式增加 `program_bundle`（schema/program/certificate，canonical 总长最多 6000 字节），仅支持 `ticket_priority_v1`、reference version 1 和 `tickets` 投影。检查器遍历全部证书区间，并在公开执行时重新检查同一份 immutable AST；准入事务同时核对当前可信配置、冻结目标／输入和实际请求。原生部署还必须安装受保护 runner/kernel/bundle/scope，使用固定 `python3 -I` 命令并核验真实前台工具记录，单独通过 admission 不足以证明执行了证书程序。示例 bundle 生成器在 `docs/research/experiments/core_kernel/certificate_probe.py --produce-only --bundle-out /absolute/private/ticket-bundle.json`；生成器属于不可信生产方。保证条件与机器证明缺口见 [实际实现映射](../research/2026-10-11-formalization-actual-mapping.md)。

帧保存 identity/policy/mechanism hash 和来源/revision/input/facts 摘要，raw facts 保持临时内存；已有显式 `persist_input_fields` 继续按原规则。goal 创建、TTL/来源/input 再检查和历史 binding 同事务完成；dedupe 保留原绑定。TTL 限制新的 planning/current knowledge，恢复、取消和已有请求继续使用明确标记 historical 的上下文。帧及消费者收据拒绝 UPDATE/DELETE 和已有身份的 INSERT OR REPLACE；改配置或 mask 不覆写旧目标绑定。

Planner、monitor capture、prepared execution request 和实际 Runs call 是不同交付阶段，timeout 不能记成远端已接收。receipt 为 `delivered_context_only`，绑定实际 payload/request；不证明模型真正使用、理解、注意或体验。单消费者 mask 只移除新增 packet：executor 的 frozen task_input、contract、source_path、工作区权限保持；monitor 的既有 prior/receipt/recheck 语义保持。正常/遮断/恢复用预先声明的不同匹配帧，比对语义内容时排除 frame/policy intervention provenance，不能要求完整 packet hashes 相同。

refinement 对 paused、全部 run_budget、goal 集合/state/lease/attempt/current submission/cancel/固定 intent identity、submission/request/execution/run/status/settled/固定 evidence 和 final truth 独立重建并比对。journal 与实际表在单一 snapshot 读取；expected counters 从领域操作推导，不复制实际 post-state。legacy checkpoint 分页、序列和初始化 marker 明确绑定；缺失/损坏不重置成新的绿色起点。默认 scan 限 100,000 events 和 32 MiB；超限返回 unavailable，不静默截断。

新 admission、发布及正向 fallback activation 使用同一写事务内的 fresh audit，不使用旧 status 授权；拒绝不会新增 budget/submission/provider call。发现 counterexample/unavailable 时恢复、stop、cancel、reconcile、旧 truthful settlement、负向 retirement 继续。post-check 失败回滚 reservation，不能提交部分状态。当前结果应逐项展示 coverage/exclusions/checkpoint boundary，并与旧 BFS 和 recorded trace 分开。

当前排除 reason、runtime/usage、source planning、模型版本、workflow 决策/effects、诊断预算、技能内部状态、verifier 正确性、OS quiescence、checkpoint 前历史及未覆盖时间/forecast/settings/applicability/resource guards。gate 对所覆盖的状态有效，不证明全部技能发布资格或任意 Python；特权者能替换控制代码或同时删除 marker/journal 的攻击不在保证范围。`settled` 与 Runs 完成状态不能升级为独立 OS 静止证据。

v0.10 的[验证记录](../research/2026-10-11-v0.10-validation.md)和[独立审查](../research/2026-10-11-v0.10-review.md)绑定干净代码 `50acabe`。430 项真实宿主/Docker 测试全部通过；唯一预登记 DeepSeek 原生工作量任务通过业务、执行审计、结算和所属进程/容器清理，认知交付绑定与当前 refinement 均合格。该 N=1 结果是集成证据，不能推断稳定收益、主观意识或通用正确性；该版本尚未交付完整 forecast miss/drift 评分端点及长程测试。v0.11 新增前瞻评分与研究记录，不追溯升级旧证据。下面继续保留 v0.9 历史证据。

### 历史 v0.9 原生有限工作验收

真实有限工作验收（会产生模型消耗）：

```bash
zhulong-python scripts/native_work_acceptance.py \
  --root /absolute/new/private/acceptance \
  --hermes-root /workspace/.cloud-onboarding/dependencies/hermes-agent \
  --hermes-command /workspace/.cloud-onboarding/bin/hermes \
  --image python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 \
  --allocations 3 --paid
```

不传 `--paid` 仅登记协议、输入和未运行分母，绝不算完成能力验收。每个分配保留独立私有 profile、失败收据、产物、native 数据库和日志；分享时只导出脱敏验证摘要。不能将缺失计费用量写成零费用。

有限 pilot 的新入口在部署启动前将可信 runner 写入原生只读缓存，以完整 SHA 纳入部署保护，并在独立 profile 中只预授权 `python3 /root/.hermes/cache/generated/zhulong-work-runner.py` 这一条精确命令。它读取并执行相同的候选代码与冻结输入字节，不携带参考答案；完整业务验收、原生轨迹审计及宿主 deny/hardline 守卫继续生效。实际 Docker 使用显式 `/root` tmpfs mode=711，owner 0；uid 1000 只能穿越、不可列举/写入该目录，来源与缓存仍只读。历史 v0.9 零 provider/gateway probe 已完成精确执行与清理；干净代码 `0f5841ebfcaa14325638cf199d8bb343bb9d1e59` 的新三任务真实验收 C 为 3/3 成功，各项业务/原生审计/静止/清理全 true。原内联 runner 和前三个探测的不完整结果分别保留，完整分母、用量范围与代码绑定见 [v0.9 验证记录](../research/2026-10-11-v0.9-validation.md)和[审查记录](../research/2026-10-11-v0.9-review.md)。

验收报告的 `auxiliary_calls` 只统计插件 `llm_daily` 预算表，native guardian 等额外调用不在该字段内；它不能作为所有模型调用或完整成本的分母。

该 CLI 的默认模式只运行 `finite_usefulness_pilot`：真实 LLM 从变化输入中发现目标，经 Hermes Runs 和 Docker 工具生成产物，再机械验收与审计原生轨迹。执行或清理未确认时停止后续分配，保留未运行分母。v0.11 的 `scripts/native_paired_trial.py` 另行运行 `paired_fixed_n`，复用明确的 native helper 配置与 strict endpoint 路径；需要先冻结完整协议，再显式 `--paid` 执行。三对六格与独立工单证书 pilot 分开报告；后者保留原发现／完成计时，不能记为配对研究的统一 180 秒端点。足量确认性研究仍见 [长期收益路线](../research/2026-10-11-confirmatory-benefit-roadmap.md)，目前未运行。

## 仍需外部条件或持续验证的项目

| 项目 | 已有基础 | 完成条件 |
|---|---|---|
| 真实邮件/日历/工单事务 | 本地草案、stable operation 和 outbox | 明确目标服务/授权凭据、服务的幂等/查询能力、真实回执与对账适配器；本版不自动发送消息 |
| 原子替换输入文件/外部输入挂载 | 冻结快照与 RO 来源 inode | 可信摄取服务在模型权限之外更新并冻结；当前固定 inode 部署仍不支持运行中替换 |
| 全 profile/work 硬磁盘配额 | 业务快照额度、Docker tmpfs/资源约束 | 支持 project quota 的底层文件系统或独立限额卷；当前 vfs bind mount 无硬配额，软阈值不能替代 |
| daemon 延迟动作与强终止 | owned 容器清理、unknown 保留、取消恢复 | 专项真实 daemon 故障/延迟注入和外层进程管理器验证；不可把 CLI 超时解释成已经静止 |
| 24/72 小时与跨日稳定性 | 有界恢复、durable CohortLedger、实际时钟有界 watch | 实际按相应时间观察及故障记录；零 provider 观察不等于持续工作服务，短 smoke 不代替长程结果 |
| 自动修改并晋升控制内核 | 代码/config hash 固定、技能候选隔离验证、旧真源保留 | 独立可信构建/测试/发布/回滚服务及产物证明；模型工具目前不能编辑控制内核 |
| 全局严格货币预算 | run/辅助/诊断次数额度、主用量和成本缺失项 | 提供商可核验的完整主/辅助/训练/迟到账单与费用停止机制；次数上限不是金额硬上限 |
| 真实因果提升与经济收益 | paired_fixed_n 协议、真实执行／资格适配器及固定 N 分析 | 业务成功率结论需同有效作用域的随机分配和足量可信独立配对样本；经济收益／成本效益另需完整可核验费用。三对集成和有限 pilot 不作上述结论 |
| 意识和通用正确性 | 功能元认知、部分工作空间、前瞻控制、工单 DSL 证书、有限不变量与当前状态对应检查 | 主观体验 unknown/not_established；完整 GWT/AST、HOT quality space、RPT/PP/IIT 底层检验、检查器机器证明／Python 对应及无界通用 theorem 仍未建立，不提供意识概率或通用正确性保证 |

早期文档中提及的 dsh/其它宿主、桌面深集成、跨 profile 联邦和公共技能市场原本不在 Hermes 本项目范围，不纳入本版虚构交付。旧版本已修复的 review 问题保留原闭环，不重复列为新发现。
