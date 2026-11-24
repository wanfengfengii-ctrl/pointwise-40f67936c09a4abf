# 北湾薄板测绘交班 V1

北湾薄板试验厂的测绘员依据采录表提交原面、局部测量量和邻接。白班复核员处理勘误、分别核验同幅独立片并分幅出件。夜班按实际签收的来件核账。交班主管凭逐组状态、净量与实收出处决定是否入账，并可按原报告号复领。

## 运行

需要 Python 3.11，使用标准库及 SQLite。命令在项目根目录执行。

```text
python3 -B check_project.py
python3 -B demo.py
```

`check_project.py` 是控制台物化时提供的完整回归入口。`demo.py` 读取 `samples/measurements.json` 和 `samples/handoff.json`，在独立新库发行来件。关闭并移除演示源库后，演示凭实收件核账，再重开离线库按号领取。样例中 A、B 是西幅的独立原面，分别为 +5、+7。东幅 C 为 +11，有正向标记。A 与 C 同向，B 与 C 反向，手算净量为 5 − 7 + 11 = 9。

## 工作顺序与接口

各写入口负责自己的提交，使用调用者提供且当前没有未提交事务的 `sqlite3.Connection`。使用两个数据库文件，分别为一个权威测绘源站和该站的离线台。建议每条新连接开启 `PRAGMA foreign_keys = ON`。各存储的 `initialize()` 可重复执行，现有记录以及后来录入的业务记录继续保留。

| 步骤 | 输入与入口 | 状态与用途 |
| --- | --- | --- |
| 1. 接纳 | `survey.batches.import_batch(revisions, ImportBatch(faces, relations))` | 保存完整快照并返回修订号，供白班复核。`Face(face_id, quantity)` 保存原面身份与局部量。`Adjacency(left, right, sign)` 保存相对方向。 |
| 2. 勘误 | `survey.batches.apply_correction(revisions, base_revision_id, measurements=..., remove_faces=..., relations=...)` | 更新指定原面或提交新原面，可明确移除原面，生成新修订。`relations` 省略时沿用基准关系，提供时整体替换。旧修订保留。 |
| 3. 冻结 | `FreezeStore.freeze_revision(revision_id)` | 返回稳定冻结号，同一修订重复冻结使用原号。`load_freeze` 读出该号的原始快照。 |
| 4. 现场核验 | `InspectionStore.inspect(freeze_id, sheet, face_ids, seams=..., anchors=...)` | 固定逐片检查结论与证据号。`SeamEnd(freeze_id, seam, end, face, sign)` 和 `Anchor(freeze_id, name, face, sign)` 绑定实际原面。`load` 领取已固定证据。 |
| 5. 发行与补发 | `delivery.issue.issue(inspections, archive, freeze_id, IssuePlan(sheet, face_ids, evidence_id))` | 同一站连接上的核验和归档共同确定发行字节。所选范围须为同幅已核验范围的非空子集。`delivery.reissue.reissue(archive, issue_id)` 返回原封存字节。 |
| 6. 实收 | `ReceiptStore.receive(raw)` | 结构和摘要有效的首次来件获得实收号。通过校验后，原样重投使用原号。同发行号异字节拒收。 |
| 7. 选案 | `CaseStore.select(receipt_ids)` | 固定非空同冻结来件集合。输入顺序与重复列出同一实收号无关。`load` 返回固定集合，后来到件独立记录。 |
| 8. 签存 | `audit.settlement.settle(cases, reports, case_id)` | 在同一离线连接按案处理，返回已提交报告与首执。报告列出逐组原面、状态、净量和逐面来件。 |
| 9. 复领 | `audit.history.read_report(reports, report_id)` | 领取原报告及首执，供主管查账。源端勘误和重开离线台均保留历史结果。 |

源站依次初始化 `RevisionStore`、`FreezeStore`、`InspectionStore`、`IssueArchive`。离线台依次初始化 `ReceiptStore`、`CaseStore`、`ReportStore`。输入不合法时抛出 `ValueError`，合法格式但号码不存在时抛出 `LookupError`。未知报告号使用 `ReportNotFound`。SQLite 写入或提交失败传播 SQLite 异常。报告正文与首执同次提交，有任何失败时都无新报告或成功首执。`demo.py` 提供实际调用示例。

## V1 来件

包是 UTF-8 JSON 字节，外层字段为 `version`、`issue_id`、`freeze_id`、`payload`、`integrity`。两个号码是同一权威源站内的正整数。`integrity` 是其余外层字段按键排序、紧凑分隔、ASCII 转义序列化后的 SHA-256 十六进制摘要。它用于检测内容损坏。`inbox.wire.encode_packet` 和 `decode_packet` 封装和解读外层，`inbox.validation.validate_packet` 校验业务结构。

载荷含 `sheet`、`faces`、`relations`、`seams`、`anchors`。`faces` 行含 `face_id`、`quantity`，`relations` 行含 `left`、`right`、`sign`，`seams` 行含 `seam`、`end`、`face`、`sign`，`anchors` 行含 `name`、`face`、`sign`。缝端和标记沿用信封的冻结出处。发行保全所选原面、范围内邻接和归属于所选原面的缝端及标记。坐标和源网格留站。名字符合非空白字符串规则，原面以标识区分，量为整数，方向系数为 +1 或 −1。相同局部量的原面分别保留。量为空、悬空引用、重复原面、单包内重复缝端或同名标记均拒收。结构合法的矛盾约束保留，用于裁定冲突。

## 核账口径

- 同案同一冻结原面的相同测量只计一次，保留该原面的全部案内实收出处。重复且一致的方向事实合并。同一原面有不同局部量、同一缝端身份有不同归属或口径、同名标记描述不一致，都使选定覆盖无效。
- 缝端按冻结号、缝名与互补端位 `a`、`b` 配对。两个实到端的 `sign` 之积是两原面之间的方向约束。某缝只有一个实到端时，它不产生连接。幅内关系与已配对关系共同建立连通组。
- 对关系 A 到 B，B 的方向系数等于 A 的方向系数乘关系系数。绝对标记直接约束自己的原面方向。组内相对关系或标记矛盾时状态为 `conflict`，净量为空。关系一致且无绝对标记时状态为 `pending`，净量为空，即使局部量恰好相抵。
- 一致且有绝对方向的组为 `oriented`，每原面以其方向乘局部量后求和。单位为采录工单统一的整数单位，无舍入，已定向的零为整数 0。组按最小原面排序，原面清单和实收号均稳定排序。等价切幅或局部参照变换保持同一原面集合的状态与净量，实收出处随实际选件变化。

`tests/test_survey.py` 核验接纳、勘误、冻结和现场逐片状态。`tests/test_delivery.py` 核验证据归属、原号补发、重投、坏件、选案和初始化保留。`tests/test_audit.py` 经真实案、报告和复领入口核验符号对照、冲突与零净量、等价切幅、重叠、孤端、超出 SQLite 整数范围的量、事务失败和历史领取。
