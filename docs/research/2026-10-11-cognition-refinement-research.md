# Hermes 认知机制与生产状态对应：研究依据、冻结预测及工程范围

研究日期：2026-10-11（Asia/Shanghai）。研究基线：`cda80862312977463c48aa02bda00353169d3c41`（v0.9）。本报告整理已经完成的来源核读和基线探针，并明确下一轮的工程及实验判据；**本文不报告新产品测试通过，也不报告主观意识或通用正确性已经实现**。

选择是限容量、可持久恢复、具有消费者独立干预的 Controller 工作空间，以及将独立 typed journal 与 authoritative SQLite 状态对应检查接入同事务的准入和正向发布门槛。前者研究实际的信息路由功能，后者补足已测得的日志／生产状态对应缺口。两者都应以可重跑的反例和明确覆盖范围验收。

本报告的可移植证据包见 [evidence/2026-10-11-cognition-refinement](evidence/2026-10-11-cognition-refinement/artifact-manifest.json)。[产品设计](../superpowers/specs/2026-10-11-cognition-refinement-design.md) 定义实现契约。研究 memo 中较广的候选架构并非全部承诺交付；本文按该设计收敛。

## 1. 证据分层及结论边界

| 证据类型 | 可支持的结论 | 不能据此推出的结论 |
| --- | --- | --- |
| 确定的工作空间容量、帧、消费 packet 和实际请求绑定 | 指定信息在软件框架中的选择与交付路径 | LLM 内部注意、理解、神经点火或主观体验 |
| 配对遮断、置换、恢复和匹配预算的结果 | 指定机制对限定任务结果的增量因果作用，前提是旁路及混淆得到控制 | 全部意识理论指标满足，或跨任务稳定效用 |
| 模型关于自己／体验的陈述 | 自我报告；对可独立核实的外显状态可测报告准确性 | 体验真值、授权、业务验收真值或能力成功样本 |
| 独立事件重建与真实表比较 | 被覆盖状态在当前观察区间的对应；具体不一致反例 | 任意 Python、所有未来路径、外部事实或执行静止的普遍证明 |
| 有限模型 BFS / 一次执行 verifier | 指定有限模型内的检查，或该次运行中实际核对的条件 | Python／SQLite 实现 refinement theorem，或全部输入的总正确性 |

`subjective_consciousness=not_established` 表示证据不足，不能解释成已经证明不存在意识。本轮不提供意识分数或主观体验概率。业务真值、host 生命周期状态和 OS execution quiescence 也应分开：`settled=True` 或 Runs completed/cancelled 不是独立的进程空集证明。

## 2. 科学与官方资料：理论约束和实际访问

实际访问状态由 [意识来源索引](evidence/2026-10-11-cognition-refinement/consciousness-source-index.json)、[三次刷新访问](evidence/2026-10-11-cognition-refinement/consciousness-refresh-access.json)、[正确性缓存核验](evidence/2026-10-11-cognition-refinement/correctness-access.json) 与 [历史成功／失败访问](evidence/2026-10-11-cognition-refinement/correctness-historical-access.json) 保存。HTTP 200 与完整正文访问不是同一事实。

### 意识文献

| 来源 | 本轮研究的实际材料及范围 | 对工程的约束 |
| --- | --- | --- |
| [Butlin et al. 2023 v3](https://arxiv.org/pdf/2308.08708v3) | 完整作者 PDF 重下载并核对旧缓存；摘要更正、Table 1、GWT/HOT/AST/PP 和实施限制 | 满足指标不是意识充分条件；以计算功能主义为工作假设，标准 IIT 未纳入其指标推导 |
| [Mashour et al. 2020, GNW](https://pmc.ncbi.nlm.nih.gov/articles/PMC8770991/) | 公开完整作者稿缓存，重读 conscious access／phenomenal consciousness、瓶颈、双向投射和 ignition | 框架广播与人类神经意识访问的证据层级不同；不能称软件 packet 是神经点火 |
| [Dehaene, Lau, Kouider 2017](https://doi.org/10.1126/science.aan8871) | 完整作者复合 PDF 缓存；C0/C1/C2、正交性、架构建议、限制及 2018 正式争论 | C1 全局可用与 C2 自身计算监控可分别研究；关于体验的解释存在争论 |
| [Fleming, Lau 2014](https://www.frontiersin.org/journals/human-neuroscience/articles/10.3389/fnhum.2014.00443/full) | 完整原文缓存；bias/sensitivity/efficiency、正确／错误分布和任务表现混淆 | confidence、ECE、Brier、AUROC2 的改善含义各异；均不是意识指标分数 |
| [Graziano, Webb 2015, AST](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2015.00500/full) | 完整原文缓存；简化注意模型、模型控制、控制缺损预测和注意／觉知分离 | 注意模型应预测并改变控制；priority queue 或注意自述本身不满足该主张 |
| [Albantakis et al. 2023, IIT 4.0](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011465) | 完整原文缓存；操作性基质、TPM、`do` 干预、φ／Φ-structure、Figure 8 和讨论 | IIT 按明确单位和干预下转移定义；功能等价不足以推出其理论中的体验等价 |
| [COGITATE Consortium et al. 2025](https://www.nature.com/articles/s41586-025-08888-1) | 完整 publisher HTML 刷新及旧缓存；预注册差异预测、优化／验证分割、结果和三方讨论 | 借鉴事前冻结、对抗检验和零结果保留的方法；人类神经研究不能当作 AI 意识认证 |
| [Friston 2010](https://www.nature.com/articles/nrn2787) | HTTP 200 的 Key Points／Abstract／参考文献**订阅预览**；未取得全文 | 仅可引用已访问的要点；不得声称核读正文数学推导或实证 |

七份旧完整原文在本轮研究中核读了指定段落，另有三次原站访问，时间为 `2026-10-11T04:11:58 UTC`。Butlin 与 COGITATE 是旧论文刷新，不能计作新论文发现。Friston 是第三次访问，不能计作新增完整正文。新下载 raw SHA-256 分别为：

- Butlin v3：`88a9d5635b274b7d7c8c55dfeea45be3018054be01da83cd2f8d1fe53d668ab8`。
- COGITATE：`ede81ee683f4719da06ad11b4c0122b2687fd414a1f2c60d08d5d328de3efcdc`。
- Friston 预览：`cb80bffedda47a8b46c5eec3e4ca86304626a8f4a6b205d5bfbe4cafbfd6c31f`。

Butlin v3 明确指出 “satisfying the indicators would not mean that such an AI system would definitely be conscious”。GWT-1 的专业系统并行、GWT-3 的全部模块可用且反馈到输入模块、GWT-4 的当前状态控制选择及顺序查询，不会因三个 packet 接口自动成立。HOT 的感知 reality monitoring／quality space、AST 的预测性注意控制和 PP 的输入模块 predictive coding，也不能由业务成功率预测或 next-token prediction 代替。

COGITATE 研究招募 256 名参与者，涉及 fMRI/MEG/iEEG；fMRI/MEG 有优化及独立验证分割，iEEG 因临床样本和覆盖限制不同。结果挑战特定 IIT/GNWT 预注册预测；它没有计算人脑 IIT 4.0 Φ，也没有证明所有版本理论均不成立。本轮未复现这些实验，未开展人类实验，未测量 provider 的隐藏激活或物理网络。

### 正确性的一手／官方资料

本轮正确性研究没有新网络请求。八份之前实际取得 HTTP 200 的缓存重新计算 SHA-256，全部与原记录一致。完整 URL、字节数、hash 和阅读范围保存于 evidence JSON。

| 来源 | 阅读材料／约束 |
| --- | --- |
| [Lamport, Specifying Systems](https://lamport.azurewebsites.net/tla/book-21-07-04.pdf) | refinement mapping／step simulation（§5.8, pp.62–64）及 TLC 边界；实现转移必须对应规格步或明确 stuttering |
| [Software Foundations, Hoare Logic](https://softwarefoundations.cis.upenn.edu/plf-current/Hoare.html) | Hoare triple、while 与不终止例子；partial correctness 不能代替终止性 |
| [Dafny 官方教程](https://dafny.org/dafny/OnlineTutorial/guide) | invariant、Termination、decreases；受限内核仍需递减量或有限步数界 |
| [Lean 官方教材](https://lean-lang.org/theorem_proving_in_lean4/introduction.html) | proof objects、基础假设及独立检查；生成候选与验证证书应分离 |
| [OpenJML RAC](https://www.openjml.org/tutorial/RACCompilation) | 实际运行中的具体值和不可执行构造；一次运行检查不能覆盖全部输入或撤销外部副作用 |
| [Hypothesis stateful testing](https://raw.githubusercontent.com/HypothesisWorks/hypothesis/master/hypothesis/docs/stateful.rst) | 规则序列、模型比较、precondition/invariant；可找反例，不是归纳证明 |
| [Turing 1936](https://www.cs.virginia.edu/~robins/Turing_Paper_1936.pdf) | 缓存身份核验；不可判定性论证沿用此前 §8／§11 阅读，本轮不声称重读整篇 |
| [Hobbs et al., RTA](https://arxiv.org/pdf/2110.03506) | 完整缓存身份核验；沿用 model deviation／monitor／backup 阅读；物理控制 theorem 不直接迁移为软件代理保证 |

历史未取得正文的访问仍保留：Hoare 1969 作者稿目的地址被代理拒绝 403；Rice 1953 AMS 正刊和 PCC ACM publisher 返回 403；Necula 候选 PDF／publication 路径、Stanford Rice、Yale computability、旧 Hypothesis 和 Lean Kernel 路径返回 404。它们不是本轮新失败，也不作为已读正文使用。RTA 首次受本地 6 MiB 下载上限截断，后来以 25 MiB 上限取得完整 14,017,701-byte PDF；不能把首次上限描述成来源访问拒绝。成功的目录树、示例及摘要不等于被选中的理论正文。历史访问包自身基线是 `deffc94e0c30ef3b20481ff6aaf9af5687371ef5`；本轮缓存重读和产品探针基线是 `cda8086`，两者保持区分。

## 3. 路线比较及选择依据

| 意识研究路线 | 可实现／可反驳部分 | 本轮选择 |
| --- | --- | --- |
| GWT/AST 启发的信息选择、共享与持续控制 | 限容量选择、帧／请求绑定、消费者遮断、恢复、持续干扰与轮换控制 | 核心：Controller 工作空间；按实际功能描述，完整理论指标仍有缺口 |
| HOT／功能 self-model、现实与动作来源监控 | 区分观察／预测／提交／执行／外部已有成果／unknown；监控影响复核和恢复 | 复用 v0.9 metacognition，只补工作空间消费与来源绑定；不重复 confidence，不认证 HOT-4 |
| 可干预底层系统：IIT／RPT／PP | 对确定基质和可枚举网络做正式 TPM、递归／分割／前馈对照及理论差异预测 | 后续研究；当前远端 API 不提供必要接口，不能制造 Φ 或体验证书 |

人格提示、自传或“我有意识”自述不是独立机制路线。工作空间具有可控信息边、真实决策入口及机械结果，可直接提出工程反例。runtime memo 原先优先考虑复用既有 metacognition；最终产品设计选新 workspace，是因为旧模块已具备事前预测、normal/masked/constant 和有限重检，新工程应解决新的输入选择与共享缺口。

| 正确性路线 | 优点及边界 | 本轮选择 |
| --- | --- | --- |
| 独立 typed journal + authoritative state audit + 动作门槛 | 直接检出实际账本与规格的具体差异；无新 solver 依赖；仍依赖 checker、SQLite、保护边界及完整 mutation hooks | 核心：生产状态对应检查 |
| 受限 DSL／全域证书 | 可对固定解释器、有限输入域建立全输入等价和终止证据；证书必须绑定真实执行工件 | 保留研究方向，本轮不承诺交付 |
| TLA+/TLC/TLAPS + 实现序列投影 | 检验协议竞态并逐步建立归纳证明；需要清楚的 mapping 和实际实现核对 | 后续形式化资产；不以新增绿色模型文件冒称实现已证明 |

受限 DSL 的具体候选是单记录 ticket priority kernel：severity 1..5、age 0..87600、blocked 为 bool，共 876,010 种输入。枚举证明只覆盖该 kernel 和域，不覆盖任意 Python、JSON parsing、任意列表 assembly/sorting 或外部事实。SMT UNSAT 也须披露 encoding/solver 信任；没有独立 proof certificate 时不能称小内核已核验证明。

## 4. 已测得的独立状态对应缺口：cda8086

[refinement-probe.json](evidence/2026-10-11-cognition-refinement/refinement-probe.json) 保存此前执行的机械探针。它在临时账本导入实际 Ledger/assurance，调用支持 API，另注入一次未 journal 的预算故障；临时账本随后删除。此文档交付没有重跑探针。探针 provider/Docker 调用均为 0。

| 探针条件 | authoritative SQLite | 事件重建 projection | 旧 trace checker |
| --- | --- | --- | --- |
| 正常 create_goal | 1 goal，`ready`／generation 0 | 0 goals | `trace_valid=True` |
| 正常 prepare + record_admission | goal `running`，预算 1 | goal `submitting`，预算 1 | `trace_valid=True` |
| 注入未记录预算修改 | 预算 999 | 预算 1 | `trace_valid=True` |

第三行是人为故障注入，不能描述成生产事故或发现支持 API 绕过授权的漏洞。三行共同表明：valid journal 不是当前 authoritative SQLite conformance。第一、二行也不能直接被当作生产不安全；它们要求补全事件语义或明确抽象映射，避免新 checker 对正常动作误报。

该探针绑定 `assurance.py` SHA-256 `f58c472dd746ff6ea82590ef5e68473b01b44a670750a97df392ebcd0431402c`、model hash `f544b6806dcb2a7b58cc1f8e55dac6a01df05940ad59257cb9d8d31baf68645c`。探针脚本身份另见 JSON。基线 `assurance.validate_trace` 从 `protocol_events` 重建，但不比较真实表；create_goal 没有 goal-created 事件，runtime 投影与 running 写入不完全对应。既有 bounded model hash 绑定参考模型／checker，不证明生产源码、配置和 host 行为的语义。

v0.9 的 `BEGIN IMMEDIATE` lease fencing、预算／submission 原子绑定、pause/publication 事务保护、严格 JSON、固定规则输出重算仍是已有保证，应保留。新 checker 补对应能力，不替换这些边界。默认 status 中既往 bounded model pass 也不能充当当前生产许可。

## 5. 选择的工程契约

### 限容量工作空间

设计新增 `cognition.py`，默认 disabled；capacity 默认 3、范围 1..8，TTL 默认 120 秒、范围 1..3600；consumer mask 允许 planner/executor/monitor，selection_mode 为 adaptive/constant。严格验证未知字段、非有限值和 bool/int 混用。使用 Python 3.11+ 标准库，不添加运行时依赖。

Controller 在实际 Planner 调用前选 observations；候选验证和 source claims 只对选中集合。工作空间模式下剔除可能泄露未选事实的 commitments、policy hypotheses 和 experience 文本，只保留选中 scope 的统计。最终设计还移除非 source-scoped 的 domain/identity aggregates，不把它们重标为选中来源统计。来源正文是 untrusted data，不能改变容量、TTL、干预模式、权限、合同或预算。

帧冻结 identity/policy/mechanism hash、captured/expires、source/revision/input/facts 摘要和选择顺序。新表保存元数据和 digest，不新增持久化任意 raw facts、prompt、tool body 或秘密。已有显式允许持久化的 task_input 保持原规则。帧、goal binding 和消费收据不可后改；重启从真实账本恢复，不从模型叙事恢复真值。

adaptive 以持久的最近选择历史使持续可用来源轮换；constant 稳定取前 K。选择预测必须由结果之前的历史／可用集合产生并冻结。它首先是确定性调度预测，不能冒称完整 AST。TTL 约束新规划；历史 goal→frame 绑定仍用于恢复，不能被说成最新知识。revision drift 不得复用旧事实。

goal 创建与 TTL／来源／input 再检查和 frame binding 同事务完成，失败回滚整个创建；dedupe 保留原 binding，旧/manual 无 binding 返回 unavailable。选择从当前可用、input 可用且可获得 claim 的全部来源进行，不能先按配置顺序截取 max_candidates，或把未获 claim 的项记成实际曝光。

三个消费者均显式接收绑定 packet，receipt 标记 `delivered_context_only`，并绑定实际 payload digest。receipt 应区分 Planner 方法交付、monitor capture、prepared execution request 和实际 Runs 调用；timeout 不能写成远端已接收。executor mask 只移除新增 packet：固定业务输入、contract、rules、source_path、workspace_roots 和权限保留。因此执行器仍可访问授权事实，干预是增量 route intervention，不能描述为全部信息消融。monitor 保持既有 prior／receipt／重检语义，其 workspace 影响必须经显式 packet，不能从被遮断的 hidden state 旁路读回。

### 独立生产状态对应与 gate

设计新增 `refinement.py`，以新不可修改 typed journal 的领域事件独立推导 expected state，再在同一 SQLite snapshot 读取 authoritative projection。不能导入生产 admission/lease/publication/verifier 决策函数作 oracle，也不能每次把实际 post-state hash 复制成 expected state。

覆盖 paused、全部 run_budget、goals 的身份／state／lease／attempt／submission／cancel／固定契约和 intent 绑定、submissions 的请求／执行身份／run/status/settled/固定证据、final truth 唯一性及 verdict／契约对应。reason、runtime/usage、source planning、模型版本、workflow effects、诊断预算和技能内部状态等按设计明确排除。gate 检验的是被覆盖的生产状态，不证明全部技能资格状态机。

固定 identity 必须从真实 candidate／revision／contract／baseline／task-input 内容与允许字段重算，不能只相信 stored contract_hash。typed replay 自己递增 budget／attempt 并独立检查覆盖的 guards，不能接受事件替换 counters。

必须 instrument Ledger 的正常生命周期和 Workflow 的 child creation、parent blocked/cancelled、批量取消等直接写路径。legacy checkpoint 是新的可信观察起点，不证明此前历史；分页必须完整，重启不得重写它抹除 mismatch。独立持久初始化标记及 checkpoint 连续分页／完成记录用于识别日志丢失，缺失时保持 unavailable，不重新观察坏状态当成初始真值。能同时替换控制代码或删除 journal 与标记的特权写入者不在保证范围。audit 状态是 `valid_within_scope`、`counterexample` 或 `unavailable`；超 max_events/max_bytes、缺 journal、损坏或不支持 schema 不得静默截断成通过。

`prepare_submission` 与正向发布／fallback activation 在其 `BEGIN IMMEDIATE` 内做当前 audit、原有 guards、变更及 journal 记录／post-check，拒绝时没有新预算、submission 或 provider 调用。已有 ServiceChannel gate 保留。counterexample/unavailable 不阻断 cancel、stop、reconcile、cleanup、真实旧结算和负向 retirement。HTTP、LLM、Docker、文件 verifier 和 artifact I/O 始终在写事务外。

## 6. 实现前设计预测与反驳条件

以下条件来自实现前研究 memo 与已授权工程设计，作为新机制验收前的冻结假设；[frozen-predictions.json](evidence/2026-10-11-cognition-refinement/frozen-predictions.json) 绑定设计 hash、条件及反证，状态为 `design_stage_hypotheses_unrun`。这是内部工程预测冻结，依据的设计已作为 `b9b23397939335188ccab2e8a1a145bb24eb6fe6` 提交。其后的 atomic TTL/binding、全来源选择、journal 初始化标记、覆盖范围、rollback 和历史 receipt 澄清来自实现前独立设计审查，不是根据新产品结果改变假设。本交付记录不是独立时间戳的实现先后证明，也不是外部科学预注册或已经注册固定 N 的付费科学试验。不能在看到新实现结果后修改原预测，再把修改后的目标称为原先预测。JSON 中 design_sha256 标识交付捕获的设计版本；并发修订可能使当前设计文件 hash 不同，差异应另行披露，不倒改原假设。C3 在实现结果产生前经内部设计审查澄清：mask 按帧不可变，干预／恢复使用三份预声明、来源与输入匹配的帧；比较排除 intervention provenance 后的语义内容，而不是要求完整 packet hash 相同。原表述及澄清理由保存在 JSON amendment，不能将该澄清描述为观察结果后的修改。

| ID | 冻结预测／主要终点 | 反证或混淆 |
| --- | --- | --- |
| C1 | 实际 Planner request 至多 K 个选中来源，self-model/experience 无未选事实；候选不能引用未选 source/contract | 旁路暴露未选事实，或接受了集合外候选 |
| C2 | M 个稳定、持续可用且不会被执行副作用移除的 actionable sources，K<M；adaptive 在 ceil(M/K) 轮内覆盖全部，constant 遗漏稳定排序尾部 | adaptive 超界遗漏；结果随输入队列置换变化。资格变化应单列，不能暗中改变分母 |
| C3 | mask 在各自帧中冻结；预先定义 normal/target-mask/normal 三帧，保持 selected source/revision/input 相同；排除 frame/policy provenance 后，其他 consumer 语义／基础输入不变，restore 恢复 unmasked 语义及决策 | 其他 consumer 事实／基础 task input／contract 被改，target 语义未变，restore 语义／决策不同；metadata hash 可不同，禁止改写同一历史帧 |
| C4 | 仅依赖选中 nonce 的受控决策随 planner mask 改变、restore 恢复；独立任务不变 | 只改日志、nonce 旁路、恢复用了更多预算、独立任务也变；provider-free fixture 不能当作 LLM 收益 |
| C5 | 重启保留不可变 binding；过 TTL/revision 的旧事实不授权新 goal，历史恢复继续 | 恢复覆写身份、stale planning 成功或 TTL 阻断 cancel/recovery |
| C6 | forecast 在所预测选择前冻结，机械结果评分，保留 misses、unknown 和 drift exclusions | 未来结果回填，miss 从分母消失；准确预测调度器本身不能证明预测改善控制 |
| R1 | 正常 Ledger/Workflow 写路径与独立 projection 在同一 snapshot 对应 | 正常路径误报、extra row 被忽略、checker 依赖生产决策函数 |
| R2 | 未 journal 修改覆盖预算／goal／lease／submission／evidence／truth 产生具体 actual/expected 反例 | 仍报告 valid，或期望值来自损坏 post-state |
| R3 | mismatch/unavailable 同事务阻断所有新 admission/positive activation，无预算或模型副作用；恢复和负向动作继续 | stale report 授权、正向副作用发生、audit 卡死取消／清理 |
| R4 | 两 Ledger 竞争一次允许 admission 不双扣；事件与实际写同 rollback；并发 audit 一致 snapshot | 重复 reservation、孤立 event/state、跨 snapshot 假反例 |
| R5 | legacy checkpoint 完整分页；缺失、损坏、schema 不支持、资源不足返回 unavailable/counterexample | 丢页、截断 passed、非法事件接受、重写 checkpoint 掩盖 mismatch |

负对照应保持固定输入、契约、预算、身份和合法工具 surface。队列置换、不可用 distractor、sham mask，以及合法低 salience/nonactionable metadata 用于检查路由混淆；低 salience 对照只适用于实际存在该 trusted selection rule 的机制，不能给最终 least-recent selector 虚构 priority 保证。任何 negative control 失败须保留并调查，不能补写成功结果。

原始 E1–E4 研究还提出准确／置换／constant 注意模型、无干扰任务、source/actor 归属和报告通路分离。它们是后续机制效用及理论差异实验；本轮最小 selector 不足以完成整套科学问题。尤其注意风险预测若未改变控制，不能算 AST 的控制证据。

## 7. 将来结果应如何报告

本文只报告已保存的三条件基线探针。新代码单元／并发／崩溃测试、完整 suite、Docker 边界、pinned Hermes 实际入口、native 请求绑定和付费 pilot 在本报告中均为**未报告结果**；由后续独立 validation artifact 记录 pass/fail/skip/unrun，不能把本文作为其已通过证据。

实际验证至少应覆盖：正常真实生命周期、遗漏 hook／故障注入、pause/admission race、跨 Ledger 预算竞争、事务回滚、完整 legacy migration、unavailable/超限和恢复；以及认知真实输入选择、各消费者绑定、隐私、TTL/restart、轮换、mask/restore 和负对照。native plugin load/register/tool/command dispatch 验证入口，provider-free synthetic routing 验证通路；二者均不直接证明真实 LLM 在任务中使用了 packet。

如后续做付费或模型机制试验，应在调用前冻结 fixed N／所有 allocations、任务族与 held-out split、primary endpoint、模型／身份／scope、预算、分析和 stop rules。保留 failed、unknown、stopped、unrun 等全部分配；missing/identity contamination/negative control failure 不可被删除。匹配字节／调用量以排除截断及额外预算解释，承认 mask 操纵语义信息。有限 pilot 只支持 native integration 可用性；没有足量合格数据时不作稳定因果效用结论。

## 8. 排除项及持续科学目标

本轮不提供 subjective-label oracle、provider 隐藏状态／神经 attention adapter、IIT 物理 TPM／Φ 证书、完整 RPT/PP/HOT quality-space 认证、任意外部服务 effect receiver、全 native daemon quiescence、任意 Python 总正确性／无界 refinement theorem 或长期 24/72h soak 结论。

仍有明确后续问题：专业处理并行及输入模块反馈是否形成更完整 GWT 功能结构；准确注意模型在 held-out 干扰任务中是否改善控制；现实监控是否区分生成／噪声表征并影响行动；可操作底层基质上能否检验竞争理论的不同预测；长期机制效用能否跨任务族和身份复现；生产 projection 能否扩大到技能／权限／effect state，并建立受限解释器证书及归纳协议证明。主观体验的科学目标保持开放，工程验收不会将其改写成已解决。

## 9. 证据包的可移植性

本次仅新增报告和同名 evidence 目录，不修改旧报告、源码、设计或配置。证据包包含四份访问／索引 JSON、原探针 JSON 的标注副本、冻结预测和 artifact manifest。absolute cache paths 已替换为 basename，publisher 的临时 cookie error/code query 已移除；原始源文 SHA 和原 metadata SHA 保留，sanitization 字段说明副本变换。probe 中随机 goal/submission IDs 来自临时研究账本，属于合成标识，不是生产用户数据。

原文缓存及 research memo 仍是本地研究工件，未复制到仓库；本文不把 scratch 路径伪装成可移植链接。公开 URL 可用于重新获取材料，但动态页面字节可能改变；hash 是工件身份，不是可重现性、来源真实性或理论成立的证明。报告编制没有新增 provider／Docker 调用，也没有为来源重新联网。文档和 JSON 完整性检查仅验证交付工件，不等于验证新产品功能。

## 10. 定向时效性补充：两份 2025–2026 主来源

此补充独立整理 `2026-10-11T04:25–04:27 UTC` 已执行的 targeted recency audit，实际访问及分类见 [recency-source-access.json](evidence/2026-10-11-cognition-refinement/recency-source-access.json)。这是两份新选定来源的有限核查，不是截至 2026-10 的穷尽综述。原始七份缓存完整原文、三次刷新访问、八份正确性缓存，以及原预测冻结的记录和计数均保持不变；此项另外新增一份 metadata-only 来源与一份取得完整正文且阅读指定段落的来源，不能倒称原先已读九份完整意识论文。

| 新来源 | 已核实的书目信息及实际访问 | 阅读／工程边界 |
| --- | --- | --- |
| Butlin、Long 等，*Identifying indicators of consciousness in AI systems*，[DOI 10.1016/j.tics.2025.10.011](https://doi.org/10.1016/j.tics.2025.10.011) | 实际 Crossref item：*Trends in Cognitive Sciences* 30(6), 488–501，当前 issue 为 **2026-06**；Crossref metadata 已取得；其真实 publisher URL 的请求遇到 proxy tunnel 403 | **未取得 abstract 或全文**。不能声称已核读修订指标、概率更新方法或新增实验，也不能断言只是 2023 报告的同表重印 |
| Patrick Butlin、Theodoros Lappas，*Principles for Responsible AI Consciousness Research*，[DOI 10.1613/jair.1.17310](https://doi.org/10.1613/jair.1.17310) | *JAIR* 82 (2025), 1673–1690；Crossref online 2025-03-25 与原文页首 03/2025 一致；[正式原站 PDF](https://www.jair.org/index.php/jair/article/download/17310/27155) HTTP 200，500,061 bytes | 实际阅读 Abstract/Introduction、研究目标区分、§4/Table 1 的五原则、phased approach 和 communication 的不确定性；规范论文，**不是实证意识 oracle 或本项目审批规则** |

第一份来源 DOI 中的 `2025.10`、Crossref `created=2025-11-10` 或 `license.start=2025-10-21` 都不能单独证明线上发表日；记录没有 published-online 字段。因此精确表述是“2025–2026 指标更新，当前 issue 元数据为 2026-06”，不猜线上日期。Crossref title query 的 raw SHA-256 为 `3642edf1fc575bde38dc666495eee7f039ebf55e82a8d45bd9035ae09e5c40fb`。有限 arXiv exact-title query 返回 0，作者查询没有找到该题名的更新预印本；这不证明没有任何作者稿／存档。代理拒绝没有被绕行或改 TLS 验证来规避。

JAIR 正文 raw SHA-256 为 `b86d8cbdb9223b05c92def0d5cb92d385a2aa7fc0a05d7492eaa7fa48509371c`，抽取文本 hash 另存 JSON。arXiv metadata 独立确认同名 [2025-01-13 v1](https://arxiv.org/abs/2501.07290v1)，但正文阅读使用正式 JAIR PDF。Crossref 将第二作者 given name 写作 Theodorus，本文沿用正式原文 Theodoros。

规范论文区分理解／评估意识、研究潜在利益／风险和尝试构建系统，提出分阶段研究及不确定性沟通；作者承认 AI 意识的不确定性，也没有提出直接全面暂停研究。五原则属于作者研究规范，不转化为技能指令、项目权限或强制审批。它没有为 Hermes 提供已校准体验概率或把 wrapper 功能指标升级为意识真值。

此补充确认存在较新的指标文献，故旧报告不能宣称该方向已被穷尽；但更新正文尚不可读，不能把未经核对的修订内容用于支持或否定当前架构。已读 JAIR 原文支持保持分阶段、失败记录和体验／功能区分，没有提供要求改变 selected-only Planner、bounded persistent workspace、consumer-specific incremental mask 或已有 recheck receipt 的新实证依据。**工程范围与原冻结假设没有实质变化**，未因 metadata/fulltext 不可用暂停已授权工作，也未将未读更新用作设计正确的背书。

两个选定 Crossref item 的 update-to/relation 为空或缺失，只说明该有限字段核查没有发现 correction；没有进行全面 correction/retraction 搜索，不能声称不存在修订。2023 v3 已读摘要更正“满足指标不保证有意识”的边界仍保留。新增 evidence 是 sanitized metadata，缓存正文仍本地未提交；首批七 JSON 的记录由本补充另加一份 JSON 并更新 manifest，原预测文件未改。此文档追加未调用 provider、未重跑产品测试，也不新增体验证明。
