# Frame — Browser Video Studio

Frame is a premium, browser-based interface for viewing video metadata, checking available resolutions, and downloading **YouTube videos for which you have appropriate authorisation**.

**Two ways to run Frame:**
- **Hosted website:** users visit a URL, paste a link, choose video/audio format and quality, and select **Download**. The backend temporarily processes the media, then transfers it to the **visitor's browser Downloads** folder. No Python installation for visitors.
- **Local Windows app:** available in `app.py`, `setup-windows.bat`, and `START-FRAME.bat` for running privately on your own computer.

## Website deployment (Render)

The GitHub repository hosts the source code. **GitHub Pages cannot operate the download backend.** You need a web-service host.

A Render blueprint is included in `render.yaml`, along with a Dockerfile installing Python, FFmpeg, yt-dlp and the web server.

1. Sign in to [Render](https://dashboard.render.com/) and connect your GitHub account.
2. Choose **New → Blueprint** and select `x25237489-cpu/youtube-video-downloader` on its `main` branch.
3. Review `render.yaml` and **the price of the Starter service** before approving deployment. Paid service resources may incur charges. No automatic deployment or payment has been authorised.
4. After deployment succeeds, Render will provide a URL such as `https://<your-service>.onrender.com`. Open that URL to use Frame, without running Python locally.
5. Test a short video you own or have permission to download at a low quality first.

For a host other than Render, build the `Dockerfile` and expose the service's `PORT`. The container launches Gunicorn serving `hosted:server`.

**Current status:** code committed on GitHub; cloud deployment and actual end-to-end YouTube download have **not** been verified. The service might need updates if YouTube or hosting providers restrict extraction.

## Hosted app safeguards and limits

- Explicit confirmation of permission to save the media.
- Accepts only individual YouTube HTTPS video links; no arbitrary URL fetching or playlists.
- Two concurrent processing jobs and five download requests/hour per apparent client IP, in memory. **Do not treat this as strong anti-abuse security or production-grade user identification.**
- Files must be within 200 MB. Files and queue data are temporary and are intended to expire after about 20 minutes (cleanup runs on subsequent requests).
- Files save through your browser; host disk storage is temporary.
- Jobs are accessible by a randomly generated URL. These links must be treated as private.
- No user accounts or built-in analytics. Your hosting provider may still keep access and network logs; provide an appropriate privacy notice before broad public use.
- No DRM circumvention or guarantee of availability.
- **Public deployment is not recommended until traffic controls, storage cleanup, host restrictions and acceptable use/legal obligations have been reviewed.** High traffic could cause charges or account suspension. Cloud infrastructure may be blocked by video services.

Important: YouTube's terms restrict downloading except when permitted by YouTube, with appropriate permission, or as allowed by law. Merely owning copyright or declaring permission may not by itself satisfy YouTube's platform terms. Read [YouTube's terms](https://www.youtube.com/t/terms).

## Windows local option

1. Install [Python 3.10+](https://www.python.org/downloads/windows/) and select **Add Python to PATH**.
2. Download this repository as ZIP, extract it, and double-click `setup-windows.bat` once.
3. Double-click `START-FRAME.bat`. Open `http://127.0.0.1:8765`.
4. Paste a permitted link, select format and quality, and confirm authorisation.

For high-resolution video or MP3, install [FFmpeg](https://ffmpeg.org/download.html).

## Technology

Python, Flask (hosted), Python standard library HTTP server (local), Gunicorn, yt-dlp, FFmpeg, HTML/CSS/vanilla JavaScript. There is no external database.

### Offline tests

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The tests do not make YouTube requests. A green CI build **does not confirm a live download**.
