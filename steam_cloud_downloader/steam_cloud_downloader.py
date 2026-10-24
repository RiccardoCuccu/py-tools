#!/usr/bin/env python3
"""
Steam Cloud Downloader - Download all Steam Cloud save files for every game on a Steam account.

Logs in via a Selenium browser window (supports 2FA), then scrapes the Remote Storage
page to enumerate app IDs, downloads each game's files, and archives everything into
a dated ZIP file before cleaning up the originals.

Usage:
    python steam_cloud_downloader.py

Notes:
    - Google Chrome must be installed and chromedriver must be on PATH.
    - Log in manually in the browser window that opens; the script waits for you.
"""

import os
import re
import shutil
from datetime import datetime

import requests
from bs4 import BeautifulSoup, Tag
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException


# HTTP status codes
HTTP_OK = 200

# Download settings
DOWNLOAD_CHUNK_SIZE = 8192
REQUEST_TIMEOUT_SECONDS = 30  # Per-request timeout for pages and file downloads
PART_FILE_SUFFIX = ".part"  # Temporary suffix while a file is being downloaded

# Minimum number of table cells expected in a file row
MIN_FILE_ROW_CELLS = 5

# Configuration
TIMEOUT_SECONDS = 300  # Seconds to wait for the user to complete manual login

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STEAM_SAVES_ROOT = os.path.join(SCRIPT_DIR, "steam_saves")

# Characters illegal in Windows file names, plus path separators and control chars
UNSAFE_FILE_NAME_CHARS = re.compile(r'[\\/*?:"<>|\x00-\x1f]')

# Windows reserved device names that cannot be used as file names
WINDOWS_RESERVED_NAMES = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{i}" for i in range(1, 10)]
    + [f"lpt{i}" for i in range(1, 10)]
)


def snake_case(text: str) -> str:
    """
    Convert a string to snake_case.

    Lowercases the text, replaces any sequence of non-alphanumeric chars with '_',
    and strips leading/trailing underscores.
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def get_game_folder_name(raw_game_name: str, appid: str) -> str:
    """Return a safe snake_case folder name, falling back to app_<appid> if empty."""
    return snake_case(raw_game_name) or f"app_{appid}"


def sanitize_file_name(file_name: str) -> str:
    """
    Turn a file name scraped from the Steam page into a safe single path component.

    Replaces path separators and characters illegal on Windows, strips trailing dots
    and spaces, and neutralises "." / ".." and Windows reserved device names so the
    result can never escape the target folder. Returns "" if nothing usable remains.
    """
    cleaned = UNSAFE_FILE_NAME_CHARS.sub("_", file_name).strip().rstrip(". ")
    if not cleaned:
        return ""
    if cleaned.split(".")[0].lower() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def unique_file_name(file_name: str, used_names: set[str]) -> str:
    """
    Return file_name, or a numbered variant if it collides (case-insensitively).

    Sanitising can map distinct remote names onto the same local name; without this
    the later download would silently overwrite the earlier one. The chosen name is
    recorded in used_names.
    """
    stem, dot, ext = file_name.rpartition(".")
    if not dot:
        stem, ext = file_name, ""
    candidate = file_name
    counter = 1
    while candidate.lower() in used_names:
        counter += 1
        candidate = f"{stem}_{counter}{dot}{ext}"
    used_names.add(candidate.lower())
    return candidate


def login_with_selenium() -> list[dict]:
    """
    Open the Steam login page in Chrome and wait for the user to log in manually.

    Waits up to TIMEOUT_SECONDS for the URL to change away from /login (indicating
    success including 2FA), then captures and returns the browser cookies (with
    their domain and path) as a list of dicts.
    """
    driver = ChromeDriver()

    try:
        print("Opening Steam login page...")
        driver.get("https://store.steampowered.com/login/")
        print(
            "Please log in manually in the opened browser window. "
            f"(Time limit: {TIMEOUT_SECONDS} seconds)"
        )

        try:
            WebDriverWait(driver, TIMEOUT_SECONDS).until(
                lambda d: "store.steampowered.com/login" not in d.current_url
            )
        except TimeoutException:
            raise TimeoutException(
                "Timed out waiting for manual login. Browser will be closed."
            ) from None

        cookies = driver.get_cookies()
        if not cookies:
            raise RuntimeError(
                "No cookies were retrieved. Ensure you completed the login successfully."
            )

        # Cookie values are session credentials: never print them
        print("\nCookies retrieved successfully. Closing the browser now.")
        return cookies

    finally:
        driver.quit()


def build_session(cookies: list[dict]) -> requests.Session:
    """Return a requests session carrying the browser cookies with domain and path."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        )
    })
    for cookie in cookies:
        # Keep domain and path so the session cookies are only sent to Steam hosts
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain", ""),
            path=cookie.get("path", "/"),
        )
    return session


def get_appids_from_remotestorage(session):
    """
    Scrape the Steam Remote Storage page and return a sorted list of app ID strings.
    """
    main_url = "https://store.steampowered.com/account/remotestorage"
    resp = session.get(main_url, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != HTTP_OK:
        print("[ERROR] Could not load the main remotestorage page.")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.find_all("a", href=re.compile(r"remotestorageapp/\?appid=\d+"))

    appids = set()
    for link in links:
        href = str(link.get("href", ""))
        match = re.search(r"appid=(\d+)", href)
        if match:
            appids.add(match.group(1))

    appids_list = sorted(appids, key=int)
    print(f"[DEBUG] Found {len(appids_list)} app ID(s) on the main page: {appids_list}")
    return appids_list


def folder_has_any_file(folder_path: str) -> bool:
    """Return True if folder_path exists and contains at least one file."""
    if not os.path.isdir(folder_path):
        return False
    for _, _, files in os.walk(folder_path):
        if files:
            return True
    return False


def download_file(session, file_url: str, file_path: str) -> bool:
    """
    Download file_url to file_path via a temporary .part file.

    The final file only appears once the transfer is complete, so an interrupted
    download never leaves a truncated save that a later run would treat as valid.
    Returns True on success; failures are reported and return False.
    """
    part_path = file_path + PART_FILE_SUFFIX
    try:
        with session.get(
            file_url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS
        ) as file_response:
            if file_response.status_code != HTTP_OK:
                print(f"  -> Error {file_response.status_code} downloading {file_url}")
                return False
            with open(part_path, "wb") as f:
                for chunk in file_response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    f.write(chunk)
        os.replace(part_path, file_path)
        return True
    except (requests.RequestException, OSError) as exc:
        print(f"  -> Error downloading to {file_path}: {exc}")
        if os.path.exists(part_path):
            os.remove(part_path)
        return False


def download_saves_for_app(session, appid):
    """
    Download all save files for appid into steam_saves/<snake_case_game_name>/.

    Skips the download entirely if the target folder already contains files. If any
    file fails, the partial folder is removed so the next run retries the whole game.
    """
    base_url = "https://store.steampowered.com/account/remotestorageapp/"
    url = f"{base_url}?appid={appid}"
    print(f"\n[DEBUG] Requesting page for appid={appid}: {url}")
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    print("[DEBUG] Response code:", response.status_code)

    if response.status_code != HTTP_OK:
        print(f"[ERROR] Could not load remotestorage page for AppID {appid}.")
        return

    soup = BeautifulSoup(response.text, "html.parser")

    main_content = soup.find("div", id="main_content", class_="page_content")
    if isinstance(main_content, Tag):
        h2_el = main_content.find("h2")
        raw_game_name = h2_el.get_text(strip=True) if isinstance(h2_el, Tag) else f"app_{appid}"
    else:
        raw_game_name = f"app_{appid}"

    game_name_snake = get_game_folder_name(raw_game_name, appid)
    print(f"[DEBUG] Using folder name '{game_name_snake}' for AppID {appid}")

    game_folder = os.path.join(STEAM_SAVES_ROOT, game_name_snake)
    if folder_has_any_file(game_folder):
        print(f"[DEBUG] Folder '{game_folder}' already exists and has files. Skipping download.")
        return

    table = soup.find("table", class_="accountTable")
    if not isinstance(table, Tag):
        print(f"[DEBUG] No <table class='accountTable'> for appid={appid}. Possibly no files.")
        return

    tbody = table.find("tbody")
    if not isinstance(tbody, Tag):
        print(f"[DEBUG] No <tbody> under accountTable for appid={appid}.")
        return

    rows = tbody.find_all("tr", recursive=False)
    print(f"[DEBUG] Found {len(rows)} row(s) for appid={appid}.")

    os.makedirs(game_folder, exist_ok=True)
    downloaded_files_count = 0
    failed_files_count = 0
    used_names: set[str] = set()

    for row in rows:
        cells = row.find_all("td", recursive=False)
        if len(cells) < MIN_FILE_ROW_CELLS:
            continue

        file_name = cells[1].get_text(strip=True)
        link_el = cells[4].find("a")
        if not isinstance(link_el, Tag):
            continue

        file_url = link_el.get("href", "")
        if not str(file_url).startswith("http"):
            continue

        safe_file_name = sanitize_file_name(file_name)
        if not safe_file_name:
            print(f"  -> Unusable file name {file_name!r} (AppID {appid})")
            failed_files_count += 1
            continue
        safe_file_name = unique_file_name(safe_file_name, used_names)

        print(f"Downloading '{safe_file_name}' (AppID {appid})...")
        file_path = os.path.join(game_folder, safe_file_name)
        if download_file(session, str(file_url), file_path):
            downloaded_files_count += 1
            print(f"  -> Saved at: {file_path}")
        else:
            failed_files_count += 1

    if failed_files_count > 0:
        # A partial folder would be skipped as "already downloaded" on the next run
        print(
            f"[ERROR] {failed_files_count} file(s) failed for AppID {appid}; "
            "discarding the partial folder so the next run retries it."
        )
        shutil.rmtree(game_folder, ignore_errors=True)
    elif downloaded_files_count > 0:
        print(f"Done: Downloaded {downloaded_files_count} file(s) to '{game_folder}'")
    else:
        print(f"No files found to download for AppID {appid}")
        shutil.rmtree(game_folder, ignore_errors=True)


def create_zip_archive(folder_path: str) -> str:
    """
    Create a ZIP archive of folder_path named YYYY_MM_DD_steam_cloud_backup.zip.

    Returns the full path of the created ZIP file, or an empty string if the
    folder does not exist.
    """
    if not os.path.isdir(folder_path):
        print(f"[DEBUG] Folder '{folder_path}' does not exist, skipping ZIP creation.")
        return ""

    today_str = datetime.now().strftime("%Y_%m_%d")
    zip_name = f"{today_str}_steam_cloud_backup"
    zip_filepath = os.path.join(SCRIPT_DIR, zip_name + ".zip")

    print(f"\n[DEBUG] Creating ZIP archive: {zip_filepath}")
    shutil.make_archive(
        base_name=os.path.splitext(zip_filepath)[0],
        format="zip",
        root_dir=folder_path,
    )
    print(f"[DEBUG] Created archive: {zip_filepath}")
    return zip_filepath


def main():
    """Log in to Steam, download all cloud saves, archive them, and clean up."""
    try:
        print("Logging in to Steam via browser...")
        cookies = login_with_selenium()
        session = build_session(cookies)

        appids = get_appids_from_remotestorage(session)
        if not appids:
            print("No app IDs found on the main remote storage page.")
            return

        for appid in appids:
            download_saves_for_app(session, appid)

        zip_path = create_zip_archive(STEAM_SAVES_ROOT)
        # Only delete the originals once a non-empty archive is confirmed on disk
        if zip_path and os.path.isfile(zip_path) and os.path.getsize(zip_path) > 0:
            print(f"[DEBUG] Removing folder '{STEAM_SAVES_ROOT}'...")
            shutil.rmtree(STEAM_SAVES_ROOT)
            print("[DEBUG] Done! All files archived and original folder removed.")

    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
