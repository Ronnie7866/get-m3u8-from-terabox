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

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600, # Cache preflight requests for 1 hour
)

@app.get("/get_m3u8_stream_fast/{stream_url:path}")
@limiter.limit("5/minute")
async def get_m3u8_stream_fast(request: Request, stream_url: str):
    try:
        log.info(f"Stream URL received: {stream_url}")

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
                        media_type="application/vnd.apple.mpegurl",
                        headers={
                            "Access-Control-Allow-Origin": "*",
                            "Access-Control-Allow-Methods": "GET, OPTIONS",
                            "Access-Control-Allow-Headers": "*",
                        }
                    )
                else:
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
