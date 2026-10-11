# 从形式模型证明到部署执行入口

研究检查点：`c04b8d7df4e08056e7e218ca9bb5eaf7b93c0994`。本路线的独立设计审查为 SPEC／QUALITY PASS；**严格解码器、新的 Lean 可执行入口和部署模式尚未实现或测试**。它不扩大当前 v0.11 的产品范围，也不改变现有 Python 检查器的证据状态。

当前一般 `HermesTicket.rowCertificateSound` 已证明：计算出的 `checkTyped=true` 与合法 row 推出独立业务 score／priority 关系。83 项闭包、14 个冻结源文件与实际重放见 [证明证据](evidence/2026-10-11-core-kernel/formal-model-proof.json)。当前受保护 runner 实际调用 `certified_ticket.py`，没有调用 Lean。因此，模型定理与部署中的 Python 检查、解析、求值之间仍有对应缺口；源码 hash 和通过 CI 不能单独关闭它。

## 选择一个可证明且实际会使用的边界

推荐先证明**安装后的 canonical bundle 字节**如何解码为现有 typed program／certificate，再将使用同一解码、`checkTyped`、`evalScore` 和 `evalRowPriority` 定义的固定 Lean 可执行文件，作为新模式的数值检查与求值入口。

安装 bundle 上限为 6,000 bytes，已接受的 program／certificate 字符串均为固定 ASCII 关键字；任意 Unicode ticket ID 不进入这一证书通道。专用 codec 只接受已声明的 canonical 字节语法：固定键顺序和标点、精确 schema／kind、完整 EOF、保留数组顺序；整数为 `0`、非零首位的正十进制或其负值。重复键、未知字段、空白、字符串转义、小数、指数、前导零、`+1`、`-0` 与尾随字节均拒绝。

这是比公共 raw Python API 更窄的新安装协议。旧 API 可以接受部分非 canonical JSON 再归一化；该归一化过程不会因此变成已证明代码。标准 Lean 4.19 `Json.parse` 会覆盖重复对象键、接受小数／指数且丢失数值词法类别，Unicode escape 处理也与 Python 不同，不能直接冒充现有 `strict_load`。专用 ASCII codec 避免将通用 JSON 语义差异藏在 typed 定理之前。

codec 的字节关系必须独立指定字面 token、符号、操作码与现有 constructor 的含义。encoder／decoder 相互 round-trip 还不够：两者可能共同把一个操作码或负号解释错。需要一般字节语义关系证明，再加固定独立字节 fixture 的回归。

## 保留实际语言与资源约定

- 支持原有 n-ary `add`、signed scalar `mul`、`min`、整数和 priority 条件分支、`blocked` 与整数 `ge`；Boolean `if` 拒绝。score 表达式的全部位置禁止引用 cached score；priority guard 按原 context 规则解码。
- 检查全部分支，包括不执行的分支。score／priority 共用最多 256 个源 AST nodes；根深度为 0，24 接受、25 拒绝。n-ary 的 representation list tails 不增加源节点／深度，scalar 参数不算独立 expression node。
- 源 literal／scalar 与 supplied affine witness 在 ±1,000,000 内，JSON Bool 不能充当整数；中间推导系数仍使用任意精度整数，不额外套 supplied-witness 上限。
- 最多 512 cells；severity 1..5、age 0..87600、实际 Bool、合法闭区间和固定 priority。保留原 occurrence／数组顺序，复用十组精确覆盖；不能只验证出现的组。singleton 检查值相等，不错误地要求 affine pair 相同。
- 安装 JSON depth 上限 28，与 AST depth 分开；bundle root 为 0，scalar leaf depth 也计入。facts 仍保留 raw 4,096-byte／冻结 hash、最多 64 rows 等现有要求。原 facts 到 numeric rows 的 Python 转换暂未证明。

完整当前操作／wrapper 对应关系见 [实际实现映射](2026-10-11-formalization-actual-mapping.md)。新的有限边界不能反向宣称公共 API、任意 Python 或任意任务已经正确。

## 两条可执行路线

| 路线 | 成功结果的数值来源 | 能支持的结论 | 仍需信任／证明的部分 |
|---|---|---|---|
| A：逐次结果验证 | Python 求值，Lean 对每个实际 row 计算并比较后才允许发布 | 本次成功验证的数值结果符合已接受 typed 程序与独立 specification | 比较／发布桥、raw row 转换、ID、排序、IO、编译与运行时；不等于通用 Python refinement |
| B：Lean 直接求值，推荐 | 固定 Lean 入口先解码与检查，再对同一 accepted AST 求值 | 新模式的数值检查／解释定义来自已证明模型，条件是所列编译与绑定假设成立 | raw row 转换、结果复制、ID、排序、IO、admission、编译与运行时 |

两条路线都不能复用候选提供的 `certified` 报告作为授权。新的入口必须每次实际计算 acceptance；serialized proof／候选 Lean source／workspace executable 都不进入受信任执行路径。

## 两个分别验收的阶段

**M2a：解码与可执行核心，尚未执行。** 新 kernel-checked obligations 包括一般 `parse_encode`／`encode_parse`／injectivity、独立字节语义关系、精确资源／context／原 cell 顺序、`checkBundle` 成功到同一 decoded AST 的 computed acceptance，以及经过验证的 numeric row batch 到每个原序 index 的 specification 结果。parser 必须由实际递归定义证明终止和有界读取，不能假定一个正确 parser oracle。CLI 成功分支必须经过 bundle 与 row batch 的检查，不提供接收未经验证 rows 的第二公共入口。

新源和新定理单独冻结并审计闭包；旧 14-file／83-closure 结果保持原证据，不能冒充新 codec 的证明。必须从同一已审阅定义构建实际 native CLI，并保留 build、link、binary／library 身份及真实正负例退出记录。审计 transitive owned `unsafe`、`@[implemented_by]`、`@[extern]` 与 compiler replacement：逻辑闭包没有新公理，也可能存在与 kernel 定义不同的可执行替代。未经审阅的自定义替代不允许；不可避免的 Lean／stdlib primitives 明列为运行时信任边界。

**M2b：部署入口，尚未执行。** 增加显式版本模式，在实际 admission 与 immutable request 中绑定 executable／codec／source／target；旧 immutable request 不改解释。固定 binary 和全部真实 loader／runtime dependencies 只读安装，runner 调用绝对路径。新模式的成功发布必须依赖这个实际入口，拒绝、缺失、hash 漂移、timeout 或不完整响应都不能退回 Python 成功路径。

请求／响应冻结完整 framing：长度的溢出与上限、负整数累积、success／error tags、单一完整响应及 EOF。绑定同一 bundle 和**完整有序 numeric rows／indices**，仅 row count 或 bundle hash 不足。实际 native audit 继续核对授权请求、runner／binary、input／output、Run／session 与 foreground 关联；额外业务 verifier 保留。该阶段即使通过，也不证明 Python row 转换、Unicode ID、插入排序、原子写入或 admission 本身。

编译器、C backend、Lean integer／string runtime、linker、libraries、OS 和主机完整性属于明确的 TCB。先实际检查 ELF／ABI 与现有固定 worker image 的兼容性，测量冷／热启动、最大合法 bundle、64 rows、深／宽／signed 边界的时间、内存和安装大小。没有实测前不宣称小体积、低延迟、静态链接或 180 秒可用性保证；不在每个 worker 安装整个证明工具链。

## 能反驳实现的验收例

独立真实字节正例至少包括两种不同 AST、signed cancellation、乱序完整证书和合法 singleton 替代 witness（例如 age=168 的 `(-2,604)`）。负例覆盖丢失负号或 n-ary 最后操作数、Bool 整数混用、错误 equality guard、score-in-score、无效 dead branch、遗漏十组之一、gap／overlap／duplicate、nonuniform guard、错误 singleton witness、所有字节／节点／深度／cell 边界及非 canonical JSON。

实际 executable 与 native gate 另测 wrong bundle、替换 binary／library、PATH spoof、wrong ordered rows／index／count、复用旧响应、尾随输出、timeout、实际 authority rejection 后没有结果发布。Unicode ID、同分排序、ID 保留是此阶段的 bridge 回归，不能称为已证明 wrapper。

如果一般定理预先假设 decoded semantics 正确、仅证明公式 fixture、成功路径可以跳过新入口、响应可绑定另一份 rows／bundle，或新 source／build／runtime 证据缺失，这一阶段验收失败。该有限路线推进模型定理的实际适用性；主观体验和因果长期收益仍需要各自经验研究。

设计来源摘要 SHA-256：`2100be04f11db474bf894858fb615e96e17bc389edc016cb6148e3c29b0ae719`；独立设计审查报告 SHA-256：`c4bd96686f557db13553a82a0d57d63e232ef51b7859a5354dcd0224c13abd66`。这些是设计与来源身份，不是新增证明或运行结果。
