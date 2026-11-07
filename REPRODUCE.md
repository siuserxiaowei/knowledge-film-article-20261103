# 下载与复现

本仓库的文章和 Skill 在默认分支 `main`。两套大工程及原有有声成片在 [v2026.11.07 发行页](https://github.com/siuserxiaowei/knowledge-film-article-20261103/releases/tag/v2026.11.07)。

## 文件清单

| 文件 | 用途 |
|---|---|
| `remotion-commons-reproduction-20261107.zip` | 《内卷的天平》本片专用 Remotion 源码、已有配音、字幕、字体及许可 |
| `claude-account-film-project-20261107.zip` | 《Claude 封号避坑》完整工程及原型、配音与审核记录 |
| `codex-knowledge-film-20261107.zip` | 独立可安装 Skill；内容也在本仓库 `skills/codex-knowledge-film` |
| `commons-balance-ming-128s.mp4` | 原有 128 秒有声成片 |
| `claude-account-film-57s.mp4` | 原有约 56.97 秒有声成片 |
| `SHA256SUMS.txt` | 下载完整性校验值 |

下载后核对 SHA256，例如 macOS/Linux 在下载目录运行 `shasum -a 256 -c SHA256SUMS.txt`。Windows 可用 PowerShell `Get-FileHash -Algorithm SHA256 文件名` 逐项比较。

## 直接打开原有作品

准备工程 `package.json` 所支持的 Node.js 版本、FFmpeg/FFprobe。首次 `npm ci` 和首次获取 Remotion 配套浏览器需要网络；下列操作使用包内音频，不调用 TTS、不申请 API Key。

《内卷的天平》解压后进入 `remotion-commons-reproduction`：

```bash
npm ci
npm run check
npm run studio
# 在 Studio 选择 CommonsBalanceNarrated
```

需要重新导出时运行 `npm run render:commons:voice`，结果为 `out/commons-balance-ming.mp4`。只修改画面可编辑 `src/commons/`。更改文稿或声音窗口后，按包内 `REPRODUCE.md` 重新准备和核对声音。

《Claude 封号避坑》解压后进入 `claude-account-film-20261103`，还需要 Python 3：

```bash
npm ci
npm run check
npm run studio
# 在 Studio 选择 KnowledgeFilm
```

需要重新导出时运行 `npm run render`，结果为 `out/film.mp4`。修改文稿或声音配置后，先运行 `python3 tools/prepare_film.py --mode import`，再检查和渲染。包内的原音频与已审核切片可以离线重建；换台词需要换对应音频。

## 制作一个新题目

按 [README 快速开始](README.md) 从本仓库内的脚手架新建独立项目。静音模式可先完成分镜与画面；制作有声片时，使用 [音频说明](skills/codex-knowledge-film/references/audio.md) 的 Ming 或导入模式。

这两条存档作品实际使用 Ming-3.0-tts-0.5B / 灵小锋，经 HF Space 生成。已有音频重建的 `networkRequests: 0` 仅表示本次离线复现没有联网，不表示原始配音从未调用云服务。官方 API 为可选适配器；用户凭据、实时额度和在线服务可用性没有通过离线测试验证。

## 2026-11-07 修复与验证范围

- 合并此前留在功能分支的文章、封面和配图，补齐默认首页。
- 新增完整 Skill 源码及发行包。全新目录生成排队示例，`npm ci`、静音准备和 `npm run check` 通过；7 项辅助测试与 62 项模板测试通过，零模型请求。
- 两套工程在独立解压目录安装并校验；Commons 另外完成 Remotion bundle 检查，Claude 使用已有音频离线重建并检查完整片与 30 秒原型。
- 发行 MP4 是原有成片的副本，本次没有重新渲染、重新生成声音或对在线 API 做稳定性测试。各工程保留原先的内容和编码审核记录；本次检查不能替代新改动后的完整试听和画面审核。
- Commons 分发移除了与该片无关的复利案例及 legacy 入口，保留本片画面、声音、来源与第三方许可。修改清单和各自验证记录见包内说明。

实际使用本文件、README 与各工程包内说明。
