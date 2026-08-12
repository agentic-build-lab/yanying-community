# YanYing Community

YanYing is a local-first digital-human video studio. It turns a script, a voice and a presenter image into a reviewable talking-head video workflow from one browser interface.

[简体中文](README.zh-CN.md) · [Architecture](docs/architecture.md) · [Engine adapters](docs/engine-adapters.md)

## What is included

- A responsive browser studio for scripts, voice selection, presenter assets, subtitles, covers and review.
- A FastAPI gateway that coordinates jobs, assets, user media and approval state.
- Independent workers for TTS, lip sync, rendering and content assistance.
- Adapter points for Edge TTS, Wav2Lip, MuseTalk, FFmpeg and OpenAI-compatible language-model APIs.
- Dry-run mode, which exercises the full orchestration path without downloading model weights.

Model weights, third-party runtimes, commercial templates, identity images, private configuration, generated media and proprietary compatibility binaries are deliberately not stored in this repository. That is why the source checkout is small: application code and documentation compress well, while models and media account for nearly all of a production installation's disk usage.

## Quick start on Windows

Requirements: Python 3.10+, PowerShell 7 or Windows PowerShell 5.1, and optionally FFmpeg for real rendering.

```powershell
git clone https://github.com/agentic-build-lab/yanying-community.git
cd yanying-community
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-community.ps1
```

Open `http://127.0.0.1:8866`. Run the smoke test in another terminal:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-community.ps1
```

Stop all services with `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-community.ps1`.

The default installation is safe for evaluation: services bind to localhost, the proprietary compatibility adapter is disabled, publishing requires review, and generated state stays under `.runtime/`.

## Real generation

Dry-run jobs need no model files. For real videos, provide a presenter image and configure at least one lip-sync engine. See [Engine adapters](docs/engine-adapters.md) for environment variables and expected directories. Each upstream model retains its own license; review it before redistribution or commercial use.

## Project status

This is an early community release. The Windows launcher and dry-run pipeline are supported. Real output depends on the external engines and checkpoints you configure.

## License

Community source is licensed under the GNU Affero General Public License v3.0. A separate commercial license is available for proprietary products or deployments; see [Commercial licensing](COMMERCIAL-LICENSE.md).
