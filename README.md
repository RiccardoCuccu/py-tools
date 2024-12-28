# Python Random Tools

Welcome to my "Python Random Tools" repository! This is a personal collection of diverse Python scripts that I've developed. The goal of this repository is to offer a range of handy tools for various tasks. These scripts are free to use and can be a great resource for anyone looking to solve practical problems with Python or just exploring different aspects of the language. Feel free to explore, use, and contribute to the development of these tools!

## [merge_python_files](https://github.com/RiccardoCuccu/py-tools/blob/main/merge_python_files/merge_python_files.py)
**Purpose:** `merge_python_files.py` is a script designed to consolidate multiple Python files from a specified directory into a single Python file. The goal is to create a unified executable file that merges the code from all `.py` files in the folder. If a `main.py` file is present, it is placed at the end of the merged file to ensure proper execution order.

### How it Works
- The script begins by scanning the specified folder for Python files. It identifies all `.py` files in the directory and stores them in a list, with the exception of `main.py`, which is treated separately.
- After gathering the files, the script writes their contents to a new output file. It first appends the contents of all Python files except `main.py` and adds a header comment to indicate the original file name. Once all other files have been written, it appends the contents of `main.py` (if present) at the end to ensure that any main execution logic is placed last.
- The merged content is written into a single Python file specified by the user. This output file can then be used as a consolidated version of all the Python scripts in the directory.

### Installation
No external dependencies are required to run this script. It operates entirely using Python's standard library.

## [pdf_highlight_extractor](https://github.com/RiccardoCuccu/py-tools/blob/main/pdf_highlight_extractor/pdf_highlight_extractor.py)
**Purpose:** `pdf_highlight_extractor.py` is an enhanced script with a basic GUI designed to extract highlighted text from PDF files. The script reads highlighted sections from the selected PDF file and saves them into a text file with the same name, facilitating easy review and referencing.

### How it Works
- When launched, the script displays a simple GUI.
- The user can select a PDF file to analyze using the GUI's file selection dialog.
- After a PDF file is selected, the script processes it to extract any highlighted text.
- The extracted text is saved to a new text file, named after the original PDF but with a `.txt` extension.
- All operations and status messages are displayed in the script's GUI window.

### Installation
To use `pdf_highlight_extractor.py`, you need to install PyMuPDF, a Python library that enables the script to read PDF files, and tkinter for the GUI. PyMuPDF can be installed using pip, the Python package installer. Run the following command in your terminal:

```
pip install PyMuPDF
```

Note: tkinter is typically included in standard Python installations. If it's not present in your environment, refer to Python's official documentation for installation instructions.

## [podcast_transcriber](https://github.com/RiccardoCuccu/py-tools/blob/main/podcast_transcriber/main.py)
**Purpose:** `podcast_transcriber` is a tool designed to download and transcribe audio from podcast episodes available on Apple Podcasts. It automates the entire process of retrieving podcast metadata, downloading the episode audio, and converting it into a text transcript using the Vosk speech recognition engine.

### How it Works
- The script first extracts the podcast ID and episode title from an Apple Podcast URL using the iTunes API. It fetches relevant metadata, including the podcast's RSS feed, which contains the necessary details about the episode.
- Once the metadata is obtained, the script identifies the direct link to the original episode audio by parsing the RSS feed and searching for the closest match to the episode title.
- After the episode link is found, the script downloads the audio using `yt-dlp` and converts it to a WAV file. The audio is processed using `FFmpeg`, converting it to a mono 16kHz WAV format for better compatibility with the transcription engine.
- The Vosk model is used for transcription. If multiple Vosk models are available in the local directory, the script prompts the user to choose one. If only one model is present, it is automatically selected.
- The audio file is transcribed using the Vosk engine. The KaldiRecognizer is initialized with the selected model, and the audio is processed frame by frame to generate the transcript. The final transcript is saved as a text file in a specified directory.
- After the transcription, the script performs cleanup operations deleting the `__pycache__` directory.

### Installation
To use `podcast_transcriber`, you'll need to install the following Python libraries:
```
pip install yt-dlp requests feedparser beautifulsoup4 vosk pydub
```
Additionally, `ffmpeg` must be installed on your system and accessible via the command line. Follow the [official FFmpeg installation guide](https://ffmpeg.org/download.html) for your operating system.

Moreover, it is necessary to download a Vosk speech recognition model. You can find and download the appropriate model from [https://alphacephei.com/vosk/models](https://alphacephei.com/vosk/models), then place the downloaded model in the `models` directory where the script will locate it.

Once everything is installed, you can run the main script and provide the link to the Apple Podcasts episode you wish to transcribe, and the script will handle the rest.

## [rda_calculator](https://github.com/RiccardoCuccu/py-tools/blob/main/rda_calculator/rda_calculator.py)
**Purpose:** `rda_calculator.py` is a script with a GUI for converting milligrams of vitamins and minerals into their respective Recommended Dietary Allowance (RDA) percentages. Specifically, it focuses on converting milligrams of Vitamin A, Vitamin C, Calcium, and Iron, which are the nutrients commonly required by the MyFitnessPal platform when adding or modifying foods in its database.

### How it Works
- The GUI allows users to input the milligram values of Vitamin A, Vitamin C, Iron, and Calcium.
- On clicking the 'Calculate' button, the script calculates the RDA percentages based on the input values.
- The results are displayed in the same window, showing how much each nutrient contributes to the daily recommended intake.

### Installation
`rda_calculator.py` requires tkinter for the GUI, which is usually included in standard Python installations. If tkinter is not installed, refer to [Python's official tkinter documentation](https://docs.python.org/3/library/tkinter.html) for guidance.

## [steam_cloud_downloader](https://github.com/RiccardoCuccu/py-tools/blob/main/steam_cloud_downloader/steam_cloud_downloader.py)
**Purpose:** `steam_cloud_downloader.py` is a script designed to automate the process of downloading game save files stored in Steam Cloud for all games linked to a Steam account. The tool also organizes the downloaded files into folders named after the respective games in snake_case format and archives the data for backup purposes.

### How it Works
- The script begins by automating the Steam login process using Selenium. A browser window opens, allowing the user to manually log in to their Steam account, including completing any required two-factor authentication.
- After a successful login, the script retrieves session cookies to authenticate subsequent HTTP requests made with the `requests` library.
- It navigates to the Steam Remote Storage page and scrapes the list of all app IDs (corresponding to games) linked to the account.
- For each app ID, the script fetches the respective game name, converts it into snake_case format, and creates a folder for the game's save files.
- It downloads all available files for each game into the corresponding folder, skipping games if their folders already contain files.
- Once all downloads are complete, the script creates a ZIP archive of all downloaded files and cleans up the original folders to save space.

### Installation
To use `steam_cloud_downloader.py`, you need to install the following Python libraries:
```bash
pip install selenium requests beautifulsoup4
```

Additionally, you must have a recent version of Google Chrome installed for Selenium automation.

## [webpage_carbon_dating](https://github.com/RiccardoCuccu/py-tools/blob/main/webpage_carbon_dating/webpage_carbon_dating.py)
**Purpose:** `webpage_carbon_dating.py` is a script designed to retrieve the oldest recorded publication date of a webpage. This script uses `requests` to fetch the HTML of a given webpage and `BeautifulSoup` to parse it and search for metadata tags that usually contain the publication date (e.g., `article:published_time`, `datePublished`, etc.). If found, it returns the date of publication.

### How it Works
- The script sends an HTTP request to retrieve the HTML of the webpage.
- It then parses the HTML content to search for specific meta tags or `<time>` elements that typically store publication dates.
- Once found, it extracts and returns the date in the `YYYY-MM-DD` format.
- If no publication date is found, it returns a message indicating that the metadata is not available.

### Installation
To use `webpage_carbon_dating.py`, you'll need to install the following Python libraries:

```
pip install requests beautifulsoup4
```

Once the dependencies are installed, you can run the script and provide the URL of the webpage you wish to analyze.
