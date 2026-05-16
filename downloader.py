import yt_dlp
import os
import uuid
import subprocess
import math
import logging

logger = logging.getLogger(__name__)
MAX_PART_BYTES = 49 * 1024 * 1024

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

FORMAT_STRATEGIES = [
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
    "bestvideo+bestaudio/best",
    "best[ext=mp4]/best",
    "best",
    "worstvideo+worstaudio/worst",
]


def _base_opts(output_template: str) -> dict:
    return {
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 3,
        "socket_timeout": 30,
        "http_headers": BROWSER_HEADERS,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "noprogress": True,
        "extractor_args": {"facebook": {"webpage_url_basename": [""]}},
    }


def _find_output(output_dir: str, unique_id: str, ydl, info: dict) -> str | None:
    filename = ydl.prepare_filename(info)
    if not filename.endswith(".mp4"):
        base = os.path.splitext(filename)[0]
        filename = base + ".mp4"
    if os.path.exists(filename):
        return filename
    for f in os.listdir(output_dir):
        if f.startswith(unique_id):
            return os.path.join(output_dir, f)
    return None


def download_facebook_video(url: str) -> tuple[str | None, str | None]:
    output_dir = "/tmp"
    last_error = None
    for strategy in FORMAT_STRATEGIES:
        unique_id = uuid.uuid4().hex
        output_template = os.path.join(output_dir, f"{unique_id}.%(ext)s")
        opts = _base_opts(output_template)
        opts["format"] = strategy
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                caption = info.get("description") or info.get("title") or ""
                filepath = _find_output(output_dir, unique_id, ydl, info)
                if filepath and os.path.exists(filepath):
                    return filepath, caption
        except yt_dlp.utils.DownloadError as e:
            last_error = str(e)
            for f in os.listdir(output_dir):
                if f.startswith(unique_id):
                    try:
                        os.remove(os.path.join(output_dir, f))
                    except Exception:
                        pass
            continue
        except Exception as e:
            last_error = str(e)
            continue
    raise RuntimeError("Could not download this video. It may be private, age-restricted, or temporarily unavailable.")


def get_video_duration(filepath: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filepath],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def split_video(filepath: str) -> list[str]:
    file_size = os.path.getsize(filepath)
    if file_size <= MAX_PART_BYTES:
        return [filepath]
    duration = get_video_duration(filepath)
    if duration <= 0:
        return [filepath]
    num_parts = math.ceil(file_size / MAX_PART_BYTES)
    part_duration = duration / num_parts
    unique_id = uuid.uuid4().hex
    output_dir = "/tmp"
    parts = []
    for i in range(num_parts):
        start = i * part_duration
        part_path = os.path.join(output_dir, f"{unique_id}_part{i + 1}.mp4")
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", filepath, "-t", str(part_duration), "-c", "copy", "-avoid_negative_ts", "make_zero", part_path]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and os.path.exists(part_path):
            parts.append(part_path)
    return parts if parts else [filepath]
