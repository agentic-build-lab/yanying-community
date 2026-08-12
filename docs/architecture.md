# Architecture

YanYing uses a small local control plane and independent media workers.

```text
Browser studio (8866)
        |
API gateway (35105)
   |       |       |       |
 TTS     Avatar  Render  Content
(35205) (35305) (35405) (35605)
```

The browser talks only to the API gateway. The gateway stores lightweight project and job records, then calls workers over localhost HTTP. Workers write generated artifacts to `.runtime/outputs/` by default.

The compatibility adapter is intentionally outside the default startup path. It defines a boundary for an optional existing engine without making that engine, its runtime or its assets part of this repository.

## Main directories

| Path | Purpose |
| --- | --- |
| `apps/studio_web` | Browser UI and identity-neutral placeholder assets |
| `services/api_gateway` | Public API, orchestration, review state and media records |
| `services/tts_worker` | Speech synthesis adapters |
| `services/avatar_worker` | Image/video presenter and lip-sync adapters |
| `services/render_worker` | FFmpeg composition, subtitles and output packaging |
| `services/content_worker` | Script extraction, rewriting and title assistance |
| `services/compatibility_adapter` | Optional boundary for an external local engine |
| `scripts` | Launch, verification and media-quality utilities |
| `models` | Placement instructions only; weights remain untracked |
| `.runtime` | Local secrets, logs, jobs and generated media; never committed |

## Trust boundaries

- Services listen on loopback by default.
- API keys are written only to `.runtime/private/` and are masked in responses.
- Automatic publishing is disabled; review remains a user action.
- External engine requests pass through dedicated adapters rather than UI code.
