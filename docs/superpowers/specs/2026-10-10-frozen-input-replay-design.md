# v0.8 冻结结构化输入与原目标字段回归

## 目的与授权

用户要求持续研究、实现、测试、独立审查并合并，推动 Hermes 自主发现、执行、验收和学习。本轮补上 v0.7 未冻结业务输入的缺口，沿用既有交付授权，不重复阶段批准。升级跨越观察、账本、请求及程序认证接口，采用书面规格/计划和 inline 执行，最后独立整分支审查。

默认不捕获。可信 source 新配置 `persist_input_fields` 显式授权指定顶层 JSON 字段持久化，仅接受 1–32 个唯一标识符字段（每个最多 64 字符），且必须为已有 `input_fields` 的子集。不能扫描保险库、聊天或工具正文，不保存源文件全文。数据只放私有 profile 账本；使用者不得授权凭据字段。`input_snapshot_bytes` 默认 8388608、0 停止新捕获，限制 payload 字节，不冒充整个 SQLite/work/profile 的磁盘硬额度。

## 选择与范围

方案 A 只记 hash，不能恢复数据；方案 B 失败后重新读取，可能混入新版本；采用方案 C，在形成目标的同一次严格 JSON 观察中取得授权投影，并与目标在同一 SQLite 写事务冻结。代价是新增受限业务字段存储，需要显式配置和有界配额。

回归限定冻结 `json_equals` 契约的字段条件，不重现文件路径、require_change、副作用、环境或推理。`replay_origin: true` 仅可用于配置了输入捕获的 source/json_equals 技能。旧模式继续完整 JSON 输出比对，旧目标不补读、不伪造快照。普通绑定不证明实际使用，有限测试不证明意识、通用正确性或因果提升。

## 输入与观察

新增 `task_inputs.py`。规则 schema=1，由 source id 与排序后的字段定义 hash。源读取一次，使用现有 strict_json 拒绝重复键、非有限数及深度超过 32 的 JSON；投影规范 JSON 最多 4096 UTF-8 字节。观察 revision 同时覆盖原有事实/使命/契约、投影规则和输入 hash。字段缺失或非法值使该观察不可用。

私有观察 `task_input` 为 schema/source_id/source_revision/rule_hash/input_hash/size/data。规划提示采用字段 allowlist，不能展开新增快照；既有 facts 仍按 2000 字符上限提供授权的临时事实。学习合成只看原有 description/examples 与最小失败凭据，不能看到冻结原输入或新增回归期待条件。

## 不可变账本与请求

为旧账本 additive 创建 task_inputs：goal_id 外键且唯一、schema/source_id/source_revision/rule_hash/input_hash/payload/size；更新和删除均拒绝。旧 goals/submissions 触发器保持；不改写历史请求。

控制器初始化把当前输入规则和额度存入 settings。create_goal 同一 BEGIN IMMEDIATE 事务插入目标/快照并检查总 payload 字节；失败完全回滚，重复目标不重复计费且不能补写旧输入。创建前有只读额度预检，关闭捕获不能新增规划模型调用；最终额度判断仍以事务为准。

内部 goal 携带 task_input。Controller 请求冻结同一 binding；prepare_submission 在预算和尝试之前事务重查规则、范围、规范数据/hash/size及请求的精确输入绑定。无快照、移除/改变规则或伪造绑定阻止新执行；已有未静止请求继续用原内容对账，不因新配置、暂停或零额度失去恢复。总请求仍最多 16384 UTF-8 字节。

公开工具、本地 goals 命令及 self-model 不导出 payload/request；输入元数据仅含是否可用、schema、hash、规则 hash 和大小。状态提供有限额度统计。

## 原目标回归与发布

新增 skill_replay.py 从真实已静止机械失败 submission、对应 goal 输入及冻结 json_equals 构建可信评测任务。缺快照/绑定损坏/规则不符明确 replay_unavailable，不调用生成模型；可信基础案例与原字段条件矛盾则 spec_conflict，同样阻止生成。

原输入独立于清单时最多追加 1 case（8+1=9）；输入与基础案例相同时复用该 case，并同时保持基础完整输出比对和字段验收。字段取值采用点路径 dict 遍历及 canonical 精确比对，不用 Python ==，因此 true/1 与 6/6.0 不混淆。候选 stdout 仍严格 JSON，答案只留控制面。

认证报告绑定 origin submission、规范输入 hash、规则/契约 hash、回归计划 digest、对应 case index 和结果。SkillStore.finish 同一发布事务重新构建可信原目标回归、检查当前 skill_manifests 和输入规则，再核对报告、全部 case 与清理凭据；单独的 replay_passed=true 或另一个 origin 的报告不能晋升。暂停及未知评测保留付费代码，预算沿用 v0.7。

## 原生证据与安装

扩展有限 smoke 为 --paid --skills --replay（--replay 依赖前两者）。输入与程序分别复制到 work；固定前台 runner 各读取一次 bytes、核对 SHA，用同一份已核验 bytes 执行程序与提供 stdin。结果返回程序 SHA、输入 SHA 与完整输出，审计严格 JSON/canonical、原生 request/session/call ID 对应结果，以及发布代码与冻结输入。演示仍标注合成无输出失败来源，有限真实 DeepSeek/native 执行，不启动永久付费服务。

新增两模块纳入插件安装及 protected hashes，升级 0.8.0。云 setup 保留官方 PM、固定 host、代理/CA及凭据绑定，验证后保存精确合并 main 与完整脚本。

## 验收

先观察缺功能/有意错误行为 RED，再 GREEN：授权投影与严格 JSON、源版本/规则变化、跨连接额度竞争和事务回滚、旧目标不可补读、篡改绑定不花预算、同键恢复不改输入、公开状态不泄漏、基础例过而原目标错拒绝、同输入去重与条件冲突、报告/origin/规则 drift 拒绝发布、未知清理和暂停保留代码、实际 Docker 和原生程序/输入 SHA 证据。现有全 suite 与 Python 3.11/3.12/3.14 CI 必须通过，独立审查后合并。
