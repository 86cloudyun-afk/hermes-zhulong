# 五方向研究的独立审查与修复

日期：2026-10-11。PR：[86cloudyun-afk/hermes-zhulong#6](https://github.com/86cloudyun-afk/hermes-zhulong/pull/6)。独立审查范围为 base `deffc94e0c30ef3b20481ff6aaf9af5687371ef5` 至原 head `1650c0365e7fde1535f5f5213f0d1822ebe1b489`。

新鲜审查者未参与五份研究的编写，并另行委派统计/科学核对。原 head 发现 0 Critical、1 Important、1 Minor；根节点验证并修复两项问题。修复验证由根节点完成，没有将其写成第二轮独立审查或 GitHub 自己批准自己的 review。

## I1：事务示例的 fence 检查原来不在写事务内

`execution_probe.py` 原 `with connection:` 并不会立即开启 SQLite 写事务。两个 SELECT 的 `in_transaction=False`，直到首个 UPDATE 才隐式 BEGIN。第二连接能在 fence=2 的读取后、效果发生前提交 fence=3，而旧 token=2 仍产生效果；这与正文的原子事务说明不符。

修复仅在所有 SELECT 前加入 `BEGIN IMMEDIATE`，由原 connection 上下文管理 commit/rollback；没有修改产品。

新增 [adapter_atomicity_probe.py](experiments/autonomy_frontiers/adapter_atomicity_probe.py) 提取当前示例的真实嵌套函数 AST，不执行示例的其他探针，不改变函数体。在 fence 读取后的确切 failpoint，用第二 SQLite 连接更新 token：

| 观察 | 修复前 | 修复后 |
|---|---:|---:|
| fence 读取处于写事务内 | false | true |
| 第二连接在效果前提交更高 token | true | false，因锁被阻塞 |
| 第一项效果数 | 1 | 1，在提高 token 前合法提交 |
| 第一项提交后提高 token，再派发旧 token | stale | stale |
| 检查器退出 | 1 | 0 |

结果分别保留为 [修复前](evidence/2026-10-11-autonomy-frontiers/adapter-atomicity-before-fix.json) 与 [修复后](evidence/2026-10-11-autonomy-frontiers/adapter-atomicity-after-fix.json)。SQL trace 与 source SHA 绑定这两个版本。这是一个受控双连接时序，不证明远程服务或任意并发协议正确。

## M1：候选状态变化没有进入发布探针的失败判据

原 publication 探针只把返回值/active 状态错误计入 violations，拒绝后状态改变仅减少 `blocked_without_mutation`。因此输出 counts 可以不满足 4095，却仍退出 0。原观测确实是 4095 次候选不变，原数字没有被推翻。

修复将拒绝后非 candidate 状态列入 violations，并要求精确 4096/1/4095 计数，六项负例也必须保持 candidate。独立临时研究脚本注入“把所有拒绝观察的状态报告为 retired”这一校验故障：原判据未检出（mutant exit=0），新判据检出（mutant exit=1）。这只变动研究校验的观察结果，不制造产品错误。

[修复前校验结果](evidence/2026-10-11-autonomy-frontiers/publication-validator-before-fix.json) 与 [修复后校验结果](evidence/2026-10-11-autonomy-frontiers/publication-validator-after-fix.json) 分别记录注入方式及检查器结果。随后完整重跑实际产品入口：4096 分区仍为 1 发布、4095 拒绝且候选保持，六个负例全部拒绝。

## 来源与证据核对

独立审查重跑原五个探针，全部退出 0；检查 53 条带 source SHA 的记录，对应 52 个缓存全文/元数据文件，字节数与 hash 均匹配。共用 UNICOG PDF 中的两篇作者论文未被冒称两次独立下载；未取得的原刊、元数据和作者方法教材仍分别标明。

审查核对了原验证索引的 22 个产品 Python、5 个研究脚本、6 个结果 hash，以及完整模拟 outcomes 的 canonical SHA。原重跑中三份结果字节一致，另三份只有 Git HEAD 字段变化，内容一致。235 测试日志 hash 和 exit=0 也与索引一致；审查者没有重复 Docker 全套测试。

根节点对两项修复重跑对应脚本并通过补充 RED→GREEN 检查。其余三项脚本未改变，原证据保留；产品 Python 未改变，原固定宿主/真实 Docker 235/235、0 skip 的结果是产品基线证据。更新的 [验证索引](evidence/2026-10-11-autonomy-frontiers/verification.json) 标记各次基线、修复后研究代码 hash 和观察范围。

当前没有遗留 Critical/Important/Minor 审查项。R0–R5 产品工作、真实模型 RCT、长时间 soak、形式证明和意识实验仍是研究路线中的后续工作，不属于本 PR 已实现能力。
