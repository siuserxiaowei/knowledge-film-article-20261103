# 声音与缓存

## 入口

- silent：字幕/时间轴与可选本地数值配乐，无旁白，narrated=false。
- ming：真实Ming生成，默认Ming-3.0-tts-0.5B/灵小锋。先短样音，再完整生成。
- import：逐句line.audioFile，相对项目路径。测实长并记录哈希；没有可核对生成记录时标导入声音、模型来源未验证，内容须与line.text核对。

`mode=silent`表示不生成人声，不等于没有底乐；audio.music默认true。用户明确要求无声时，将film.json的audio设为 `{"mode":"silent","music":false}`（可保留其余音色/后端字段），最终应没有音频流。ming/import下music=false表示仅保留导入或生成的人声。

新片用实际声音确定镜头长度：场景前停留、各句声音、句尾停留、场景间隔。静音时用silentSeconds；估计时长必须写明。固定片长先比较真实时长，再改文稿/镜头，不强行压缩人声。

项目目录中的命令：

```bash
python3 tools/prepare_film.py --dry-run
python3 tools/prepare_film.py --mode silent
python3 tools/prepare_film.py --mode ming --backend official --sample
python3 tools/prepare_film.py --mode ming --backend official
```

公开演示把backend换成hf-space；导入先设置各句audioFile，再 `python3 tools/prepare_film.py --mode import`。显式mode/backend会修改film.json，干跑不修改；sample只准备最多前三句与独立报告，不发布整片ready。

## 官方百灵

协议：<https://developer.ant-ling.com/zh-CN/docs/api-reference/audio/tts/>

`POST https://api.ant-ling.com/v1/audio/speech`，Bearer Auth。只从环境MING_API_KEY或当前项目.env读取密钥，不source/eval。基础字段model/input/voice/response_format/sample_rate；WAV与SSE有适配，当前参数以官方文档为准。蚂蚁百灵与阿里云百炼不同，不混用令牌/音色ID/地址；协议兼容OpenAI不等于服务由OpenAI提供。离线契约测试不能证明用户权限、额度与在线状态。

## 公开HF演示

Space：<https://huggingface.co/spaces/hugging-apps/ming-3-tts-05b>

模型：<https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5B>

协议核对日期2026-11-02；实际使用前核对当前Use via API/schema：

- POST /gradio_api/call/v2/builtin_voice，text/voice/seed/cfg/sigma。
- GET /gradio_api/call/builtin_voice/{event_id}，complete返回音频。
- 已核对单次上限400字符、原生44.1kHz；示例seed1895/cfg2/sigma0.25。
- 不支持instructions/speed，不能声称应用；报告保留忽略项。

匿名和登录都有额度/排队约束，以当前账号与[官方ZeroGPU文档](https://huggingface.co/docs/hub/spaces-zerogpu)为准。quota、权限、服务错误停止，不盲重试、切身份或绕过限制。已有授权登录可正常浏览器操作，不提取Cookie当API令牌。

缺密钥时先查当前任务允许的配置与登录，必要时用公开演示；不保证免登录/无限免费/自动开户。不要默认让不便操作的用户自行填整套配置，只有必要登录验证才请用户做具体一步。没有真实生成成功不能报告已配音。

## 长音频

接口限制内可以批次合成；不能按字数均匀切。需词时间戳、按文稿顺序匹配、边界检查，再逐句识别/试听确认首尾。记录整段来源、哈希、范围、参数；缓存身份包含批次上下文。

使用已有Whisper/remio或其他已授权ASR，不默认下载大模型。保留同音字差异和原ASR，根据实际声音/另一识别明确审核，不能改原ASR文本后称零错误。

本版本提供通用切片、合并与审核守卫，见[切句审核与来源守卫](alignment-and-provenance.md)。ASR/词时间戳由已有工具产生；本工具不推理ASR，也不假装能仅凭波形自动理解语义。指定源区间后统一完整重采样再按样本切，审核最终行映射；不能复制旧作品的固定句数、时间窗或报告。

模板自动准备器只支持内置音色，不静默接收真人声音克隆配置。用户明确要克隆时，需要在授权范围内另接references路径，voice与references二选一，先验证音色与内容；原始参考声音不进入公开静态目录或分享包。

## 处理与状态

缓存原音频后重采样48kHz，裁多余首尾静音，保留句内停顿，短边缘淡入淡出；人声出现时压低配乐，归一响度/限制峰值。有人声时目标约−16 LUFS，纯底乐约−24 LUFS，以实测为准。

缓存覆盖后端、模型、音色/参考声音内容、文本、实际参数，密钥除外。静音/导入/真实Ming分别记录。失败不publish ready。文件可读、元数据或mock通过不等于台词内容已核对。

`sourceContext` 的声音在准备时核对原源和PCM；审核未完成时可保留技术预览，`npm run check` / `npm run render` 会拒绝正式输出。普通无长源的逐句导入仍可使用；未提供可核对来源时明确记录未验证，不冒充Ming。显式声明的 `audio.provenanceFile` 和 `audio.alignmentReport` 都是必需输入，文件缺失或改变后不能沿用旧构建。
