"""Frame — Local Video Studio: local-only UI for authorised video downloads."""
from __future__ import annotations
import argparse
import importlib.util
import json
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'
DEFAULT_FOLDER = Path.home() / 'Downloads'
ALLOWED_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}
VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')
MAX_POST_BYTES = 16_384
MAX_JOBS = 80
MAX_PENDING = 15
QUALITIES = {'best', '2160', '1440', '1080', '720', '480', '360'}
FORMATS = {'mp4', 'audio-m4a', 'audio-mp3'}

lock = threading.RLock()
jobs: dict[str, dict] = {}
download_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='dl')

def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def validate_youtube_url(value: str) -> tuple[str, str]:
    """Return canonical single-video URL and ID without making a network request."""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Please paste a valid YouTube video link.')
    value = value.strip()
    try:
        u = urlparse(value)
        host = (u.hostname or '').lower()
        if u.scheme != 'https' or host not in ALLOWED_HOSTS or u.username or u.password or u.port not in (None, 443):
            raise ValueError
        parts = [p for p in u.path.split('/') if p]
        video_id = ''
        if host.endswith('youtu.be'):
            if len(parts) != 1:
                raise ValueError
            video_id = parts[0]
        elif u.path == '/watch':
            ids = parse_qs(u.query).get('v', [])
            if len(ids) != 1:
                raise ValueError
            video_id = ids[0]
        elif len(parts) == 2 and parts[0] in ('shorts', 'live'):
            video_id = parts[1]
        if not VIDEO_ID_RE.fullmatch(video_id):
            raise ValueError
        return 'https://www.youtube.com/watch?v=' + video_id, video_id
    except (ValueError, TypeError):
        raise ValueError('Use a YouTube video URL (youtube.com/watch, /shorts, /live, or youtu.be). Playlists and other sites are not supported.') from None

def public_job(job: dict) -> dict:
    return {key: val for key, val in job.items() if key not in ('url', 'video_id', 'internal_error')}

def youtube_module():
    if importlib.util.find_spec('yt_dlp') is None:
        raise RuntimeError('yt-dlp is not installed. Run setup-windows.bat first.')
    import yt_dlp
    return yt_dlp

def inspect_video(url: str) -> dict:
    yt_dlp = youtube_module()
    canonical, video_id = validate_youtube_url(url)
    opts = {
        'quiet': True, 'no_warnings': True, 'skip_download': True,
        'noplaylist': True, 'extract_flat': False, 'socket_timeout': 15,
        'retries': 1, 'extractor_retries': 1,
    }
    with yt_dlp.YoutubeDL(opts) as dl:
        info = dl.extract_info(canonical, download=False)
    if not isinstance(info, dict) or info.get('_type') in ('playlist', 'multi_video'):
        raise ValueError('This link did not resolve to an individual video.')
    if info.get('is_live'):
        raise ValueError('Live broadcasts are not supported. Try again after the video is archived.')
    return {
        'id': video_id,
        'title': str(info.get('title') or 'Untitled video')[:250],
        'channel': str(info.get('uploader') or info.get('channel') or 'YouTube')[:140],
        'duration': info.get('duration') if isinstance(info.get('duration'), (int, float)) else None,
        'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
        'available_heights': sorted({int(f.get('height')) for f in info.get('formats', []) if isinstance(f, dict) and isinstance(f.get('height'), int) and f['height'] > 0}, reverse=True),
        'url': canonical,
    }

def ffmpeg_available() -> bool:
    return bool(shutil.which('ffmpeg'))

def format_options(fmt: str, quality: str, folder: Path, hook) -> dict:
    opts = {
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'outtmpl': str(folder / '%(title).180B [%(id)s].%(ext)s'),
        'restrictfilenames': False, 'windowsfilenames': True,
        'overwrites': False, 'continuedl': True,
        'progress_hooks': [hook],
        'socket_timeout': 20, 'retries': 3, 'fragment_retries': 3,
        'extractor_retries': 2, 'max_filesize': 8 * 1024 * 1024 * 1024,
    }
    if fmt == 'mp4':
        height = '' if quality == 'best' else f'[height<={quality}]'
        if ffmpeg_available():
            opts['format'] = f'bestvideo{height}+bestaudio/best{height}'
            opts['merge_output_format'] = 'mp4'
        else:
            opts['format'] = f'best[ext=mp4]{height}/best{height}'
    elif fmt == 'audio-m4a':
        opts['format'] = 'bestaudio[ext=m4a]/bestaudio'
        if ffmpeg_available():
            opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}]
    else:
        if not ffmpeg_available():
            raise ValueError('MP3 conversion needs FFmpeg. Install it and restart the app.')
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
    return opts

def update_job(job_id: str, **fields) -> None:
    with lock:
        if job_id in jobs:
            jobs[job_id].update(fields)
            jobs[job_id]['updated_at'] = iso_now()

def run_download(job_id: str, url: str, fmt: str, quality: str, folder: Path) -> None:
    update_job(job_id, status='downloading', stage='Preparing download')
    try:
        yt_dlp = youtube_module()
        def hook(info):
            if info.get('status') == 'downloading':
                downloaded = info.get('downloaded_bytes') or 0
                total = info.get('total_bytes') or info.get('total_bytes_estimate') or 0
                pct = round(min(99, downloaded / total * 100), 1) if total else 0
                update_job(job_id, progress=pct, stage='Downloading', speed=info.get('speed'), eta=info.get('eta'))
            elif info.get('status') == 'finished':
                update_job(job_id, progress=99, stage='Processing file…', speed=None, eta=None)
        with yt_dlp.YoutubeDL(format_options(fmt, quality, folder, hook)) as dl:
            dl.download([url])
        update_job(job_id, status='completed', progress=100, stage='Saved to Downloads', speed=None, eta=None)
    except Exception as exc:
        update_job(job_id, status='failed', stage='Download failed', error=str(exc).splitlines()[0][:260])

def json_response(handler: BaseHTTPRequestHandler, code: int, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(payload)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Referrer-Policy', 'no-referrer')
    handler.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
    handler.end_headers()
    handler.wfile.write(payload)

class Handler(BaseHTTPRequestHandler):
    server_version = 'YTLocalStudio/1.0'
    def log_message(self, format: str, *args) -> None:
        pass

    def headers_safe(self) -> bool:
        host = self.headers.get('Host', '').lower()
        if host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
            return False
        origin = self.headers.get('Origin')
        if origin:
            try:
                parsed = urlparse(origin)
                if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.port != self.server.server_port:
                    return False
            except ValueError:
                return False
        fetch_site = self.headers.get('Sec-Fetch-Site', '')
        return fetch_site in ('', 'same-origin', 'none')

    def do_GET(self) -> None:
        if not self.headers_safe():
            json_response(self, 403, {'error': 'Only this local app may access the service.'})
            return
        path = urlparse(self.path).path
        if path == '/api/config':
            json_response(self, 200, {
                'ffmpeg': ffmpeg_available(), 'yt_dlp': importlib.util.find_spec('yt_dlp') is not None,
                'folder': str(DEFAULT_FOLDER), 'local_only': True,
            })
        elif path == '/api/jobs':
            with lock:
                recent = sorted(jobs.values(), key=lambda x: x['created_at'], reverse=True)
                json_response(self, 200, {'jobs': [public_job(j) for j in recent[:MAX_JOBS]]})
        elif path == '/' or path == '/index.html':
            data = (STATIC_DIR / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' https://i.ytimg.com data:; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)
        elif path in ('/static/main.css', '/static/app.js'):
            name = path.rsplit('/', 1)[-1]
            data = (STATIC_DIR / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/css; charset=utf-8' if name.endswith('.css') else 'text/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
        else:
            json_response(self, 404, {'error': 'Not found'})

    def do_POST(self) -> None:
        if not self.headers_safe():
            json_response(self, 403, {'error': 'Only this local app may access the service.'})
            return
        path = urlparse(self.path).path
        if path not in ('/api/inspect', '/api/download'):
            json_response(self, 404, {'error': 'Not found'})
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            json_response(self, 415, {'error': 'Expected JSON request'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > MAX_POST_BYTES:
                json_response(self, 413, {'error': 'Invalid request size'})
                return
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Invalid request.')
            url, video_id = validate_youtube_url(body.get('url', ''))
            if path == '/api/inspect':
                try:
                    result = inspect_video(url)
                    json_response(self, 200, {'video': result})
                except Exception as exc:
                    json_response(self, 422, {'error': str(exc).splitlines()[0][:240]})
                return
            if body.get('authorized') is not True:
                raise ValueError('Please confirm you are authorised to download this video.')
            fmt = body.get('format', 'mp4')
            quality = str(body.get('quality', '720'))
            if fmt not in FORMATS or quality not in QUALITIES:
                raise ValueError('Invalid format or quality.')
            if fmt == 'audio-mp3' and not ffmpeg_available():
                raise ValueError('FFmpeg is required for MP3 conversion.')
            if importlib.util.find_spec('yt_dlp') is None:
                raise ValueError('yt-dlp is not installed; run setup-windows.bat.')
            DEFAULT_FOLDER.mkdir(parents=True, exist_ok=True)
            with lock:
                pending = sum(1 for j in jobs.values() if j['status'] in ('queued', 'downloading'))
                if pending >= MAX_PENDING:
                    json_response(self, 429, {'error': 'Queue is full. Please try again later.'})
                    return
                if len(jobs) >= MAX_JOBS:
                    for old_id in sorted(jobs, key=lambda k: jobs[k]['created_at']):
                        if jobs[old_id]['status'] not in ('queued', 'downloading'):
                            del jobs[old_id]
                            break
                job_id = uuid.uuid4().hex
                job = {
                    'id': job_id, 'title': str(body.get('title') or ('YouTube video ' + video_id))[:180],
                    'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
                    'status': 'queued', 'stage': 'Waiting in queue', 'format': fmt, 'quality': quality,
                    'progress': 0, 'speed': None, 'eta': None, 'error': None,
                    'created_at': iso_now(), 'updated_at': iso_now(),
                }
                jobs[job_id] = job
            download_executor.submit(run_download, job_id, url, fmt, quality, DEFAULT_FOLDER)
            json_response(self, 202, {'job': public_job(job)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            json_response(self, 400, {'error': str(exc)})
        except OSError:
            json_response(self, 500, {'error': 'Could not access Downloads folder.'})

def main():
    parser = argparse.ArgumentParser(description='Run local-only Frame Studio')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535:
        parser.error('Choose a port between 1024 and 65535')
    import webbrowser
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    address = f'http://127.0.0.1:{args.port}'
    print(f'\n  Frame is running at {address}')
    print(f'  Files save to: {DEFAULT_FOLDER}')
    print('  Press Ctrl+C to stop. Accessible only on this PC.\n')
    if not args.no_browser:
        threading.Timer(0.65, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print('\nStopping…')
    finally:
        server.server_close()
        download_executor.shutdown(wait=False)

if __name__ == '__main__':
    main()
