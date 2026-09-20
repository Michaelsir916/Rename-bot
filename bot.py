"""
Document -> Video Converter Bot (Telegram)
-------------------------------------------
Takes video files sent as "document" and re-sends them as streamable videos.
The thumbnail is extracted from the exact middle of the video using ffmpeg.
Supports files up to 2GB (4GB for Telegram Premium accounts) because it uses
Pyrogram (MTProto) directly instead of the standard HTTP Bot API, which is
limited to much smaller file sizes.

Requirements:
    pip install -r requirements.txt
    ffmpeg must be installed on the system (apt install ffmpeg)

Environment variables needed (get API_ID / API_HASH from my.telegram.org,
and BOT_TOKEN from @BotFather on Telegram):
    API_ID=xxxxxx
    API_HASH=xxxxxxxxxxxxxxxxxxxxxxxx
    BOT_TOKEN=xxxxxxxxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
"""

import os
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message

# ---------- Config ----------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

DOWNLOAD_DIR = "downloads"
THUMB_DIR = "thumbs"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".ts", ".3gp")

app = Client(
    "doc2video_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


# ---------- Helpers ----------
def is_video_document(message: Message) -> bool:
    """Check whether the incoming document is actually a video file."""
    doc = message.document
    if not doc:
        return False
    if doc.mime_type and doc.mime_type.startswith("video/"):
        return True
    if doc.file_name and doc.file_name.lower().endswith(VIDEO_EXTENSIONS):
        return True
    return False


def get_duration(path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
    ).decode().strip()
    return float(out) if out else 0.0


def get_dimensions(path: str):
    """Get video width and height using ffprobe."""
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            path,
        ]
    ).decode().strip()
    if "x" not in out:
        return 0, 0
    w, h = out.split("x")
    return int(w), int(h)


def extract_middle_thumbnail(path: str, out_path: str, duration: float):
    """Extract a single frame from the middle of the video as a thumbnail."""
    timestamp = duration / 2 if duration > 0 else 1
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", path,
            "-frames:v", "1",
            "-q:v", "2",
            out_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------- Handler ----------
@app.on_message(filters.document)
async def convert_document_to_video(client: Client, message: Message):
    if not is_video_document(message):
        return

    status = await message.reply_text("Downloading... 0%")

    file_name = message.document.file_name or f"video_{message.id}.mp4"
    local_path = os.path.join(DOWNLOAD_DIR, f"{message.id}_{file_name}")
    thumb_path = os.path.join(THUMB_DIR, f"{message.id}.jpg")

    last_shown = {"percent": -5}

    async def dl_progress(current, total):
        percent = current * 100 / total
        if percent - last_shown["percent"] >= 5 or percent >= 100:
            last_shown["percent"] = percent
            try:
                await status.edit_text(f"Downloading... {percent:.0f}%")
            except Exception:
                pass

    try:
        await message.download(file_name=local_path, progress=dl_progress)
    except Exception as e:
        await status.edit_text(f"Download failed: {e}")
        return

    await status.edit_text("Extracting thumbnail (from the middle of the video)...")

    duration, width, height = 0.0, 0, 0
    thumb_ok = False
    try:
        duration = get_duration(local_path)
        width, height = get_dimensions(local_path)
        extract_middle_thumbnail(local_path, thumb_path, duration)
        thumb_ok = os.path.exists(thumb_path)
    except Exception:
        pass

    last_shown["percent"] = -5
    await status.edit_text("Uploading as video... 0%")

    async def up_progress(current, total):
        percent = current * 100 / total
        if percent - last_shown["percent"] >= 5 or percent >= 100:
            last_shown["percent"] = percent
            try:
                await status.edit_text(f"Uploading... {percent:.0f}%")
            except Exception:
                pass

    try:
        await message.reply_video(
            local_path,
            thumb=thumb_path if thumb_ok else None,
            duration=int(duration),
            width=width or None,
            height=height or None,
            supports_streaming=True,
            caption=message.caption or "",
            progress=up_progress,
        )
        await status.delete()
    except Exception as e:
        await status.edit_text(f"Upload failed: {e}")
    finally:
        for p in (local_path, thumb_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


if __name__ == "__main__":
    print("Bot running... (Ctrl+C to stop)")
    app.run()
