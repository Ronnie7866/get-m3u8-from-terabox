import os
import time
import logging
import requests
from typing import Optional, List

GITHUB_REPO_OWNER = "Ronnie7866"
GITHUB_REPO_NAME =  "Cookie"
GITHUB_COOKIE_PATH = "teradl_I_bot-cookie.txt"
GITHUB_TOKEN = ""
COOKIES = [
    "ndus=YSsUGCpteHuiYIuaOYSrMN43qmDa5LnR-eGMk5_b",
    "ndus=YVyeg3HteHuifc4kdRSb2i79wEwfQqSwESeVmFD4",
]

# Setup logger
logger = logging.getLogger('cookie_manager')

class GithubCookieManager:
    def __init__(self, repo_owner, repo_name, file_path, token=None):
        """
        Initialize the GitHub cookie manager
        
        Args:
            repo_owner: GitHub username who owns the repository
            repo_name: Name of the repository
            file_path: Path to the cookie file in the repository
            token: Optional GitHub personal access token for private repos
        """
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.file_path = file_path
        self.token = token
        self.cookies = []  # List to hold multiple cookies
        self.current_cookie_index = 0  # Index for round-robin
        self.last_fetch_time = 0
        self.fetch_interval = 900  # Check GitHub every 15 minutes
        
        # Headers for GitHub API
        self.headers = {
            "Accept": "application/vnd.github.v3.raw",
            "User-Agent": "TeraBox-Cookie-Fetcher"
        }
        
        if token:
            self.headers["Authorization"] = f"token {token}"
        
        # URL for raw content
        self.raw_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/main/{file_path}"
        
        # Initial load of multiple cookies from config
        self.initialize_cookies()
    
    def initialize_cookies(self):
        """Initialize cookies from config and/or GitHub"""
        # Try to fetch cookies from GitHub
        github_cookies = self.fetch_from_github()
        
        # Add cookies from config
        if hasattr(COOKIES, '__iter__') and not isinstance(COOKIES, str):
            # If COOKIES is iterable (list, tuple), add all cookies
            for cookie in COOKIES:
                if cookie and "ndus=" in cookie and cookie not in self.cookies:
                    self.cookies.append(cookie)
        
        # Add GitHub cookies if valid and not already in the list
        for github_cookie in github_cookies:
            if github_cookie and github_cookie not in self.cookies:
                self.cookies.append(github_cookie)
        
        # If no cookies were found, but we have COOKIES, use the first one
        if not self.cookies and COOKIES and len(COOKIES) > 0:
            self.cookies.append(COOKIES[0])
            
        logger.info(f"Initialized {len(self.cookies)} cookies for round-robin usage")
    
    def fetch_from_github(self) -> List[str]:
        """
        Fetch cookies from GitHub
        
        Returns:
            List of cookie strings
        """
        cookies = []
        try:
            logger.info(f"Fetching cookies from GitHub: {self.raw_url}")
            response = requests.get(self.raw_url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                # Parse the content - could be one cookie per line
                content = response.text.strip()
                cookie_lines = content.split('\n')
                
                for line in cookie_lines:
                    line = line.strip()
                    # Validate each line as a cookie
                    if line and "ndus=" in line:
                        if line not in cookies:
                            cookies.append(line)
                
                if cookies:
                    logger.info(f"Successfully fetched {len(cookies)} cookies from GitHub")
                    self.last_fetch_time = time.time()
                else:
                    logger.error("No valid cookies found in GitHub file")
            else:
                logger.error(f"Failed to fetch cookies from GitHub. Status code: {response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching cookies from GitHub: {str(e)}")
        
        return cookies
    
    def get_cookie(self) -> str:
        """
        Get the next cookie in round-robin fashion
        
        Returns:
            The cookie string
        """
        current_time = time.time()
        
        # Check if it's time to refresh cookies from GitHub
        if current_time - self.last_fetch_time > self.fetch_interval:
            github_cookies = self.fetch_from_github()
            new_cookies_added = 0
            
            for github_cookie in github_cookies:
                if github_cookie and github_cookie not in self.cookies:
                    self.cookies.append(github_cookie)
                    new_cookies_added += 1
            
            if new_cookies_added > 0:
                logger.info(f"Added {new_cookies_added} new cookies from GitHub, total cookies: {len(self.cookies)}")
        
        # If we have no cookies, use fallback from config
        if not self.cookies and COOKIES and len(COOKIES) > 0:
            self.cookies.append(COOKIES[0])
            logger.warning("No valid cookies found, using fallback from config")
        
        # If we still have no cookies, return empty string
        if not self.cookies:
            logger.error("No valid cookies available")
            return ""
        
        # Get next cookie in round-robin fashion
        cookie = self.cookies[self.current_cookie_index]
        
        # Update index for next call
        self.current_cookie_index = (self.current_cookie_index + 1) % len(self.cookies)
        
        # Log which cookie is being used (partially masked for privacy)
        masked_cookie = cookie[:30] + "..." if len(cookie) > 30 else cookie
        logger.info(f"Using cookie #{self.current_cookie_index}/{len(self.cookies)}: {masked_cookie}")
        
        return cookie
    
    def force_refresh(self) -> str:
        """
        Force a refresh of cookies from GitHub
        
        Returns:
            The current cookie value after refresh
        """
        logger.info("Forcing refresh of cookies from GitHub")
        self.last_fetch_time = 0  # Reset the timer to force a fetch
        github_cookies = self.fetch_from_github()
        new_cookies_added = 0
        
        for github_cookie in github_cookies:
            if github_cookie and github_cookie not in self.cookies:
                self.cookies.append(github_cookie)
                new_cookies_added += 1
        
        if new_cookies_added > 0:
            logger.info(f"Added {new_cookies_added} new cookies from GitHub during force refresh, total cookies: {len(self.cookies)}")
        
        return self.get_cookie()

# Create a singleton instance using config values
cookie_manager = GithubCookieManager(
    repo_owner=GITHUB_REPO_OWNER,
    repo_name=GITHUB_REPO_NAME,
    file_path=GITHUB_COOKIE_PATH,
    token=GITHUB_TOKEN
) 