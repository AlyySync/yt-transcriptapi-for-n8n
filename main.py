"""
YouTube Transcript API service.

Give it a video ID -> returns the transcript as JSON.
Designed to be called from n8n's HTTP Request node.

It does NOT download the video. It only fetches the caption data,
so it stays light on a VM.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Header, Request, Depends
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# Load variables from a .env file (if one exists) into the environment.
load_dotenv()

# Set up logging (reads LOG_LEVEL / LOG_RETENTION_DAYS / LOG_DIR from env).
from logging_config import setup_logging

logger = setup_logging()

# How many requests are allowed in a time window, e.g. "20/minute", "5/second".
# Configurable from the .env file.
RATE_LIMIT = os.getenv("RATE_LIMIT", "20/minute")

app = FastAPI(title="YouTube Transcript API")

# Rate limiter: limits are counted per client IP address.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

logger.info("Rate limit set to %s per client IP", RATE_LIMIT)


def require_api_key(x_api_key: str = Header(None)):
    """
    Reject any request that does not send the correct secret key.

    The secret lives in the .env file as API_KEY. The caller (n8n) must send
    the exact same value in the 'X-API-Key' request header.
    """
    expected = os.getenv("API_KEY")

    # Fail closed: if no key is configured on the server, block everything.
    if not expected:
        logger.critical("API_KEY is not set in the environment - rejecting all requests")
        raise HTTPException(status_code=503, detail="Server not configured: API_KEY is missing.")

    if not x_api_key or x_api_key != expected:
        logger.warning("Rejected request: missing or invalid API key")
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


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


@app.get("/transcript/{video_id}", dependencies=[Depends(require_api_key)])
@limiter.limit(RATE_LIMIT)
def get_transcript(
    request: Request,
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