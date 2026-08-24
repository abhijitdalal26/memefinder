"""Unzip the MakeMeMeme curated image dataset inside Google Colab.

Flow (matches the plan in the zip):
  1. Mount Google Drive (the .zip lives there).
  2. Copy the zip into local Colab storage (/content) so extraction is fast.
  3. Extract it into MAKEMEME_IMAGES/curated, preserving the per-subreddit layout
     (curated/<subreddit>/<file>...), which is exactly what the pipeline expects.

The same script is embedded at the root of curated_images.zip as a convenience, but
the canonical copy is committed in this repo under colab/.

Usage in Colab:
    %env MAKEMEME_IMAGES=/content/MakeMeMeme/data
    !python colab/unzip_dataset.py
"""
import os
import shutil
import zipfile
from pathlib import Path

# ---- config ----
# On the laptop this zip lives at:
#   H:\My Drive\MakeMeMeme\curated_images.zip
# which Drive for desktop syncs to the "MyDrive/MakeMeMeme" folder. When Colab
# mounts Drive at /content/drive, that same file is at the path below.
DRIVE_ZIP_PATH = "/content/drive/MyDrive/MakeMeMeme/curated_images.zip"
LOCAL_ZIP_PATH = "/content/curated_images.zip"
# Destination images root; the zip's "curated/" folder is extracted underneath it.
IMAGES_DIR = os.environ.get("MAKEMEME_IMAGES", "/content/MakeMeMeme/data")
EXTRACT_TO = os.path.join(IMAGES_DIR, "curated")


def mount_drive():
    try:
        from google.colab import drive
        drive.mount("/content/drive")
    except Exception:
        print("google.colab not available or already mounted; skipping mount.")


def stage_zip():
    """Make sure the zip is available at LOCAL_ZIP_PATH (copy from Drive if needed)."""
    if os.path.exists(LOCAL_ZIP_PATH) and os.path.getsize(LOCAL_ZIP_PATH) > 0:
        print(f"Using local zip: {LOCAL_ZIP_PATH}")
        return
    if not os.path.exists(DRIVE_ZIP_PATH):
        raise FileNotFoundError(
            f"Zip not found at {DRIVE_ZIP_PATH}. Upload it to Drive or set "
            "DRIVE_ZIP_PATH / LOCAL_ZIP_PATH at the top of this script."
        )
    print(f"Copying {DRIVE_ZIP_PATH} -> {LOCAL_ZIP_PATH} ...")
    shutil.copyfile(DRIVE_ZIP_PATH, LOCAL_ZIP_PATH)
    print(f"Copied ({os.path.getsize(LOCAL_ZIP_PATH)} bytes).")


def extract():
    os.makedirs(EXTRACT_TO, exist_ok=True)
    print(f"Extracting {LOCAL_ZIP_PATH} -> {EXTRACT_TO} ...")
    with zipfile.ZipFile(LOCAL_ZIP_PATH) as z:
        z.extractall(EXTRACT_TO)
    n = sum(1 for p in Path(EXTRACT_TO).rglob("*") if p.is_file())
    print(f"Done. {n} files under {EXTRACT_TO}")


if __name__ == "__main__":
    mount_drive()
    stage_zip()
    extract()
