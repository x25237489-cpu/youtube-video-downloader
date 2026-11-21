# Frame — Local Video Studio

A premium browser interface for downloading **YouTube videos you are authorised to save** onto your own Windows PC. Runs on `127.0.0.1`, not GitHub Pages.

## Windows setup

1. Install [Python 3.10+](https://www.python.org/downloads/windows/) and tick **Add Python to PATH**.
2. Download this repository as ZIP (Code → Download ZIP), then extract it.
3. Double-click `setup-windows.bat` once; it installs the Python dependency in a virtual environment.
4. Double-click `START-FRAME.bat`. The app opens at **http://127.0.0.1:8765**.
5. Paste a permitted video URL, select format/quality, confirm authorisation, and save to your **Downloads** folder.
6. Keep the terminal window open while using Frame. Press Ctrl+C to stop.

**Recommended:** Install [FFmpeg](https://ffmpeg.org/download.html) and add it to PATH. FFmpeg is needed for MP3 conversion and merging high-resolution video+audio.

## Features

- Single-video links: YouTube watch, Shorts, archived Live, and youtu.be.
- Preview metadata and thumbnail before downloading.
- MP4, M4A, and MP3; adjustable quality where available.
- Download queue, progress, speed, ETA and failure handling.
- Maximum 15 pending jobs; two download workers.
- Fixed destination: `%USERPROFILE%\Downloads`.
- Local-only API; no logins, tracking, or cloud backend.

## Usage and limitations

Only download material you own, have permission to download, or are otherwise authorised to save under applicable rights and YouTube's terms. This is an independent project, not affiliated with YouTube. It does not bypass DRM. Downloads may fail when upstream services change, and quality is not guaranteed.

## Technical details

Python standard library HTTP server, `yt-dlp`, optional FFmpeg, HTML/CSS/JavaScript. Server binds solely to `127.0.0.1`. API endpoints: `/api/config`, `/api/inspect`, `/api/download`, `/api/jobs`. The service is **not designed to be exposed to the internet**. Job history resets on app restart; downloaded files remain on disk.

## Troubleshooting

- Can't start: install Python, run `setup-windows.bat`, and verify the terminal output.
- Metadata/download errors: update `yt-dlp` using `.venv\Scripts\python.exe -m pip install -U yt-dlp`.
- High-resolution video missing audio / MP3 unavailable: install FFmpeg and restart.
- Port occupied: run `.venv\Scripts\python.exe app.py --port 8766`.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests do not need a live YouTube connection.

## GitHub hosting

GitHub hosts the **source code**, not the running Python downloader. After cloning or downloading the repo, run the Windows launcher locally. Do not publish this app's Python server as a public service.
