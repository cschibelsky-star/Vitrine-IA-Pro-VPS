# HeyGen Automation V1

## Workflow

`HEYGEN_VIDEO_GENERATOR V1`

Webhook: `POST /webhook/vitrine-heygen-video-v1`

## Runtime secret

The n8n runtime must contain `HEYGEN_API_KEY`. Never commit or print the value.

## Request contract

Required:
- `request_id`
- `avatar_id`
- exactly one of `script`, `audio_url`, `audio_asset_id`

Optional:
- `voice_id`
- `title`
- `aspect_ratio` (default `9:16`)
- `resolution` (default `1080p`)
- `callback_url`
- `motion_prompt`

Example:

```json
{
  "request_id": "vid_20260918_001",
  "avatar_id": "YOUR_AVATAR_LOOK_ID",
  "script": "Texto exato do vídeo.",
  "voice_id": "OPTIONAL_PRIVATE_VOICE_ID",
  "aspect_ratio": "9:16",
  "resolution": "1080p"
}
```

## Safety

The workflow is imported as a draft. Publication requires a successful API credential smoke test and an HML request using non-sensitive synthetic content.
