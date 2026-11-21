"""Public-web companion for Frame.

Use behind a real HTTPS hosting platform. Jobs are temporary; downloads
are user-initiated browser attachments, not saved to the host's Downloads.
"""
from __future__ import annotations
import collections
import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
import yt_dlp

from app import validate_youtube_url, inspect_video, format_options, ffmpeg_available

server = Flask(__name__, static_folder=None)
server.config["MAX_CONTENT_LENGTH"] = 16_384
MAX_BYTES = 200 * 1024 * 1024
MAX_PENDING = 2
JOB_LIFETIME = 20 * 60
MAX_HOURLY = 5
STORAGE = Path(tempfile.mkdtemp(prefix="frame-web-"))
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="frame-web")
lock = threading.RLock()
jobs = {}
access = collections.defaultdict(collections.deque)


def now():
    return time.time()


def client_id():
    # Do not trust arbitrary client-supplied IP forwarding headers.
    # Render can provide the actual remote client through its proxy, but
    # platform-level throttling is also recommended.
    return request.remote_addr or "unknown"


def cleanup():
    with lock:
        for jid, job in list(jobs.items()):
            if now() - job["created"] > JOB_LIFETIME:
                shutil.rmtree(STORAGE / jid, ignore_errors=True)
                jobs.pop(jid, None)
        for client, history in list(access.items()):
            while history and history[0] <= now() - 3600:
                history.popleft()
            if not history:
                access.pop(client, None)


def redact(job):
    return {key: job.get(key) for key in ("id", "title", "status", "stage", "format", "quality", "progress", "speed", "eta", "error", "thumbnail", "download_url", "created_at")}


def error(message, code=400):
    return jsonify({"error": message}), code


@server.before_request
def protect():
    cleanup()
    if request.path.startswith("/api/") and request.method in ("POST", "GET"):
        # Intentionally no cross-origin allowance.
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return error("Cross-origin requests are not permitted.", 403)


@server.get("/")
def home():
    return send_from_directory("static", "index.html", max_age=0)


@server.get("/static/<path:filename>")
def asset(filename):
    if filename not in ("main.css", "app.js"):
        return error("Not found", 404)
    return send_from_directory("static", filename, max_age=0)


@server.get("/api/config")
def config():
    return jsonify({"hosted": True, "yt_dlp": True, "ffmpeg": ffmpeg_available(), "folder": "Your browser's Downloads folder", "max_file_mb": 200})


@server.post("/api/inspect")
def inspect():
    data = request.get_json(silent=True) or {}
    try:
        url, _ = validate_youtube_url(data.get("url", ""))
        result = inspect_video(url)
        return jsonify({"video": result})
    except Exception as exc:
        return error(str(exc).splitlines()[0][:250], 422)


def worker(jid, url, fmt, quality):
    jobdir = STORAGE / jid
    jobdir.mkdir(parents=True, exist_ok=True)
    def up(**fields):
        with lock:
            if jid in jobs:
                jobs[jid].update(fields)
    def hook(info):
        if info.get("status") == "downloading":
            done = info.get("downloaded_bytes") or 0
            total = info.get("total_bytes") or info.get("total_bytes_estimate") or 0
            if done > MAX_BYTES or total > MAX_BYTES:
                raise ValueError("File is larger than the 200 MB website limit.")
            up(status="downloading", stage="Downloading", progress=round(min(99, done * 100 / total), 1) if total else 0, speed=info.get("speed"), eta=info.get("eta"))
        elif info.get("status") == "finished":
            up(status="processing", stage="Preparing browser download", progress=99)
    try:
        options = format_options(fmt, quality, jobdir, hook)
        options["max_filesize"] = MAX_BYTES
        options["quiet"] = True
        options["no_warnings"] = True
        options["noplaylist"] = True
        with yt_dlp.YoutubeDL(options) as engine:
            engine.download([url])
        candidates = [p for p in jobdir.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
        if not candidates:
            raise RuntimeError("No completed file was produced.")
        result = max(candidates, key=lambda p: p.stat().st_size)
        if result.stat().st_size > MAX_BYTES:
            raise ValueError("Completed file exceeds the website size limit.")
        up(status="completed", stage="Ready to save", progress=100, speed=None, eta=None, file=str(result), download_url=f"/api/file/{jid}", error=None)
    except Exception as exc:
        shutil.rmtree(jobdir, ignore_errors=True)
        up(status="failed", stage="Download failed", error=str(exc).splitlines()[0][:240])


@server.post("/api/download")
def download():
    data = request.get_json(silent=True) or {}
    try:
        url, vid = validate_youtube_url(data.get("url", ""))
        if data.get("authorized") is not True:
            return error("Confirm that you are authorised to download this content.")
        fmt = data.get("format")
        quality = str(data.get("quality", "720"))
        if fmt not in ("mp4", "audio-m4a", "audio-mp3") or quality not in ("best", "2160", "1440", "1080", "720", "480", "360"):
            return error("Invalid format or quality.")
        if fmt == "audio-mp3" and not ffmpeg_available():
            return error("MP3 conversion is unavailable on this host.")
        with lock:
            client = client_id()
            history = access[client]
            if len(history) >= MAX_HOURLY:
                return error("Hourly download limit reached. Try again later.", 429)
            if sum(job["status"] in ("queued", "downloading", "processing") for job in jobs.values()) >= MAX_PENDING:
                return error("Server is busy. Try again shortly.", 429)
            history.append(now())
            jid = uuid.uuid4().hex
            job = {"id": jid, "title": str(data.get("title") or ("YouTube video " + vid))[:180],
                   "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                   "format": fmt, "quality": quality, "status": "queued", "stage": "Queued", "progress": 0,
                   "speed": None, "eta": None, "error": None, "created": now(), "created_at": int(now()),
                   "download_url": None, "file": None}
            jobs[jid] = job
        pool.submit(worker, jid, url, fmt, quality)
        return jsonify({"job": redact(job)}), 202
    except ValueError as exc:
        return error(str(exc))


@server.get("/api/jobs")
def list_jobs():
    # No global exposure of all visitors' jobs.
    return jsonify({"jobs": []})


@server.get("/api/job/<jid>")
def get_job(jid):
    with lock:
        job = jobs.get(jid)
        if not job:
            return error("Job expired or not found", 404)
        return jsonify({"job": redact(job)})


@server.get("/api/file/<jid>")
def get_file(jid):
    with lock:
        job = jobs.get(jid)
        if not job or job["status"] != "completed" or not job.get("file"):
            return error("Download is not ready or has expired.", 404)
        path = Path(job["file"])
    if not path.exists():
        return error("File has expired.", 410)
    result = send_file(path, as_attachment=True, download_name=path.name, mimetype="application/octet-stream", conditional=True)
    result.headers["Cache-Control"] = "private, no-store"
    result.headers["X-Content-Type-Options"] = "nosniff"
    return result


@server.get("/health")
def health():
    return jsonify({"ok": True})


@server.errorhandler(RequestEntityTooLarge)
def too_large(_):
    return error("Request too large", 413)


@server.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' https://i.ytimg.com data:; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"
    return response


if __name__ == "__main__":
    server.run(host="127.0.0.1", port=int(os.getenv("PORT", "8765")), debug=False)
