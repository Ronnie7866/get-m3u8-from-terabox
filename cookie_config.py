import time
import logging
import requests
import threading
from typing import List

from config import (GITHUB_REPO_OWNER, GITHUB_REPO_NAME, GITHUB_COOKIE_PATH, GITHUB_TOKEN,
                    PREMIUM_COOKIE_PATH, DM_COOKIE_PATH, COOKIES)
# Setup logger
logger = logging.getLogger('cookie_manager')

class GithubCookieManager:
    def __init__(self, repo_owner, repo_name, token=None):
        """
        Initialize the GitHub cookie manager
        
        Args:
            repo_owner: GitHub username who owns the repository
            repo_name: Name of the repository
            token: Optional GitHub personal access token for private repos
        """
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.token = token
        
        self.cookies = []
        self.current_cookie_index = 0
        
        self.premium_cookies = []
        self.current_premium_cookie_index = 0
        
        self.dm_cookies = []
        self.current_dm_cookie_index = 0

        self.last_fetch_times = {
            GITHUB_COOKIE_PATH: 0,
            PREMIUM_COOKIE_PATH: 0,
            DM_COOKIE_PATH: 0
        }
        
        self.fetch_interval = 900  # Check GitHub every 15 minutes
        self.validation_interval = 1800  # Validate cookies every 30 minutes
        self.last_validation_time = 0
        self.validation_running = False
        
        # Headers for GitHub API
        self.headers = {
            "Accept": "application/vnd.github.v3.raw",
            "User-Agent": "TeraBox-Cookie-Fetcher"
        }
        
        if token:
            self.headers["Authorization"] = f"token {token}"
        
        # Initial load of multiple cookies from config
        self.initialize_cookies()

        # Start background validation task
        self.start_validation_task()
    
    def _fetch_cookies_from_path(self, file_path: str) -> List[str]:
        """
        Fetch cookies from a specific file path in the GitHub repository.
        
        Args:
            file_path: The path to the cookie file in the repository.
            
        Returns:
            A list of cookie strings.
        """
        cookies = []
        raw_url = f"https://raw.githubusercontent.com/{self.repo_owner}/{self.repo_name}/main/{file_path}"
        
        try:
            logger.info(f"Fetching cookies from GitHub: {raw_url}")
            response = requests.get(raw_url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                content = response.text.strip()
                cookie_lines = content.split('\n')
                
                for line in cookie_lines:
                    line = line.strip()
                    if line and "ndus=" in line:
                        if line not in cookies:
                            cookies.append(line)
                
                if cookies:
                    logger.info(f"Successfully fetched {len(cookies)} cookies from {file_path}")
                    self.last_fetch_times[file_path] = time.time()
                else:
                    logger.warning(f"No valid cookies found in {file_path}")
            else:
                logger.error(f"Failed to fetch {file_path}. Status code: {response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching {file_path} from GitHub: {str(e)}")
            
        return cookies

    def initialize_cookies(self):
        """Initialize cookies from config and/or GitHub"""
        # Fetch regular, premium, and DM cookies from GitHub
        self.cookies = self._fetch_cookies_from_path(GITHUB_COOKIE_PATH)
        self.premium_cookies = self._fetch_cookies_from_path(PREMIUM_COOKIE_PATH)
        self.dm_cookies = self._fetch_cookies_from_path(DM_COOKIE_PATH)

        # Add cookies from config as a fallback for regular cookies
        if hasattr(COOKIES, '__iter__') and not isinstance(COOKIES, str):
            for cookie in COOKIES:
                if cookie and "ndus=" in cookie and cookie not in self.cookies:
                    self.cookies.append(cookie)

        # If no cookies were found, but we have COOKIES, use the first one
        if not self.cookies and COOKIES and len(COOKIES) > 0:
            self.cookies.append(COOKIES[0])

        logger.info(f"Initialized {len(self.cookies)} regular, {len(self.premium_cookies)} premium, and {len(self.dm_cookies)} DM cookies.")

    def get_cookie(self) -> str:
        """
        Get the next regular cookie in round-robin fashion.
        
        Returns:
            The cookie string.
        """
        current_time = time.time()
        
        if current_time - self.last_fetch_times.get(GITHUB_COOKIE_PATH, 0) > self.fetch_interval:
            github_cookies = self._fetch_cookies_from_path(GITHUB_COOKIE_PATH)
            new_cookies_added = 0
            
            for github_cookie in github_cookies:
                if github_cookie and github_cookie not in self.cookies:
                    self.cookies.append(github_cookie)
                    new_cookies_added += 1
            
            if new_cookies_added > 0:
                logger.info(f"Added {new_cookies_added} new regular cookies, total: {len(self.cookies)}")
        
        if not self.cookies:
            logger.error("No valid regular cookies available")
            return ""
        
        cookie = self.cookies[self.current_cookie_index]
        self.current_cookie_index = (self.current_cookie_index + 1) % len(self.cookies)
        
        masked_cookie = cookie[:30] + "..." if len(cookie) > 30 else cookie
        logger.info(f"Using regular cookie #{self.current_cookie_index}/{len(self.cookies)}: {masked_cookie}")
        
        return cookie

    def get_premium_cookie(self) -> str:
        """
        Get the next premium cookie in round-robin fashion.

        Returns:
            The premium cookie string.
        """
        current_time = time.time()

        if current_time - self.last_fetch_times.get(PREMIUM_COOKIE_PATH, 0) > self.fetch_interval:
            premium_cookies = self._fetch_cookies_from_path(PREMIUM_COOKIE_PATH)
            new_premium_cookies_added = 0

            for premium_cookie in premium_cookies:
                if premium_cookie and premium_cookie not in self.premium_cookies:
                    self.premium_cookies.append(premium_cookie)
                    new_premium_cookies_added += 1

            if new_premium_cookies_added > 0:
                logger.info(f"Added {new_premium_cookies_added} new premium cookies, total: {len(self.premium_cookies)}")

        if not self.premium_cookies:
            logger.error("No valid premium cookies available")
            return ""

        cookie = self.premium_cookies[self.current_premium_cookie_index]
        self.current_premium_cookie_index = (self.current_premium_cookie_index + 1) % len(self.premium_cookies)

        masked_cookie = cookie[:30] + "..." if len(cookie) > 30 else cookie
        logger.info(f"Using premium cookie #{self.current_premium_cookie_index}/{len(self.premium_cookies)}: {masked_cookie}")

        return cookie

    def get_next_dm_cookie_with_retry(self):
        current_time = time.time()

        # Check if we need to refresh DM cookies
        if current_time - self.last_fetch_times.get(DM_COOKIE_PATH, 0) > self.fetch_interval:
            dm_cookies = self._fetch_cookies_from_path(DM_COOKIE_PATH)
            new_dm_cookies_added = 0

            for dm_cookie in dm_cookies:
                if dm_cookie and dm_cookie not in self.dm_cookies:
                    self.dm_cookies.append(dm_cookie)
                    new_dm_cookies_added += 1

            if new_dm_cookies_added > 0:
                logger.info(f"Added {new_dm_cookies_added} new DM cookies, total: {len(self.dm_cookies)}")

        if not self.dm_cookies:
            logger.error("No DM cookies available.")
            return None, None

        cookie_index_to_try = self.current_dm_cookie_index
        cookie = self.dm_cookies[cookie_index_to_try]

        # Move to the next index for the subsequent call
        self.current_dm_cookie_index = (self.current_dm_cookie_index + 1) % len(self.dm_cookies)

        return cookie, cookie_index_to_try

    def force_refresh(self):
        """
        Force a refresh of all cookies from GitHub.
        """
        logger.info("Forcing refresh of all cookies from GitHub")
        self.initialize_cookies()
        logger.info(f"After force refresh, {len(self.cookies)} regular, {len(self.premium_cookies)} premium, and {len(self.dm_cookies)} DM cookies loaded.")

    def force_refresh_dm_cookies(self):
        """
        Force a refresh of DM cookies from GitHub.
        """
        logger.info("Forcing refresh of DM cookies from GitHub")
        old_count = len(self.dm_cookies)
        self.dm_cookies = self._fetch_cookies_from_path(DM_COOKIE_PATH)
        logger.info(f"DM cookies refreshed: {old_count} -> {len(self.dm_cookies)}")

        # Reset the index if it's out of bounds
        if self.current_dm_cookie_index >= len(self.dm_cookies):
            self.current_dm_cookie_index = 0

    def validate_cookie(self, cookie: str) -> bool:
        """
        Validate a single cookie by testing if it can get a dlink.

        Args:
            cookie: The cookie string to validate.

        Returns:
            True if cookie is valid, False otherwise.
        """
        try:
            test_url = "https://www.1024tera.com/sharing/link?surl=CGCs3R1E3fxFW7OcaxLPEA"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
                'Cookie': cookie,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            response = requests.get(test_url, headers=headers, timeout=10, allow_redirects=True)
            if "login" in response.text.lower() and "password" in response.text.lower():
                return False
            if "dlink" in response.text or "download" in response.text.lower():
                return True
            return False
        except Exception as e:
            logger.warning(f"Cookie validation failed: {str(e)}")
            return False

    def validate_all_cookies(self):
        """
        Validate all types of cookies and remove invalid ones.
        """
        if self.validation_running:
            return
        self.validation_running = True
        logger.info("Starting cookie validation...")

        try:
            # Validate regular cookies
            valid_cookies = [c for c in self.cookies if self.validate_cookie(c)]
            removed_count = len(self.cookies) - len(valid_cookies)
            if removed_count > 0:
                logger.warning(f"Removed {removed_count} invalid regular cookies.")
            self.cookies = valid_cookies
            if self.current_cookie_index >= len(self.cookies):
                self.current_cookie_index = 0

            # Validate premium cookies
            valid_premium_cookies = [c for c in self.premium_cookies if self.validate_cookie(c)]
            removed_premium_count = len(self.premium_cookies) - len(valid_premium_cookies)
            if removed_premium_count > 0:
                logger.warning(f"Removed {removed_premium_count} invalid premium cookies.")
            self.premium_cookies = valid_premium_cookies
            if self.current_premium_cookie_index >= len(self.premium_cookies):
                self.current_premium_cookie_index = 0
                
            # Validate DM cookies
            valid_dm_cookies = [c for c in self.dm_cookies if self.validate_cookie(c)]
            removed_dm_count = len(self.dm_cookies) - len(valid_dm_cookies)
            if removed_dm_count > 0:
                logger.warning(f"Removed {removed_dm_count} invalid DM cookies.")
            self.dm_cookies = valid_dm_cookies
            if self.current_dm_cookie_index >= len(self.dm_cookies):
                self.current_dm_cookie_index = 0

            logger.info("Cookie validation complete.")
            logger.info(f"Remaining: {len(self.cookies)} regular, {len(self.premium_cookies)} premium, {len(self.dm_cookies)} DM cookies.")
            self.last_validation_time = time.time()
        except Exception as e:
            logger.error(f"Error during cookie validation: {str(e)}")
        finally:
            self.validation_running = False

    def start_validation_task(self):
        """
        Start the background validation task.
        """
        def validation_loop():
            while True:
                try:
                    current_time = time.time()
                    if current_time - self.last_validation_time > self.validation_interval:
                        self.validate_all_cookies()
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"Error in validation loop: {str(e)}")
                    time.sleep(60)

        validation_thread = threading.Thread(target=validation_loop, daemon=True)
        validation_thread.start()
        logger.info("Cookie validation task started (runs every 30 minutes)")

# Create a singleton instance
cookie_manager = GithubCookieManager(
    repo_owner=GITHUB_REPO_OWNER,
    repo_name=GITHUB_REPO_NAME,
    token=GITHUB_TOKEN
)
