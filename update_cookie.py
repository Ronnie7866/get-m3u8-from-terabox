import sys
import requests
import os

def update_cookie_from_file(cookie_file_path, api_url="http://localhost:8080/update_cookie"):
    """Update the cookie in the API using a Netscape cookie file."""
    
    # Check if the file exists
    if not os.path.exists(cookie_file_path):
        print(f"Error: File {cookie_file_path} not found")
        return False
    
    # Read the cookie file
    try:
        with open(cookie_file_path, 'r') as f:
            cookie_data = f.read()
    except Exception as e:
        print(f"Error reading file: {str(e)}")
        return False
    
    # Prepare the request
    headers = {"Content-Type": "application/json"}
    payload = {"cookie_data": cookie_data}
    
    # Send the request
    try:
        response = requests.post(api_url, json=payload, headers=headers)
        response.raise_for_status()
        print(f"Success: {response.json()}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error updating cookie: {str(e)}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python update_cookie.py path/to/cookie.txt")
        sys.exit(1)
    
    cookie_file_path = sys.argv[1]
    update_cookie_from_file(cookie_file_path) 