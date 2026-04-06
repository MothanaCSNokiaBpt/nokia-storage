"""
Image Helper - Bulletproof image handling for Android and Desktop.
All images stored as BLOB in SQLite, displayed via temp files written
to the same directory as the database (guaranteed writable).
"""

import os
import struct
import zlib

_cache_dir = None
_default_path = None


def get_cache_dir(app_path):
    """Get/create image cache directory next to the database."""
    global _cache_dir
    if _cache_dir and os.path.isdir(_cache_dir):
        return _cache_dir
    _cache_dir = os.path.join(app_path, "imgcache")
    try:
        os.makedirs(_cache_dir, exist_ok=True)
    except Exception:
        _cache_dir = app_path  # Fallback to app dir itself
    return _cache_dir


def create_default_png_bytes():
    """Generate a 64x64 phone silhouette PNG as raw bytes. Pure Python, no dependencies."""
    W, H = 64, 64
    bg = (220, 232, 255)
    body = (170, 188, 215)
    screen = (150, 170, 205)
    raw = b''
    for y in range(H):
        raw += b'\x00'
        for x in range(W):
            in_body = (20 <= x <= 44) and (6 <= y <= 52)
            in_screen = (23 <= x <= 41) and (13 <= y <= 38)
            in_btn = ((x - 32) ** 2 + (y - 45) ** 2) <= 16
            if in_screen:
                raw += bytes(screen)
            elif in_body or in_btn:
                raw += bytes(body)
            else:
                raw += bytes(bg)
    compressed = zlib.compress(raw, 9)

    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack('>I', len(data)) + c + crc

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', compressed)
    png += chunk(b'IEND', b'')
    return png


def get_default_image_path(app_path):
    """Get path to default phone image. Creates it if needed."""
    global _default_path
    if _default_path and os.path.exists(_default_path):
        return _default_path
    cache = get_cache_dir(app_path)
    path = os.path.join(cache, "_default.png")
    if not os.path.exists(path):
        try:
            data = create_default_png_bytes()
            with open(path, 'wb') as f:
                f.write(data)
        except Exception:
            return ""
    if os.path.exists(path):
        _default_path = path
        return path
    return ""


def blob_to_file(blob_bytes, item_key, app_path):
    """Write image BLOB to a unique cached file. Returns the file path.
    Uses a hash-based filename to avoid Kivy Image cache issues."""
    if not blob_bytes:
        return ""
    cache = get_cache_dir(app_path)
    ext = ".png" if blob_bytes[:4] == b'\x89PNG' else ".jpg"
    # Use data length + first bytes as simple hash for unique filename
    # This ensures Kivy sees a NEW path when image data changes
    import hashlib
    h = hashlib.md5(blob_bytes[:1024]).hexdigest()[:8]
    path = os.path.join(cache, f"{item_key}_{h}{ext}")
    if os.path.exists(path):
        return path  # Already written with same content
    # Clean old versions of this item
    import glob
    for old in glob.glob(os.path.join(cache, f"{item_key}_*")):
        try: os.remove(old)
        except: pass
    try:
        with open(path, 'wb') as f:
            f.write(blob_bytes)
        return path
    except Exception:
        return ""


def clear_cached_image(item_key, app_path):
    """Remove a cached image file so it gets recreated from DB."""
    cache = get_cache_dir(app_path)
    for ext in (".img", ".jpg", ".png"):
        path = os.path.join(cache, f"{item_key}{ext}")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def read_image_from_path(path):
    """Read image bytes from a file path or Android content:// URI."""
    if not path:
        return None

    # Regular file
    if not path.startswith("content://"):
        try:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
        except Exception:
            pass
        return None

    # Android content:// URI
    try:
        from kivy.utils import platform
        if platform != "android":
            return None
    except Exception:
        return None

    # Method 1: ParcelFileDescriptor -> Python fd (most reliable)
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        context = PythonActivity.mActivity
        Uri = autoclass("android.net.Uri")
        uri = Uri.parse(path)
        pfd = context.getContentResolver().openFileDescriptor(uri, "r")
        fd = pfd.detachFd()
        with os.fdopen(fd, "rb") as f:
            data = f.read()
        if data and len(data) > 0:
            return data
    except Exception:
        pass

    # Method 2: InputStream -> temp file via Java FileOutputStream
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        context = PythonActivity.mActivity
        Uri = autoclass("android.net.Uri")
        uri = Uri.parse(path)
        inp = context.getContentResolver().openInputStream(uri)
        FileOutputStream = autoclass("java.io.FileOutputStream")
        Array = autoclass("java.lang.reflect.Array")
        Byte = autoclass("java.lang.Byte")
        tmp_path = os.path.join(os.path.dirname(path) if not path.startswith("content") else "/data/local/tmp", "_read_tmp.bin")
        # Use app cache dir instead
        try:
            from android.storage import app_storage_path
            tmp_path = os.path.join(app_storage_path(), "_read_tmp.bin")
        except Exception:
            tmp_path = "/data/local/tmp/_read_tmp.bin"
        out = FileOutputStream(tmp_path)
        jbuf = Array.newInstance(Byte.TYPE, 8192)
        while True:
            n = inp.read(jbuf)
            if n == -1:
                break
            out.write(jbuf, 0, n)
        inp.close()
        out.close()
        with open(tmp_path, "rb") as f:
            data = f.read()
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        if data and len(data) > 0:
            return data
    except Exception:
        pass

    return None
