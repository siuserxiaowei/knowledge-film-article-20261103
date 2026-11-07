# 项目数据约定 v1

`content/film.json` 是文字、视觉参数与声音请求的真源。`src/generated/timeline.json` 只由准备器生成，React 不发模型请求。

```json
{
  "version": 1,
  "id": "queue-example",
  "title": "排队为什么越挤越慢",
  "fps": 30,
  "width": 1920,
  "height": 1080,
  "theme": {"background":"#090705","foreground":"#EEE8D8","accent":"#C9AD68","danger":"#C56052"},
  "audio": {"mode":"silent","backend":"hf-space","model":"Ming-3.0-tts-0.5B","voice":"灵小锋","seed":1895,"cfg":2,"sigma":0.25},
  "pacing": {"leadSeconds":0.3,"tailSeconds":0.45,"sceneGapSeconds":0.3},
  "scenes": [
    {"id":"hook","kind":"queue","title":"一个出口，挤着也不会变宽", "visual":{"labels":["等候的人","出口"],"values":[8,1]},
      "lines":[{"id":"line-01","text":"每个人都想快一点出去。","silentSeconds":3.5}]},
    {"id":"close","kind":"title","title":"让通道保持畅通","lines":[],"durationSeconds":3}
  ]
}
```

## 输入

- `id`、scene.id、line.id 均为唯一的小写字母/数字/连字符；line.id 在整片唯一。
- `kind` 示例支持 `title`、`queue`、`budget`、`comparison`、`process`、`custom`。新题目按分镜新增专用 React/SVG 场景；示例不等于所有内容都套通用图表。
- 每场有 0 到多句 `lines`，字幕文本就是 line.text。静音版每句用显式 `silentSeconds`；没有时可估计，但报告必须注明是估计。
- 没有 lines 的片名/结尾用 `durationSeconds`。一个场景可以贯穿多句，禁止强制一句换一张幻灯片。
- `audio.mode`: `silent`（真实静音/可有本地配乐，不宣称配音）、`ming`（官方或公开HF后端生成）、`import`（逐句读取 line.audioFile，相对项目路径）。
- `audio.music`默认true；mode=silent只表示无旁白，严格无声需同时music=false。ming/import下music=false则只保留人声。
- `audio.backend`: `official` 读取项目 .env/环境中的 MING_API_KEY，`hf-space` 不读密钥，遇额度/服务错误停止，不自动重试。Space 不支持 instructions/speed；报告必须记录忽略项。
- 导入音频不能仅凭 audio.model 配置认定由 Ming 生成。没有可核对来源时写 `imported-unverified-provider`，保留文件哈希。
- 长源切片用 `line.sourceContext={sourceFile,sourceSha256,startSeconds,endSeconds}`；原源与逐句声音均须在项目内。设置 `audio.alignmentReport` 指向最终行映射的审核JSON。显式 `audio.provenanceFile` 指向外部生成记录回执。二者的格式和失效规则见[切句与来源](alignment-and-provenance.md)。
- 新片默认音频决定镜头长度；准备器不挤压实际人声，不默认变速。用户明确指定成片时长时另按真实时长调整文稿/镜头。

## 生成时间轴

顶层必须有 `version`, `ready:true`, `specHash`, `title`, `fps`, `width`, `height`, `durationSeconds`, `durationInFrames`, `audioSrc`（相对 public，null表示无音轨）, `narrated`（真实有人声）, `provenance`, `theme`, `scenes`, `captions`。

每个 scene：`id`, `kind`, `title`, `visual`, `startSeconds`, `endSeconds`, `startFrame`, `durationInFrames`。

每个 caption：`id`, `sceneId`, `text`, `startSeconds`, `endSeconds`, `startFrame`, `endFrame`。

所有秒数从绝对时间一次转换为帧：JavaScript `Math.round(seconds * fps)`，Python 对非负时间使用 `floor(seconds * fps + 0.5)`，scene.durationInFrames 为 endFrame-startFrame，总帧数只取整一次，不逐段向上累加。字体加载完成后渲染。全片新项目 Composition ID 固定 `KnowledgeFilm`，用内容里的 title 作为片名，避免动态 Composition ID 破坏命令。

准备器成功后写 `content/build-report.json` 与 `public/captions.srt`；specHash 使用 JSON 递归键排序、整值float转int、UTF8紧凑JSON SHA256，与Node保持一致。生成失败清除ready，不能继续读取上次成功时间轴冒充当前文稿。

`ready` 与构建 `complete` 只表示技术准备完成。来源核对和切句审核在构建报告中独立记录，导出时重新验证当前文件与审核绑定；视觉和最终口播仍需实际检查，不因声音审核通过自动改为已审。
