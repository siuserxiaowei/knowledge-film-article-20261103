# 安装与使用

解压得到 `codex-knowledge-film/`，其中应直接有 `SKILL.md`。

个人安装：整个文件夹放入本机Codex技能目录（本次为 `~/.codex/skills/`，或本机支持的 `~/.agents/skills/`）。项目安装：放入 `.agents/skills/codex-knowledge-film/`。已有同名目录先保留原版并比较，不直接覆盖。重新打开/刷新会话后查找“知识短片工坊”。

使用示例：

> 使用 $codex-knowledge-film，做一条解释“为什么排队越挤越慢”的中文知识短片，16:9，暖黑金风格，用Ming配音，先做30秒原型，再完成成片。

可以提供参考视频和文稿，明确需要静音、已有声音或Ming。只运行示例时先检查Node、Python3和FFmpeg/FFprobe，在Skill目录执行：

```bash
python3 scripts/new_film.py ~/Movies/my-knowledge-film --example queue
cd ~/Movies/my-knowledge-film
npm ci
python3 tools/prepare_film.py --mode silent
npm run check
npm run studio
```

attention是第二个示例。制作新题目时，让Codex按Skill重新设计分镜和场景；脚手架不会根据新标题自动生成论点。导出用 `npm run render`，配音见 `references/audio.md`。

包内不含密钥、账号、模型权重、真实声音样本或原片。公开Ming演示有额度/登录/排队约束，官方API需要可用凭据。未配置时可先静音原型，不能声称已完成真实配音。

版本见 `VERSION`。分发包内 `RELEASE.json` 列出每个文件的SHA256；重新打包可运行 `python3 scripts/package_skill.py --output /实际输出目录/codex-knowledge-film.zip`。打包器排除依赖、缓存、审核素材和环境密钥，并拒绝符号链接。长音频切片必须使用本版新增的[审核与来源约定](references/alignment-and-provenance.md)；不会把旧候选报告自动升级为已审。
