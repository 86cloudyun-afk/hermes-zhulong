# 限定检查器机械证明实施计划

依据：[独立审查通过的设计](../specs/2026-10-11-ticket-kernel-formal-design.md)。Lean 实现与 C 运行时修复分属隔离文件，合入仓库前完成独立证明审查与来源核对。

- [x] 检查实际 kernel、formalization roadmap 和 actual mapping，固定有限目标及独立设计审查。
- [x] 取得固定 Lean v4.19.0 toolchain，保留 verified-TLS 来源、source commit、实际 archive SHA、版本、真实 setup exit status；不更改全局工具链。实际 archive 为 343,842,845 bytes，SHA-256 `6fe3ce97a58f44e2b3567d455b994eacec5bfe9ae7774f2a573444480ba813fe`；Lean／Lake 版本命令均 exit 0。见 [安装来源](../../research/evidence/2026-10-11-core-kernel/lean-toolchain-installation.json)。
- [x] 表示完整 typed grammar／上下文，定义实际 concrete evaluator 和 source-equivalent resource accounting，通过 checked termination；证明 n-ary Terms 表示对应。
- [x] 证明 arbitrary integer affine bounds、add／scale／difference、uniform ge／min／if 和 singleton zero-extrema equality；编译边界例子。
- [x] 证明完整 mutually recursive derivation soundness，包含 n-ary、全部 Int／Bool／Priority constructors 和 priority score compatibility。
- [x] 实现并证明 computed all-cell checks／十组 filtering、occurrence-preserving sorting、contiguous-chain coverage 和每 cell 独立业务规范。
- [x] 组合一般 `rowCertificateSound` 及独立 priority-spec corollary；两个非相同 AST 的完整 fixture 接受证明、乱序输入和真实负例由 kernel 检查。
- [x] 冻结确切 source/tool bytes；完整 build、导出定理及正例的公理审计、fresh-directory replay 各自 exit 0；记录实际标准公理集合和所有失败日志。
- [x] 对确切源码与实际编译证据进行独立规格／质量审查，修复实质发现后定向复审。
- [x] 在 C 运行时提交结束后合入公开 Lean 源码、边界说明与可复用验证／CI 入口；5036c20 包装独立 SPEC／QUALITY PASS、root actual entry clean replay 四命令退出 0，当前 Python 测试与 proof build 分开报告。GitHub Actions 执行尚待实际记录。

所有未经实际执行的证明、build、审查和 CI 项目保持未完成。该计划不重新运行、回填或改变既有业务试验与真实时间 cohort 的原始分母。
