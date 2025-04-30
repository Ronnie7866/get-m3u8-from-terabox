import re
import time
import urllib.parse
import uuid
from typing import Optional, Dict

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from get_m3u8_stream_fast import get_m3u8_fast_stream
from logger_config import setup_logger

log = setup_logger("get-m3u8-stream")

app = FastAPI(
    title="TeraBox Streaming API",
    description="API to extract streaming URLs from TeraBox share links",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

m3u8_storage = {}

# Clean up old entries (older than 1 hour)
def cleanup_storage():
    current_time = time.time()
    to_remove = [token for token, (content, timestamp) in m3u8_storage.items()
                 if current_time - timestamp > 3600]
    for token in to_remove:
        del m3u8_storage[token]


@app.get("/m3u8/{token}")
async def serve_m3u8(token: str):
    cleanup_storage()
    if token in m3u8_storage:
        content, _ = m3u8_storage[token]
        return PlainTextResponse(content, media_type="application/x-mpegURL")
    else:
        raise HTTPException(status_code=404, detail="M3U8 content not found")

# Response models
class StreamingResponse(BaseModel):
    m3u8_url: str
    filename: str
    quality: str

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
        parsed_url = urllib.urlparse(url)
        query_params = urllib.parse_qs(parsed_url.query)
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

async def get_streaming_url(video_filename: str, resolution: str) -> Optional[str]:
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

    response = requests.get(url, params=params, headers=headers, cookies=COOKIES)
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
        token = str(uuid.uuid4())
        m3u8_storage[token] = (response.text, time.time())
        m3u8_url = f"https://api.ronnieverse.site/m3u8/{token}"  # Update domain if different
        log.info(f"Stored M3U8 content with token: {token}")
        return m3u8_url
    else:
        log.warning(f"Unexpected response format: {response.text[:100]}...")
        return None


@app.get("/get_m3u8", response_model=StreamingResponse,
         responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_m3u8(
        url: str = Query(..., description="TeraBox sharing URL"),
        quality: str = Query("720", description="Desired quality (360, 480, 720, 1080)"),
        target_path: str = Query("/", description="Target path in TeraBox storage to save the file")
):
    try:
        # Step 1: First save the video to TeraBox
        save_success = save_terabox_video(session, url, target_path)
        if not save_success:
            raise HTTPException(status_code=500, detail="Failed to save video to TeraBox")

        # Step 2: Extract the filename from the TeraBox URL
        video_filename = await get_filename_from_terabox_url(url)
        if not video_filename:
            raise HTTPException(status_code=404, detail="Could not extract filename from TeraBox URL")

        # Step 3: Get the streaming URL
        stream_url = await get_streaming_url(video_filename, quality)
        if not stream_url:
            raise HTTPException(status_code=404, detail="Could not retrieve streaming URL")

        return {"m3u8_url": stream_url, "filename": video_filename, "quality": quality}

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
async def get_m3u8_stream_fast(current_url: str) -> str :
    """
    Get the M3U8 stream URL from a TeraBox sharing URL.

    Args:
        current_url: The TeraBox sharing URL.

    Returns:
        The M3U8 stream URL.
    """
    decode_url = urllib.parse.unquote(current_url)
    headers = {
        'sec-ch-ua-platform':'"Windows"',
        'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
        'sec-ch-ua':'"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        'sec-ch-ua-mobile':'?0',
        'accept':'*/*',
        'sec-fetch-site':'same-origin',
        'sec-fetch-mode':'cors',
        'sec-fetch-dest':'empty',
        'referer':f'{decode_url}]',
        'accept-encoding':'gzip, deflate, br, zstd',
        'accept-language':'en-GB,en-US;q=0.9,en;q=0.8',
        'priority':'u=1, i',
        'cookie':f'{COOKIE_STRING}'
    }


    stream_url_fast = await get_m3u8_fast_stream(current_url)
    if stream_url_fast:
        log.info(f"Stream URL Fast: {stream_url_fast}")
        response = requests.get(stream_url_fast, headers=headers)
        with open("response0.txt", "w", encoding="utf-8") as file:
            file.write(response.text)
            print("Response saved to response.txt")
        return stream_url_fast
    else:
        raise HTTPException(status_code=404, detail="M3U8 stream Fast URL not found")


def main():
    uvicorn.run("get-m3u8-stream:app", host="0.0.0.0", port=8080, reload=True)


if __name__ == "__main__":
    main()