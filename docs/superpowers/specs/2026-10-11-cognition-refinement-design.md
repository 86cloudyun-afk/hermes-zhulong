# 意识机制实验与运行时正确性对应设计

日期：2026-10-11（Asia/Shanghai）。基线：`cda80862312977463c48aa02bda00353169d3c41`。

用户已授权研究、实现、测试、独立审查、PR 与审查后合并。本设计延续该授权。

## 研究问题与路线选择

意识研究区分自主行动、功能性自我监控、理论相关机制和主观体验。Butlin et al. (2023, arXiv:2308.08708v3) 的指标并非意识充分条件；COGITATE (2025, Nature, doi:10.1038/s41586-025-08888-1) 检验的是特定人类神经预测，不能据此给远程语言模型计算意识概率。现有监控已有事前预测、负对照和限定重检，本轮不重复构建 confidence。

比较三条意识路线：人格/自述包装不能提供独立证据；远程模型隐藏状态或 IIT 物理转移分析缺少接口和合法测量条件；实际可控的信息选择、持续保持与消费通路可以提出有限、可反驳的功能预测。本轮选择第三条。

正确性比较独立实现对应检查、受限 DSL 全域证书、TLA+/归纳证明。当前最具体缺口是日志与真实 SQLite 状态没有对应检查，故先落实第一条。有限模型枚举仍保留为单独证据；本轮不宣称任意 Python 的总正确性、不宣称无界 refinement theorem。未来 DSL 必须由同一个可信解释器执行证明对应的工件，不能给任意 Python 贴一个证明标签。

## 共同约束

- Python 3.11+，标准库，无新运行时依赖；使用实际 Hermes 插件入口、Controller 和 SQLite Ledger。
- HTTP、LLM、Docker、Verifier 文件或 argv I/O 必须在 SQLite 写事务外。
- 权限、固定验收契约、任务输入、预算、租约、取消与恢复不可由认知实验降低。
- 未知、审计不完整、超时与接口不可用保持明确状态，不转换成成功、失败或零成本。
- 研究报告分别列出实际功能证据、未运行实验和无法识别的主观体验；不生成 consciousness score。
- 托管环境沿用当前隔离 checkout 的功能分支，不建立额外 worktree；安装脚本的完整模块列表必须同步更新。

## A. 限容量认知工作空间

新增 `cognition.py`。`validate_cognition(raw)` 验证可选 `autonomy.cognition`：`enabled` 默认 false；`capacity` 默认 3、范围 1..8；`ttl_seconds` 默认 120、范围 1..3600；`mask_consumer` 默认 null、允许 planner/executor/monitor；`selection_mode` 默认 adaptive、允许 adaptive/constant。拒绝未知字段、非有限值与 bool/int 混用。

`Workspace(ledger, policy, identity)` 提供 `select(observations, now)`、`planner_view(frame, observations, now)`、`bind_goal(goal_id, frame, now, *, connection=None)`、`execution_packet(goal_id)`、`monitor_packet(goal_id)`、`summary()`。SQLite 初始化、帧和绑定写入与元数据检查均不做外部调用。Ledger.create_goal 接收可选 cognition frame，并在创建目标的同一事务里重检 TTL、来源/revision/input binding 和写入 goal-frame 绑定；失败必须回滚整个目标创建。

dedupe 命中时保留原绑定，不把新帧写到旧目标；旧/manual 目标无绑定时返回 unavailable，workflow child 可以继承父目标的明确历史绑定。调用 planner_view 前重新核对观察 facts/input 哈希，拒绝替换。配置与 mask 随帧冻结；重启改配置不改历史 goal 的 packet。execution_packet/monitor_packet 返回 historical metadata（含捕获/到期时间），不声称事实仍最新。

每个帧冻结 schema、identity hash、政策/机制 hash、captured/expires、至多 K 条 source_id/revision/input_hash/facts_hash、选择顺序及事前 selection forecast。帧只存元数据和摘要；观察事实保持短暂内存，已有明确允许持久化的 task_input 仍按原规则保存。帧、goal binding 与 consumer receipt 必须不可 UPDATE/DELETE。消费记录绑定帧和实际 payload hash，记录交付渠道而非声称模型内部读取。

adaptive 选择使用持久的最近选取次序，使持续可用且尚可规划的来源轮换；constant 对照始终按稳定来源顺序取前 K。预测下一选择必须在该轮实际选择前由旧历史与当前可用集合计算并冻结，不能用结果填预测；它是确定性注意调度预测，不能称为完整 attention schema theory。TTL 限制新规划与当前信息消费；已创建 goal 的历史绑定用于重启恢复，不因旧帧到期改写固定任务。

Controller 必须在真正调用 Planner 前进行容量选择，Planner 只获得选中的 observations。选择集合是全部当前可用、input snapshot 可用且 source claim 可获得的来源；不能先按配置顺序截取 max_candidates 再选择工作空间。source claim 与工作空间次序必须确保未获得 claim 的来源不会被记为实际规划曝光。工作空间启用时去除 `active_commitments`、`policy_hypotheses`、`experience` 等可能携带未选事实的上下文旁路，仅保留与选中来源匹配的 scoped statistics。LLMPlanner 明确接收冻结的 workspace packet。planner mask 保留身份、revision、契约 ID 等授权元数据并遮断新增事实渠道；候选验证仍使用原始选中 observations。帧到期后不得创建新 goal。

现有 domains/contexts 是 domain/identity 聚合而非 source-scoped，启用工作空间时也应移除，不能重标为已选来源的统计。consumer receipt 区分 Planner 方法交付、monitor capture、prepared execution request 与实际 Runs 调用；预备收据绑定 submission ID 和精确请求 hash，调用超时不能写远端成功接收。

每个由 Planner 创建的 goal 绑定当时帧；execution intent 和 attempt monitor 捕获同一历史绑定的 consumer packet。executor mask 只遮新增 workspace packet；固定任务输入、contract、source_path 及合法工具访问保留。monitor mask 只遮新增 packet，已有独立 metacognition 权限和重检语义不改变。receipt 明确 `delivered_context_only`；既有 API 没有 hidden activation、attention map 或物理状态访问，相关能力返回 unavailable。

功能实验预先冻结预测与条件：容量外来源不进入 Planner；持续干扰下 adaptive 能轮换而 constant 会遗漏尾部来源；遮断 planner 通路改变依赖该事实的受控决策并可恢复；指定消费者遮断不影响另外两个 packet；重启和 TTL 不伪造最新知识。真实 Hermes 注册/入口/请求绑定须验证。受控消费者结果只支持该通路的功能作用，native context delivery 不等于模型实际使用，更不等于主观体验。

## B. 独立生产状态对应检查

新增 `refinement.py`，不导入生产 admission、lease、publication 或 Verifier 决策函数。独立严格 JSON 事件语义重建预期状态，另从 authoritative 表计算实际投影，在同一个 SQLite snapshot 对比。

最小覆盖：paused；所有 run_budget；goal 集合、state、owner/generation/lease_until、attempts/current submission/cancel_requested、contract_hash 与固定 intent identity；submission 集合、goal/attempt、request/identity hashes、run_id/host_status、settled、固定证据 hash；final truth 的唯一性、verdict 与契约绑定。允许 reason、runtime/usage、source planning、模型版本、workflow effects、诊断预算、技能内部状态等明确 stuttering/exclusions；技能发布 gate 只依赖这些受覆盖生产状态，并不证明技能全部状态机。

固定 identity 从实际 candidate/source_revision/contract 内容/baseline/task-input binding 与允许 payload/created/deadline 推导，submission 固定身份包括 request/session/execution identity/created/retention。不得仅相信存储的 contract_hash。typed replay 自己递增预算和 attempt，独立检查已覆盖的 pause/budget/cancel/ready/lease fencing/current submission/final verdict/contract binding，不接受事件提供替换 counters。未知 workflow/skill 决策仍列为排除项。

`initialize(c)` 创建新的不可修改 journal，迁移仅记录有界分页的完整初始 checkpoint。它是可信观察起点，不证明历史；以独立持久标记识别已初始化账本，重启发现日志丢失、清空或 schema 不符必须保持 unavailable，不能从坏状态重新建 checkpoint。`record(c, action, payload, now)` 记录明确领域操作，参考重建器依据操作语义推导改变，禁止以每次实际 post-state hash 当成期望值。必须覆盖 Ledger create/claim/renew/release/admission/runtime/transition/attempt evidence/finish/cancel/pause 及 Workflow 直接创建、阻塞和取消写路径。

标记、checkpoint 全部分页与完成页数在同一事务提交，校验连续 seq/pages 与内容完整性。可信边界包含受保护 checker、SQLite、合法写路径；能同时删除日志和标记或替换控制代码的特权写入者不在保证范围。

`audit(c, *, max_events=100000, max_bytes=33554432)` 返回 `valid_within_scope`、`counterexample` 或 `unavailable`；字段包括 schema/checker hash、through_seq、snapshot hash、coverage/exclusions/checkpoint boundary 与具体 actual/expected 差异。超过预算、不支持 schema、journal 缺失、解码失败返回 unavailable，不截断为通过。遍历期间使用单一 read transaction，不把并发合法 commit 当成 mismatch。

新 `prepare_submission` 在已有 `BEGIN IMMEDIATE` 内先 audit，再做既有 guards/reservation/typed record，最后核对 post-state；counterexample 或 unavailable 拒绝 admission，预算、submission 与模型调用不发生。正向技能发布和 rollback activation 也在其事务内 audit；负向退休、拒绝、取消、stop/reconcile/cleanup 不被 gate 阻断。失败原因明确为 `refinement_blocked` 并可查询。生产 status 每次展示当前 audit，与旧 bounded model check 明确区分。

post-audit 失败需显式回滚整个 reservation 后才返回拒绝，不能在 connection context 内 return 而提交。SkillStore.sync 同时退休旧版本和启用 fallback 时，审计失败只延迟正向 fallback，负向退休提交。日志不可用时恢复写路径保持可用，audit 持续 unavailable，不重置期望状态来“修复”结果。

业务验收 truth、host 生命周期观察与 OS execution quiescence 必须分开。`settled` 在此投影中只是账本字段；远程 Runs 完成状态不是独立 OS 进程空集证明。本轮不制造 quiescence certificate。

## 验收与边界

真实 Ledger 生命周期/Workflow/技能发布无误报；直接遗漏日志的预算、状态、owner、submission、evidence 修改给出反例；两 Ledger 并发 admission 仍只扣一次；事件和真实写同 rollback；损坏后取消/恢复允许；预算超限明确 incomplete；大型 legacy checkpoint 完整且分页。认知测试检验真实规划输入、各消费者绑定、隐私、TTL、重启、公平选择与负对照，不以自述作为 oracle。

最终运行完整 suite、实际 Docker 边界与 pinned Hermes 插件加载和新增入口验证；结果分开记录 pass/fail/skip/unrun。独立审查后提交 PR，CI 通过再合并。付费实验如运行则使用已授权 DeepSeek 优先模型并冻结次数/条件，不能用单次 pilot 宣称因果改善。长期科学目标不因此被标为解决。
