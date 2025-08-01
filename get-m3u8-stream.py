import time
import urllib.parse
import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from logger_config import setup_logger
from cookie_config import cookie_manager

log = setup_logger("get-m3u8-stream")

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="TeraBox Streaming API",
    description="API to extract streaming URLs from TeraBox share links",
    version="1.0.0"
)

# Add rate limiting state and exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Define allowed origins for CORS
allowed_origins = [
    "https://player.teraboxdl.site",
]

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

@app.get("/get_m3u8_stream_fast/{stream_url:path}")
@limiter.limit("5/minute")
async def get_m3u8_stream_fast(request: Request, stream_url: str):
    # Referer check to ensure requests come from the player domain
    referer = request.headers.get("referer")
    if not referer or not referer.startswith("https://player.teraboxdl.site"):
        log.warning(f"Forbidden request from referer: {referer}")
        raise HTTPException(status_code=403, detail="Forbidden: Invalid referer")

    try:
        log.info(f"Stream URL received from a valid referer: {stream_url}")

        decoded_stream_url = urllib.parse.unquote(stream_url)
        if "dm.1024tera.com/share/streaming" not in decoded_stream_url and "1024tera.com/share/streaming" not in decoded_stream_url:
            log.warning(f"Invalid stream URL format: {decoded_stream_url}")
            raise HTTPException(status_code=400, detail="Invalid stream URL format. Expected a TeraBox streaming URL.")

        for i in range(len(cookie_manager.dm_cookies)):
            cookie, cookie_index = cookie_manager.get_next_dm_cookie_with_retry()
            if not cookie:
                log.error("No valid cookies available")
                raise HTTPException(status_code=401, detail="No valid cookies available")

            masked_cookie = cookie
            log.info(f"Attempting with cookie #{cookie_index + 1}/{len(cookie_manager.dm_cookies)}: {masked_cookie}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.terabox.app/',
                'Origin': 'https://www.terabox.app',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Cookie': cookie
            }

            response = robust_get(decoded_stream_url, headers=headers)

            if response.status_code == 200:
                content = response.text
                if content.strip().startswith('#EXTM3U'):
                    log.info(f"Successfully fetched M3U8 content with cookie #{cookie_index + 1}")
                    return Response(
                        content=content,
                        media_type="application/vnd.apple.mpegurl"
                    )
                else:
                    # Check if the error indicates invalid file ID - if so, stop trying other cookies
                    # TeraBox returns errno:2 with various show_msg values for invalid files
                    if ('"errno":2' in content and
                        ('"show_msg":"fid is invalid"' in content or
                         '"show_msg":"invalid type"' in content or
                         '"fid is invalid"' in content)):
                        log.error(f"File ID is invalid (errno:2) - stopping cookie rotation. Content: {content[:200]}")
                        raise HTTPException(status_code=400, detail="Invalid file ID. The requested file does not exist or is not accessible.")

                    log.warning(f"Invalid M3U8 content with cookie #{cookie_index + 1}, trying next. Content: {content[:200]}")
            else:
                log.warning(f"Stream request failed with cookie #{cookie_index + 1}, status {response.status_code}, trying next cookie.")

        log.error("All cookies failed to fetch the stream")
        raise HTTPException(status_code=401, detail="All available cookies failed to fetch the stream.")

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Unexpected error in get_m3u8_stream_fast: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cookie-status")
async def get_cookie_status():
    """Get the current status of all cookies"""
    return {
        "regular_cookies": len(cookie_manager.cookies),
        "premium_cookies": len(cookie_manager.premium_cookies),
        "dm_cookies": len(cookie_manager.dm_cookies),
        "current_dm_index": cookie_manager.current_dm_cookie_index,
        "last_fetch_times": {
            "regular": cookie_manager.last_fetch_times.get("cookies.txt", 0),
            "premium": cookie_manager.last_fetch_times.get("cookiesPremium.txt", 0),
            "dm": cookie_manager.last_fetch_times.get("cookiesDM.txt", 0)
        }
    }

@app.post("/refresh-dm-cookies")
async def refresh_dm_cookies():
    """Force refresh DM cookies from GitHub"""
    try:
        cookie_manager.force_refresh_dm_cookies()
        return {
            "status": "success",
            "dm_cookies_count": len(cookie_manager.dm_cookies),
            "message": "DM cookies refreshed successfully"
        }
    except Exception as e:
        log.error(f"Error refreshing DM cookies: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh DM cookies: {str(e)}")

def robust_get(*args, retries=3, backoff=2, **kwargs):
    for attempt in range(retries):
        try:
            return requests.get(*args, **kwargs)
        except requests.exceptions.ConnectionError as e:
            if attempt == retries - 1:
                raise
            time.sleep(backoff ** attempt)

def main():
    uvicorn.run("get-m3u8-stream:app", host="0.0.0.0", port=8080, reload=True)


if __name__ == "__main__":
    main()
