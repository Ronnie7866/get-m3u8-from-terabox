import re
import time
import urllib.parse
from typing import Optional, Dict

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from get_m3u8_stream_fast import get_m3u8_fast_stream
from logger_config import setup_logger
from cookie_config import cookie_manager

log = setup_logger("get-m3u8-stream")

app = FastAPI(
    title="TeraBox Streaming API",
    description="API to extract streaming URLs from TeraBox share links",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://player.teraboxdl.site",  # Your player domain
        "http://player.teraboxdl.site",   # In case HTTP is used
        "https://www.teraboxdl.site",     # Main site
        "http://www.teraboxdl.site",
        "https://teraboxdl.site",
        "http://teraboxdl.site",
        "http://localhost",               # For local development
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],  # Specify the HTTP methods you need
    allow_headers=["*"],                       # Allow all headers
    expose_headers=["*"],                      # Expose all headers
    max_age=3600,                             # Cache preflight requests for 1 hour
)

# Video cache to track saved videos and avoid re-saving
video_cache = {}

# Clean up old video cache entries (older than 6 hours)
def cleanup_video_cache():
    current_time = time.time()
    to_remove = [url_hash for url_hash, (_, timestamp) in video_cache.items()
                 if current_time - timestamp > 21600]  # 6 hours
    for url_hash in to_remove:
        del video_cache[url_hash]
        log.info(f"Cleaned up cached video entry: {url_hash}")

def get_url_hash(url: str) -> str:
    """Generate a hash for the URL to use as cache key"""
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()

def is_video_cached(url: str) -> tuple[bool, Optional[str]]:
    """Check if video is already saved and return filename if cached"""
    cleanup_video_cache()
    url_hash = get_url_hash(url)
    if url_hash in video_cache:
        filename, _ = video_cache[url_hash]
        log.info(f"Video found in cache: {filename}")
        return True, filename
    return False, None

def cache_video(url: str, filename: str):
    """Cache the video filename for this URL"""
    url_hash = get_url_hash(url)
    video_cache[url_hash] = (filename, time.time())
    log.info(f"Cached video: {filename} for URL hash: {url_hash}")

# Response models
class ErrorResponse(BaseModel):
    error: str

class CookieUpdateRequest(BaseModel):
    cookie_data: str

class CookieUpdateResponse(BaseModel):
    success: bool
    message: str

# Define the cookie string from the successful curl command
COOKIE_STRING = (
    "browserid=nxk3JtCDsYjPBd3IRAeZafvjnxE3gG9r08eS0BEx4gFNEosSiGBOmPmzNf5Fw9Zd_jH2EvbcG5wNCCRY; "
    "lang=en; "
    "TSID=yBaW7pVuFDtJBFfrxUpRaf2Pb8VH1Pv3; "
    "__bid_n=195cc23abf820742fe4207; "
    "_ga=GA1.1.245945211.1742886652; "
    "PANWEB=1; "
    "csrfToken=_IX8ieIPIAVktV8pn8E3wbz9; "
    "ndus=YVyeg3HteHui15K1RdVGWbvhLeCtMVM67bWoCFGT; "
    "ndut_fmt=4317435892BF06900004C6FA708C14491A37BC0D9E569E8663175C44D1821B4A; "
    "ab_sr=1.0.1_YzIxMGVmZDI0ZjE1ODgzMDU2NjExZDYzMTdlODY2NmQ0ZDQ2ZGE0ZGUzMGVhODBlOTBmNTFiNThhZmE2YWVlZWU3OWQzMDY4N2I0NmNmNWVjMmRkZjg5MWViMmU2ZWYyMjdjYWZkN2Q0MWFlZjZlNDlmZDk2YzM3OTUyYTMzZGFjZjkxYzc3MTJkMDYwYTUwODVmMWY4NzJjNjljOGJkMg==; "
    "_ga_06ZNKL8C2E=GS1.1.1744481055.25.1.1744481106.9.0.0"
)

# Parse cookies into a dictionary
COOKIES = {k.strip(): v.strip() for k, v in (cookie.split('=', 1) for cookie in COOKIE_STRING.split('; '))}

# Default headers for HTTP requests
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'sec-ch-ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"'
}

import json

# Helper functions for save_terabox_video
def find_between(text: str, first: str, last: str) -> str:
    """Extract a substring between two markers."""
    try:
        start = text.index(first) + len(first)
        end = text.index(last, start)
        return text[start:end]
    except ValueError:
        return ""

def extract_surl_from_url(url: str) -> str | None:
    """
    Extracts the complete surl from a Terabox URL.
    Handles various URL formats including direct shares and embed links.
    If surl starts with '1', removes it.
    """
    try:
        # Remove leading '1' if present
        if url.startswith('1'):
            url = url[1:]

        # First try to get surl from query parameters (embed URLs)
        parsed_url = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        if 'surl' in query_params:
            surl = query_params['surl'][0]
            # Remove leading '1' from surl if present
            if surl.startswith('1'):
                surl = surl[1:]
            log.info(f"Extracted surl from query params: {surl}")
            return surl

        # Then try to extract from path (direct share URLs)
        path_match = re.search(r"/s/([A-Za-z0-9_-]+)", url)
        if path_match:
            surl = path_match.group(1)
            # Remove leading '1' from surl if present
            if surl.startswith('1'):
                surl = surl[1:]
            log.info(f"Extracted surl from path: {surl}")
            return surl

        # Try to extract URLs that are just the code or already in surl format
        direct_match = re.search(r"([A-Za-z0-9_-]+)", url)
        if direct_match:
            surl = direct_match.group(0)
            # Remove leading '1' from surl if present
            if surl.startswith('1'):
                surl = surl[1:]
            log.info(f"Extracted surl from direct format: {surl}")
            return surl

        log.warning(f"No surl found in URL: {url}")
        return None
    except Exception as e:
        log.error(f"Error in extract_surl_from_url: {str(e)}")
        return None

def save_terabox_video(session: requests.Session, url: str, target_path: str = "/") -> bool:
    """
    Saves a single video from a shared TeraBox URL to your TeraBox storage.

    :param session: A requests.Session object with authentication cookies set.
    :param url: The shared TeraBox URL pointing to a single video.
    :param target_path: The path in your TeraBox storage where the video will be saved (default is root "/").
    :return: True if the video is saved successfully, False otherwise.
    """
    try:
        # Step 1: GET the URL to extract jsToken and logid
        response = session.get(url)
        response.raise_for_status()  # Ensure the request succeeded
        text = response.text
        js_token = find_between(text, 'fn%28%22', '%22%29')
        if not js_token:
            log.error("Could not extract jsToken")
            return False
        logid = find_between(text, 'dp-logid=', '&')
        if not logid:
            log.error("Could not extract dp-logid")
            return False

        # Step 2: Extract surl from the URL
        surl = extract_surl_from_url(url)
        if not surl:
            log.error("Could not extract surl from URL")
            return False

        # Step 3: GET /share/list to get the video's fs_id, share_id, and uk
        list_url = (
            f"https://www.terabox.app/share/list?app_id=250528&web=1&channel=0&"
            f"jsToken={js_token}&dp-logid={logid}&page=1&num=1000&by=name&order=asc&"
            f"site_referer=&shorturl={surl}&root=1"
        )
        response = session.get(list_url)
        response.raise_for_status()
        r_j = response.json()
        if r_j.get("errno") != 0:
            log.error(f"Failed to get file list: {r_j}")
            return False

        file_list = r_j.get("list", [])
        if not file_list:
            log.error("No files found in the shared link")
            return False
        if len(file_list) > 1:
            log.error("URL points to multiple files; expected a single video")
            return False
        item = file_list[0]
        if item.get("isdir") == "1":
            log.error("URL points to a folder, not a single video")
            return False

        fs_id = str(item.get("fs_id", ""))
        if not fs_id:
            log.error("Could not extract fs_id")
            return False
        share_id = str(r_j.get("share_id", ""))
        uk = str(r_j.get("uk", ""))

        # Step 4: POST to /share/transfer to save the video
        transfer_url = (
            f"https://www.terabox.app/share/transfer?"
            f"app_id=250528&web=1&channel=dubox&clienttype=0&"
            f"jsToken={js_token}&dp-logid={logid}&"
            f"ondup=newcopy&async=1&scene=purchased_list&"
            f"shareid={share_id}&from={uk}"
        )
        payload = {
            "fsidlist": json.dumps([fs_id]),
            "path": target_path
        }
        response = session.post(transfer_url, data=payload)
        response.raise_for_status()
        result = response.json()
        if result.get("errno") == 0:
            log.info(f"Successfully saved video to {target_path}")
            return True
        else:
            log.error(f"Failed to save video: {result}")
            return False

    except requests.RequestException as e:
        log.error(f"Network error occurred: {e}")
        return False
    except Exception as e:
        log.error(f"Unexpected error in save_terabox_video: {e}")
        return False

# Initialize a session object
session = requests.Session()
session.cookies.update(COOKIES)
session.headers.update(DEFAULT_HEADERS)

async def get_filename_from_terabox_url(url: str) -> Optional[str]:
    """
    Extract filename from a TeraBox sharing URL by parsing HTML content

    Args:
        url: TeraBox sharing URL

    Returns:
        The extracted filename or None if not found
    """
    try:
        # Fetch the webpage content
        response = requests.get(url, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        html_content = response.text

        # Method 1: Extract filename from <title> tag
        title_match = re.search(r'<title>(.*?)</title>', html_content, re.DOTALL)
        if title_match:
            title = title_match.group(1)  # e.g., "Dhoom_Dhaam_(2025)_...mkv - Share Files Online..."
            parts = title.split(' - ', 1)  # Split only on first occurrence
            if parts and parts[0]:
                filename = parts[0].strip()
                if filename:  # Ensure it's not empty
                    log.info(f"Found filename from title: {filename}")
                    return filename

        # Method 2: Fallback to meta description
        desc_match = re.search(r'<meta name="description" content="(.*?)">', html_content)
        if desc_match:
            desc = desc_match.group(1)  # e.g., "Dhoom_Dhaam_(2025)_...mkv - Please input..."
            parts = desc.split(' - ', 1)
            if parts and parts[0]:
                filename = parts[0].strip()
                if filename:
                    log.info(f"Found filename from meta description: {filename}")
                    return "/" + filename

        log.warning("Could not find filename in title or meta description")
        return None

    except requests.RequestException as e:
        log.error(f"Error retrieving the page: {e}")
        return None
    except Exception as e:
        log.error(f"Error parsing the page: {e}")
        return None

async def get_streaming_content(video_filename: str, resolution: str) -> Optional[str]:
    """
    Get M3U8 streaming content directly from TeraBox API
    Returns either a direct M3U8 URL or the M3U8 content as a string
    """
    url = "https://www.1024terabox.com/api/streaming"
    if not video_filename.startswith('/'):
        video_filename = '/' + video_filename
    params = {
        'path': video_filename,
        'app_id': '250528',
        'clienttype': '0',
        'type': f'M3U8_AUTO_{resolution}',
        'vip': '1'
    }
    encoded_path = urllib.parse.quote(video_filename)
    headers = DEFAULT_HEADERS.copy()
    headers['Referer'] = f"https://www.1024terabox.com/play/video?path={encoded_path}&t=-1"

    response = robust_get(url, params=params, headers=headers, cookies=COOKIES)
    response.raise_for_status()

    if response.headers.get('content-type', '').startswith('application/json'):
        data = response.json()
        if "m3u8" in data:
            log.info(f"Retrieved M3U8 URL: {data['m3u8']}")
            return data["m3u8"]
        else:
            log.warning(f"No 'm3u8' in JSON: {data}")
            return None
    elif response.text.startswith("#EXTM3U"):
        log.info("Retrieved M3U8 content directly")
        return response.text  # Return M3U8 content directly instead of storing with token
    else:
        log.warning(f"Unexpected response format: {response.text[:100]}...")
        return None


@app.get("/get_m3u8")
async def get_m3u8(
        url: str = Query(..., description="TeraBox sharing URL"),
        quality: str = Query("720", description="Desired quality (360, 480, 720, 1080)"),
        target_path: str = Query("/", description="Target path in TeraBox storage to save the file")
):
    try:
        # Step 1: Check if video is already cached (smart caching)
        is_cached, cached_filename = is_video_cached(url)

        if is_cached:
            log.info(f"Using cached video: {cached_filename}")
            video_filename = cached_filename
        else:
            # Step 1a: Save the video to TeraBox (only if not cached)
            log.info("Video not in cache, saving to TeraBox...")
            save_success = save_terabox_video(session, url, target_path)
            if not save_success:
                raise HTTPException(status_code=500, detail="Failed to save video to TeraBox")

            # Step 1b: Extract the filename from the TeraBox URL
            video_filename = await get_filename_from_terabox_url(url)
            if not video_filename:
                raise HTTPException(status_code=404, detail="Could not extract filename from TeraBox URL")

            # Cache the video for future requests
            cache_video(url, video_filename)

        # Step 2: Get the M3U8 streaming content directly
        stream_content = await get_streaming_content(video_filename, quality)
        if not stream_content:
            raise HTTPException(status_code=404, detail="Could not retrieve streaming content")

        # Step 3: Return M3U8 content directly with proper headers
        if stream_content.startswith("#EXTM3U"):
            # Return M3U8 content directly
            return Response(
                content=stream_content,
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                }
            )
        else:
            # It's a URL, return JSON response for compatibility
            return {"m3u8_url": stream_content, "filename": video_filename, "quality": quality}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint to verify API status"""
    return {"status": "healthy", "version": "1.0.0"}

@app.get("/refresh_cookies")
async def refresh_cookies():
    """Force refresh cookies from GitHub repository for get_m3u8_stream_fast only"""
    try:
        new_cookie = cookie_manager.force_refresh()
        if new_cookie:
            return {"status": "success", "message": "Cookies for get_m3u8_stream_fast refreshed successfully"}
        else:
            raise HTTPException(status_code=500, detail="No valid cookies found from GitHub")
    except Exception as e:
        log.error(f"Error refreshing cookies: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error refreshing cookies: {str(e)}")


def parse_netscape_cookie(cookie_data: str) -> Dict[str, str]:
    """
    Parse Netscape cookie format into a dictionary suitable for requests.Session.cookies
    
    Example format:
    # Netscape HTTP Cookie File
    # http://curl.haxx.se/rfc/cookie_spec.html
    # This is a generated file!  Do not edit.
    
    .1024tera.com	TRUE	/	FALSE	1748070638	browserid	nxk3JtCDsYjPBd3IRAeZafvjnxE3gG9r08eS0BEx4gFNEosSiGBOmPmzNf5Fw9Zd_jH2EvbcG5wNCCRY
    
    Args:
        cookie_data: String containing cookies in Netscape format
        
    Returns:
        Dictionary mapping cookie names to values
    """
    cookie_dict = {}
    
    try:
        # Split the input data into lines
        lines = cookie_data.strip().split('\n')
        
        for line in lines:
            # Skip empty lines and comments
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Handle the tab-separated format
            # Domain, flag, path, secure, expiration, name, value
            parts = re.split(r'\s+', line)
            
            # Make sure we have enough parts for a valid cookie entry
            if len(parts) >= 7:
                domain = parts[0]
                name = parts[5]
                value = parts[6]
                
                cookie_dict[name] = value
                log.info(f"Parsed cookie: {name}={value[:10]}... for domain {domain}")
        
        log.info(f"Successfully parsed {len(cookie_dict)} cookies")
        return cookie_dict
    
    except Exception as e:
        log.error(f"Error parsing Netscape cookie format: {str(e)}")
        return {}

@app.post("/update_cookie", response_model=CookieUpdateResponse)
async def update_cookie(request: CookieUpdateRequest):
    """
    Update the cookies used for TeraBox API requests
    
    Args:
        request: Contains cookie_data in Netscape format
        
    Returns:
        Success status and message
    """
    try:
        global COOKIES
          # Parse the provided cookie data
        new_cookies = parse_netscape_cookie(request.cookie_data)
        
        if not new_cookies:
            raise HTTPException(status_code=400, detail="Failed to parse cookie data")
            
        # Update the global COOKIES dictionary
        COOKIES.update(new_cookies)
        
        # Update the session cookies
        session.cookies.update(new_cookies)
        
        log.info(f"Successfully updated cookies with {len(new_cookies)} new values")
        return {"success": True, "message": f"Successfully updated {len(new_cookies)} cookies"}
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating cookies: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating cookies: {str(e)}")


@app.get("/get_m3u8_stream_fast/{current_url:path}")
async def get_m3u8_stream_fast(current_url: str):
    try:
        decoded_url = urllib.parse.unquote(current_url)
        log.info(f"Processing URL: {decoded_url}")

        # Get the actual streaming URL from the share URL
        stream_url = await get_m3u8_fast_stream(current_url)
        if not stream_url:
            log.error("Failed to generate streaming URL")
            raise HTTPException(status_code=404, detail="Failed to generate streaming URL")

        log.info(f"Generated stream URL: {stream_url[:100]}...")  # Log truncated URL for security

        # Use fresh cookies from cookie manager
        current_cookie = cookie_manager.get_cookie()
        if not current_cookie:
            log.error("No valid cookies available")
            raise HTTPException(status_code=401, detail="No valid cookies available")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.terabox.app/',
            'Origin': 'https://www.terabox.app',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cookie': current_cookie  # Use cookie from cookie manager
        }

        # Get the M3U8 content from the stream URL (not the original URL)
        response = robust_get(stream_url, headers=headers)

        if response.status_code != 200:
            log.error(f"Stream request failed. Status: {response.status_code}, Response: {response.text[:200]}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to fetch stream. Response: {response.text[:200]}"
            )

        # Verify the content is actually M3U8
        content = response.text
        if not content.strip().startswith('#EXTM3U'):
            if "errno" in content:
                # Parse the error response
                try:
                    error_data = response.json()
                    log.error(f"TeraBox API error: {error_data}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"TeraBox API error: {error_data.get('errmsg', 'Unknown error')}"
                    )
                except ValueError:
                    pass
            log.error(f"Invalid M3U8 content received: {content[:200]}")
            raise HTTPException(status_code=400, detail="Invalid M3U8 content received")

        # Return the content with appropriate headers
        return Response(
            content=content,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            }
        )

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