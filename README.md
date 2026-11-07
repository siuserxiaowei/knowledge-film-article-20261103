# 知识短片工坊：文章、Skill 与两套 Remotion 工程

用 Coding Agent 写分镜和 React/SVG 动画，用 Remotion 编排与导出，用真实旁白确定声音和字幕时间轴。

**先读 [完整文章](article-codex-draft.md)，或直接下载 [工程与有声样片](https://github.com/siuserxiaowei/knowledge-film-article-20261103/releases/tag/v2026.11.07)。**

![两条知识短片的制作案例](images/xiaowei-vibe-cover-16x9.jpg)

## 这里有什么

| 内容 | 入口 | 说明 |
|---|---|---|
| 制作文章 | [阅读全文](article-codex-draft.md) | 工具、来源、声音对齐和制作过程 |
| 可安装 Skill | [skills/codex-knowledge-film](skills/codex-knowledge-film/SKILL.md) | 自带脚本、模板、字体许可与安装说明，不依赖作者电脑 |
| 《内卷的天平》工程 | [Release 下载](https://github.com/siuserxiaowei/knowledge-film-article-20261103/releases/tag/v2026.11.07) | 128 秒，1920×1080，30fps；包含配音、字幕及来源说明 |
| 《Claude 封号避坑》工程 | [Release 下载](https://github.com/siuserxiaowei/knowledge-film-article-20261103/releases/tag/v2026.11.07) | 视频流约 56.97 秒；另有 30 秒原型 |
| 核对与复现说明 | [REPRODUCE.md](REPRODUCE.md) | 各工程命令、真实配音后端与本次验证范围 |

工程与 MP4 放在 GitHub Releases，避免把大媒体塞入 Git 历史。每份下载的大小与 SHA256 见发行页及 `SHA256SUMS.txt`。

## 从这个仓库开始制作

需要 Git、Node.js（建议满足模板 `package.json` 的 engines）、Python 3，以及可在命令行调用的 FFmpeg/FFprobe。

```bash
git clone https://github.com/siuserxiaowei/knowledge-film-article-20261103.git
cd knowledge-film-article-20261103

# 在仓库旁边创建一个新项目；遇到非空目录会停止，不会覆盖。
python3 skills/codex-knowledge-film/scripts/new_film.py ../my-knowledge-film --example queue
cd ../my-knowledge-film
npm ci
python3 tools/prepare_film.py --mode silent
npm run check
npm run studio
```

这会创建带字幕和底乐的排队示例，**还没有人声**。要制作新选题，让 Agent 按 Skill 重新写事实、分镜和专用场景；脚手架不会仅靠替换标题生成新内容。

安装到 Agent 的方式见 [INSTALL.md](skills/codex-knowledge-film/INSTALL.md)。支持 Agent Skills 的工具可加载该目录；不同 Agent 的安装位置和调用方式以各自文档为准，尚未逐一验证所有 Agent。

给 Agent 的示例指令：

> 阅读本仓库的 skills/codex-knowledge-film/SKILL.md。为我制作一条解释“为什么任务排得越满，做完的反而越少”的中文知识短片。先给出事实和分镜，完成约 30 秒原型；配音先让我听样音，再按实测时长完善画面并导出。保留声音与参考资料来源。

## 配音如何选择

- **复现这两条片子**：工程包内带已有的 Ming 配音，不需要重新申请密钥，也不需要重新调用 TTS。
- **为新片生成 Ming 配音**：Skill 有官方 API 和 HF Space 两个独立后端；官方接口需要用户自己的有效凭据，Space 受当前额度、登录和排队约束。先做短样音。
- **使用自己的录音或其他 TTS**：先取得逐句音频，配置 `audioFile` 后使用导入模式。豆包等其他服务可生成后导入；本 Skill 尚未提供豆包原生 API 适配器。

两条已存档作品实际使用的是 [Ming-3.0-tts-0.5B](https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5B)、“灵小锋”音色，经 [HF Space](https://huggingface.co/spaces/hugging-apps/ming-3-tts-05b) 生成。官方 API 是可选适配路径，未进行本仓库修复期间的在线付费调用或稳定性测试；不能把文档支持某字段等同于本片实际使用了它。

具体命令与密钥环境变量见 [音频说明](skills/codex-knowledge-film/references/audio.md)。密钥不得放入 Git、公开静态目录或发行包。

## 来源与许可

讲解方法参考 [HeyChengC/vibe-knowledge-film](https://github.com/HeyChengC/vibe-knowledge-film)，早期工程迁移参考 [hyai-dev/motion-studio](https://github.com/hyai-dev/motion-studio)。第一条片子的内容参考 [Fia乔乔《内卷的天平》](https://www.bilibili.com/video/BV1F6ps6aEgv/)；未分发该参考片的原画面或音轨。

新增 Skill 代码的许可和来源见 [LICENSE](skills/codex-knowledge-film/LICENSE) 与 [SOURCES.md](skills/codex-knowledge-film/SOURCES.md)。工程包分别保留来源和第三方许可；Remotion、字体、模型及其他依赖遵守各自条款。这些许可不授予参考视频本身的使用权。

实际安装、下载与执行以本 README、REPRODUCE.md 和发行包内的说明为准。
