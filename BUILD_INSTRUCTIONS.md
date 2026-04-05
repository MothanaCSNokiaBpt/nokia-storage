# Nokia Storage - Build Instructions

## Project Overview
Android application for managing Nokia phone inventory and spare parts.

## Features
- Two tabs: Nokia Phones / Accessories & Spare Parts
- Search by name, ID, or release date (across both categories)
- Phone detail profile page with image
- Add phones/spare parts with camera or gallery images
- Import phones from Excel (.xlsx)
- Export data to Excel (2 sheets: Phones + Spare Parts)
- Bulk image import with details assignment
- Full backup/restore (database + images as .zip)
- Share backup via email/Google Drive

## Build APK

### Option 1: Build on Linux/WSL (Recommended)

```bash
# Install buildozer dependencies
sudo apt update
sudo apt install -y python3-pip git zip unzip openjdk-17-jdk autoconf \
    libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \
    libtiff5-dev libgstreamer1.0-dev cmake libffi-dev libssl-dev \
    automake

# Install buildozer
pip3 install buildozer cython==0.29.36

# Navigate to project
cd nokia_storage/

# Build debug APK
buildozer android debug

# APK will be in: bin/nokiastorage-1.0.0-arm64-v8a_armeabi-v7a-debug.apk
```

### Option 2: Build using Google Colab (Free, No Setup)

1. Open Google Colab (colab.research.google.com)
2. Create a new notebook
3. Run these cells:

```python
# Cell 1: Install buildozer
!pip install buildozer cython==0.29.36
!sudo apt update && sudo apt install -y openjdk-17-jdk autoconf libtool \
    pkg-config zlib1g-dev libncurses5-dev cmake libffi-dev
```

```python
# Cell 2: Upload project files
from google.colab import files
# Upload main.py, database.py, buildozer.spec, and fileprovider_src/ folder
uploaded = files.upload()
```

```python
# Cell 3: Setup project structure
!mkdir -p fileprovider_src/res/xml
# Move filepaths.xml to correct location if needed
```

```python
# Cell 4: Build APK
!buildozer android debug 2>&1 | tail -50
```

```python
# Cell 5: Download APK
from google.colab import files
import glob
apk = glob.glob('bin/*.apk')[0]
files.download(apk)
```

### Option 3: GitHub Actions (Automated)

Create `.github/workflows/build.yml` in a GitHub repo:

```yaml
name: Build APK
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - uses: actions/setup-java@v4
        with:
          distribution: 'temurin'
          java-version: '17'
      - run: pip install buildozer cython==0.29.36
      - run: buildozer android debug
      - uses: actions/upload-artifact@v4
        with:
          name: apk
          path: bin/*.apk
```

## Testing on Desktop

```bash
pip install kivy kivymd pillow openpyxl plyer
python main.py
```

## Creating Sample Data

```bash
pip install openpyxl
python create_sample_excel.py
# Then import sample_nokia_phones.xlsx via the app
```

## Excel Import Format

| ID | Name | Release Date | Appearance Condition | Working Condition | Remarks |
|----|------|-------------|---------------------|-------------------|---------|
| N3310-001 | Nokia 3310 | 2000 | Excellent | Working | Classic |

Column names are flexible - the app matches common variations:
- ID: `id`, `phone_id`, `phone id`
- Name: `name`, `phone_name`, `model`
- Release Date: `release_date`, `date`, `year`
- Appearance: `appearance_condition`, `appearance`, `look`
- Working: `working_condition`, `working`, `status`
- Remarks: `remarks`, `notes`, `comments`

## Backup & Restore

The backup creates a `.zip` file containing:
- `nokia_storage.db` (SQLite database)
- `images/phones/` (all phone images)
- `images/spares/` (all spare part images)

To restore on a new device:
1. Install the APK
2. Copy the backup .zip to the phone
3. Open the app -> Menu -> Backup & Restore -> Restore from Backup
4. Select the .zip file
