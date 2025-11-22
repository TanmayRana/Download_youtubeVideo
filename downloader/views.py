import os
import tempfile
from urllib.parse import urlparse

from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

import yt_dlp


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _extract_video_info(url: str):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
    }

    # Optionally use a cookies file if configured via env var.
    # This is needed for some YouTube videos that require login / bot verification.
    cookie_file = os.getenv("YTDLP_COOKIE_FILE")
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


@csrf_exempt
@require_POST
def analyze_url(request):
    url = request.POST.get("url") or (
        getattr(request, "body", b"") and getattr(request, "content_type", "").startswith("application/json")
    )

    if request.content_type == "application/json":
        import json

        try:
            data = json.loads(request.body.decode("utf-8"))
            url = data.get("url")
        except Exception:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if not url or not _is_valid_url(url):
        return JsonResponse({"error": "Invalid or missing URL"}, status=400)

    try:
        info = _extract_video_info(url)
    except yt_dlp.utils.DownloadError as e:
        detail = str(e)

        # Handle common YouTube bot-check / login-required message more explicitly
        if "Sign in to confirm you’re not a bot" in detail or "Sign in to confirm you're not a bot" in detail:
            return JsonResponse(
                {
                    "error": "YouTube is blocking this request",
                    "detail": detail,
                    "hint": "This video requires authentication / bot verification. Configure a YouTube cookies file on the server and set the YTDLP_COOKIE_FILE env var if you need to support such videos.",
                },
                status=403,
            )

        return JsonResponse({"error": "Failed to retrieve video information", "detail": detail}, status=400)
    except Exception as e:
        return JsonResponse({"error": "Unexpected error while analyzing URL", "detail": str(e)}, status=500)

    formats_data = []
    for f in info.get("formats", []):
        if not f.get("url"):
            continue
        fmt_type = "audio" if f.get("vcodec") == "none" else ("video" if f.get("acodec") == "none" else "video+audio")
        formats_data.append(
            {
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "resolution": f.get("format_note") or f"{f.get('width', '')}x{f.get('height', '')}",
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "fps": f.get("fps"),
                "tbr": f.get("tbr"),
                "vcodec": f.get("vcodec"),
                "acodec": f.get("acodec"),
                "type": fmt_type,
            }
        )

    response_data = {
        "id": info.get("id"),
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "channel": info.get("channel"),
        "webpage_url": info.get("webpage_url", url),
        "formats": formats_data,
    }

    return JsonResponse(response_data)


@csrf_exempt
@require_GET
def download_format(request):
    url = request.GET.get("url")
    format_id = request.GET.get("format_id")
    custom_filename = request.GET.get("filename")  # e.g. "my_video.mp4" or "my_video"
    subfolder = request.GET.get("subfolder")  # e.g. "music", "movies"

    if not url or not _is_valid_url(url):
        return JsonResponse({"error": "Invalid or missing URL"}, status=400)
    if not format_id:
        return JsonResponse({"error": "Missing format_id"}, status=400)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    videos_dir = os.path.join(base_dir, "videos")

    if subfolder:
        safe_subfolder = subfolder.replace("/", "").replace("\\", "")
        videos_dir = os.path.join(videos_dir, safe_subfolder)

    os.makedirs(videos_dir, exist_ok=True)

    if custom_filename:
        safe_name = custom_filename.replace("/", "").replace("\\", "")
        if "." in safe_name:
            outtmpl = os.path.join(videos_dir, safe_name)
        else:
            outtmpl = os.path.join(videos_dir, f"{safe_name}.%(ext)s")
    else:
        outtmpl = os.path.join(videos_dir, "%(title)s.%(ext)s")

    ydl_opts = {
        "format": format_id,
        "outtmpl": outtmpl,
        "quiet": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_path = ydl.prepare_filename(info)
    except yt_dlp.utils.DownloadError as e:
        return JsonResponse({"error": "Failed to download video", "detail": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": "Unexpected error while downloading", "detail": str(e)}, status=500)

    if not os.path.exists(downloaded_path):
        return JsonResponse({"error": "Downloaded file not found on server"}, status=500)

    filename = os.path.basename(downloaded_path)

    response = FileResponse(open(downloaded_path, "rb"), as_attachment=True, filename=filename)

    return response


# POST http://127.0.0.1:8000/api/analyze/
# Content-Type: application/json

# {
#   "url": "https://www.youtube.com/watch?v=H5FAxTBuNM8"
# }


# download
# Method: GET
# URL: http://127.0.0.1:8000/api/download/
# Params:
# url = https://www.youtube.com/watch?v=H5FAxTBuNM8
# format_id = 95  //chack format id from analyze api


# run 
# python manage.py runserver 8000