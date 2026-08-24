"""Build curated_images.zip from data/curated for upload to Google Drive.

The zip layout:
    curated/<subreddit>/<image>...   (the dataset, what the pipeline consumes)
    unzip_dataset.py                  (Colab helper to extract it)

Run: python scripts/build_images_zip.py
"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "curated")
SCRIPT = os.path.join(ROOT, "colab", "unzip_dataset.py")
OUT = os.path.join(ROOT, "curated_images.zip")


def main():
    if not os.path.isdir(SRC):
        raise SystemExit(f"No source dir: {SRC}")

    total = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_STORED) as z:
        # embed the unzip helper at the zip root
        z.write(SCRIPT, "unzip_dataset.py")
        print(f"added unzip_dataset.py")

        for dirpath, _, files in os.walk(SRC):
            for name in files:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, SRC)          # <subreddit>/<image>
                arcname = os.path.join("curated", rel).replace("\\", "/")
                z.write(full, arcname)
                total += 1
                if total % 2000 == 0:
                    print(f"  ... {total} files")
    print(f"Wrote {OUT} ({os.path.getsize(OUT)} bytes) with {total} image files.")


if __name__ == "__main__":
    main()
