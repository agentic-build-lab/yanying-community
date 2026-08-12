# Engine adapters

The dry-run pipeline works without model weights. Real generation requires tools that are intentionally installed outside Git.

## Speech

Edge TTS is the default community provider. Set `METAHUMAN_TTS_EDGE_VOICE` to another supported voice. The worker also has a Windows SAPI fallback.

## Lip sync

For Wav2Lip, set:

```powershell
$env:METAHUMAN_WAV2LIP_REPO = 'C:\tools\Wav2Lip'
$env:METAHUMAN_WAV2LIP_CHECKPOINT = 'C:\models\wav2lip_gan.pth'
$env:METAHUMAN_DEFAULT_AVATAR_IMAGE = 'C:\media\presenter.png'
```

For MuseTalk, set `METAHUMAN_MUSETALK_REPO` and select the MuseTalk mode through the API or interface. Consult the upstream project's license before using or distributing its checkpoints.

## Rendering

Install FFmpeg and make `ffmpeg` available on `PATH`, or set `METAHUMAN_FFMPEG_PATH` to the executable. Generated files go to `.runtime/outputs/` unless `METAHUMAN_OUTPUT_ROOT` is set.

## Language models

The content worker accepts local Ollama or an OpenAI-compatible HTTPS endpoint. Provider keys are stored in `.runtime/private/content_api_config.json`, which is excluded by `.gitignore`. Never place a key in source code or `.env.example`.

## Optional compatibility adapter

The adapter is disabled by default. It is a protocol boundary only; no proprietary binary, licensed asset or third-party runtime is distributed here. Enable it only when you own and have separately configured a compatible local engine.
