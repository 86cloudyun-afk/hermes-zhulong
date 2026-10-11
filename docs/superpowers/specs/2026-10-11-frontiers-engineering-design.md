# 研究落地与真实 Hermes 工作验收

日期：2026-10-11。依据：用户已授权研究、实施、测试、PR、独立审查与合并，并要求将五份专题和历史遗留问题落地。沿用此授权，不重复阶段审批。

## 目标与选择

目标是可部署、能完成实际工作且能辨认自身失败和未知的 Hermes 插件。研究资产不等同于产品能力；主观意识、任意程序正确性以及长期收益不能由本次发布证明。

选择把 R0–R5 分成可独立验证的工程组件，通过已有 Controller/SQLite/Hermes Runs 接入。直接修改宿主工具循环会扩大可信边界；只增加提示词则不能约束恢复、证据或晋升。保留现有固定宿主、共享预算和独立机械验收，使用明确的可信配置描述工作流程。

## 全局约束

- Python 3.11/3.12/3.14；产品仅标准库；兼容旧账本与 11 hooks、4 tools、1 command。
- Hermes 宿主固定 `73162b00eefde3794bed0afb53d84a19c0eed230`；真实验收使用 `deepseek / deepseek-flash`，不声称已核验底层 V4.1。
- 不保存凭据或私有推理，不允许模型改变契约、权限、预算或控制代码。
- 新工作遵循暂停、取消、租约代次和原子预算；未静止执行优先对账，未知外部效果不盲目重试。
- 现有请求最多 16384 UTF-8 字节；授权业务快照最多 4096 字节/深度 32；传输封套与业务深度分开。

## R0：验收与证据契约

主 `json_equals` 使用全文件严格 JSON：拒绝重复键、非有限值（含溢出指数），保留布尔/整数/浮点类型区别。检查版本升级为 2，旧收据不重写。业务文件统一深度 32；深度改变作为兼容性变化说明。

增加可信内置 `json_reference` 契约：`path, reference_id, reference_version=1, require_change, safe_retry`。`reference_output(reference_id,data)` 计算工作量汇总、工单优先级和来源索引的确定性结果。`Verifier.capture(contract,task_input=None)` 与 `check(contract,baseline,task_input=None)` 只用已冻结且 hash/size/rule 绑定有效的授权输入，整份输出严格比较。契约跨不同输入保持不变；执行请求包含规则说明而不包含期望答案。无快照/版本不符为 unknown。

技能正向发布在同一个 BEGIN IMMEDIATE 事务内检查 paused；暂停期间保留已付费候选、token 和计划以便恢复，负向安全结算允许。选定的语义是 pause 返回后不再新激活技能；pause 前已提交发布不回滚。

## R1：持久步骤与效果

`workflow.py` 提供 `validate_workflows(raw,policy)` 与 `WorkflowStore(ledger,manifests)`。可信 `autonomy.workflows` 清单最多 8 个步骤/工作流，引用同一来源已配置的契约，依赖无环。冻结计划与步骤意图，父目标不直接派发；每个可就绪步骤原子绑定一个 child goal，沿用冻结输入与来源版本，经真实 Hermes Runs 执行。

`sync(now)` 注册父目标；`advance(now,admissible)` 对账、创建至多一个新 child；`is_parent(goal_id)`、`dispatchable(goal_id)` 与 `summary()` 支持 Controller。完成步骤不因重启重做；失败只在原 safe_retry 规则和预算内局部重试，依赖受阻可见。父成功要求所有步骤成功且静止及最终机械验收。

稳定 operation ID 和 effect ledger 记录动作意图及收据。普通 Hermes 文件/远程动作不宣称 exactly-once；opaque 模式阻止新重试，明确 unknown。受支持的本地事务 outbox 可以原子按 operation ID/intent hash 写一次通知记录，外部投递必须另有真实连接器对账。

## R2：有界干预诊断

`diagnostics.py` 从真实已结算的失败候选/机械收据建立冻结诊断计划。可信配置预先指定最多 3 个因素、各组合的纯 JSON 程序变体、参考例、原失败重放和负对照；禁止 LLM 临时改干预/评分。复用独立 Docker 评测器，冻结代码、输入、原收据、计划和环境 hash。

每 tick 最多执行一格实验，独立持久预算且共享暂停/停止。缺少可信原始绑定或旧输入为 unavailable；模型叙述只能为 hypothesis。全部可靠收据完成且负对照成立才能输出 intervention_supported；处理多因素背景和最小修复集合，不能把输入缩减当根因证明。未知/清理不明保留候选与未决实验，不伪造失败。

## R3：真实效用与因果试验

`causal_trial.py` 保存预注册协议、全部分配、固定输入 hash、随机顺序、机制与作用域版本，输出包含失败、未知、未执行在内的分母与成本缺失项。控制/处理必须冻结目标、身份范围和机制；不拷贝跨 profile 不适用技能，不以 learning_enabled 同时关闭多个机制冒充单机制消融。

`scripts/native_work_acceptance.py` 在保留的临时部署目录中启动真正 Hermes gateway/supervisor/Docker，用变化的工作数据做确定性业务任务。产物由可信参考函数验收，同时核对实际 native tool 调用、输入/产物 hash、run 静止及停止/清理结果。开始前写分配记录，失败也写收据；静止或清理未确认则停止后续调用，保留未运行分配。初次只做小型真实能力验收，不给出统计收益断言。

实施审查裁定：本版同时交付 `paired_fixed_n` 的不可变预注册、单机制/相同作用域校验、合格收据接口和固定 N 分析；真实 pilot 使用隔离 profile，不满足同一有效身份的配对干预要求。不得把它直接拼成合格的随机试验。真实同作用域配对执行适配器及足量实际样本仍待落实，明确列入工程清单，不自动开启长期付费服务。

## R4：功能元认知

`metacognition.py` 提供 `initialize(c)`, `prepare(c,goal,identity,request,now,policy)` 与持久绑定。准备请求时仅使用同来源/领域/契约/执行身份、同首次/重试分层、已静止且早于派发的布尔尝试结果，冻结当前尝试概率、样本数、模型/输入/请求 hash 和控制决策。零样本为 prior_only，不冒充模型置信度；旧收据明确保留 goal_prior 来源。

低可信度可触发有界独立前置复查及前提提醒，真实检查的收据/额外次数分别记录，不降低原验收。不使用生成后的结果反填预测。自我模型增加 AUROC2（平局 0.5）、confidence gap、类别数量及 coverage-risk，保留旧 availability 字段兼容并明确其含义。功能监控不产生意识分数。

## R5：有限状态保证

`assurance.py` 独立定义 admission/pause/lease/publication 的有限参考转移与不变量，BFS 枚举显式小范围。输出模型 hash、界限、状态/转移数、反例或在该界内未发现反例；不声明无限域/真实世界通用正确性。真实 SQLite 事务写最小 versioned protocol events，测试将实现轨迹投影到模型。

不变量至少包括：预算不超、未静止不新派发、陈旧租约拒绝、相同 operation 意图不变、pause 后无新激活、unknown 不作失败晋升。受控双连接时序验证 pause-before-publish 和 publish-before-pause。

## 历史问题的闭环

交付建立独立问题清单，每项有代码位置、测试和状态。深层 manifest 封套限制按业务值独立检查；来源变更需可信摄取/冻结途径而不放宽执行器权限；停止/清理未知准确保留；常驻健康/预算与磁盘阈值可测。真实邮箱/日历需要目标服务与凭据；硬 bind-volume 配额需要底层文件系统支持；24/72 小时稳定性只能实际运行相应时长。控制内核自动替换需要独立验证与可信发布边界。这些不得标为已完成，不能用本地 outbox、软阈值或短 smoke 代替其验收。

## 验收与交付

每个组件先记录 RED，再实现 GREEN；现有 suite、真实宿主导入和 Docker 测试保持通过。新增工作流程与根因实验须真正接入 runtime；功能缺配置时清楚标 disabled/unavailable。进行小型付费真实 Hermes 验收、独立任务审查及全分支审查，修复实质问题后 PR/CI/合并，再同步经测试的安装与云环境启动草稿。证据标注精确代码 revision，失败和未运行项不省略。
