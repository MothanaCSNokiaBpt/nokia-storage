"""
Image Helper - Simple, bulletproof image handling.
Images stored as BLOB in SQLite. Written to temp file for Kivy display.
"""
import os
import struct
import zlib
import hashlib
import glob


_cache_dir = None
_default_path = None


def get_cache_dir(app_path):
    global _cache_dir
    if _cache_dir and os.path.isdir(_cache_dir):
        return _cache_dir
    _cache_dir = os.path.join(app_path, "ic")
    try:
        os.makedirs(_cache_dir, exist_ok=True)
    except Exception:
        _cache_dir = app_path
    return _cache_dir


def create_default_png_bytes():
    """64x64 phone silhouette PNG. Pure Python."""
    W, H = 64, 64
    bg, body, scr = (220, 232, 255), (170, 188, 215), (150, 170, 205)
    raw = b''
    for y in range(H):
        raw += b'\x00'
        for x in range(W):
            ib = (20 <= x <= 44) and (6 <= y <= 52)
            isc = (23 <= x <= 41) and (13 <= y <= 38)
            ibtn = ((x-32)**2 + (y-45)**2) <= 16
            if isc: raw += bytes(scr)
            elif ib or ibtn: raw += bytes(body)
            else: raw += bytes(bg)
    comp = zlib.compress(raw, 9)
    def ch(t, d):
        c = t + d
        return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
    p = b'\x89PNG\r\n\x1a\n'
    p += ch(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0))
    p += ch(b'IDAT', comp)
    p += ch(b'IEND', b'')
    return p


def get_default_image_path(app_path):
    global _default_path
    if _default_path and os.path.exists(_default_path):
        return _default_path
    c = get_cache_dir(app_path)
    p = os.path.join(c, "def.png")
    if not os.path.exists(p):
        try:
            with open(p, 'wb') as f:
                f.write(create_default_png_bytes())
        except:
            return ""
    if os.path.exists(p):
        _default_path = p
    return _default_path or ""


def write_blob_to_file(blob_bytes, key, app_path):
    """Write BLOB to uniquely-named file. Returns path or empty string."""
    if not blob_bytes:
        return ""
    c = get_cache_dir(app_path)
    ext = ".png" if blob_bytes[:4] == b'\x89PNG' else ".jpg"
    h = hashlib.md5(blob_bytes[:512]).hexdigest()[:6]
    fname = f"{key}_{h}{ext}"
    path = os.path.join(c, fname)
    if os.path.exists(path):
        return path
    # Remove old versions
    for old in glob.glob(os.path.join(c, f"{key}_*")):
        try: os.remove(old)
        except: pass
    try:
        with open(path, 'wb') as f:
            f.write(blob_bytes)
        return path
    except:
        return ""


def clear_item_cache(key, app_path):
    c = get_cache_dir(app_path)
    for old in glob.glob(os.path.join(c, f"{key}_*")):
        try: os.remove(old)
        except: pass


def read_bytes_from_path(filepath):
    """Read image file bytes. Handles regular paths.
    For Android content:// URIs, returns None (handled separately)."""
    if not filepath:
        return None
    try:
        if os.path.isfile(filepath):
            with open(filepath, "rb") as f:
                data = f.read()
            if data and len(data) > 100:
                return data
    except:
        pass
    return None


def read_android_uri(uri_string):
    """Read bytes from Android content:// URI using file descriptor."""
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        ctx = PythonActivity.mActivity
        Uri = autoclass("android.net.Uri")
        uri = Uri.parse(uri_string)
        # Method: ParcelFileDescriptor -> native Python fd
        pfd = ctx.getContentResolver().openFileDescriptor(uri, "r")
        fd = pfd.detachFd()
        with os.fdopen(fd, "rb") as f:
            data = f.read()
        if data and len(data) > 100:
            return data
    except:
        pass
    # Fallback: InputStream -> Java FileOutputStream -> read file
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        ctx = PythonActivity.mActivity
        Uri = autoclass("android.net.Uri")
        uri = Uri.parse(uri_string)
        inp = ctx.getContentResolver().openInputStream(uri)
        Arr = autoclass("java.lang.reflect.Array")
        Byte = autoclass("java.lang.Byte")
        FOS = autoclass("java.io.FileOutputStream")
        from android.storage import app_storage_path
        tmp = os.path.join(app_storage_path(), "_tmp_read.bin")
        out = FOS(tmp)
        jbuf = Arr.newInstance(Byte.TYPE, 16384)
        while True:
            n = inp.read(jbuf)
            if n == -1:
                break
            out.write(jbuf, 0, n)
        inp.close()
        out.close()
        with open(tmp, "rb") as f:
            data = f.read()
        try: os.remove(tmp)
        except: pass
        if data and len(data) > 100:
            return data
    except:
        pass
    return None


def smart_read(path_or_uri):
    """Read image bytes from any source - file path or content:// URI."""
    if not path_or_uri:
        return None
    # Try regular file first
    data = read_bytes_from_path(path_or_uri)
    if data:
        return data
    # Try as Android content URI
    if path_or_uri.startswith("content://"):
        return read_android_uri(path_or_uri)
    return None
