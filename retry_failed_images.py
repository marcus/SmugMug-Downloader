import os
import requests
import logging
import hashlib
import re
import argparse
import sys

# ---------------------------- #
#        Argument Parsing       #
# ---------------------------- #

parser = argparse.ArgumentParser(description="Retry failed SmugMug image downloads.")
parser.add_argument(
    "-s", "--session", help="Session ID (required if user is password protected); log in on a web browser and paste the SMSESS cookie", required=True)
parser.add_argument(
    "-l", "--log", help="Path to the log file where failed downloads are logged", default="smugmug_downloader.log")
parser.add_argument(
    "-o", "--output", default="output/", help="Output directory where images should be saved")
args = parser.parse_args()

# ---------------------------- #
#        Configuration          #
# ---------------------------- #

LOG_FILE = args.log
output_dir = args.output.rstrip(os.sep)
cookies = {"SMSESS": args.session}  # Session cookie passed as CLI argument

# ---------------------------- #
#        Helper Functions       #
# ---------------------------- #

def sanitize_filename(filename):
    """
    Sanitizes the filename by replacing unwanted characters with underscores.
    """
    return re.sub(r'[^\w\-_\. ]', '_', filename)

def get_unique_id(url):
    """
    Generates a unique ID based on the URL.
    """
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:8]

def get_image_filename(url):
    """
    Constructs the image filename using a unique identifier and sanitizes it.
    """
    basename = os.path.basename(url)
    name, ext = os.path.splitext(basename)
    unique_id = get_unique_id(url)
    sanitized_name = sanitize_filename(name)
    return f"{sanitized_name}_{unique_id}{ext}"

def retry_failed_images():
    """
    Reads the log file for failed image URLs and retries downloading them.
    """
    if not os.path.exists(LOG_FILE):
        print(f"Log file '{LOG_FILE}' does not exist.")
        sys.exit(1)

    with open(LOG_FILE, 'r') as log_file:
        for line in log_file:
            if "ERROR - Could not fetch image" in line:
                # Extract the image URL from the log file
                url_start = line.find("http")
                if url_start != -1:
                    image_url = line[url_start:].strip()
                    download_image(image_url)

def download_image(image_url):
    """
    Downloads the image and saves it to the correct folder.
    """
    # Get the filename and directory structure
    album_url_path = extract_album_path(image_url)
    album_path = os.path.join(output_dir, album_url_path)

    if not os.path.exists(album_path):
        try:
            os.makedirs(album_path)
            logging.info(f"Created directory: {album_path}")
        except OSError as e:
            logging.error(f"Could not create directory {album_path}: {e}")
            return

    # Get the full image path (sanitized and with unique id)
    image_filename = get_image_filename(image_url)
    image_path = os.path.join(album_path, image_filename)

    # Skip download if the file already exists
    if os.path.isfile(image_path):
        logging.info(f"Image already exists: {image_path}. Skipping.")
        return

    try:
        logging.info(f"Downloading image: {image_url}")
        response = requests.get(image_url, cookies=cookies, stream=True)
        response.raise_for_status()

        with open(image_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        logging.info(f"Downloaded image: {image_path}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Could not fetch image from {image_url}: {e}")

def extract_album_path(image_url):
    """
    Extracts the album path from the image URL.
    """
    # Example format: https://photos.smugmug.com/photos/i-xxxxx/0/M/album_path/D/i-xxxxx-D.jpg
    # This will extract 'album_path' as the album path
    match = re.search(r'photos/(.+)/D', image_url)
    if match:
        return match.group(1)
    return "unknown_album"

# ---------------------------- #
#        Main Script            #
# ---------------------------- #

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Ensure the output directory exists
    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            logging.info(f"Created output directory: {output_dir}")
        except OSError as e:
            logging.error(f"Could not create output directory {output_dir}: {e}")
            sys.exit(1)

    # Retry the failed images
    retry_failed_images()
    logging.info("Retry process completed.")
