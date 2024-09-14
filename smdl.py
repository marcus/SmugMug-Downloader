import os
import sys
import requests
import json
import re
import argparse
import hashlib
import logging
from bs4 import BeautifulSoup
from tqdm import tqdm
from colored import fg, attr

# ---------------------------- #
#        Configuration         #
# ---------------------------- #

def setup_logging(output_dir):
    """
    Sets up logging with separate handlers for file and console.
    - File Handler: DEBUG level and above (captures all logs)
    - Console Handler: INFO level and above (excludes DEBUG)
    """
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # File handler - captures all logs
    log_file = os.path.join(output_dir, 'smugmug_downloader.log')
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(fh_formatter)
    logger.addHandler(fh)

    # Console handler - INFO and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch_formatter = logging.Formatter('%(message)s')  # Clean console output
    ch.setFormatter(ch_formatter)
    logger.addHandler(ch)

# ---------------------------- #
#        Argument Parsing      #
# ---------------------------- #

parser = argparse.ArgumentParser(description="SmugMug Downloader")
parser.add_argument(
    "-s", "--session", help="Session ID (required if user is password protected); log in on a web browser and paste the SMSESS cookie")
parser.add_argument(
    "-u", "--user", help="Username (from URL, USERNAME.smugmug.com)", required=True)
parser.add_argument("-o", "--output", default="output/",
                    help="Output directory")
parser.add_argument(
    "--albums", help="Specific album names to download, split by $. Defaults to all. Wrap in single quotes to avoid shell variable substitutions. (e.g. --albums 'Title 1$Title 2$Title 3')")

args = parser.parse_args()

# ---------------------------- #
#           Setup              #
# ---------------------------- #

endpoint = "https://www.smugmug.com"

SMSESS = args.session

if SMSESS:
    cookies = {"SMSESS": SMSESS}
    print("Using provided SMSESS cookie for authentication.")
else:
    cookies = {}
    print("No SMSESS cookie provided. Proceeding without authentication.")

output_dir = args.output.rstrip(os.sep)

# Create output directory if it doesn't exist
if not os.path.exists(output_dir):
    try:
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")
    except OSError as e:
        print(f"ERROR: Could not create output directory {output_dir}: {e}")
        sys.exit(1)

# Setup logging after ensuring output directory exists
setup_logging(output_dir)
logging.info("Starting SmugMug Downloader.")

if args.albums:
    specific_albums = [x.strip() for x in args.albums.split('$')]
    logging.info(f"Specific albums to download: {specific_albums}")
else:
    specific_albums = []
    logging.info("No specific albums specified. Will download all albums.")

# ---------------------------- #
#        Helper Functions      #
# ---------------------------- #

def get_json(url):
    """
    Retrieves JSON data from a given URL with retries.
    """
    num_retries = 5
    for i in range(num_retries):
        try:
            r = requests.get(endpoint + url, cookies=cookies)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            pres = soup.find_all("pre")
            if not pres:
                raise ValueError("No <pre> tags found in response.")
            return json.loads(pres[-1].text)
        except Exception as e:
            logging.error(f"Error fetching JSON from URL {endpoint + url}: {e}")
            if i + 1 < num_retries:
                logging.info("Retrying...")
            else:
                logging.error("Max retries reached. Skipping this request.")
    return None

def sanitize_filename(filename):
    """
    Sanitizes the filename by replacing unwanted characters with underscores.
    """
    return re.sub(r'[^\w\-_\. ]', '_', filename)

# ---------------------------- #
#       Main Script Logic      #
# ---------------------------- #

# Retrieve the list of albums
logging.info("Retrieving album list...")
albums_data = get_json(f"/api/v2/folder/user/{args.user}!albumlist")
if albums_data is None:
    logging.error("Could not retrieve album list. Exiting.")
    sys.exit(1)
logging.info("Album list retrieved successfully.")

# Process album list
try:
    album_list = albums_data["Response"]["AlbumList"]
    if not album_list:
        logging.warning(f"No albums found for user {args.user}. Exiting.")
        sys.exit(1)
except KeyError:
    logging.error(f"No albums were found for the user {args.user}. The user may not exist or may be password protected.")
    sys.exit(1)

# Loop through each album
for album in tqdm(album_list, desc="Albums", unit="album"):
    album_name = album.get("Name", "Unnamed_Album").strip()
    if specific_albums and album_name not in specific_albums:
        continue

    album_url_path = album.get("UrlPath", "").lstrip('/')
    if not album_url_path:
        logging.warning(f"Album '{album_name}' has no UrlPath. Skipping.")
        continue

    album_path = os.path.join(output_dir, album_url_path)
    if not os.path.exists(album_path):
        try:
            os.makedirs(album_path)
            logging.info(f"Created directory: {album_path}")
        except OSError as e:
            logging.error(f"Could not create directory {album_path}: {e}")
            continue

    # Retrieve images in the album
    images_data = get_json(f"{album.get('Uri')}!images")
    if images_data is None:
        logging.error(f"Could not retrieve images for album '{album_name}'. Skipping.")
        continue

    images = images_data.get("Response", {}).get("AlbumImage", [])
    if not images:
        logging.info(f"No images found in album '{album_name}'. Skipping.")
        continue

    # Handle pagination
    next_page_url = images_data["Response"]["Pages"].get("NextPage")
    while next_page_url:
        next_images_data = get_json(next_page_url)
        if next_images_data is None:
            logging.error(f"Could not retrieve next page for album '{album_name}'.")
            break
        next_images = next_images_data.get("Response", {}).get("AlbumImage", [])
        images.extend(next_images)
        next_page_url = next_images_data["Response"]["Pages"].get("NextPage")

    # Loop through each image
    for image in tqdm(images, desc=f"Album: {album_name}", unit="image", leave=False):
        # Get unique identifier
        unique_id = image.get('ArchivedMD5') or image.get('MD5Sum')
        if not unique_id:
            unique_id = image.get('id')
            if not unique_id:
                image_uri = image.get('Uri', '')
                if image_uri:
                    unique_id = hashlib.sha256(image_uri.encode('utf-8')).hexdigest()
                    logging.warning(f"Image in album '{album_name}' is missing 'id' and 'ArchivedMD5'. Using hash of 'Uri' as unique identifier.")
                else:
                    logging.error(f"Image in album '{album_name}' is missing 'id', 'ArchivedMD5', and 'Uri'. Skipping image.")
                    continue

        # Get filename
        file_name = image.get("FileName", "unknown_filename")
        sanitized_filename = sanitize_filename(file_name)
        name, ext = os.path.splitext(sanitized_filename)
        short_unique_id = unique_id[:8]
        unique_filename = f"{name}_{short_unique_id}{ext}"
        image_path = os.path.join(album_path, unique_filename)

        # Check if image already exists
        if os.path.isfile(image_path):
            continue  # Already downloaded

        # Determine download URL
        largest_media = None
        if "LargestVideo" in image["Uris"]:
            largest_media = "LargestVideo"
        elif "ImageDownload" in image["Uris"]:
            largest_media = "ImageDownload"
        elif "LargestImage" in image["Uris"]:
            largest_media = "LargestImage"

        if largest_media and largest_media in image["Uris"]:
            image_req = get_json(image["Uris"][largest_media]["Uri"])
            if image_req is None:
                logging.error(f"Could not retrieve image data for {image['Uris'][largest_media]['Uri']}. Skipping image.")
                continue
            download_url = image_req["Response"][largest_media]["Url"]
        else:
            # Use archive link if no suitable URI found
            download_url = image.get("ArchivedUri")
            if not download_url:
                logging.error(f"No download URL found for image '{unique_filename}' in album '{album_name}'. Skipping image.")
                continue

        # Download the image
        try:
            response = requests.get(download_url, cookies=cookies, stream=True)
            response.raise_for_status()
            with open(image_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            logging.debug(f"Downloaded image: {image_path}")
        except Exception as e:
            logging.error(f"Could not fetch image from {download_url}: {e}")
            continue

logging.info("All downloads completed successfully.")
print("Completed.")
