"""
YouTube Transcript API service.

Give it a video ID -> returns the transcript as JSON.
Designed to be called from n8n's HTTP Request node.

It does NOT download the video. It only fetches the caption data,
so it stays light on a VM.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

load_dotenv()

# Set up logging (reads LOG_LEVEL / LOG_RETENTION_DAYS / LOG_DIR from env).
from logging_config import setup_logging

logger = setup_logging()

app = FastAPI(title="YouTube Transcript API")


def build_client() -> YouTubeTranscriptApi:
    """
    Build the transcript client.

    If ALL four proxy variables are set in the environment, route requests
    through that proxy. Otherwise, connect directly using the server's own IP.

        PROXY_IP=geo.iproyal.com
        PROXY_PORT=12321
        PROXY_USER=your_user
        PROXY_PASS=your_pass
    """
    proxy_ip = os.getenv("PROXY_IP")
    proxy_port = os.getenv("PROXY_PORT")
    proxy_user = os.getenv("PROXY_USER")
    proxy_pass = os.getenv("PROXY_PASS")

    # Use the proxy only when all four values are present.
    if proxy_ip and proxy_port and proxy_user and proxy_pass:
        proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_ip}:{proxy_port}"
        logger.info("Proxy loaded -> using %s:%s", proxy_ip, proxy_port)
        from youtube_transcript_api.proxies import GenericProxyConfig
        return YouTubeTranscriptApi(
            proxy_config=GenericProxyConfig(
                http_url=proxy_url,
                https_url=proxy_url,
            )
        )

    logger.info("No proxy set -> connecting directly with the server IP")
    return YouTubeTranscriptApi()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/transcript/{video_id}")
def get_transcript(
    video_id: str,
    lang: str = Query(
        "en",
        description="Comma-separated language priority, e.g. 'en' or 'en,ur,de'",
    ),
):
    languages = [code.strip() for code in lang.split(",") if code.strip()]

    logger.info("Transcript requested | video_id=%s | languages=%s", video_id, languages)

    try:
        client = build_client()
        fetched = client.fetch(video_id, languages=languages)
    except TranscriptsDisabled:
        logger.warning("Transcripts disabled | video_id=%s", video_id)
        raise HTTPException(status_code=404, detail="Transcripts are disabled for this video.")
    except NoTranscriptFound:
        logger.warning("No transcript found | video_id=%s | languages=%s", video_id, languages)
        raise HTTPException(
            status_code=404,
            detail=f"No transcript found for languages: {languages}",
        )
    except VideoUnavailable:
        logger.warning("Video unavailable | video_id=%s", video_id)
        raise HTTPException(status_code=404, detail="Video is unavailable.")
    except Exception as e:
        # logger.exception() records the full traceback to error.log too.
        # Most commonly this is an IP block when running on a VM.
        logger.exception("Failed to fetch transcript | video_id=%s", video_id)
        raise HTTPException(status_code=502, detail=f"Failed to fetch transcript: {e}")

    segments = fetched.to_raw_data()  # list of {text, start, duration}
    full_text = " ".join(seg["text"] for seg in segments)

    logger.info(
        "Transcript OK | video_id=%s | lang=%s | segments=%d",
        video_id,
        fetched.language_code,
        len(segments),
    )

    return {
        "video_id": video_id,
        "language": fetched.language,
        "language_code": fetched.language_code,
        "is_generated": fetched.is_generated,
        "text": full_text,
        "segments": segments,
    }