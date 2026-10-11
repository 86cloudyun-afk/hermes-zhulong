# Hermes 的通用正确性边界与可落实验证路线

随仓库交付的 [来源访问索引](evidence/2026-10-11-source-access/correctness.json)、[可移植复现命令](experiments/autonomy_frontiers/README.md) 与 [根节点重跑证据](evidence/2026-10-11-autonomy-frontiers/) 可独立核对。下文同名 scratch 文件指本次研究缓存；PDF/HTML 全文与原始下载日志留在 scratch，不随仓库发布。

研究日期：2026-10-11 UTC。只读基线：`deffc94e0c30ef3b20481ff6aaf9af5687371ef5`（v0.8 main）。未修改产品或环境配置；未进行付费模型调用。完整访问记录及下载哈希见同名独立目录的 `access-index.json`。

**可以推进的目标是：在明确的输入、工具权限、状态和故障假设下，证明具体程序或控制内核满足具体规格。无法承诺的是：存在一个总能结束、对任意程序和任意语义目标都给出正确答案的通用自动判定器。** 这不妨碍对无限输入域的某些具体算法做归纳证明；“无限输入”本身不等于“无法证明”。

## 1. 精选八项实际获取的一手或官方来源

| 来源 | 实际阅读范围 | 对 Hermes 的含义 |
|---|---|---|
| [Turing, 1936, *On Computable Numbers, with an Application to the Entscheidungsproblem*](https://www.cs.virginia.edu/~robins/Turing_Paper_1936.pdf)，原论文大学存档 | PDF §8、§11 的不可判定性论证 | 任意程序的终止/某些语义性质不存在普遍、完备且总终止的判定过程。原文以 circle-free 与逻辑判定为表述，不伪称原文直接使用现代 halting problem 名称。 |
| [Software Foundations, Programming Language Foundations, *Hoare Logic*](https://softwarefoundations.cis.upenn.edu/plf-current/Hoare.html)，官方可机检教材 | Hoare triple、while、不终止循环与 partial/total correctness | `{P} C {Q}` 的部分正确性仅要求 C 若终止则 Q 成立；无限循环可让它真空成立。完整执行必须另证明终止或活性。 |
| [Lamport, *Specifying Systems*](https://lamport.azurewebsites.net/tla/book-21-07-04.pdf)，作者专著 | refinement/step simulation、公平性、TLC 枚举算法与有界配置 | `Init /\ [][Next]_vars` 可描述账本状态机；安全不变量与“最终完成”的活性要分别定义。TLC 的有界实例通过不等于任意数量 worker/故障模型全部正确。 |
| [Hypothesis 官方 stateful testing](https://raw.githubusercontent.com/HypothesisWorks/hypothesis/master/hypothesis/docs/stateful.rst) | 规则组合、参考模型比较、前置条件与每步不变量 | 测单个函数之外，还应测试 pause→resume、lease expiry→reclaim、rule drift→late report 等操作序列；属性测试找反例，不能代替演绎证明。 |
| [Dafny 官方教程](https://dafny.org/dafny/OnlineTutorial/guide) | requires/ensures、循环不变量、decreases | 在有限语法/显式规格下可以生成验证条件，证明安全和终止。证明的是给定规格，规格错误或过弱依然可能得出无用“正确”结果。 |
| [Hobbs et al., *Run Time Assurance for Safety-Critical Systems*](https://arxiv.org/abs/2110.03506)，作者预印本 | 已读全文相关部分：模型偏差、forward invariance、monitor/backup、safety filtering；PDF 实际取得 14,017,701 字节 | 不要求复杂主控制器自身可信，而由独立保证层约束实际动作。物理控制系统的动力学保证不能直接搬成代理软件的通用保证；可借鉴其架构与假设透明度。 |
| [OpenJML 官方 Runtime Assertion Checking](https://www.openjml.org/tutorial/RACCompilation) | RAC 编译/执行、检查范围与不可执行注解 | 运行时契约只证明这一运行中检查到的值；事后发现违规可能已经产生副作用，因此需要动作前约束与隔离。 |
| [Lean 官方 *Theorem Proving in Lean 4*, Introduction](https://lean-lang.org/theorem_proving_in_lean4/introduction.html) | 形式公理基础、完整 proof objects、独立检查 | 生成器可以输出候选证明，但可信性来自受控基础上的独立检查；模型说“已证明”或自然语言证明并非证书。 |

补充边界：Rice（1953）的定理适用于部分可计算函数或其语言的非平凡、外延语义性质。它不禁止判定代码长度、受限语法、固定步数内结果等性质。原刊 DOI `10.1090/S0002-9947-1953-0053041-6` 的 AMS PDF 返回 403，本轮没有读到该正文，结论按标准定理限定表述，不声称完成原刊全文复核。Hoare 1969 的 CMU 存档被代理明确拒绝，改用上述官方教材。Necula 的 *Proof-Carrying Code*（POPL 1997，DOI `10.1145/263699.263712`）作者存档路径 404、ACM 页面 403；这里仅讨论该设计模式，未冒称重读原论文。

## 2. 不可判定性究竟限制什么

对任意 Python 程序 P 和语义规格 S，不能制造一个算法 A，保证每次都有限时间返回“正确/错误”，同时对全部程序都准确。用测试集替代证明只能扩大已观察范围；用超时截断只能决定“是否在本次步数/资源预算内完成”，不能决定无限等待后的行为。即使输入域只含一个值，允许任意程序无限执行时仍没有通用终止判定器。

可行方式包括：限制为有限状态机并穷举全部可达状态；限制为可证明终止的 DSL；为一个具体算法提交归纳不变量与递减量；让检查器可以拒绝或返回 unknown。证明系统允许“不知道”，从而保持可靠性。`unknown` 不能被统计成功率或模型信心改写为 `passed`。

安全性是“坏事不会发生”，例如未经当前规则授权的请求不被新认领、未知清理状态不发布。活性是“好事最终发生”，例如已认领目标最终结束。活性必须假设宿主最终响应、调度公平、预算可用、目标可实现，并说明 deadline/cancel 如何改变目标；无限断网、永久宿主卡死或不可能的契约不满足这些假设。

## 3. v0.8 的真实基础与差距

`autonomy_store.py:183` 在 `BEGIN IMMEDIATE` 内验证租约、submission ID、新请求的当前输入/技能规则和预算；已有未结算请求优先恢复，不生成新请求。`skill_store.py:213` 在写事务内重验候选租约、当前 manifest、当前 frozen-input 规则、code/task/image、origin replay 与案例回执。`skill_replay.py:21` 从不可变目标和原请求重建评测计划。`skill_evaluator.py:210` 对有限案例严格 JSON 与 canonical 比较，未确认 cleanup 时返回 unknown。

这些是有价值的控制门槛，但并不证明任意生成 Python 的语义、全部副作用或完整工作流。报告中的 `code_hash` 说明绑定的代码身份，不能单独证明执行轨迹。有限案例相等不等于未见输入全正确，也不证明失败根因或因果提升。`runtime_policy.py` 的权限、只读挂载与隔离应属于受信计算基础，其与真实容器/宿主行为的对应关系仍需验证。

| 待补差距 | 可检验要求 |
|---|---|
| 尚无协议的机检状态规格 | 为提交/恢复/评测/发布定义显式状态、允许转移与 invariant；分别列安全/活性。 |
| 外部 gate 与事务之间的暂停边界 | `SkillStore.finish` 不读取 paused；当前支持入口由 `SkillLearner.tick` 在外部 gate 阻止暂停发布。要保证原子顺序，需在同一发布事务读 paused 或 policy/admission epoch，并重新验证。 |
| 脚本与抽象模型没有 refinement 证明 | 从真实账本事件导出精简状态，与模型逐步比较；模型遗漏的路径不能自动得到保证。 |
| 总正确性无明确范围 | 为受限计算提供总函数规格、终止递减量、资源预算；对任意 Python 保留超时/未知。 |
| 完整执行的副作用不在字段契约内 | 选择一个多步骤真实任务，将每一步预条件、允许写集合、结果、补偿和幂等键写成契约。 |
| 证据等级不够显式 | 区分有限案例通过、原任务回归通过、监控到的执行、形式化证书；不能合并成“通用正确”。 |

暂停观察是层次边界，不是已复现的生产竞态。可能的交错是外部 gate 为 true→另一连接设置 paused→发布事务；本轮没有启动多进程证明该交错在部署中发生，因此不得写成已确认漏洞。

## 4. 本轮无新依赖的实际有限枚举

脚本：同名目录 `publication_probe.py`；结果：`publication-probe.json`；退出状态：`publication-probe.exit` 为 `0`。它调用基线实际的 `Ledger`、`SkillStore.finish` 与 `SkillLearner.tick`，借用已有 `ReplayTests` 创建真实临时 SQLite 账本；只替换 Docker `_case` 和 cleanup，以避免模型、网络和实际容器。它**不是独立抽象状态机，更不是对整个产品的形式验证**。

对象界限：一个原始失败目标、一个 scope、一个冻结候选、一个当前租约、四项固定可信案例。对以下十二个条件的真假作笛卡尔积：租约当前、manifest 当前、输入规则当前、cleanup 确认、verdict 为布尔 true、code hash 正确、task digest 正确、evaluation digest 正确、原 submission 正确、原回放通过、所有案例回执 passed、案例 input hash 正确。共 `2^12 = 4096` 个分区，每次从同一冻结基线克隆独立账本。

反例条件：返回值或发布 active 状态与“十二个条件全部为真”不一致；或拒绝后候选状态发生变化。结果：**1 次合法发布，4095 次拒绝且保持候选，0 个所定义反例。** 额外的 image 错误、缺案例、passed 数错误、verdict=1、cleanup=1、origin passed=1 六个负例全部拒绝。

成对暂停实验：直接调用 `finish` 在 paused 时可接受合法报告；通过支持的 `SkillLearner.tick` 入口、使用当前 paused 作为 admissible 时，生成和评测均为 0，候选保留。未知恢复实验：cleanup 未确认的 unknown 报告不接受；defer/reclaim 保持原代码、原 token、原 evaluation digest，仅推进租约 generation。

这些结果没有枚举任意 JSON 值、任意 Python、两个 worker 的操作序列、多个候选 head 排序、SQLite 崩溃或 Docker cleanup 故障；也没有 TLC/Lean/Dafny 实际证明。最初研究探针误用 `Ledger.pause` 而失败，已改为真实 API `set_pause` 并完整重跑；这是探针错误，不是产品错误。

复现（不安装依赖）：

```bash
source /workspace/.cloud-onboarding/env.sh
zhulong-python docs/research/experiments/autonomy_frontiers/publication_probe.py /tmp/hermes-correctness-probe
```

JSON 记录实际 Git HEAD；在未来版本运行时必须比较实现差异，不能把不同 HEAD 的结果说成本次证据。

## 5. 推荐最小验证内核

把不受信的规划器、生成器放在保证层外，最小内核只做：严格解析请求；检查冻结输入、当前规则、scope 与 lease epoch；限制动作集合与写入资源；在事务里原子认领/发布；接收可信执行器的有限证据；对 unknown 保留恢复状态；执行撤销、隔离和审计。自然语言目的、信心和自我陈述不参与授权判定。

最先形式化的具体不变量应是：

1. 新提交必须带同一目标冻结输入和当前授权；恢复旧请求不得改写已冻结意图。
2. 同一 scope 最多一个 active 版本；过期租约/旧 generation/规则漂移不得改变版本发布状态。
3. unknown/cleanup 未确认/缺回执不得发布；重启复用冻结代码而不再次付费生成。
4. 暂停与撤销生效后不发生新的 admission/publication；其线性化点与已在执行的动作处理规则必须先定义。
5. 预算、snapshot 容量、active 数的检查和扣减在同一事务内，所有跨实例认领也满足上限。

推荐分阶段：先将这些协议转移写成 TLA+ 规格，TLC 取两个 worker、两个 goal、两个候选、三个租约 epoch、预算 0/1/2 的有界实例，明确消息重复/延迟/崩溃/规则变更范围。再用实现状态投影与模型做事件序列比较，把发现的最短反例纳入回归。最后只对小型纯函数或受限 DSL 引入 Dafny/Lean 等证明，不在第一阶段尝试给整个 Python/LLM/Docker 系统做全量证明。

受限生成代码可以逐步采用证书：候选给出输入域、总函数规格、允许操作、终止论证及 proof object；独立检查器绑定 code/spec/input-rule/compiler/运行语义哈希，并拒绝未批准的假设、admit/sorry 或受信外部调用。哈希绑定不能填补 Python 与验证语言语义差异；从验证程序到最终执行工件必须有受控编译/解释路径或逐步 refinement。只把 Lean 对一个数学函数的证明附在任意 Python 文件旁边，不能构成程序证书。

每项保证必须附可信假设：SQLite 事务/持久性语义成立、检查器与配置不被模型篡改、哈希抗碰撞、固定宿主/容器和工具权限真正执行、观测与契约足以表达目标。证明说明这些假设下的结论，不证明假设本身、更不证明主观意识。若下一阶段只能选择一项工程，应优先定义原子暂停/撤销与发布的协议，再建立可重放的状态事件轨迹和两 worker 的模型检查。

## 6. 交付与明确未完成范围

可提交的是本报告、`access-index.json`、`publication_probe.py`、`publication-probe.json`；源 PDF/HTML、下载辅助脚本、提取文本与 stdout 日志保持 scratch。没有提交产品改动，没有启动形式证明器，没有宣称普遍正确性、实际生产竞态、因果提升或意识成立。PCC/Rice 原刊访问受限已逐项记录，未绕过访问拒绝。

## 后续工程入口（v0.9）

有限 BFS 模型检查、错误变体反例与真实事务轨迹的当前保证范围见 [工程清单](../deployment/engineering-closure.md)；实现范围与验收设计见 [研究落地规格](../superpowers/specs/2026-10-11-frontiers-engineering-design.md)。本报告的研究时点、实验结果和未运行提案保留原记录。
