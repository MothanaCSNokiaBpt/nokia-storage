# Initial Gallery Images

Drop image files in this folder to be auto-imported into phone galleries on first launch.

## Naming Convention

Each image filename (without extension) is matched against:
1. **Phone NAME** (e.g. `1100.jpg` matches phone named "1100")
2. **Phone ID** (e.g. `0001.jpg` matches phone with ID "0001")

If multiple images for the same phone, append a suffix:
- `1100.jpg`
- `1100_2.jpg` (won't match - only exact name match works)

To upload multiple images for the same phone, use unique filenames matching the phone name/ID exactly. For multiple images per phone, manual workaround: rename to include the phone name, e.g. `1100.jpg`, `1100-back.jpg` (only `1100.jpg` will auto-link).

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
