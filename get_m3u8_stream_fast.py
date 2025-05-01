import asyncio
import re
import traceback
import urllib.parse
from typing import Union, List, Dict
from urllib.parse import urlparse, parse_qs
import aiohttp
import requests

from cookie_config import cookie_manager
from logger_config import setup_logger

log = setup_logger('terabox_downloader')

def get_formatted_size(size_bytes: int) -> str:
    """
    Returns a human-readable file size.
    Supports b, KB, MB, and GB units.
    """
    try:
        if size_bytes >= 1024 * 1024 * 1024:  # >= 1 GB
            size = size_bytes / (1024 * 1024 * 1024)
            unit = "GB"
        elif size_bytes >= 1024 * 1024:  # >= 1 MB
            size = size_bytes / (1024 * 1024)
            unit = "MB"
        elif size_bytes >= 1024:  # >= 1 KB
            size = size_bytes / 1024
            unit = "KB"
        else:
            size = size_bytes
            unit = "b"

        formatted_size = f"{size:.2f} {unit}"
        log.debug(f"Converted {size_bytes} bytes to {formatted_size}")
        return formatted_size
    except Exception as e:
        log.error(f"Error in get_formatted_size: {str(e)}")
        log.debug(traceback.format_exc())
        return "0 b"

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
    Extracts the surl parameter from a given URL.
    """
    try:
        # Use urllib.parse module correctly
        parsed_url = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        surl = query_params.get("surl", [])

        if surl:
            log.info(f"Extracted surl: {surl[0]}")
            return surl[0]
        else:
            log.warning(f"No surl found in URL: {url}")
            return False
    except Exception as e:
        log.error(f"Error in extract_surl_from_url: {str(e)}")
        log.debug(traceback.format_exc())
        return False

class TeraBoxExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
            "Connection": "keep-alive",
            "Cookie": cookie_manager.get_cookie(),  # Get cookie from GitHub
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        }
        self.all_files = []
        self.js_token = ""
        self.uk = ""
        self.share_id = ""

    def _get_fresh_headers(self):
        """Get headers with a fresh cookie"""
        self.headers["Cookie"] = cookie_manager.get_cookie()  # Refresh cookie from GitHub
        return self.headers

    async def extract_url_params(self, direct_link: str) -> dict:
        """
        Extract required parameters from the direct link URL
        Returns a dictionary of parameters
        """
        try:
            # Parse the URL to get query parameters
            parsed = urllib.parse.urlparse(direct_link)
            # Get the actual URL from the worker URL if present
            actual_url = urllib.parse.parse_qs(parsed.query).get('url', [None])[0] or direct_link

            # Parse the actual URL
            parsed_actual = urllib.parse.urlparse(actual_url)
            params = urllib.parse.parse_qs(parsed_actual.query)

            # Extract required parameters
            fid = params.get('fid', [''])[0].split('-')[2] if 'fid' in params else ''
            sign = params.get('sign', [''])[0].split('-')[1] if 'sign' in params else ''

            return {
                'fid': fid,
                'sign': sign,
                'timestamp': params.get('time', [''])[0],
            }
        except Exception as e:
            log.error(f"Error extracting parameters: {e}")
            return {}

    async def construct_stream_url(self, direct_link: str, uk: str, share_id: str) -> str:
        """
        Construct stream URL for a file

        Args:
            direct_link: The direct download link
            uk: The uk value from API response
            share_id: The share_id value from API response
        """
        try:
            # Extract parameters from direct link
            url_params = await self.extract_url_params(direct_link)

            stream_url = (
                f"https://www.1024tera.com/share/streaming?"
                f"uk={uk}"
                f"&shareid={share_id}"
                f"&type=M3U8_AUTO_360"
                f"&fid={url_params.get('fid', '')}"
                f"&sign={url_params.get('sign', '')}"
                f"&timestamp={url_params.get('timestamp', '')}"
                f"&jsToken={self.js_token}"
                f"&esl=1"
                f"&isplayer=1"
                f"&ehps=1"
                f"&clienttype=0"
                f"&app_id=250528"
                f"&web=1"
                f"&channel=dubox"
            )

            return stream_url
        except Exception as e:
            log.error(f"Error constructing stream URL: {e}")
            return ""


    async def process_file(self, session: aiohttp.ClientSession, file_data: Dict, shorturl: str, uk: str, share_id: str,
                           default_thumbnail: str) -> Dict:
        """Process a single file and get its download link"""
        try:
            fs_id = file_data.get("fs_id", "")
            dlink = file_data.get("dlink", "")

            if not dlink:
                raise ValueError(f"Missing dlink for file {file_data.get('server_filename')}")

            # Get direct link with a HEAD request
            async with session.head(dlink, headers=self.headers, allow_redirects=False) as response:
                direct_link = response.headers.get("location", "")

            processed_file = {
                "file_name": file_data.get("server_filename"),
                "fs_id": fs_id,
                "download_url": dlink,
                "direct_link": direct_link,
                "thumb": (
                    file_data["thumbs"].get("url3")
                    if "thumbs" in file_data
                    else default_thumbnail
                ),
                "size": get_formatted_size(int(file_data.get("size", 0))),
                "sizebytes": int(file_data.get("size", 0))
            }

            self.all_files.append(processed_file)
            return processed_file

        except Exception as e:
            log.error(f"Error processing file: {e}")
            return {"error": str(e)}

    async def get_folder_contents(self, session: aiohttp.ClientSession, shorturl: str, dir_path: str,
                                  jsToken: str, logid: str) -> List[Dict]:
        """Get contents of a folder"""
        try:
            dir_path = aiohttp.helpers.quote(dir_path)
            reqUrl = f"https://www.terabox.app/share/list?app_id=250528&web=1&channel=0&jsToken={jsToken}&dp-logid={logid}&page=1&num=1000&by=name&order=asc&site_referer=&shorturl={shorturl}&dir={dir_path}&root=0"

            async with session.get(reqUrl, headers=self.headers) as response:
                r_j = await response.json()
                log.info(f"Folder contents response for {dir_path}: {r_j}")

                if response.status != 200 or r_j.get("errno") != 0:
                    return []

                return r_j.get("list", [])
        except Exception as e:
            log.error(f"Error getting folder contents: {e}")
            return []

    async def process_folder(self, session: aiohttp.ClientSession, folder_data: Dict, shorturl: str,
                             uk: str, share_id: str, default_thumbnail: str, jsToken: str, logid: str) -> Dict:
        """Process a folder and its contents recursively"""
        folder_path = folder_data.get("path", "")
        log.info(f"Processing folder: {folder_path}")

        folder_contents = await self.get_folder_contents(session, shorturl, folder_path, jsToken, logid)

        # Process all files in the folder concurrently
        tasks = []
        for item in folder_contents:
            if str(item.get("isdir")) == "1":
                task = self.process_folder(session, item, shorturl, uk, share_id,
                                           default_thumbnail, jsToken, logid)
            else:
                task = self.process_file(session, item, shorturl, uk, share_id, default_thumbnail)
            tasks.append(task)

        # Wait for all processing to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out errors and flatten folder results
        folder_files = []
        for result in results:
            if isinstance(result, dict):
                if "files" in result:
                    folder_files.extend(result["files"])
                else:
                    folder_files.append(result)

        return {
            "folder_name": folder_data.get("server_filename"),
            "path": folder_path,
            "files": folder_files,
            "total_files": len(folder_files),
        }

    async def get_data(self, url: str) -> Union[List[Dict], Dict, bool]:
        """Main method to get data from TeraBox URL"""
        original_url = url
        share_code = None

        # Handle both teraboxapp.com and terabox.com URL formats
        if any(domain in url for domain in ['/teraboxapp.com/s/', '/terabox.com/s/']):
            match = re.search(r'/s/([A-Za-z0-9_-]+)', url)
            if match:
                share_code = match.group(1)
                # Remove leading '1' if present
                if share_code.startswith('1'):
                    share_code = share_code[1:]
                log.info(f"Extracted share code: {share_code}")

        # Try alternate domains if we have a share code
        if share_code:
            # List of domains to try
            domains = [
                f"https://www.1024tera.com/sharing/link?surl={share_code}",
                f"https://1024terabox.com/s/{share_code}",
                f"https://terabox.com/s/{share_code}",
                f"https://www.terabox.com/sharing/link?surl={share_code}"
            ]

            # Add the original URL as a fallback
            if original_url not in domains:
                domains.append(original_url)

            # Try each domain until one works
            for alt_url in domains:
                try:
                    log.info(f"Trying alternate URL: {alt_url}")
                    result = await self._fetch_data(alt_url)
                    if result:
                        return result
                except Exception as e:
                    log.warning(f"Failed with URL {alt_url}: {e}")
                    continue

            # If we get here, all attempts failed
            log.error("All domain attempts failed")
            return False

        # If no share code was extracted, try with the original URL
        return await self._fetch_data(url)

    async def _fetch_data(self, url: str) -> Union[List[Dict], Dict, bool]:
        """Internal method that does the actual data fetching"""
        async with aiohttp.ClientSession() as session:
            try:
                # Get fresh headers with updated cookie from GitHub
                headers = self._get_fresh_headers()
                log.info(f"Using cookie: {headers.get('Cookie', '')[:30]}...")

                self.all_files = []  # Reset all_files for new request

                # Initial request
                async with session.get(url, headers=headers) as response:
                    redirect_url = str(response.url)
                    text = await response.text()

                    # Check if we're getting a login page
                    if "login" in text.lower() and "password" in text.lower():
                        log.error("TeraBox is returning a login page - cookie is invalid")
                        # Force refresh the cookie from GitHub
                        cookie_manager.force_refresh()
                        return False

                default_thumbnail = find_between(text, 'og:image" content="', '"')
                logid = find_between(text, "dp-logid=", "&")
                jsToken = find_between(text, "fn%28%22", "%22%29")
                self.js_token = jsToken
                shorturl = extract_surl_from_url(redirect_url)

                if not shorturl:
                    return False

                # Get initial file/folder list with fresh headers
                reqUrl = f"https://www.terabox.app/share/list?app_id=250528&web=1&channel=0&jsToken={jsToken}&dp-logid={logid}&page=1&num=1000&by=name&order=asc&site_referer=&shorturl={shorturl}&root=1"

                async with session.get(reqUrl, headers=headers) as response:
                    r_j = await response.json()
                    if response.status != 200 or r_j.get("errno") != 0:
                        return False

                    file_list = r_j.get("list", [])
                    if not file_list:
                        return False

                    share_id = str(r_j.get("share_id", ""))
                    uk = str(r_j.get("uk", ""))
                    self.uk = uk
                    self.share_id = share_id

                    # Process all items concurrently
                    tasks = []
                    for item in file_list:
                        if item.get("isdir") == "1":
                            task = self.process_folder(session, item, shorturl, uk, share_id,
                                                       default_thumbnail, jsToken, logid)
                        else:
                            task = self.process_file(session, item, shorturl, uk, share_id,
                                                     default_thumbnail)
                        tasks.append(task)

                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Process the gathered results
                    processed_results = []
                    for result in results:
                        if isinstance(result, Exception):
                            log.error(f"Error processing item: {result}")
                            continue
                        if isinstance(result, dict):
                            if "files" in result:  # It's a folder result
                                processed_results.extend(result["files"])
                            else:  # It's a file result
                                processed_results.append(result)

                    # Standardize results
                    default_structure = {
                        "file_name": "Unknown_File",
                        "size": "Unknown_Size",
                        "thumb": default_thumbnail,
                        "dlink": None
                    }

                    standardized_results = [
                        {**default_structure, **file} for file in processed_results
                    ]

                    return {
                        "structure": standardized_results[0] if len(
                            standardized_results) == 1 else standardized_results,
                        "all_files": standardized_results,
                    }

            except Exception as e:
                log.error(f"Error in _fetch_data: {e}")
                log.debug(traceback.format_exc())
                raise  # Re-raise to allow domain fallback


async def get_m3u8_fast_stream(current_url: str) -> str:
    extractor = TeraBoxExtractor()
    try:
        # Fetch data from the TeraBox URL
        data = await extractor.get_data(current_url)
        if not data:
            log.error("Failed to fetch data from TeraBox URL")
            return None

        # Retrieve the direct link
        direct_link = data.get('structure', {}).get('direct_link')
        if not direct_link:
            log.error("Direct link not found in the response")
            return None

        # Construct the stream URL
        stream_url = await extractor.construct_stream_url(direct_link, extractor.uk, extractor.share_id)
        if stream_url:
            return stream_url
        else:
            log.error("Failed to construct stream URL")
            return None
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        return None

