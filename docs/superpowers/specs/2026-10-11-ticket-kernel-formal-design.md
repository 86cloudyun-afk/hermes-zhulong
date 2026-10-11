# 限定工单检查器：第一个机械证明里程碑

日期：2026-10-11 UTC。用户已授权持续研究、实现、测试、独立审查、PR 和合并。本里程碑落实 [formalization roadmap](../../research/2026-10-11-formalization-roadmap.md) 和 [实际实现映射](../../research/2026-10-11-formalization-actual-mapping.md)，不修改已经冻结的 attention／native 试验及其结果。

独立设计审查 **PASS**；报告 SHA-256 `6d365cee73b0885773936b79e14b4fea648d25350ab7ec09adc5986cfe66fab8`。本规格吸收审查对 n-ary 预算、独立 priority 规范、occurrence 覆盖、公理及 clean replay 的明确要求。设计通过不等于定理已经证明。

## 目标与语义对象

实际 Python 检查器为 `certified_ticket.py`，SHA-256 `232a90b524f8c248d764950bc021ab9fe2cc731c379fe5519b58bc99862fbbd2`。形式模型针对它的 typed post-decoder 核心，支持完整 Int／Bool／Priority 语法、score／priority 两种上下文、全部 affine 和统一分支规则，以及十组 severity／blocked 的完整区间覆盖。

主要定理的前提必须是计算出的 `checkTyped program certificate = true`。结论对每个合法 severity=1..5、age=0..87600、blocked:Boolean 成立：候选 score 等于独立业务规范 `100*severity + min(age,168) + blocked_bonus`，priority 等于独立 `businessPriority(specScore row)`（500／300 阈值）。不得把 score 正确、cell 正确或覆盖成立另加为最终定理前提。

必须实际证明两个不同程序和完整证书被接受，排除 always-reject 的空洞证明。正例包括实际 26-cell reference fixture 和非相同 AST 的等价程序；负例包括漏组、gap、overlap、duplicate、错误 witness／threshold、非统一分支及资源违规。

## 模型与检查要求

- Int 支持 literal、severity、age、priority-context score、n-ary add、常数乘、min、Int-if；Bool 支持 blocked／ge，禁止 Bool-if；Priority 支持三种常量和 Priority-if。保留 selected-only if、eager min 与左侧 tie 规则。
- n-ary add 的每个 operand 都是父节点的直接子节点。辅助 Terms cons 不增加 Python AST 节点或深度；root depth=0，24 可接受、25 拒绝，score／priority 合计最多 256 个节点。预算检查涵盖未选择分支。literal／scalar 与 supplied witness 的边界保持实际限制，不能额外限制 derived intermediate coefficients。
- affine extrema 证明覆盖正／零／负系数；比较依赖 difference 的双端点 min／max，uniform false 使用严格负上界。singleton 只要求值相等，不要求 coefficient pair 相同。
- score-reference soundness 显式使用“已实际计算 score 与当前 affine 相符”的条件，并由 score derivation 证明解除。独立规范不调用候选程序或证书计算。
- 全部 cells 都验证 numeric bounds／witness，并执行真实十组枚举、filter、排序及从 0 到 87601 的连续链。排序保持 occurrence permutation，链证明覆盖与唯一 occurrence；不能用样本计数替代覆盖。有效乱序输入必须通过。

## 工具、来源与公理

固定 Lean **v4.19.0**，官方 tag 的已核对 source commit 为 `6caaee842e9495688c1567e78c0e68dbb96942aa`。仅使用其 bundled Lean／Std；不引入 Mathlib、外部 solver 或模型调用。实际下载通过既有 proxy／CA 和 verified TLS；发行 API 的 publisher digest 为 null，实际本地 SHA 用于固定取得的 artifact，不称为独立发行方 checksum 认证。

标准 Lean foundational dependencies 的允许集合为 `propext`、`Quot.sound`、`Classical.choice`，并只报告实际使用者。`sorryAx`、用户新增 axiom、unchecked evaluation／oracle、`native_decide` 和未审查 `.olean` 均不能通过验收。采用 checked termination；完整 build、`#print axioms` 和 fresh build-directory replay 必须成功并分别保留 exit status、输出和 hash。

## 范围与完成条件

完成后可记录的是：**形式 typed checker／evaluator 模型的一般 soundness 定理通过 Lean kernel 检查**。JSON 解析／状态行为、Python 对应、实际固定 list wrapper、IO、准入／SQLite 和 native association 仍是另行对应与运行层义务。主观意识、长期收益和任意程序正确性不由该定理推出。

实现阶段只写隔离 proof workspace；C 保持唯一共享运行时实现者。随后按确切字节独立审查，再集成可审查 Lean 源码、来源和可复用验证入口。证明源码、正例接受证明、公理审计、clean replay 或 source/tool identity 任一不足，都保留失败／未完成状态，不以更弱定理替换后宣称原目标完成。
