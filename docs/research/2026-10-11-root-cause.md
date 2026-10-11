# Hermes v0.8：失败根因的可验证研究

随仓库交付的 [来源访问索引](evidence/2026-10-11-source-access/root-cause.json)、[可移植复现命令](experiments/autonomy_frontiers/README.md) 与 [根节点重跑证据](evidence/2026-10-11-autonomy-frontiers/) 可独立核对。下文同名 scratch 文件指本次研究缓存；PDF/HTML 全文与原始下载日志留在 scratch，不随仓库发布。

日期：2026-10-11。只读基线：`deffc94e0c30ef3b20481ff6aaf9af5687371ef5`。未修改产品；所有下载、探测和实验在独立目录 `2026-10-11-root-cause/`。模型/API 调用为 0。

结论：v0.8 能证明部分任务没有满足冻结验收条件，并能要求新技能对原失败输入重新通过有限测试；这些证据还不足以确定失败根因。下一步应把诊断做成独立的、预算受限的实验对象：记录原失败，提出可证伪假设，冻结干预计划，在隔离副本中改变指定因子，再由可信检查器决定证据等级。语言模型的自述、可疑度排名和最小复现输入都不能单独升级成“已确定根因”。

## 1. 来源和实际访问范围

代理与 CA 保持继承配置，TLS 校验未关闭。正文下载均留下原 URL、HTTP 结果、字节数和 SHA-256；详见 `probe.json`、`probe-extra.json`、`probe-final.json`。源码定位属于本地基线，论文方法与工程建议分开陈述。

以下精选 8 项。出版社空响应、404、503 不冒充读过正文；教材是可用的权威方法正文，不冒充其所引用原始论文。特别校正：`arXiv:1301.2275` 实际提供 UAI **2001** 会议正文，不是 2005 年 BJPS 修订稿；首次下载文件名已更正为 `halpern-pearl-2001.pdf`，`probe.json` 的原始探测名称保留作为审计记录。

### 1) Causes and Explanations: A Structural-Model Approach — Part I: Causes

- 作者、年份：Joseph Y. Halpern、Judea Pearl，**2001**，UAI 2001，pp. 194–202。
- 官方存档：<https://arxiv.org/abs/1301.2275>；实际正文：<https://arxiv.org/pdf/1301.2275>。
- 访问：完整 PDF 已下载；复核结构方程、干预语义、AC1/AC2/AC3 定义、双重纵火/先占例子与模型依赖讨论。没有声称复核 2005 修订版。
- 方法：用结构方程模型 `M` 和具体上下文 `u` 明确哪些变量能被干预；实际原因须发生过、在适当反事实条件下影响结果，并满足最小性。多个事件均可能使简单“删掉一个是否还失败”判据失效。
- 对 Hermes：先声明诊断变量及可信边界，区别“某段轨迹与失败同时出现”与“指定改变在复现实验中改变结果”。
- 局限：反事实结论相对于已选模型；漏变量、错误依赖关系、不可行干预以及先占机制会改变归因。论文不是从任意代理日志自动恢复真实因果图的方法。

### 2) A Modification of the Halpern-Pearl Definition of Causality

- 作者、年份：Joseph Y. Halpern，2015，UAI 2015。
- 官方存档及正文：<https://arxiv.org/abs/1505.00162>、<https://arxiv.org/pdf/1505.00162>。
- 访问：完整 PDF 已下载；复核 §2 的 AC1、AC3、AC2(am)、§3 示例以及复杂度讨论。
- 方法：修改 HP 定义，对辅助变量的干预限制到实际上下文的取值；将实际因果与一般因果区分开，也说明不同合理定义会给出不同原因集合。
- 对 Hermes：诊断记录必须保存“实际输入、实际因子值、被改变变量、冻结检查器”，不能只保存一句原因。没有明确模型时，使用 `intervention_supported_cause` 比“唯一最终根因”准确。
- 局限：这仍是关于模型的定义，不消除多原因、模型选择与正常性判断的问题。小规模因子实验不等于满足任意 HP 定义的全部量化条件。

### 3) Simplifying and Isolating Failure-Inducing Input / Delta Debugging

- 作者、年份：Andreas Zeller、Ralf Hildebrandt，2002，IEEE TSE 28(2)。DOI：<https://doi.org/10.1109/32.988498>。
- 方法正文：Zeller 本人的《The Debugging Book》“Reducing Failure-Inducing Inputs”：<https://www.debuggingbook.org/html/DeltaDebugger.html>。
- 访问：Crossref 元数据复核题名、作者与年份；原作者旧站两个 PDF 路径均 503，未读到原论文正文。教材完整 HTML 下载，复核 `ddmin()`、PASS/FAIL/UNRESOLVED、1-minimal 定义、非确定性限制和匹配原错误类型的示例；教材明确其 `ddmin` 使用 2002 原实现的 Python 3 适配。
- 方法：逐步删除输入块；只保留仍复现**同一个失败谓词**的缩减。最后逐元素尝试删除，得到 1-minimal 复现，而不是全局最小输入。
- 对 Hermes：优先缩减已授权冻结 JSON 的数组项、非必要字段或可重放工具操作序列，降低后续诊断成本；必须区分新错误、原错误与无法判断。
- 局限：最小输入不是唯一根因；多种故障可能分别有不同最小输入。无效语法、变更验收、混入新异常与波动性会破坏解释。只能在副本中缩减，不能改写原目标输入或验收记录。

### 4) Program Slicing / Tracking Failure Origins

- 作者、年份：Mark Weiser，1984，IEEE TSE 10(4)。DOI：<https://doi.org/10.1109/TSE.1984.5010248>。
- 权威方法正文：Andreas Zeller，《The Debugging Book》“Tracking Failure Origins”：<https://www.debuggingbook.org/html/Slicer.html>。
- 访问：Crossref 元数据复核原论文；出版社返回 202 空响应，两个校园 PDF 猜测路径 404，故原论文正文未复核。教材完整 HTML 下载，复核数据依赖、控制依赖、动态切片、静态与动态切片区别及 “Things that do not Work”。
- 方法：从错误输出的变量/语句沿数据与控制依赖向后追溯，缩小需要检查的位置。Weiser 原始方法为静态切片；教材实现的是某次执行的动态切片，二者不混称。
- 对 Hermes：首先做任务级来源图：目标输入 → 提交请求 → 工具调用 → 工具结果 → 输出工件 → 验收收据。然后只对有本地源码且可重放的执行节点做程序级切片。
- 局限：依赖是诊断候选，并不等同干预证明。教材工具对异常、多语句行、条件表达式/推导式和 async 支持有限；不能直接装进生产 Hermes 并声称有完整跨进程或模型内部切片。

### 5) On the Accuracy of Spectrum-based Fault Localization / Ochiai

- 作者、年份：Rui Abreu、Peter Zoeteweij、Arjan J. C. van Gemund，2007，TAICPART。DOI：<https://doi.org/10.1109/TAIC.PART.2007.13>。
- 权威方法正文：Andreas Zeller，《The Debugging Book》“Statistical Debugging”：<https://www.debuggingbook.org/html/StatisticalDebugger.html>。
- 访问：Crossref 元数据复核原论文；出版社 202 空响应、作者校园 PDF 500，未复核原论文具体实验。教材完整 HTML 下载，复核 Tarantula/Ochiai 算法、排名评价与对开发者实际效用的限制。教材引用的 Ochiai 后续论文年份为 2009，故不把其具体结果反填进 2007 论文。
- 方法：汇总成功/失败运行中事件是否出现。Ochiai 可疑度为 `ef / sqrt((ef+nf)*(ef+ep))`，其中 `ef` 为失败且事件出现、`nf` 为失败且事件未出现、`ep` 为成功且事件出现的次数。它给出候选排名。
- 对 Hermes：按工具名、错误码、超时阶段、技能版本、上下文等匿名结构化事件排序，把最高候选交给干预实验；成功与失败样本必须处于可比作用域。
- 局限：相关性不证明原因；共同前置条件、总是同时执行的事件、任务难度、选择偏差与多故障都能误导排名。某行“高可疑”不能自动写入根因字段或自动停用全域能力。

### 6) Chaos Engineering / Principles of Chaos Engineering

- 论文作者、年份：Ali Basiri、Niosha Behnam、Ruud de Rooij、Lorin Hochstein、Luke Kosewski、Justin Reynolds、Casey Rosenthal，2016，IEEE Software，“Chaos Engineering”。DOI：<https://doi.org/10.1109/MS.2016.60>。
- 官方方法正文：“Principles of Chaos Engineering”，Chaos Community，页面注明最后更新 **2019-03**：<https://principlesofchaos.org/>。
- 访问：论文 Crossref 元数据复核，未获取论文正文；官方原则完整 HTML 下载并逐项复核稳态假设、控制/实验组、模拟真实扰动、证伪以及限制影响范围原则。这里的方法依据官方原则正文，不声称论文实验已复现。
- 方法：先定义可测量正常行为，提出扰动下仍保持正常的假设，在实验组施加指定故障，寻找相对控制组的偏离。
- 对 Hermes：在隔离测试配置中注入 HTTP 超时/结果缺失/进程崩溃/租约丢失/清理失败；检验不重复提交、证据不误发布、预算不越界、状态可恢复等具体不变量。
- 局限：故障注入暴露的是选定扰动与环境的系统弱点；注入成功不证明真实历史失败由该扰动造成。官方原则倾向生产实验，这不构成授权直接扰动用户生产；当前阶段应在副本与可撤销夹具中实施。

### 7) Reflexion: Language Agents with Verbal Reinforcement Learning

- 作者、年份：Noah Shinn、Federico Cassano、Edward Berman、Ashwin Gopinath、Karthik Narasimhan、Shunyu Yao，2023，NeurIPS 2023。官方存档及正文：<https://arxiv.org/abs/2303.11366>、<https://arxiv.org/pdf/2303.11366>。
- 访问：完整 PDF v4 下载；复核 actor/evaluator/self-reflection 三部分、反馈进入 episodic memory、实验与 §5/附录局限。没有进行模型实验复现。
- 方法：把环境反馈转换为语言反思，保存在记忆中，用于下一轮任务，不直接更新模型权重。
- 对 Hermes：适合生成“下次可尝试的策略假设”；与当前 `experience.py` 接口接近。可与独立验收结合检验后续行为表现。
- 局限：反思文本并不是程序轨迹或根因证据；它可以有帮助而不忠实于真正原因。论文讨论局部最优、记忆约束、测试驱动开发适用性等局限，不能推出通用自主纠错保证。

### 8) Language Models Don’t Always Say What They Think: Unfaithful Explanations in Chain-of-Thought Prompting

- 作者、年份：Miles Turpin、Julian Michael、Ethan Perez、Samuel R. Bowman，2023，NeurIPS 2023。官方存档及正文：<https://arxiv.org/abs/2305.04388>、<https://arxiv.org/pdf/2305.04388>。
- 访问：完整 PDF v2 下载；复核摘要、§3 对选项顺序等提示偏置的干预、CoT 未提及该偏置的示例与研究范围。没有复现这些付费模型实验。
- 方法：控制性地改变提示中的偏置因子，观察预测与解释是否变化；说明看似合理的解释可以遗漏真正影响输出的因子。
- 对 Hermes：模型可提出诊断假设，但不能自行赋予自己的解释 `intervention_supported_cause` 等级。证据升级应由实验收据与可信规则决定。
- 局限：研究对象是当时特定模型、任务与提示；不是证明所有解释总是不忠实，更不直接测量当前 DeepSeek 的内部机制。

## 2. 当前 v0.8 已有能力与缺口

| 已复核源码 | 已有能力 | 根因层尚缺什么 |
|---|---|---|
| `autonomy_checks.py:207–245`、`autonomy.py:228–247` | 机械验收的结果、工件哈希、契约哈希；区分失败/未知；某些安全重试 | 验收不满足通常只说明结果，不能分清错误输入、错误算法、工具失败或环境变化；`reason` 不是因果字段 |
| `task_inputs.py`、`skill_replay.py:25–59` | 原任务授权输入冻结；绑定失败提交；新技能覆盖原输入的字段回归 | 新技能通过证明有限条件，不证明旧失败为何发生，也没有对照旧代码/执行环境的因子干预 |
| `scripts/skill_smoke_evidence.py:46–91` | 在有限 smoke 中核对原生请求、终端命令、程序/输入 SHA 与返回值 | 不是全部任务都必须经过这个执行审计；不能把局部命令证据当成所有失败的完整轨迹 |
| `experience.py:29–35`、`experience_store.py:75–82` | 只把独立失败收据传给策略生成，并明确不得发明失败轨迹或原因 | 没有诊断实验计划、干预目录、对照收据、判别失败签名或根因证据持久账 |
| `self_model.py:112–115`、`reflect.py:295` | 状态为 hypothesis；模型复盘明确标记未经核验 | 没有“已否定假设”与“干预支持但作用域有限的原因”独立状态 |
| `skill_store.py:127–140`、`experience_store.py:177–188` | 根据绑定任务的独立失败停用/回退技能；策略基于独立首轮成功积累 | 绑定技能后目标失败是关联；尚未证明技能被执行以及失败由技能造成。可作为保守停用策略，但不能描述成已定位因果根因 |

一个实际解析一致性探测也暴露了可定位的入口：主 `json_equals` 在 `autonomy_checks.py:223` 用 `json.loads`，而技能评测和原生 smoke 用 `strict_json`。临时工件 `{"sum":0,"sum":6}` 在主验收中通过，反序 `{"sum":6,"sum":0}` 不通过，两个工件均被严格解析器拒绝为 `duplicate_json_key`。合法 `{"sum":6}` 在两边正常，布尔值输出不能混同整数。

这证明**当前两个可信路径的 JSON 解析策略不一致**；若升级要求全链拒绝重复键，主验收路径仍需补足。这里没有把它称为某次真实生产失败的已证根因，也没有改产品。原始结果在 `verifier-parser-probe.json`。前轮“重复 JSON 键已修复”应精确指向被修复的执行证据审计路径，不能自动扩展到主验收的所有 JSON 入口。

## 3. 已执行的低成本因子干预与缩减实验

实验脚本：`2026-10-11-root-cause/experiment.py`；收据：`experiment-results.json`。移植后的命令为加载管理环境后执行 `zhulong-python docs/research/experiments/autonomy_frontiers/root_cause_probe.py /tmp/hermes-root-cause-probe`。所有代码均为研究者写的确定性小夹具，使用新鲜 `Python -I` 子进程、2 秒超时；不调用模型，不触及真实业务输入，不声称获得容器隔离认证。

冻结参考函数为：对授权 JSON `observations` 的整数列表求和，期望 `{"sum":sum(observations)}`。两个明确注入的因子：

- A：在求和前错误丢弃负数；A=0 表示移除这个故障。
- B：在求和前错误丢弃最后一个元素；B=0 表示移除这个故障。

对每个上下文完整枚举 `2×2`，每格重复 3 次；固定随机种子 `20261011` 打乱 36 个运行顺序。每次记录输入/代码/输出哈希、期望值、实际值及干预因子，不更改参考函数。独立的缩减调用另计，不属于这 36 个因子运行。

| 输入上下文 | A=0,B=0 | A=1,B=0 | A=0,B=1 | A=1,B=1 |
|---|---:|---:|---:|---:|
| `[3,-2,4]`，两个故障均可显现 | 0/3 失败 | 3/3 失败 | 3/3 失败 | 3/3 失败 |
| `[3,0,4]`，负数过滤无影响 | 0/3 失败 | 0/3 失败 | 3/3 失败 | 3/3 失败 |
| `[3,-2,0]`，移除末尾零无影响 | 0/3 失败 | 3/3 失败 | 0/3 失败 | 3/3 失败 |

主上下文对应输出分别为 5、7、1、3，期望 5。36 次运行的确定性结果与表一致。能够得出的结论：A 在含负数且 B=0 的见证上下文足以触发此谓词失败；B 在末尾非零且 A=0 的见证上下文也足以触发此谓词失败。对实际 A=B=1 的联合故障，单独修复 A 或 B 都仍失败；两者都修复才通过。因此“修一处后仍失败”不是该处完全无关的证据。

这不是形式化认证某个 HP 实际原因定义的全部条件。二者为研究者选择的已知注入因素，结论仅限这些程序与输入；没有把结果外推到未枚举故障、不同算法、模型内部错误或真实历史运行。

缩减保留同一个谓词“夹具输出与参考求和函数不同”，得到：

| 故障配置 | 缩减输入 | 每次删掉单个剩余元素后 | 可陈述范围 |
|---|---|---|---|
| A=1,B=1 | `[4]` | 不再失败 | 1-minimal；暴露 B，完全看不见 A 的负数机制 |
| A=1,B=0 | `[-2]` | 不再失败 | 1-minimal；揭示负数过滤相关的最小见证 |
| A=0,B=1 | `[4]` | 不再失败 | 1-minimal；揭示末项遗漏相关的最小见证 |

这里按缩减输入重新计算数学参考值，是预先固定的参考**函数**，不是篡改验收。Hermes 原目标的固定 `json_equals.value` 不允许被诊断器改写：若缩减输入需要动态参考值，须在独立诊断任务中明确授权该参考函数，与原目标收据分开。该实验直接展示最小复现为什么不等于完整、多原因诊断。

## 4. 可落实的证据等级与诊断契约

建议新增独立诊断对象，而不是把当前失败 `reason` 改称根因：

| 等级 | 升级所需证据 | 允许说什么 |
|---|---|---|
| `observation` | 可信失败/未知收据，绑定提交、输入、代码（若可知）、检查器版本和工件哈希 | “该运行没有满足条件”；未知执行不写成确定失败 |
| `hypothesis` | 可测试的因子、预测、作用域；引用 observation | “可能由 X 造成”；LLM 与统计排名只能到此层 |
| `intervention_supported_cause` | 冻结实验计划；原失败可复现；指定干预、控制组与阴性对照；独立收据；同一失败签名；可执行作用域；预算与清理确认 | “在输入/代码/环境 H 下改变 X 影响了该失败谓词”；允许多个原因，不声明普遍/唯一原因 |
| `refuted` / `inconclusive` | 可信反例，或复现/环境/清理/检查器不确定 | “该假设在此实验被否定”或“证据不足”；不得为了闭环强填原因 |

最小持久字段建议：

```json
{
  "schema": 1,
  "origin_submission_id": "...",
  "origin_evidence_hash": "...",
  "input_hash": "...",
  "contract_hash": "...",
  "execution_context_hash": "...",
  "level": "hypothesis",
  "factor": {"id": "approved_factor", "actual": "...", "alternative": "..."},
  "prediction": "...",
  "plan_hash": "...",
  "failure_signature": "...",
  "control_receipts": [],
  "intervention_receipts": [],
  "negative_control_receipts": [],
  "scope": "Exact frozen task and tested environment only"
}
```

诊断器可读最小授权快照，不自动复制聊天、凭据、原始工具文本或扩大持久化授权。摘要只输出因子编号、证据哈希、等级与作用域。模型不修改输入绑定、检查器、环境身份、预算及证据等级；可信程序在发布事务中重新核对这些对象。诊断实验、代码生成、外部模型调用均有独立计数上限，失败/未知清理时停止。

## 5. 建议的下一阶段验收

1. **先有来源链与分类。** 为 frozen input、提交、工具执行和验收记录可核对关联；对没有完整轨迹的旧失败给出 unavailable，不让模型补写。将宿主超时、工具失败、验收失败、解析失败、未知清理分开，避免把现象混成原因。
2. **先采用小型可信干预目录。** 可撤销的输入选择、单个代码变换、固定 HTTP/进程故障、验收解析策略等，均在隔离副本运行。任意模型生成“修复脚本”先作为普通待测代码，不享有实验调度权限。
3. **把缩减与归因分开。** 缩减得到稳定的同类失败见证；因子实验再验证哪个改变影响结果。复杂输入使用语法/类型保持的删除规则，未知结果记为 unresolved。
4. **以证据错升为核心测试。** 无轨迹假设不可升级；未知不能计失败；任务/代码/检查器/环境漂移阻断升级；阴性对照同样改变结果时为 inconclusive；联合故障可以保存多个原因与最小修复集；重启不能重复占预算或发布旧实验结论。
5. **先离线完成真正可复现的门。** 本报告的 36 次夹具证明方法可低成本执行，但不是产品验证。生产接入时应对实际源码中的一个可控制路径完成影子对照，保存同一输入、同一检查器、明确因子差异及两边收据，再判断是否具备该路径的诊断能力。

不建议下一版使用“已自主找到所有失败根因”。更准确的工程目标是“对于具备完整可信输入与可重放执行的受限任务，自动提出并检验根因假设；其余任务保留无法判断状态”。这个目标可以落实、审查与测试，也能直接服务后续自主修复，而不需要假定主观意识或通用正确性。

## 后续工程入口（v0.9）

有界因子干预、独立 Docker 收据与 unavailable/unknown 的当前状态见 [工程清单](../deployment/engineering-closure.md)；实现范围与验收设计见 [研究落地规格](../superpowers/specs/2026-10-11-frontiers-engineering-design.md)。本报告的研究时点、实验结果和未运行提案保留原记录。
