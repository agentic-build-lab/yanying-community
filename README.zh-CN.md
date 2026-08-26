# 言影（YanYing）数字人口播工作台

言影是一套本地优先的数字人口播视频工作台。它把文案、声音、人物素材、字幕、封面和审核流程集中在一个浏览器界面中，并由多个独立服务完成任务编排。

[English](README.md) · [架构说明](docs/architecture.md) · [引擎接入](docs/engine-adapters.md)

## 开源了什么

- 可直接打开使用的工作台前端，而不是展示用空页面；
- 负责项目、素材、任务、审核状态和接口编排的 API 网关；
- 语音合成、人物驱动、视频渲染和文案处理工作节点；
- Edge TTS、Wav2Lip、MuseTalk、FFmpeg 及 OpenAI 兼容接口的接入层；
- 不下载模型也能验证整条调用链的 dry-run 模式；
- 启动、停止、验证脚本以及可重复执行的配置与质量检查。

公开仓库体积小，是因为代码、网页和文档本身通常只有几 MB，生产环境中占空间的主要是模型权重、第三方运行时和音视频素材。这些大文件既有各自的授权要求，也不适合提交到 Git，所以没有包含在公开仓库中。

以下内容不会公开：商业人物模板、声音模型及样本、授权记录、个人图片、用户配置、生成成片、私有密钥、第三方闭源程序和本机运行环境。

## Windows 快速启动

需要 Python 3.10+。真实渲染还需要 FFmpeg 和自行配置的口型模型。

```powershell
git clone https://github.com/agentic-build-lab/yanying-community.git
cd yanying-community
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-community.ps1
```

浏览器打开 `http://127.0.0.1:8866`。另开终端执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-community.ps1`，结束时执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-community.ps1`。

默认仅监听本机地址，商业兼容接口默认关闭，发布动作必须人工审核，运行数据统一放在不会被 Git 提交的 `.runtime/` 中。

## 许可证

社区版源码使用 GNU AGPL v3.0。需要闭源集成、再分发或商业授权时，请查看 [商业授权说明](COMMERCIAL-LICENSE.md)。外部模型和工具仍分别受其原始许可证约束。
