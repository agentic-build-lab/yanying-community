# Services

Each service is an independent Python module with a narrow responsibility. The root launcher supplies ports and local runtime paths, so service folders contain no machine-specific configuration.

- `api_gateway`: browser-facing API and job orchestration
- `tts_worker`: speech synthesis
- `avatar_worker`: presenter and lip-sync generation
- `render_worker`: video composition and packaging
- `content_worker`: script and title assistance
- `compatibility_adapter`: optional external-engine boundary, disabled by default

Start the supported local stack from the repository root with `scripts/start-community.ps1`.
