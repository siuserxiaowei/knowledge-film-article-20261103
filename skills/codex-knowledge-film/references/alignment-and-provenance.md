# 切句审核与来源守卫（1.1.0）

适用于从整段旁白切句、合并语义段、核对导入来源。全部工具离线运行，不调用ASR或声音模型；使用已有ASR、词时间戳及实际试听确定候选边界。文件名、配置中的模型名、文本相似度都不能独立证明内容或模型来源。

## 从源区间生成切片

在项目中保存原始长音频，例如 `assets/audio/source.wav`。所有路径相对项目，不能越出目录。

```bash
python3 tools/alignment_review.py cut --source assets/audio/source.wav --start 0.10 --end 2.32 --output assets/audio/lines/line-01.wav
```

命令返回 `audioFile`、`sourceContext`、音频哈希；将前两项放入对应 `film.json` 的行。`sourceContext` 包含 `sourceFile/sourceSha256/startSeconds/endSeconds`。每句需要真实范围，不照抄示例时间。

工具先把完整原源解码为48kHz、单声道PCM16，再按绝对样本索引切WAV。守卫用相同方法重建区间，与实际导入声音逐样本比较，并核对原源哈希、范围和路径。不能在带来源证明的切片上先做变速、去噪、淡入淡出或有损压缩；这些处理由准备器对已验证切片另行完成。其他切法可能因重采样差异不通过，此时保留原文件并重新输出新切片，不放宽阈值或改哈希。它证明PCM与所声明区间一致，不证明模型身份或台词语义。

## 建立唯一的最终行映射

逐句ASR输入JSON是数组，必须覆盖最终所有导入行，id唯一：

```json
[
  {"id":"line-01","rawAsr":"实际识别出来的原文。"},
  {"id":"line-02","rawAsr":"另一句原文。","normalizations":[
    {"kind":"homophone","from":"深诉","to":"申诉","reason":"记录实际试听结果或独立ASR证据路径与结论"}
  ]}
]
```

示例仅说明结构，不是可用于其他声音的识别证据。保留原ASR文件，不用文稿冒充ASR。归一化只忽略标点、大小写和Unicode形式；同音替换保留原文、等长且局部，并要求理由。删词、增词、整句替换及大面积改写会被拒绝；需要重新识别或试听补证。

```bash
python3 tools/alignment_review.py candidate --asr reviews/asr-lines.json --output reviews/alignment-candidate.json
```

候选始终是 `status:pending`、`review:null`。检查结果逐句列出首尾覆盖、缺字/多字方向与相邻串句/重复；相似度仅用于诊断，任何未解释的字词差异都会阻止通过。审核绑定最终行序、id、文本、音频路径与哈希、完整sourceContext。旧16行候选不能充当合并后15行的最终审核。

实际逐句核对后，保留候选原件，将审核副本存为 `reviews/alignment-reviewed.json`，设置 `status:"reviewed"` 与以下记录，其他绑定及原ASR不手改：

```json
{"reviewer":"实际审核者","method":"实际核对方式与证据位置","reviewedAt":"带时区的ISO8601时间"}
```

这是人工/助手审核记录，不是数字签名；工具会重算内容差异和当前绑定，不能只把失败结果字段改绿。审核元数据不能代替实际听审。设置 `audio.alignmentReport` 为审核副本路径后运行：

```bash
python3 tools/alignment_review.py validate
python3 tools/prepare_film.py --mode import
npm run check
```

需要先预览时可prepare后直接运行 `npm run studio`，技术ready不表示已审。含sourceContext的声音，正式check/render必须有有效审核；审核文件、声音或范围改动后需要重新prepare，文本或映射改动还需重新审核。普通无长源的逐句导入可不配置该审核，报告仍明确内容未核对。

## 语义连读就合并

若句尾跑进下一句，先标为失败；调整停顿边界或合并连续源区间，不把多出来的词从ASR中删去。

```bash
python3 tools/alignment_review.py merge --line-ids line-09 line-15 --new-id appeal --text '合并后的实际完整口语稿。' --output assets/audio/lines/appeal.wav
```

id列表必须在当前文稿中连续同序，源文件和哈希相同，源区间在样本上首尾相接。命令只生成新WAV和替换提案，不改文稿、不复用旧审核。将原行替换为提案的新行，字幕可在画面组件中按阅读需要换行；对合并后的实际声音重新识别/核对，重建唯一最终映射和审核。无法从声音确定边界时保留较长语义段。

## 可核对的外部生成回执

普通导入始终标记 `modelVerified:false`。有外部生成记录时，可设置 `audio.provenanceFile` 指向JSON回执：

```json
{
  "version":1,
  "provider":"实际记录的提供方",
  "backend":"例如hf-space-ui",
  "model":"实际生成记录中的模型",
  "voice":"实际音色",
  "parameters":{"seed":1895,"cfg":2,"sigma":0.25},
  "evidence":{"kind":"browser-generation","reference":"不含凭据的记录或证据路径","observedAt":"实际观察时间","observer":"实际记录者"},
  "lines":[{"id":"line-01","text":"当前完整口语稿。","audioFile":"assets/audio/lines/line-01.wav","audioSha256":"当前文件SHA256","sourceContext":{"sourceFile":"assets/audio/source.wav","sourceSha256":"原源SHA256","startSeconds":0.1,"endSeconds":2.32}}]
}
```

`lines` 必须与所有最终导入行同序且字段完全匹配（无sourceContext的行不写该字段）。只记录真正生效的参数；保留本地原始回执可供复核，不能将凭据写入此文件。该回执只提升为“记录了外部来源证据”，不冒充适配器亲自生成或独立鉴定模型。没有回执仍可明确以未验证来源导入。

准备器的缓存身份包含当前文本、切片/原源哈希与区间、回执/审核内容哈希及实际记录的后端/模型/音色/参数。构建报告分别记录技术状态、来源和切句审核，画面与编码仍待核对。导出守卫重读当前输入，拒绝缺失、篡改、旧映射和文件变化。`verify_render.py` 还会保存文稿、画面代码、混音、审核文件与成片的哈希快照；最终画面/口播是否正确仍须实际检查。
