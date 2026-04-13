# Initial Gallery Images

Drop image files in this folder to be auto-imported into phone galleries on first launch.

## Naming Convention

Each image filename (without extension) is matched against:
1. **Phone NAME** (e.g. `1100.jpg` matches phone named "1100")
2. **Phone ID** (e.g. `0001.jpg` matches phone with ID "0001")

## Multiple images per phone

Append `_2`, `_3`, etc. to add multiple images to the same phone:
- `8800.jpg` -> Nokia 8800
- `8800_2.jpg` -> Nokia 8800 (second image)
- `8800_3.jpg` -> Nokia 8800 (third image)
- `N95.jpg`, `N95_2.png` -> Nokia N95 (two images)

The `_N` suffix is stripped before matching, so all variations link to the same phone.

## Supported formats
- `.jpg`, `.jpeg`, `.png`, `.webp`

## Behavior
- Images are imported ONCE on first matching launch
- A `.gallery_imported.json` marker tracks imported filenames
- Re-importing the same filename is skipped (safe to re-run)
- Adding new files later → next app launch will import only the new ones

## Size
- Recommend keeping images under 1MB each to keep APK size reasonable
- 70 images x 500KB = 35MB added to APK
