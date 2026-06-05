# Subtitle Nexus (Kodi add-on)

Generate AI subtitles for your local video files via
[Subtitle Nexus](https://subtitlenexus.com), directly from Kodi.

The flow is **player-side and on-demand**: Kodi runs on the playback
device, so the add-on operates per-file rather than indexing a library.

> **NOTE: Under construction — not guaranteed to work.** v0.1.0 code is
> complete but has not been installed in a real Kodi instance yet. See
> the [TODO](#todo) section below for the punch list.

## TODO

### Before first install

- [ ] Zip the add-on directory and install via **Settings → Add-ons →
      Install from zip file** on a real Kodi 19+ instance. Confirm
      Kodi accepts the manifest without complaints.
- [ ] Confirm `script.module.requests` dependency resolves
      automatically from Kodi's official repo; if not, document the
      manual install path.
- [ ] Open the add-on's settings page and confirm every setting from
      `resources/settings.xml` renders with the correct widget type
      (string, bool, enum, password mask for API key).
- [ ] Run *Validate API key* from the action picker and confirm it
      returns success against a real Nexus API key.

### Before first generation job

- [ ] End-to-end test against a short local video missing subs — both
      the cache-hit path and the full-transcription path.
- [ ] Confirm `xbmc.Player().setSubtitles(srt_path)` actually loads the
      SRT mid-playback when the source directory is read-only and the
      SRT lands in `<userdata>/addon_data/...`.
- [ ] Verify the subtitle-provider extension point works in Kodi's
      built-in subtitle search dialog (*Player ▸ Subtitles ▸ Download
      subtitle*). Particularly that the synthetic "Transcribe with
      Subtitle Nexus" entry appears on cache miss.
- [ ] Verify the right-click context menu entry shows up on library
      items and on raw files-view items.
- [ ] Verify `xbmc.convertLanguage(name, xbmc.ISO_639_1)` produces
      correct mappings for the common languages Kodi exposes (English,
      Japanese, Spanish, French, German, Chinese). Currently falls
      back to first-two-letters when the API doesn't resolve — confirm
      this isn't producing wrong codes for exotic dialects.
- [ ] Confirm the `DialogProgressBG` progress hook in `poll_and_stream`
      updates correctly across the polling loop.

### Before publishing

- [ ] **Replace `icon.png`** — currently a 1×1 placeholder (68 bytes).
      Kodi's official repo requires 256×256.
- [ ] **Replace `fanart.jpg`** — currently a 1×1 placeholder (331
      bytes). Kodi's official repo requires 1920×1080.
- [ ] Build a release zip with the correct directory name
      (`service.subtitles.subtitlenexus-0.1.0.zip`) and attach to
      a GitHub release.
- [ ] Submit to the official Kodi add-on repository (or document
      installation via a third-party repo if you maintain one).
- [ ] Add a CI workflow that lints `addon.xml` against the Kodi schema
      and packages the zip on each tag.

### Platform-specific testing

- [ ] **Kodi 19 Matrix** — primary target (Python 3.8).
- [ ] **Kodi 20 Nexus** — verify Python 3.11 compatibility.
- [ ] **Kodi 21 Omega** — verify on the latest stable.
- [ ] **Android TV** — ffmpeg is typically unavailable; document the
      sideload / static-binary workflow.
- [ ] **LibreELEC / OSMC** — confirm ffmpeg ships and the bundled
      binary works.

### Deferred (post-v1)

- [ ] Detached-worker pattern so multiple transcription jobs can run in
      parallel from a single Kodi process. Currently each invocation is
      its own short-lived script process, which is fine for typical use
      but may benefit power users.
- [ ] Listen for Kodi's `Player.OnPlay` event to auto-offer transcription
      for newly-played files without subs.

## Features

- **Subtitle provider** — appears in Kodi's built-in subtitle search dialog
  (Player ▸ Subtitles ▸ Download). Hashes the playing file, looks it up in
  the Nexus community cache, and offers AI transcription if no cache hit.
- **Context menu item** — right-click any video in the library or files view
  and pick *Generate Nexus Subtitles*.
- **Script entry** — runs from the Programs/Video add-ons menu with a small
  action picker (current item, file browser, validate key, settings).

Cached subs from other users are returned for free. Generating new
transcriptions consumes Nexus tokens or daily credits — confirmation prompts
appear before any paid work runs.

## Requirements

- **Kodi 19 Matrix** or newer (Python 3.8+)
- An API key from <https://subtitlenexus.com/account>
- **ffmpeg** available either:
  - on the system `PATH`, or
  - at a path you set via *Add-on settings ▸ Advanced ▸ ffmpeg Path*
  - On most desktop Kodi installs ffmpeg is already on PATH; on Android TV
    you typically need to install it via a separate package or sideload a
    static binary and point the setting at it.

## Install

### From zip (recommended)

1. Download the latest release zip from the project's GitHub releases page.
2. In Kodi: *Settings ▸ Add-ons ▸ Install from zip file*. (You'll be prompted
   to enable "Unknown sources" if you haven't already.)
3. Point Kodi at the downloaded zip.

### Manual (developer install)

Drop the `subtitlenexus-kodi-plugin/` directory into Kodi's add-ons folder
under a name matching the add-on id:

| OS | Path |
| --- | --- |
| Linux | `~/.kodi/addons/service.subtitles.subtitlenexus/` |
| macOS | `~/Library/Application Support/Kodi/addons/service.subtitles.subtitlenexus/` |
| Windows | `%APPDATA%\Kodi\addons\service.subtitles.subtitlenexus\` |
| Android | `Android/data/org.xbmc.kodi/files/.kodi/addons/service.subtitles.subtitlenexus/` |

Restart Kodi after copying, then enable the add-on from *Settings ▸ Add-ons
▸ My add-ons ▸ Services / Subtitles*.

## Configure

Open the add-on and pick *Open settings*, or *Settings ▸ Add-ons ▸ My add-ons
▸ Services ▸ Subtitle Nexus ▸ Configure*.

| Setting | Default | Description |
| --- | --- | --- |
| API Key | _(blank)_ | Required. From <https://subtitlenexus.com/account>. |
| API Domain | `api.subtitlenexus.com` | Override only for self-hosted deployments. |
| Model Version | `lulu-2605` | Subtitle model slug. |
| Subtitle Language | `en` | Output language (ISO-639-1). |
| Audio Language | `ja` | Source audio language. |
| Visibility | `PUBLIC` | `PUBLIC` shares with the community cache; `UNLISTED` keeps it private. |
| Ignore Community Subs | _off_ | Skip cached subs from other users; only reuse your own. |
| Disable Cache Search | _off_ | Always submit a new request, skipping the cache lookup. |
| Auto-Purchase Over Daily Limit | _off_ | Automatically spend tokens when the daily free-download limit is hit. |
| ffmpeg Path | _(blank)_ | Absolute path to ffmpeg; blank = use PATH. |

After saving the API key, run the *Validate API key* option from the
add-on's action picker to confirm connectivity.

## Use

### Subtitle search dialog (in-player)

1. Start playing a local video file.
2. Open *Player controls ▸ Subtitles ▸ Download subtitle*.
3. Subtitle Nexus appears as a provider. Selecting it:
   - lists any cached subs (free) — click one to load it.
   - or shows a single "Transcribe with Subtitle Nexus" entry when no cache
     hit. Click it to confirm and kick off the AI pipeline; the SRT loads
     automatically when finished.

### Context menu (in the library)

Right-click a video item ▸ *Generate Nexus Subtitles*. Confirms before
transcribing and notifies when the file lands on disk.

### Direct launch

Open *Subtitle Nexus* from *Programs add-ons*. The action picker lets you:

- Generate subs for the currently playing video
- Browse to a file and generate subs
- Validate your API key
- Open settings

## Output

Subtitles are written as sidecar SRTs next to the source video:

```
my_video.mkv
my_video.en.srt   <- generated by Subtitle Nexus
```

If the directory containing the video is read-only (e.g. a network share
mounted RO), the SRT lands in the add-on's user profile dir
(`<userdata>/addon_data/service.subtitles.subtitlenexus/subtitles/`) and is
loaded into the active player via `Player.setSubtitles` so you still see it
during the current session.

## Placeholder icons

`icon.png` and `fanart.jpg` ship as 1x1 placeholder pixels. Replace before
publishing to the official repo — Kodi expects `icon.png` to be a 256x256
PNG and `fanart.jpg` to be 1920x1080.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "No API key configured" | Paste your key into *Settings ▸ API Key*. |
| "ffmpeg failed" during extraction | Install ffmpeg or set the *ffmpeg Path* to an absolute path. |
| Subtitle provider doesn't appear in the player dialog | Ensure the add-on is enabled and Kodi was restarted after install. |
| Transcription stalls | Tail the Kodi log (*Settings ▸ System ▸ Logging ▸ View log*) and look for `[Subtitle Nexus]` lines. |

## Development

Repo layout:

```
service.subtitles.subtitlenexus/
├── addon.xml                    # manifest: subtitle.module + context.item + script
├── default.py                   # script entry (action picker / validate / generate)
├── service.py                   # subtitle provider (search / download / transcribe)
├── context.py                   # context menu handler
├── resources/
│   ├── settings.xml             # Kodi settings UI
│   ├── language/.../strings.po  # translatable strings
│   └── lib/
│       ├── nexus_api.py         # HTTP client for the Nexus REST API
│       ├── nexus_hash.py        # OS-hash + sha256-endpoints
│       ├── audio.py             # ffmpeg shell-out
│       ├── settings.py          # typed settings loader
│       └── generator.py         # orchestration (process_video, poll_and_stream)
└── icon.png / fanart.jpg        # placeholder media
```

## License

MIT. See `LICENSE`.
