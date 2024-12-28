import os
import re
import shutil
import requests
from datetime import datetime
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

###################################################################
# CONFIGURATION
###################################################################
TIMEOUT_SECONDS = 300  # Time (in seconds) to wait for manual login
###################################################################

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STEAM_SAVES_ROOT = os.path.join(SCRIPT_DIR, "steam_saves")

def snake_case(text: str) -> str:
    """
    Convert a string to snake_case by:
    - Lowercasing
    - Replacing any sequence of non-alphanumeric chars with '_'
    - Stripping leading/trailing underscores
    """
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    return text.strip('_')

def login_with_selenium():
    """
    Opens Steam login page in Chrome, waits up to TIMEOUT_SECONDS for manual login (including 2FA).
    Once the URL changes away from /login, it assumes the login is successful,
    grabs the cookies, then closes the browser.
    Returns session cookies as a dictionary.
    """
    driver = webdriver.Chrome()  # Ensure chromedriver is in your PATH

    try:
        print("Opening Steam login page...")
        driver.get("https://store.steampowered.com/login/")
        print(
            "Please log in manually in the opened browser window. "
            f"(Time limit: {TIMEOUT_SECONDS} seconds)"
        )

        # Wait until the current URL changes away from /login or until timeout
        try:
            WebDriverWait(driver, TIMEOUT_SECONDS).until(
                lambda d: "store.steampowered.com/login" not in d.current_url
            )
        except TimeoutException:
            raise TimeoutException(
                "Timed out waiting for manual login. Browser will be closed."
            )

        cookies = driver.get_cookies()
        if not cookies:
            raise Exception(
                "No cookies were retrieved. Ensure you completed the login successfully."
            )

        session_cookies = {cookie["name"]: cookie["value"] for cookie in cookies}

        print("\n[DEBUG] Retrieved cookies from Selenium:")
        for k, v in session_cookies.items():
            print(f"  {k} = {v}")

        print("\nCookies retrieved successfully. Closing the browser now.")
        return session_cookies

    finally:
        driver.quit()

def get_appids_from_remotestorage(session):
    """
    Scrapes 'https://store.steampowered.com/account/remotestorage'
    for links 'remotestorageapp/?appid=...' and returns a list of unique app IDs.
    """
    main_url = "https://store.steampowered.com/account/remotestorage"
    # print(f"\n[DEBUG] Fetching main remote storage page: {main_url}")
    resp = session.get(main_url)
    if resp.status_code != 200:
        print("[ERROR] Could not load the main remotestorage page.")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.find_all("a", href=re.compile(r"remotestorageapp/\?appid=\d+"))

    appids = set()
    for link in links:
        href = link.get("href", "")
        match = re.search(r"appid=(\d+)", href)
        if match:
            appid = match.group(1)
            appids.add(appid)

    appids_list = sorted(appids, key=int)
    print(f"[DEBUG] Found {len(appids_list)} app ID(s) on the main page: {appids_list}")
    return appids_list

def folder_has_any_file(folder_path: str) -> bool:
    """
    Return True if 'folder_path' exists and contains at least one file.
    """
    if not os.path.isdir(folder_path):
        return False
    for _, _, files in os.walk(folder_path):
        if files:
            return True
    return False

def download_saves_for_app(session, appid):
    """
    Fetch the page 'remotestorageapp/?appid={appid}', parse the <table class="accountTable">,
    and download each file to 'steam_saves/<snake_case_game_name>/'.

    If the target folder already exists and is not empty, skip downloads.
    """
    base_url = "https://store.steampowered.com/account/remotestorageapp/"
    url = f"{base_url}?appid={appid}"
    print(f"\n[DEBUG] Requesting page for appid={appid}: {url}")
    response = session.get(url)
    print("[DEBUG] Response code:", response.status_code)

    if response.status_code != 200:
        print(f"[ERROR] Could not load remotestorage page for AppID {appid}.")
        return

    soup = BeautifulSoup(response.text, "html.parser")

    main_content = soup.find("div", id="main_content", class_="page_content")
    if main_content:
        h2_el = main_content.find("h2")
        if h2_el:
            raw_game_name = h2_el.get_text(strip=True)
        else:
            raw_game_name = f"app_{appid}"
    else:
        raw_game_name = f"app_{appid}"

    game_name_snake = snake_case(raw_game_name)
    print(f"[DEBUG] Using folder name '{game_name_snake}' for AppID {appid}")

    game_folder = os.path.join(STEAM_SAVES_ROOT, game_name_snake)
    if folder_has_any_file(game_folder):
        print(f"[DEBUG] Folder '{game_folder}' already exists and has files. Skipping download.")
        return

    table = soup.find("table", class_="accountTable")
    if not table:
        print(f"[DEBUG] No <table class='accountTable'> for appid={appid}. Possibly no files.")
        return

    tbody = table.find("tbody")
    if not tbody:
        print(f"[DEBUG] No <tbody> under accountTable for appid={appid}.")
        return

    rows = tbody.find_all("tr", recursive=False)
    print(f"[DEBUG] Found {len(rows)} row(s) for appid={appid}.")

    os.makedirs(game_folder, exist_ok=True)
    downloaded_files_count = 0

    for row in rows:
        cells = row.find_all("td", recursive=False)
        if len(cells) < 5:
            continue

        file_name_cell = cells[1]
        file_name = file_name_cell.get_text(strip=True)

        download_cell = cells[4]
        link_el = download_cell.find("a")
        if not link_el:
            continue

        file_url = link_el.get("href", "")
        if not file_url.startswith("http"):
            continue

        safe_file_name = re.sub(r'[\\/*?:"<>|]', "_", file_name)

        print(f"Downloading '{safe_file_name}' (AppID {appid})...")
        file_response = session.get(file_url, stream=True)
        if file_response.status_code == 200:
            file_path = os.path.join(game_folder, safe_file_name)
            with open(file_path, "wb") as f:
                for chunk in file_response.iter_content(chunk_size=8192):
                    f.write(chunk)
            downloaded_files_count += 1
            print(f"  -> Saved at: {file_path}")
        else:
            print(f"  -> Error {file_response.status_code} downloading {safe_file_name}")

    if downloaded_files_count > 0:
        print(f"Done: Downloaded {downloaded_files_count} file(s) to '{game_folder}'")
    else:
        print(f"No files found to download for AppID {appid}")

def create_zip_archive(folder_path: str) -> str:
    """
    Creates a ZIP archive of the given folder using today's date
    in the format YYYY_MM_DD_steam_cloud_backup.zip.

    Returns the full path of the created ZIP file.
    """
    if not os.path.isdir(folder_path):
        print(f"[DEBUG] Folder '{folder_path}' does not exist, skipping ZIP creation.")
        return ""

    today_str = datetime.now().strftime("%Y_%m_%d")
    zip_name = f"{today_str}_steam_cloud_backup"
    zip_filepath = os.path.join(SCRIPT_DIR, zip_name + ".zip")

    print(f"\n[DEBUG] Creating ZIP archive: {zip_filepath}")
    # 'make_archive' needs a base_name without .zip, so split it out
    shutil.make_archive(
        base_name=os.path.splitext(zip_filepath)[0],
        format='zip',
        root_dir=folder_path
    )
    print(f"[DEBUG] Created archive: {zip_filepath}")

    return zip_filepath

def main():
    try:
        print("Logging in to Steam via browser...")
        cookies = login_with_selenium()

        # Initialize requests session with cookies
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
            )
        })
        for name, value in cookies.items():
            session.cookies.set(name, value)

        # Get all app IDs from the main remotestorage page
        appids = get_appids_from_remotestorage(session)
        if not appids:
            print("No app IDs found on the main remote storage page.")
            return

        # Download saves for each app ID (skips if folder non-empty)
        for appid in appids:
            download_saves_for_app(session, appid)

        # Create a ZIP of the entire 'steam_saves' folder
        zip_path = create_zip_archive(STEAM_SAVES_ROOT)
        if zip_path:
            # Remove the original 'steam_saves' folder
            print(f"[DEBUG] Removing folder '{STEAM_SAVES_ROOT}'...")
            shutil.rmtree(STEAM_SAVES_ROOT)
            print("[DEBUG] Done! All files archived and original folder removed.")

    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    main()
