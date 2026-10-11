# 完整执行与长期自主任务：可靠工程研究（2026-10-11）

随仓库交付的 [来源访问索引](evidence/2026-10-11-source-access/full-execution.json)、[可移植复现命令](experiments/autonomy_frontiers/README.md) 与 [根节点重跑证据](evidence/2026-10-11-autonomy-frontiers/) 可独立核对。下文同名 scratch 文件指本次研究缓存；PDF/HTML 全文与原始下载日志留在 scratch，不随仓库发布。

本报告已完成正文核对、代码核对和无付费本地探针。研究基线为 `/workspace/hermes-zhulong` 的 main `deffc94e0c30ef3b20481ff6aaf9af5687371ef5`（v0.8）。没有修改产品代码或测试，没有读取凭据或调用付费模型。所有下载和探针位于同名独立子目录，来源访问状态和 SHA-256 在 `2026-10-11-full-execution/source-status.json`，探针结果在 `probe-results.json`。

## 可执行结论

目前最值得推进的是**可恢复的步骤执行与外部效果协议**。v0.8 能证明某次固定程序和固定输入实际执行，并核验冻结字段后置条件；这些条件并不能证明整条流程、每项副作用、取消后的静止或任意环境里的正确性。长任务应把规划层与可信执行控制层分开：模型提议有限步骤，控制层持久化计划版本、步骤前置条件、稳定操作 ID、请求 hash、承认/效果/核验/补偿记录；恢复优先对账已经准备的步骤，不从头生成另一套有副作用的计划。

现有 Runs 幂等是良好的基础，但必须区分 **run 只被承认一次**、**业务副作用只发生一次**、**整个工作流所有条件都满足**。稳定 submission key 只在宿主声明的持久幂等保留时间及同一身份/同一请求内提供承认语义；任意外部邮件、文件、订单或 shell 操作仍需要自己的幂等、效果查询、事务或补偿能力。不能把租约 generation 当成任意外部资源已执行的 fencing token。

## 三类“完整”的证据边界

| 命题 | 可取得的证据 | 当前状态 | 不足以证明它的东西 |
|---|---|---|---|
| 原程序确实执行 | 同一程序 bytes 的 SHA、同一输入 bytes 的 SHA、原生 run→session→tool-call→成功工具结果映射 | v0.8 的有限 native smoke 已建立；本次核对实现，没有重新付费执行 | 程序已发布、模型说使用了程序、单个产物字段正确 |
| 完整流程及副作用可恢复 | 版本化步骤 DAG、每步输入/前后条件、持久效果 ID、服务端回执和效果查询、未知状态对账、补偿、终局及静止证据 | 目前只有目标/run 粒度部分能力；步骤和跨服务效果尚未建立 | 单次成功 run、重放原例 stdout、客户端停止请求、整个流程末尾一个字段 |
| 所有环境通用正确 | 要明确程序类、环境模型、规范与证明规则；不受限的现实环境没有可由有限测试提供的普遍证明 | 未建立；本报告没有主张已实现 | 任意数量有限 holdout、固定镜像、论文里的某一模型分数、功能自我模型 |

“恢复”也不要求重演内部推理。应恢复可信事实、已知承认和持久效果，而不是复制私有思维链或依赖模型事后自述。内容持久化继续采用显式授权、有限字段和独立私有账本；审计 hash 不是敏感数据不可推断的保证。

## 精选一手资料与证据表

以下选入 7 项来源家族，另记录 1 项未复核的原始论文。Temporal 两页属于同一个工程来源。公开网址使用继承代理与 CA，TLS 校验保持开启；没有切换代理、绕路或修改网络策略。托管状态返回 desired unrestricted/state unknown，执行器快照仍显示启动期 restricted，因此**可达性以此次实际请求为准**，不据配置名推断所有域名已放开。

| 来源、正文位置与版本 | 本次取得与核对 | 它支持的工程结论 | 它不支持的推断 |
|---|---|---|---|
| [Temporal Workflow Execution](https://docs.temporal.io/workflow-execution)，Durability / Replays / Commands；[Activities](https://docs.temporal.io/activities)，2026-10-11 访问 | 两页 HTTP 200；保存 HTML 与文本。原先 `/workflow-execution/durable-execution` 为 404，使用官网现行 Workflow Execution 页 | 工作流以持久 Event History 和确定性命令重放恢复；Activity 可非确定，建议幂等；重试从初始状态开始，heartbeat details 才是其检查点。大操作拆为多 Activity，更容易故障恢复 | 文档中 workflow “effectively once” 不等于任意外部副作用 exactly-once；把 LLM 调用放入任意重放代码不会自动确定，也不提供数学终止证明 |
| Malcolm Featonby, [AWS Builders’ Library: Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)，Reducing client complexity / Semantic equivalence / Late arriving requests / Same client request ID, different intent | HTTP 200，正文核对。原文明确幂等 token 与 mutating operations 需要 ACID “all or nothing”，同 token 的参数变化返回 validation error，保留时间按服务/资源确定 | 使用调用方稳定表达的意图 ID；服务端把 token、效果和可查询结果一起原子提交；同 ID 不同意图拒绝；迟到请求和保留窗口属于协议，不是简单无限重试 | 对不合作的第三方 API 无法仅靠本地 SQLite 或请求 header 消除提交成功、回复丢失的歧义；参数 hash 本身不能区分“重试”与“确实要创建第二份相同资源” |
| [AWS Prescriptive Guidance: Saga orchestration](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/saga-orchestration.html)，Issues and considerations / High-level architecture | HTTP 200，核对订单、库存、付款事务及补偿结构；原文明确 eventual consistency、参与者幂等、无 transaction isolation 和 semantic locking | 多服务长事务分成可本地提交的步骤；可重试故障走恢复，业务失败触发已定义补偿；补偿本身也需记录和幂等；并发下需要语义锁或版本前置条件 | Saga 不是全局 ACID 回滚；补偿不是撤销时间。已发邮件、已被他方消费的资源等动作未必可逆，需模型之外显式定义其边界 |
| Nau et al., [SHOP2: An HTN Planning System](https://arxiv.org/pdf/1106.4869)，JAIR 20 (2003), §3.1、Figure 5、§3.2–3.3 | HTTP 200，PDF 215,456 bytes，核对标题、作者及算法正文 | 用 compound task/method 分解，primitive operator 带前置条件及 add/delete effects；任务可部分有序，按实际执行顺序模拟状态，备选方法通过搜索处理。适合有限授权领域的结构化步骤契约 | “domain-independent” 不是不需要领域知识。方法/操作符和可观测状态错误时，形式计划正确也不保证现实执行；本报告不把 SHOP2 直接宣称为当前 Hermes 的完备性证明 |
| Yao et al., [ReAct](https://arxiv.org/pdf/2210.03629)，ICLR 2023；下载 v3 2023-03-10，§2、§3.3、§4、Appendix A.3 | HTTP 200，正文和有限环境方法核对 | 观测、行动与计划更新交错，比一次生成整段操作更适合例外处理；实验显式考察子目标跟踪，并记录推理/搜索/幻觉等失败方式 | 论文是若干固定 benchmark 的经验改进，不是 durable workflow；其 WebShop 实验不能真的购买，人工编辑失败轨迹的示例不是无人可靠性；无需在本项目保存或导出思维链 |
| Liu et al., [AgentBench](https://arxiv.org/pdf/2308.03688)，ICLR 2024；本次下载 v3 2025-10-04，§3–4、Table 2、Table 4 与 failure discussion | HTTP 200，PDF 23,017,024 bytes；核对方法、8 环境、Dev/Test、任务轮数与失败分类。最初 16 MiB 本地下载上限导致未保存，后在同一公开地址提高本地上限至64 MiB取得全文 | 有限多轮执行应分开计量任务成功、格式/非法动作、上下文耗尽、任务步数耗尽等。正文说明不同环境使用不同指标，不能只合并一个总分来判断恢复能力 | 论文的 failure category 是观测分类，不是反事实根因证明；8 环境仍不证明所有环境。下载修订日期不是声称 2025 有新实验，本文不新增或推断 2025/2026 模型成绩 |
| Boisvert et al., [WorkArena++](https://arxiv.org/pdf/2407.05291)，NeurIPS 2024 Datasets and Benchmarks；下载 v2 2025-02-05，§2.2、§3、§4.1–4.4、Table 2 | HTTP 200，PDF 24,628,627 bytes；核对组合任务、Oracle/validator、数据库与页面核验、随机 seed、50 步预算。最初16 MiB本地上限后同址提高至64 MiB获取全文 | 使用多层任务与隐藏最终数据库/页面验证；区分给出步骤的 L2 与需查知识库推导步骤的 L3；固定评测 seeds 0–9，调整用别的 seeds；记录最终完成和预算截止 | 这不是数周 daemon 实验。Table 2 的当时基线 L3 235项均0成功，只说明论文给定模型/agent/50步设置的难度，不能外推 DeepSeek 当前 alias 的能力或证明任务不可能 |
| García-Molina & Salem, *Sagas* (SIGMOD 1987)，尝试 [Cornell 教学 PDF](https://www.cs.cornell.edu/andru/cs711/2002fa/reading/sagas.pdf) | HTTP 421/SNI 错误，**本次未取得/未复核原论文正文**；没有绕开代理/TLS或使用同域替代路线 | 原论文可列为后续追溯书目；本报告具体 Saga 工程断言以已核对 AWS 官方资料为证 | 不引用未核对原文段落、定理或实验数值；不把官方实现指导伪称此次阅读了1987原文 |

## 当前代码能力与差距

| 代码证据 | 已有能力 | 后续工程差距与影响 |
|---|---|---|
| `autonomy_store.py:34`、`119`、`179`；SQLite BEGIN IMMEDIATE、synchronous=FULL、冻结 goal/submission trigger | 目标与请求持久、goal 去重、预算与提交准备同事务；原请求恢复先于新派发限制 | schema 是 goals/submissions/evidence，不是版本化步骤、依赖和效果 journal。重试仍是整次 goal 的新 attempt；不能从已完成第 N 步推进 |
| `autonomy_store.py:140` / `161` / `245`；owner+generation+lease_until；`autonomy.py` 心跳 | 不同 owner 接管时旧租约不能写账本，当前 submission 再比较防止迟到写错尝试 | generation 没有传给普通外部动作并由资源服务拒绝。运行 lease 过期不代表原外部调用已静止；模型也不能只凭新的 generation 假设旧调用效果不存在 |
| `hermes_runs.py:62` / `102`；Controller `_reconcile` | 要求宿主 durable runs_idempotency，稳定 submission id 和冻结 body/session/身份；先查 run_id，404 在 retention 内重放原请求，过期保留 unknown | 宿主单 run admission 原子并不使 run 里的任意 shell/API 效果原子。缺每个效果的支持能力清单、稳定 business key、查询接口、效果回执和终止对账 |
| `autonomy.py:205` `_reconcile` 和 `250` `_dispatch` | 恢复已有在途请求；未知保留占额；only safe_retry 且验收明确失败才新尝试；deadline 触发 stop 而不直接称静止 | safe_retry 是配置方对整个契约的布尔授权，不是基于每个已执行步骤的事实重规划。缺执行前条件检查、环境版本、局部修复、补偿进度 |
| `runtime_supervisor.py:67`、`188`、`201`；`runtime_channel.py` | 自有进程组、实际 readiness/进度 watchdog、有限重启、入场关闭、按 ownership label 清理 Docker，记录 forced shutdown | 实测生命周期有限；尚无24/72小时按计划的 soak/fault matrix、归档/硬磁盘配额、队列迟到请求截止协议。杀进程组/删容器不等于所有已经远端提交的动作被撤销 |
| `skill_evaluator.py:166` / `210`；`skill_replay.py` | pinned image、隔离与限额、规范 JSON exact equality、原输入字段条件、清理后发布 | 最多9个纯 stdin/stdout case，不重建 filesystem/API/time/network/credential/environment；成功候选仍没有 effect envelope 与通用正确性证书 |
| `scripts/skill_smoke_evidence.py:18` / `46` | 同一读取的程序和输入bytes先 hash后运行；原生 call/result绑定 | 是 finite smoke 的只读审计，不是生产里每个动作必经的可信执行 broker；流程末尾产物仍不能单独归因于指定程序 |
| `autonomy_checks.py:205`–`235`；Verifier.capture/check | 路径与inode范围检查、文件大小限额、规范比较区分 true/1 与6/6.0、baseline/require_change、argv有界子进程 | 仅 postcondition，不绑定产物写入者或每步效果；`json_equals` 对整文档用普通 `json.loads`，存在下述继承严格性边界 |

### 普通 json_equals 的最小复现和范围

本次仅创建独立临时目录、输入产物与正常契约，调用实际 `contract_policy` 和 `Verifier.capture`；未改产品。复现命令：

```bash
source /workspace/.cloud-onboarding/env.sh
zhulong-python docs/research/experiments/autonomy_frontiers/execution_probe.py /tmp/hermes-execution-probe
```

目标契约 `type=json_equals, field=sum, value=6`，产物文本 `{"sum":0,"sum":6}` 得到 `verdict=true, reason=contract_satisfied`。倒序 `{"sum":6,"sum":0}` 得到 false。同一语义数据会随重复键顺序改变验收，原因是普通 `json.loads` 保留最后的键；这与 v0.8 的 source snapshot / candidate evaluator / native audit 拒绝重复键不一致。

| 精确探针 | 实际结果 |
|---|---|
| `{"sum":6,"unused":NaN}`，sum=6 | true |
| `{"sum":6,"unused":Infinity}`，sum=6 | true |
| `{"sum":6,"unused":1e999}`，sum=6 | true |
| `{"sum":NaN}` 或 `{"sum":Infinity}`，sum=6 | unknown；目标值 canonical 拒绝非有限数 |
| `{"sum":true}` 配 value=1；`{"sum":1}` 配 value=true | false，**没有 bool/int 混淆** |
| `{"sum":6.0}` 配 value=6；`{"sum":6}` 配 value=6.0 | false，规范比较保留数字表示差异 |
| 契约自身 value=NaN/Infinity | contract_policy 抛 ValueError，拒绝配置 |

因此问题是**整份 JSON 的严格解析和重复键歧义**，不能说当前 Verifier 把 true/1 判相等，也不能把它说成非有限字段本身被匹配。NaN/Infinity 明确不符合标准 JSON；重复键按 JSON 互操作约束具有歧义，但单说“field=6”且契约没有全对象条件，也不能把任意额外合法字段称为错误。推荐将整个 artifact 严格解析作为有限、明确的独立接口修复：默认拒绝重复键及任何位置非有限数，保留合法额外字段、当前类型判等、大小上限和未知语义。深度限额需单独设计兼容性，不以复用某个默认32层顺带改变旧验收的合法输入范围。

现有 `tests/test_autonomy_checks.py:77` 覆盖 broken JSON → unknown；`:82` 覆盖 integer1与expected true不匹配；没有重复键、未检查字段NaN/Infinity/exponent overflow覆盖。本次将该文件现有测试实跑，**10/10通过，exit0，1.045s**，日志与exit另存 `verifier-baseline.log`/`.exit`。影响限于普通本地产物 `json_equals` 的读取及由其建立的 capture/check/baseline/最终机械证据；不可外推 strict candidate stdout 和冻结源 JSON 也存在同一问题。这是继承的真实接口缺口，本次只报告，不扩大研究任务为产品修复。

## 已做的有限实验与下一阶段验收

### 实验1：跨进程丢承认回复恢复（本次实跑）

```bash
source /workspace/.cloud-onboarding/env.sh
zhulong-python -m unittest discover -s tests -p test_runtime_recovery.py
```

当前 main **2/2通过，exit0，0.616s**；完整输出和 exit 单独保存。一个实验让7个真实 source-owner 子进程退出后继续认领，不耗尽规划次数；另一个在 fixture 服务已接受并执行后丢回复，两个恢复子进程得到 **posts=2、admissions=1、effects=1、attempts=1、final succeeded evidence=1**。此结论依赖 fixture 服务按幂等 key 原子记录单次效果；不是所有未知服务的 exactly-once 证明。

下一阶段把此实验扩展到每个步骤边界：prepare 前/后、发送前、服务端 effect commit 后 reply 前、receipt 入账前、verify 前后、compensation commit 后 reply 前，加入 SIGKILL、丢/重复响应、租约过期接管、原 owner 迟到、宿主404/retention expiry。对实际支持原子幂等的本地 connector，验收每个 schedule 下 final效果最多一次、相同 key/请求不变、预算只占一次、依赖不提前、旧 owner不能发布。对无法查询/幂等的 connector，正确结果是 durable unknown 与禁止盲目重试，而非强行实现1次。

### 实验2：账本 fencing 与效果服务 fencing 的区别（本次实跑协议探针）

`probe_boundaries.py` 使用真实 Ledger：generation1过期后generation2接管，old `record_admission=False`、fresh `True`，证明本地拒绝旧写。另以故意不知道租约的效果 sink模拟两名操作者，效果计数2：这只是清楚展示缺协议的模型，不是观察到 native gateway 在生产重复执行。

同脚本另有**独立 SQLite connector 协议原型**：服务端检查当前高水位token=2，并在同一个本地事务写 operation key/request hash/result/效果。stale token返回stale；current首次返回1；模拟reply丢失后的same-key重放仍返回1；same-key更改delta返回conflict；效果计数1。它不是已集成产品 connector，也未证明远程服务总体事务。

下一阶段指标：有支持能力的 adapter 每个 stale schedule 的新效果=0；同意图重放结果语义相等；同key参数变化100%拒绝；效果未知不可被模型覆盖；cancel截止后拒绝入场，并区分已入场效果、截止后的新效果与真实静止确认。服务端fence部署/确认必须成为契约部分，不能仅由本地生成token就宣称对端使用。

### 实验3：组合任务与长期恢复评测（提案，未跑模型）

建立无需真实付费外部服务的确定性本地工作台：比如有业务数据库的“扫描库存→取补货规则→建立订单→更新状态→验收”4–8步任务；额外构造规则变化、写冲突、效果回复丢失、不可用资源、替代方法与补偿失败。后端 oracle验证终局、所有禁止状态和资源账，不能只验最终report字段。显式步骤/L2与仅业务目标+知识库/L3分开，调试seeds与隐藏评测seeds分开。代理版本、模型alias、程序/image/input/计划 hash、限时/步数/token/费用都固定记录。

先做无模型的确定性状态机100个seed×所有有限failpoints；再有预算地比较旧goal-level agent与step-level agent的相同任务，报告 whole-workflow success、verified partial completion、unknown比例、重复/遗漏效果、恢复时长p50/p95、每个完成任务调用成本、补偿完成率、违规0计数。**这些数字是拟定验收，不是本次已经跑出的成绩**。长期验证先1小时故障run，再24小时再72小时，每阶段按产生的证据提升声称；需包含队列公平性、跨日预算、retention窗口、磁盘上限与清理。WorkArena++有50步任务预算，并不能替代这样的wall-clock soak。

## 下一阶段优先级与实施接口建议

1. **P0：先统一有限JSON验收语义并建立效果能力契约。** 普通 Verifier 严格性是已复现的小缺口，可单独 RED→GREEN 修复；外部adapter必须先声明 read-only / idempotent+queryable / compensatable / opaque-nonretryable 等明确能力，并由真实服务端响应与接口证明。未知效果保持unknown。不要先让LLM拆更多有副作用的任务然后期待状态账本自动解决它们。
2. **P0：durable step journal +确定性执行状态机。** 新增 plan_version、steps、effects/operation_records、event sequence；步骤请求和契约冻结，阶段例如 prepared/admitted/effect_unknown/verified/compensating/compensated，不用一个completed把这些差别抹掉；效果查询及同键重放先于新plan；一开始只做本地事务connector和只读步骤，避免同时引入多个真实外部账户。
3. **P1：在已授权有限领域做HTN式方法与局部重规划。** 模型输出有界candidate DAG，可信 validator检查依赖无环、scope、操作类型、前置条件与预算。运行期观测不满足前置条件时，创建新plan revision，保留已发生effects与原目标contract，不重写已完成事实；替代方法从当前可信状态出发，不能把恢复包装为“重新开始”。
4. **P1：效果补偿与长时间故障矩阵。** 补偿动作需显式业务定义、稳定ID、可重试和独立核验；执行者不可自己发明撤销已不可逆动作的承诺。随后再加入host/worker杀进程、client timeout/daemon迟到、硬profile/work磁盘限额以及24/72小时运行验证。

采用 Temporal/类似成熟引擎与自己在SQLite中增量实现属于工程选择。当前项目本地部署和小规模单主账本更适合先把协议与状态机做小；一旦要求多机、持续多年、众多外部任务、版本升级与大事件历史，成熟引擎降低重造调度、定时器、确定性重放和升级兼容的成本。两种方案都不能替代每个外部服务的效果协议，也不会通过安装一个“意识插件”取得主观意识。

本报告不宣称已经完成整体事务执行、全部根因识别、因果提升、意识或通用正确性。它把“完整执行”改为有明确范围、可被故障实验推翻和由机械证据支持的下一阶段目标。

## 后续工程入口（v0.9）

持久步骤 DAG、本地效果/outbox 与待完成外部事务的当前状态见 [工程清单](../deployment/engineering-closure.md)；实现范围与验收设计见 [研究落地规格](../superpowers/specs/2026-10-11-frontiers-engineering-design.md)。本报告的研究时点、实验结果和未运行提案保留原记录。
