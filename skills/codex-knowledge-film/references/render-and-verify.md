# 环境与交付

需要Node（package.json engines）、Python3、FFmpeg/FFprobe。先检查 `node --version`、`python3 --version`、`ffmpeg -version`、`ffprobe -version`，按本机包管理器补缺项。模板使用stdlib+FFmpeg，无需Torch/Whisper即可做静音和逐句声音导入。

首次项目运行 `npm ci`；依赖与Headless Shell首次下载需要网络，与语音推理分开。不为短片无关升级整个环境。

## 预览与导出

先prepare，再 `npm run check`，再 `npm run studio`，选择KnowledgeFilm。检查字体、字幕、动作、转场、开头结尾，以及正反定位时声音位置。用户要成片时 `npm run render`，得到out/film.mp4。

整段声音的切片可以先prepare并直接开Studio预览；正式check/render要求[当前切句审核](alignment-and-provenance.md)有效。不要删除sourceContext或审核配置来规避检查。`verify_render.py` 也会重新运行项目的导出守卫，报告绑定当前文稿、画面代码、混音、审核文件与成片的哈希；这是核对对象快照，不是自动内容审核。

命令保留H.264/CRF18、配套Headless Shell与disable-shared-memory-capture，用于规避原型时本机SVG捕获异常，其他机器检查后可调整。Studio使用Html5Audio且useWebAudioApi=false，导出使用@remotion/media.Audio。取消请求/编码异常先查文件、Range、控制台与版本，不直接归为所有WAV不支持。

## 验证

```bash
python3 SKILL_DIR/scripts/verify_render.py --project PROJECT_DIR --video out/film.mp4
```

脚本对照时间轴检查尺寸、帧率、时长、音频格式，完整解码、测响度与抽帧，输出reviews/render-verification.json与联系表。真正无声时允许没有音频流，技术失败非零退出。

脚本不理解画面、不核对台词，报告会明确这些仍待检查。交付前助手实际查看联系表与必要原尺寸帧，检查开头、难镜头、跨幕、结尾；有人声时转录/试听实际MP4并对照口语稿。记录实际发现、修复与未验证项，不捏造已完整看过/听过。

## 排错

- Timeline is stale：改过文稿/参数，重新prepare，不手改hash。
- ready=false：失败或只做sample，修复具体错误再完整准备。
- unimplemented custom scene：实现并注册专用组件，不能导出待制作画面。
- Ming quota/401/403：保留缓存，停止新增请求；按音频参考处理配置/登录，不换模型冒充指定模型。
- 可解码但重复画块、字幕遮挡或声音不清：看编码抽帧和最终声音，不能仅凭退出码交片。

## 交付

给工程、预览/MP4、字幕和事实来源；写明真实后端/模型/音色或静音/导入来源未验证，区分技术检查与实际画面/台词核对。分享Skill排除密钥、依赖、缓存、旧机器路径、私有素材与原片，保留代码/字体许可。
