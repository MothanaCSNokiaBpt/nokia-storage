"""
Nokia Storage Manager - Android Application
Manage Nokia phones inventory and spare parts with images,
CSV export, search, backup/restore, and reports.
"""

import csv
import json
import os
import shutil
import time
import zipfile
from datetime import datetime
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import (
    StringProperty, ObjectProperty, NumericProperty, BooleanProperty
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

from database import NokiaDatabase

if platform == "android":
    try:
        from android.permissions import request_permissions, Permission
        from android.storage import primary_external_storage_path, app_storage_path
    except Exception:
        pass

PAGE_SIZE = 50

# ── Helpers ─────────────────────────────────────────────────────
def get_app_path():
    if platform == "android":
        try:
            return app_storage_path()
        except Exception:
            return os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.abspath(__file__))

def get_images_path():
    p = os.path.join(get_app_path(), "images")
    os.makedirs(p, exist_ok=True)
    return p

def get_phone_images_path():
    p = os.path.join(get_images_path(), "phones")
    os.makedirs(p, exist_ok=True)
    return p

def get_spare_images_path():
    p = os.path.join(get_images_path(), "spares")
    os.makedirs(p, exist_ok=True)
    return p

def get_phone_gallery_path(phone_id):
    p = os.path.join(get_images_path(), "gallery", phone_id)
    os.makedirs(p, exist_ok=True)
    return p

def get_db_path():
    return os.path.join(get_app_path(), "nokia_storage.db")

def get_downloads_path():
    if platform == "android":
        try:
            return os.path.join(primary_external_storage_path(), "Download")
        except Exception:
            pass
    return os.path.join(get_app_path(), "exports")

DEFAULT_IMG = ""
def _create_default_png(path):
    """Create a 120x120 phone silhouette PNG using only struct+zlib (no Pillow needed)."""
    import struct, zlib
    W, H = 120, 120
    # Pre-render a simple phone icon: light blue bg, darker phone shape
    bg = (230, 238, 255)
    phone_body = (180, 195, 220)
    phone_screen = (160, 178, 210)
    raw = b''
    for y in range(H):
        raw += b'\x00'  # filter byte
        for x in range(W):
            # Phone body: rect from (35,10) to (85,100) with rounded feel
            in_body = 38 <= x <= 82 and 12 <= y <= 98
            # Screen: rect from (43,25) to (77,72)
            in_screen = 43 <= x <= 77 and 25 <= y <= 72
            # Circle button: center(60,84) r=7
            in_btn = (x - 60)**2 + (y - 84)**2 <= 49
            if in_screen:
                raw += bytes(phone_screen)
            elif in_body or in_btn:
                raw += bytes(phone_body)
            else:
                raw += bytes(bg)
    compressed = zlib.compress(raw, 6)
    def chunk(ctype, data):
        c = ctype + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xffffffff)
        return struct.pack('>I', len(data)) + c + crc
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0)))
        f.write(chunk(b'IDAT', compressed))
        f.write(chunk(b'IEND', b''))

def get_default_image():
    global DEFAULT_IMG
    if DEFAULT_IMG and os.path.exists(DEFAULT_IMG):
        return DEFAULT_IMG
    # Check bundled location first (same dir as main.py)
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_phone.png")
    if os.path.exists(src):
        DEFAULT_IMG = src
        return src
    p = os.path.join(get_app_path(), "default_phone.png")
    if not os.path.exists(p):
        try:
            from PIL import Image as PILImage, ImageDraw
            img = PILImage.new("RGB", (120, 120), (230, 238, 255))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle([38, 12, 82, 98], radius=8,
                                    fill=(180, 195, 220), outline=(160, 175, 200), width=1)
            draw.rounded_rectangle([43, 25, 77, 72], radius=3, fill=(160, 178, 210))
            draw.ellipse([53, 77, 67, 91], fill=(160, 178, 210))
            img.save(p, optimize=True)
        except Exception:
            try:
                _create_default_png(p)
            except Exception:
                return ""
    DEFAULT_IMG = p
    return p

def safe_image(path):
    if path and os.path.exists(path):
        return path
    return get_default_image()

def copy_image_to_storage(source_path, dest_folder):
    if not source_path or not os.path.exists(source_path):
        return ""
    ext = os.path.splitext(source_path)[1] or ".jpg"
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
    dest = os.path.join(dest_folder, filename)
    try:
        shutil.copy2(source_path, dest)
        return dest
    except Exception:
        return ""

def get_gallery_images(phone_id):
    gdir = os.path.join(get_images_path(), "gallery", phone_id)
    if not os.path.exists(gdir):
        return []
    exts = ('.jpg', '.jpeg', '.png', '.bmp', '.gif')
    imgs = []
    for f in sorted(os.listdir(gdir)):
        if f.lower().endswith(exts):
            imgs.append(os.path.join(gdir, f))
    return imgs


# ── Custom Widgets ──────────────────────────────────────────────
class ClickableBox(ButtonBehavior, BoxLayout):
    pass

class ClickableLabel(ButtonBehavior, Label):
    pass

class PhoneCard(ButtonBehavior, BoxLayout):
    phone_id = StringProperty("")
    phone_name = StringProperty("")
    phone_date = StringProperty("")
    phone_image = StringProperty("")

class SpareCard(ButtonBehavior, BoxLayout):
    spare_id = NumericProperty(0)
    spare_name = StringProperty("")
    spare_desc = StringProperty("")
    spare_image = StringProperty("")

class SearchBar(BoxLayout):
    def on_search_enter(self, text):
        app = App.get_running_app()
        if app.root:
            screen = app.root.current_screen
            if hasattr(screen, "do_search"):
                screen.do_search(text)


# ── KV Layout ──────────────────────────────────────────────────
KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<ClickableBox>:
<ClickableLabel>:

<PhoneCard>:
    size_hint_y: None
    height: dp(80)
    padding: dp(8)
    spacing: dp(10)
    orientation: 'horizontal'
    canvas.before:
        Color:
            rgba: 1, 1, 1, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
    AsyncImage:
        source: root.phone_image or ''
        size_hint: None, None
        size: dp(62), dp(62)
        pos_hint: {'center_y': .5}
        allow_stretch: True
        keep_ratio: True
    BoxLayout:
        orientation: 'vertical'
        spacing: dp(2)
        padding: 0, dp(4)
        Label:
            text: root.phone_name
            font_size: sp(15)
            bold: True
            color: 0.1, 0.1, 0.18, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.4
        Label:
            text: 'ID: ' + root.phone_id
            font_size: sp(11)
            color: 0.4, 0.4, 0.4, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.3
        Label:
            text: root.phone_date
            font_size: sp(10)
            color: 0.5, 0.5, 0.5, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.3

<SpareCard>:
    size_hint_y: None
    height: dp(74)
    padding: dp(8)
    spacing: dp(10)
    orientation: 'horizontal'
    canvas.before:
        Color:
            rgba: 1, 1, 1, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
    AsyncImage:
        source: root.spare_image or ''
        size_hint: None, None
        size: dp(56), dp(56)
        pos_hint: {'center_y': .5}
        allow_stretch: True
        keep_ratio: True
    BoxLayout:
        orientation: 'vertical'
        spacing: dp(2)
        padding: 0, dp(4)
        Label:
            text: root.spare_name
            font_size: sp(14)
            bold: True
            color: 0.1, 0.1, 0.18, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.5
        Label:
            text: root.spare_desc
            font_size: sp(11)
            color: 0.5, 0.5, 0.5, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.5

<SearchBar>:
    size_hint_y: None
    height: dp(48)
    padding: dp(10), dp(5)
    canvas.before:
        Color:
            rgba: 0.95, 0.96, 0.98, 1
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        canvas.before:
            Color:
                rgba: 1, 1, 1, 1
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(20)]
        padding: dp(12), dp(3)
        spacing: dp(6)
        Label:
            text: 'Search'
            size_hint_x: None
            width: dp(50)
            font_size: sp(12)
            color: 0.5, 0.5, 0.5, 1
        TextInput:
            id: search_input
            hint_text: 'name, ID or date, press Enter'
            multiline: False
            background_color: 0, 0, 0, 0
            foreground_color: 0.1, 0.1, 0.1, 1
            hint_text_color: 0.6, 0.6, 0.6, 1
            cursor_color: 0, 0.314, 0.784, 1
            font_size: sp(13)
            padding: 0, dp(7)
            on_text_validate: root.on_search_enter(self.text)

ScreenManager:
    id: sm
    MainScreen:
        name: 'main'
    PhoneDetailScreen:
        name: 'phone_detail'
    SpareDetailScreen:
        name: 'spare_detail'
    AddPhoneScreen:
        name: 'add_phone'
    AddSpareScreen:
        name: 'add_spare'
    ExportScreen:
        name: 'export_data'
    BulkImageScreen:
        name: 'bulk_images'
    BackupScreen:
        name: 'backup'
    SearchAllScreen:
        name: 'search_all'
    ReportScreen:
        name: 'report'

<MainScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(14), dp(8)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            Label:
                text: 'NOKIA Storage'
                font_size: sp(19)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            ClickableLabel:
                text: 'Menu'
                size_hint_x: None
                width: dp(46)
                font_size: sp(12)
                color: 1, 1, 1, 1
                on_release: root.show_menu()
        SearchBar:
            id: search_bar
        BoxLayout:
            size_hint_y: None
            height: dp(40)
            ClickableBox:
                padding: dp(6)
                on_release: root.switch_tab('phones')
                canvas.before:
                    Color:
                        rgba: (0, 0.314, 0.784, 1) if root.current_tab == 'phones' else (0.92, 0.92, 0.92, 1)
                    Rectangle:
                        pos: self.pos
                        size: self.size
                Label:
                    text: 'Nokia Phones'
                    bold: True
                    font_size: sp(13)
                    color: (1,1,1,1) if root.current_tab == 'phones' else (0.3,0.3,0.3,1)
            ClickableBox:
                padding: dp(6)
                on_release: root.switch_tab('spares')
                canvas.before:
                    Color:
                        rgba: (0, 0.314, 0.784, 1) if root.current_tab == 'spares' else (0.92, 0.92, 0.92, 1)
                    Rectangle:
                        pos: self.pos
                        size: self.size
                Label:
                    text: 'Spare Parts'
                    bold: True
                    font_size: sp(13)
                    color: (1,1,1,1) if root.current_tab == 'spares' else (0.3,0.3,0.3,1)
        ScrollView:
            id: scroll_view
            do_scroll_x: False
            GridLayout:
                id: content_list
                cols: 1
                spacing: dp(6)
                padding: dp(10)
                size_hint_y: None
                height: self.minimum_height
        BoxLayout:
            size_hint_y: None
            height: dp(50)
            padding: dp(10), dp(5)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 1, 1, 1, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            Label:
                id: count_label
                text: '0 items'
                font_size: sp(11)
                color: 0.5, 0.5, 0.5, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            ClickableBox:
                size_hint_x: None
                width: dp(90)
                padding: dp(10), dp(5)
                canvas.before:
                    Color:
                        rgba: 0, 0.314, 0.784, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(20)]
                on_release: root.add_item()
                Label:
                    text: '+ Add'
                    color: 1, 1, 1, 1
                    font_size: sp(13)
                    bold: True
            ClickableBox:
                size_hint_x: None
                width: dp(90)
                padding: dp(10), dp(5)
                canvas.before:
                    Color:
                        rgba: 0, 0.44, 1, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(20)]
                on_release: root.search_all()
                Label:
                    text: 'Search All'
                    color: 1, 1, 1, 1
                    font_size: sp(12)
                    bold: True

<PhoneDetailScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(36)
                text: '<'
                font_size: sp(22)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Phone Details'
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            ClickableLabel:
                size_hint_x: None
                width: dp(44)
                text: 'Edit'
                font_size: sp(13)
                color: 1, 1, 1, 1
                on_release: root.edit_phone()
            ClickableLabel:
                size_hint_x: None
                width: dp(40)
                text: 'Del'
                font_size: sp(13)
                color: 1, 0.6, 0.6, 1
                on_release: root.confirm_delete()
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(14)
                spacing: dp(10)
                BoxLayout:
                    size_hint_y: None
                    height: dp(220)
                    padding: dp(16)
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(14)]
                    AsyncImage:
                        id: phone_image
                        source: root.image_source or ''
                        allow_stretch: True
                        keep_ratio: True
                BoxLayout:
                    size_hint_y: None
                    height: dp(34)
                    spacing: dp(6)
                    ClickableBox:
                        padding: dp(8), dp(4)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.12
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(7)]
                        on_release: root.change_image()
                        Label:
                            text: 'Change Image'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(12)
                            bold: True
                    ClickableBox:
                        padding: dp(8), dp(4)
                        canvas.before:
                            Color:
                                rgba: 0, 0.44, 1, 0.12
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(7)]
                        on_release: root.add_gallery_image()
                        Label:
                            text: '+ Gallery Photo'
                            color: 0, 0.44, 1, 1
                            font_size: sp(12)
                            bold: True
                # Info Card
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(14)
                    spacing: dp(8)
                    canvas.before:
                        Color:
                            rgba: 1, 1, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(10)]
                    Label:
                        text: root.p_name
                        font_size: sp(20)
                        bold: True
                        color: 0.1, 0.1, 0.18, 1
                        size_hint_y: None
                        height: dp(28)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: 'ID: ' + root.p_id
                        font_size: sp(13)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: dp(20)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: 'Release: ' + root.p_date
                        font_size: sp(13)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: dp(20)
                        text_size: self.size
                        halign: 'left'
                    # Conditions VERTICAL
                    BoxLayout:
                        size_hint_y: None
                        height: dp(28)
                        padding: dp(8), dp(4)
                        canvas.before:
                            Color:
                                rgba: 0.26, 0.63, 0.28, 0.12
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(5)]
                        Label:
                            text: 'Appearance: ' + root.p_appear
                            font_size: sp(12)
                            color: 0.26, 0.63, 0.28, 1
                            bold: True
                            text_size: self.size
                            halign: 'left'
                            valign: 'middle'
                    BoxLayout:
                        size_hint_y: None
                        height: dp(28)
                        padding: dp(8), dp(4)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.12
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(5)]
                        Label:
                            text: 'Working: ' + root.p_working
                            font_size: sp(12)
                            color: 0, 0.314, 0.784, 1
                            bold: True
                            text_size: self.size
                            halign: 'left'
                            valign: 'middle'
                    Label:
                        text: 'Remarks:'
                        font_size: sp(12)
                        bold: True
                        color: 0.3, 0.3, 0.3, 1
                        size_hint_y: None
                        height: dp(18)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: root.p_remarks or '-'
                        font_size: sp(12)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: self.texture_size[1] + dp(6)
                        text_size: self.width, None
                        halign: 'left'
                # Gallery
                Label:
                    text: 'Photo Gallery'
                    font_size: sp(15)
                    bold: True
                    color: 0.1, 0.1, 0.18, 1
                    size_hint_y: None
                    height: dp(26)
                    text_size: self.size
                    halign: 'left'
                GridLayout:
                    id: gallery_grid
                    cols: 3
                    spacing: dp(6)
                    size_hint_y: None
                    height: self.minimum_height
                # Spare Parts
                Label:
                    text: 'Related Spare Parts'
                    font_size: sp(15)
                    bold: True
                    color: 0.1, 0.1, 0.18, 1
                    size_hint_y: None
                    height: dp(26)
                    text_size: self.size
                    halign: 'left'
                GridLayout:
                    id: spare_parts_grid
                    cols: 1
                    spacing: dp(6)
                    size_hint_y: None
                    height: self.minimum_height
                ClickableBox:
                    size_hint_y: None
                    height: dp(36)
                    padding: dp(10), dp(6)
                    canvas.before:
                        Color:
                            rgba: 0, 0.314, 0.784, 0.1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(7)]
                    on_release: root.add_spare_for_phone()
                    Label:
                        text: '+ Add Spare Part'
                        color: 0, 0.314, 0.784, 1
                        font_size: sp(13)
                        bold: True
                Widget:
                    size_hint_y: None
                    height: dp(30)

<SpareDetailScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(36)
                text: '<'
                font_size: sp(22)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Spare Part Details'
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            ClickableLabel:
                size_hint_x: None
                width: dp(40)
                text: 'Del'
                font_size: sp(13)
                color: 1, 0.6, 0.6, 1
                on_release: root.confirm_delete()
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(14)
                spacing: dp(10)
                BoxLayout:
                    size_hint_y: None
                    height: dp(220)
                    padding: dp(16)
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(14)]
                    AsyncImage:
                        source: root.s_image or ''
                        allow_stretch: True
                        keep_ratio: True
                ClickableBox:
                    size_hint_y: None
                    height: dp(34)
                    padding: dp(10), dp(5)
                    canvas.before:
                        Color:
                            rgba: 0, 0.314, 0.784, 0.12
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(7)]
                    on_release: root.change_image()
                    Label:
                        text: 'Change Image'
                        color: 0, 0.314, 0.784, 1
                        font_size: sp(12)
                        bold: True
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(14)
                    spacing: dp(8)
                    canvas.before:
                        Color:
                            rgba: 1, 1, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(10)]
                    Label:
                        text: root.s_name
                        font_size: sp(20)
                        bold: True
                        color: 0.1, 0.1, 0.18, 1
                        size_hint_y: None
                        height: dp(28)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: 'ID: ' + root.s_id_str
                        font_size: sp(13)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: dp(20)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: 'Linked Phone: ' + (root.s_phone_id or '-')
                        font_size: sp(13)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: dp(20)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: 'Description:'
                        font_size: sp(12)
                        bold: True
                        color: 0.3, 0.3, 0.3, 1
                        size_hint_y: None
                        height: dp(18)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: root.s_desc or '-'
                        font_size: sp(12)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: self.texture_size[1] + dp(6)
                        text_size: self.width, None
                        halign: 'left'
                Widget:
                    size_hint_y: None
                    height: dp(30)

<AddPhoneScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(36)
                text: '<'
                font_size: sp(22)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: root.screen_title
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(14)
                spacing: dp(12)
                BoxLayout:
                    size_hint_y: None
                    height: dp(160)
                    padding: dp(14)
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(10)]
                    AsyncImage:
                        id: preview_image
                        source: root.image_preview or ''
                        allow_stretch: True
                        keep_ratio: True
                BoxLayout:
                    size_hint_y: None
                    height: dp(36)
                    spacing: dp(6)
                    ClickableBox:
                        padding: dp(6), dp(5)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.12
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(7)]
                        on_release: root.pick_from_gallery()
                        Label:
                            text: 'Gallery'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(12)
                            bold: True
                    ClickableBox:
                        padding: dp(6), dp(5)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.12
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(7)]
                        on_release: root.take_photo()
                        Label:
                            text: 'Camera'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(12)
                            bold: True
                TextInput:
                    id: input_id
                    hint_text: 'Phone ID *'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                TextInput:
                    id: input_name
                    hint_text: 'Phone Name *'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                TextInput:
                    id: input_date
                    hint_text: 'Release Date'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                TextInput:
                    id: input_appear
                    hint_text: 'Appearance Condition'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                TextInput:
                    id: input_working
                    hint_text: 'Working Condition'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                TextInput:
                    id: input_remarks
                    hint_text: 'Remarks'
                    multiline: True
                    size_hint_y: None
                    height: dp(70)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                ClickableBox:
                    size_hint_y: None
                    height: dp(46)
                    padding: dp(14), dp(9)
                    canvas.before:
                        Color:
                            rgba: 0, 0.314, 0.784, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(9)]
                    on_release: root.save_phone()
                    Label:
                        text: 'Save Phone'
                        color: 1, 1, 1, 1
                        font_size: sp(15)
                        bold: True
                Widget:
                    size_hint_y: None
                    height: dp(20)

<AddSpareScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(36)
                text: '<'
                font_size: sp(22)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Add Spare Part'
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(14)
                spacing: dp(12)
                BoxLayout:
                    size_hint_y: None
                    height: dp(160)
                    padding: dp(14)
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(10)]
                    AsyncImage:
                        id: spare_preview_image
                        source: root.image_preview or ''
                        allow_stretch: True
                        keep_ratio: True
                BoxLayout:
                    size_hint_y: None
                    height: dp(36)
                    spacing: dp(6)
                    ClickableBox:
                        padding: dp(6), dp(5)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.12
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(7)]
                        on_release: root.pick_from_gallery()
                        Label:
                            text: 'Gallery'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(12)
                            bold: True
                    ClickableBox:
                        padding: dp(6), dp(5)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.12
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(7)]
                        on_release: root.take_photo()
                        Label:
                            text: 'Camera'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(12)
                            bold: True
                TextInput:
                    id: spare_input_name
                    hint_text: 'Spare Part Name *'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                TextInput:
                    id: spare_input_desc
                    hint_text: 'Description'
                    multiline: True
                    size_hint_y: None
                    height: dp(70)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                TextInput:
                    id: spare_input_phone_id
                    hint_text: 'Link to Phone ID (optional)'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                ClickableBox:
                    size_hint_y: None
                    height: dp(46)
                    padding: dp(14), dp(9)
                    canvas.before:
                        Color:
                            rgba: 0, 0.314, 0.784, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(9)]
                    on_release: root.save_spare()
                    Label:
                        text: 'Save Spare Part'
                        color: 1, 1, 1, 1
                        font_size: sp(15)
                        bold: True
                Widget:
                    size_hint_y: None
                    height: dp(20)

<ExportScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(36)
                text: '<'
                font_size: sp(22)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Export Data'
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
        BoxLayout:
            orientation: 'vertical'
            padding: dp(18)
            spacing: dp(14)
            Label:
                text: 'Export all data as CSV files\\nsaved to Downloads folder.'
                font_size: sp(14)
                color: 0.3, 0.3, 0.3, 1
                text_size: self.width, None
                size_hint_y: None
                height: self.texture_size[1] + dp(10)
                halign: 'left'
            Label:
                id: export_status
                text: ''
                font_size: sp(13)
                color: 0.26, 0.63, 0.28, 1
                size_hint_y: None
                height: dp(50)
                text_size: self.width, None
                halign: 'left'
            ClickableBox:
                size_hint_y: None
                height: dp(48)
                padding: dp(14), dp(10)
                canvas.before:
                    Color:
                        rgba: 0, 0.314, 0.784, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(9)]
                on_release: root.do_export()
                Label:
                    text: 'Export to CSV'
                    color: 1, 1, 1, 1
                    font_size: sp(15)
                    bold: True
            Widget:

<BulkImageScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(36)
                text: '<'
                font_size: sp(22)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Bulk Image Import'
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
        BoxLayout:
            orientation: 'vertical'
            padding: dp(14)
            spacing: dp(10)
            BoxLayout:
                size_hint_y: None
                height: dp(36)
                spacing: dp(6)
                ClickableBox:
                    padding: dp(10), dp(5)
                    canvas.before:
                        Color:
                            rgba: (0, 0.314, 0.784, 1) if root.target_type == 'phones' else (0.9, 0.9, 0.9, 1)
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(7)]
                    on_release: root.set_target('phones')
                    Label:
                        text: 'Phones'
                        color: (1,1,1,1) if root.target_type == 'phones' else (0.3,0.3,0.3,1)
                        font_size: sp(12)
                        bold: True
                ClickableBox:
                    padding: dp(10), dp(5)
                    canvas.before:
                        Color:
                            rgba: (0, 0.314, 0.784, 1) if root.target_type == 'spares' else (0.9, 0.9, 0.9, 1)
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(7)]
                    on_release: root.set_target('spares')
                    Label:
                        text: 'Spare Parts'
                        color: (1,1,1,1) if root.target_type == 'spares' else (0.3,0.3,0.3,1)
                        font_size: sp(12)
                        bold: True
            ClickableBox:
                size_hint_y: None
                height: dp(40)
                padding: dp(10), dp(7)
                canvas.before:
                    Color:
                        rgba: 0, 0.314, 0.784, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(9)]
                on_release: root.select_images()
                Label:
                    text: 'Select Images'
                    color: 1, 1, 1, 1
                    font_size: sp(13)
                    bold: True
            Label:
                id: bulk_status
                text: 'Select images to assign'
                font_size: sp(12)
                color: 0.5, 0.5, 0.5, 1
                size_hint_y: None
                height: dp(20)
            ScrollView:
                do_scroll_x: False
                GridLayout:
                    id: bulk_grid
                    cols: 1
                    spacing: dp(8)
                    size_hint_y: None
                    height: self.minimum_height

<BackupScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(36)
                text: '<'
                font_size: sp(22)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Backup & Restore'
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
        BoxLayout:
            orientation: 'vertical'
            padding: dp(18)
            spacing: dp(14)
            Label:
                text: 'Full backup of data + images.\\nRestore on new device.'
                font_size: sp(13)
                color: 0.3, 0.3, 0.3, 1
                text_size: self.width, None
                size_hint_y: None
                height: self.texture_size[1] + dp(6)
                halign: 'left'
            ClickableBox:
                size_hint_y: None
                height: dp(46)
                padding: dp(14), dp(10)
                canvas.before:
                    Color:
                        rgba: 0.26, 0.63, 0.28, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(9)]
                on_release: root.create_backup()
                Label:
                    text: 'Create Backup'
                    color: 1, 1, 1, 1
                    font_size: sp(15)
                    bold: True
            ClickableBox:
                size_hint_y: None
                height: dp(46)
                padding: dp(14), dp(10)
                canvas.before:
                    Color:
                        rgba: 1, 0.6, 0, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(9)]
                on_release: root.restore_backup()
                Label:
                    text: 'Restore from Backup'
                    color: 1, 1, 1, 1
                    font_size: sp(15)
                    bold: True
            Label:
                id: backup_status
                text: ''
                font_size: sp(12)
                color: 0.26, 0.63, 0.28, 1
                size_hint_y: None
                height: dp(60)
                text_size: self.width, None
                halign: 'left'
            Widget:

<SearchAllScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(36)
                text: '<'
                font_size: sp(22)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Search All'
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
        SearchBar:
            id: search_all_bar
        ScrollView:
            do_scroll_x: False
            GridLayout:
                id: results_list
                cols: 1
                spacing: dp(6)
                padding: dp(10)
                size_hint_y: None
                height: self.minimum_height

<ReportScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(36)
                text: '<'
                font_size: sp(22)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Storage Report'
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
        ScrollView:
            do_scroll_x: False
            GridLayout:
                id: report_grid
                cols: 1
                spacing: dp(8)
                padding: dp(14)
                size_hint_y: None
                height: self.minimum_height
"""


# ── Screen Classes ──────────────────────────────────────────────

class MainScreen(Screen):
    current_tab = StringProperty("phones")
    _all_items = []
    _current_page = 0
    _total_items = 0
    _is_search = False

    def on_enter(self):
        Clock.schedule_once(lambda dt: self.refresh_list(), 0.2)

    def switch_tab(self, tab):
        self.current_tab = tab
        self._current_page = 0
        self._is_search = False
        try:
            self.ids.search_bar.ids.search_input.text = ""
        except Exception:
            pass
        self.refresh_list()

    def refresh_list(self):
        app = App.get_running_app()
        if not app.db:
            return
        self._current_page = 0
        if self.current_tab == "phones":
            self._all_items = app.db.get_all_phones()
        else:
            self._all_items = app.db.get_all_spare_parts()
        self._total_items = len(self._all_items)
        self._is_search = False
        self._render_page()

    def do_search(self, text):
        app = App.get_running_app()
        if not text.strip():
            self.refresh_list()
            return
        self._current_page = 0
        if self.current_tab == "phones":
            self._all_items = app.db.search_phones(text)
        else:
            self._all_items = app.db.search_spare_parts(text)
        self._total_items = len(self._all_items)
        self._is_search = True
        self._render_page()

    def _render_page(self):
        grid = self.ids.content_list
        grid.clear_widgets()
        start = self._current_page * PAGE_SIZE
        end = min(start + PAGE_SIZE, self._total_items)
        page_items = self._all_items[start:end]
        total_pages = max(1, (self._total_items + PAGE_SIZE - 1) // PAGE_SIZE)
        cur_pg = self._current_page + 1
        lbl_type = "found" if self._is_search else ("phones" if self.current_tab == "phones" else "parts")
        self.ids.count_label.text = f"{self._total_items} {lbl_type} | {cur_pg}/{total_pages}"

        if self.current_tab == "phones":
            for p in page_items:
                card = PhoneCard(
                    phone_id=p["id"], phone_name=p["name"],
                    phone_date=p.get("release_date", "") or "",
                    phone_image=safe_image(p.get("image_path", "")),
                )
                card.bind(on_release=partial(self._open_phone, p["id"]))
                grid.add_widget(card)
        else:
            for s in page_items:
                card = SpareCard(
                    spare_id=s["id"], spare_name=s["name"],
                    spare_desc=s.get("description", "") or "",
                    spare_image=safe_image(s.get("image_path", "")),
                )
                card.bind(on_release=partial(self._open_spare, s["id"]))
                grid.add_widget(card)

        if self._total_items > PAGE_SIZE:
            pager = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6), padding=(dp(4), dp(4)))
            if self._current_page > 0:
                pb = ClickableBox(padding=(dp(10), dp(4)))
                with pb.canvas.before:
                    Color(0, 0.314, 0.784, 1)
                    pb._bg = RoundedRectangle(pos=pb.pos, size=pb.size, radius=[dp(7)])
                pb.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
                pb.add_widget(Label(text="< Prev", color=(1,1,1,1), font_size=sp(12), bold=True))
                pb.bind(on_release=lambda *a: self._go_page(-1))
                pager.add_widget(pb)
            else:
                pager.add_widget(Widget())
            pager.add_widget(Label(text=f"{cur_pg}/{total_pages}", font_size=sp(12), color=(0.4,0.4,0.4,1), size_hint_x=None, width=dp(50)))
            if end < self._total_items:
                nb = ClickableBox(padding=(dp(10), dp(4)))
                with nb.canvas.before:
                    Color(0, 0.314, 0.784, 1)
                    nb._bg = RoundedRectangle(pos=nb.pos, size=nb.size, radius=[dp(7)])
                nb.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
                nb.add_widget(Label(text="Next >", color=(1,1,1,1), font_size=sp(12), bold=True))
                nb.bind(on_release=lambda *a: self._go_page(1))
                pager.add_widget(nb)
            else:
                pager.add_widget(Widget())
            grid.add_widget(pager)
        try:
            self.ids.scroll_view.scroll_y = 1
        except Exception:
            pass

    def _go_page(self, d):
        self._current_page += d
        self._render_page()

    def _open_phone(self, pid, *a):
        app = App.get_running_app()
        app.root.get_screen("phone_detail").load_phone(pid)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "phone_detail"

    def _open_spare(self, sid, *a):
        app = App.get_running_app()
        app.root.get_screen("spare_detail").load_spare(sid)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "spare_detail"

    def add_item(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="left")
        if self.current_tab == "phones":
            s = app.root.get_screen("add_phone")
            s.edit_mode = False
            s.clear_form()
            app.root.current = "add_phone"
        else:
            s = app.root.get_screen("add_spare")
            s.clear_form()
            app.root.current = "add_spare"

    def search_all(self):
        app = App.get_running_app()
        try:
            q = self.ids.search_bar.ids.search_input.text
        except Exception:
            q = ""
        app.root.get_screen("search_all").initial_query = q
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "search_all"

    def show_menu(self):
        app = App.get_running_app()
        popup = ModalView(size_hint=(0.72, None), height=dp(240))
        content = BoxLayout(orientation="vertical", spacing=dp(2), padding=dp(10))
        with content.canvas.before:
            Color(1, 1, 1, 1)
            content._bg = RoundedRectangle(pos=content.pos, size=content.size, radius=[dp(10)])
        content.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        for txt, tgt in [("Export Data", "export_data"), ("Bulk Image Import", "bulk_images"),
                          ("Backup & Restore", "backup"), ("Storage Report", "report")]:
            btn = ClickableBox(size_hint_y=None, height=dp(46), padding=(dp(14), dp(8)))
            btn.add_widget(Label(text=txt, font_size=sp(14), color=(0.1,0.1,0.18,1), text_size=(dp(200), None), halign="left"))
            btn.bind(on_release=lambda *a, t=tgt, p=popup: (p.dismiss(), self._goto(t)))
            content.add_widget(btn)
        popup.add_widget(content)
        popup.open()

    def _goto(self, name):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="left")
        app.root.current = name


class PhoneDetailScreen(Screen):
    p_id = StringProperty("")
    p_name = StringProperty("")
    p_date = StringProperty("")
    p_appear = StringProperty("")
    p_working = StringProperty("")
    p_remarks = StringProperty("")
    image_source = StringProperty("")

    def load_phone(self, phone_id):
        app = App.get_running_app()
        phone = app.db.get_phone(phone_id)
        if not phone:
            return
        self.p_id = phone["id"]
        self.p_name = phone["name"]
        self.p_date = phone.get("release_date", "") or ""
        self.p_appear = phone.get("appearance_condition", "") or ""
        self.p_working = phone.get("working_condition", "") or ""
        r = phone.get("remarks", "") or ""
        self.p_remarks = "" if r == "None" or r == "none" else r
        self.image_source = safe_image(phone.get("image_path", ""))
        Clock.schedule_once(lambda dt: self._load_extras(), 0.1)

    def _load_extras(self):
        self._load_gallery()
        self._load_spares()

    def _load_gallery(self):
        grid = self.ids.gallery_grid
        grid.clear_widgets()
        imgs = get_gallery_images(self.p_id)
        if not imgs:
            grid.add_widget(Label(text="No gallery photos", font_size=sp(12), color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(24)))
            return
        for img_path in imgs:
            box = BoxLayout(size_hint_y=None, height=dp(100), padding=dp(2))
            box.add_widget(AsyncImage(source=img_path, allow_stretch=True, keep_ratio=True))
            grid.add_widget(box)

    def _load_spares(self):
        app = App.get_running_app()
        grid = self.ids.spare_parts_grid
        grid.clear_widgets()
        spares = app.db.get_spare_parts_for_phone(self.p_name)
        if not spares:
            grid.add_widget(Label(text="No spare parts", font_size=sp(12), color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(24)))
            return
        for s in spares:
            card = SpareCard(spare_id=s["id"], spare_name=s["name"],
                             spare_desc=s.get("description", "") or "",
                             spare_image=safe_image(s.get("image_path", "")))
            card.bind(on_release=partial(self._open_spare, s["id"]))
            grid.add_widget(card)

    def _open_spare(self, sid, *a):
        app = App.get_running_app()
        app.root.get_screen("spare_detail").load_spare(sid)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "spare_detail"

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"

    def edit_phone(self):
        app = App.get_running_app()
        s = app.root.get_screen("add_phone")
        s.edit_mode = True
        s.load_for_edit(self.p_id)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "add_phone"

    def confirm_delete(self):
        popup = ModalView(size_hint=(0.78, None), height=dp(130))
        c = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        with c.canvas.before:
            Color(1,1,1,1)
            c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        c.add_widget(Label(text=f"Delete {self.p_name}?", font_size=sp(15), color=(0.1,0.1,0.18,1), size_hint_y=None, height=dp(28)))
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        cb = ClickableBox(padding=(dp(8), dp(5)))
        cb.add_widget(Label(text="Cancel", font_size=sp(13), color=(0.4,0.4,0.4,1)))
        cb.bind(on_release=lambda *a: popup.dismiss())
        db = ClickableBox(padding=(dp(8), dp(5)))
        with db.canvas.before:
            Color(0.9, 0.22, 0.21, 1)
            db._bg = RoundedRectangle(pos=db.pos, size=db.size, radius=[dp(7)])
        db.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        db.add_widget(Label(text="Delete", font_size=sp(13), color=(1,1,1,1), bold=True))
        db.bind(on_release=lambda *a: self._do_delete(popup))
        row.add_widget(cb)
        row.add_widget(db)
        c.add_widget(row)
        popup.add_widget(c)
        popup.open()

    def _do_delete(self, popup):
        app = App.get_running_app()
        app.db.delete_phone(self.p_id)
        popup.dismiss()
        self.go_back()

    def change_image(self):
        app = App.get_running_app()
        popup = ModalView(size_hint=(0.7, None), height=dp(120))
        c = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(10))
        with c.canvas.before:
            Color(1,1,1,1)
            c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        gb = ClickableBox(size_hint_y=None, height=dp(42), padding=(dp(10), dp(6)))
        gb.add_widget(Label(text="Pick from Gallery", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        gb.bind(on_release=lambda *a: (popup.dismiss(), self._pick_image_gallery()))
        cb = ClickableBox(size_hint_y=None, height=dp(42), padding=(dp(10), dp(6)))
        cb.add_widget(Label(text="Take Photo", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        cb.bind(on_release=lambda *a: (popup.dismiss(), self._pick_image_camera()))
        c.add_widget(gb)
        c.add_widget(cb)
        popup.add_widget(c)
        popup.open()

    def _pick_image_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("phone", self.p_id)
        app.open_file_chooser()

    def _pick_image_camera(self):
        app = App.get_running_app()
        app.pick_image_for = ("phone", self.p_id)
        app.take_camera_photo()

    def add_gallery_image(self):
        app = App.get_running_app()
        app.pick_image_for = ("phone_gallery", self.p_id)
        app.open_file_chooser(multiple=True)

    def add_spare_for_phone(self):
        app = App.get_running_app()
        s = app.root.get_screen("add_spare")
        s.clear_form()
        Clock.schedule_once(lambda dt: self._prefill(s), 0.2)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "add_spare"

    def _prefill(self, s):
        try:
            s.ids.spare_input_name.text = self.p_name
            s.ids.spare_input_phone_id.text = self.p_id
        except Exception:
            pass


class SpareDetailScreen(Screen):
    s_id = NumericProperty(0)
    s_id_str = StringProperty("")
    s_name = StringProperty("")
    s_desc = StringProperty("")
    s_phone_id = StringProperty("")
    s_image = StringProperty("")

    def load_spare(self, spare_id):
        app = App.get_running_app()
        spare = app.db.get_spare_part(spare_id)
        if not spare:
            return
        self.s_id = spare["id"]
        self.s_id_str = str(spare["id"])
        self.s_name = spare["name"]
        d = spare.get("description", "") or ""
        self.s_desc = "" if d == "None" else d
        self.s_phone_id = spare.get("phone_id", "") or ""
        self.s_image = safe_image(spare.get("image_path", ""))

    def change_image(self):
        app = App.get_running_app()
        popup = ModalView(size_hint=(0.7, None), height=dp(120))
        c = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(10))
        with c.canvas.before:
            Color(1,1,1,1)
            c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        gb = ClickableBox(size_hint_y=None, height=dp(42), padding=(dp(10), dp(6)))
        gb.add_widget(Label(text="Pick from Gallery", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        gb.bind(on_release=lambda *a: (popup.dismiss(), self._pick_gallery()))
        cb = ClickableBox(size_hint_y=None, height=dp(42), padding=(dp(10), dp(6)))
        cb.add_widget(Label(text="Take Photo", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        cb.bind(on_release=lambda *a: (popup.dismiss(), self._pick_camera()))
        c.add_widget(gb)
        c.add_widget(cb)
        popup.add_widget(c)
        popup.open()

    def _pick_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("spare_direct", self.s_id)
        app.open_file_chooser()

    def _pick_camera(self):
        app = App.get_running_app()
        app.pick_image_for = ("spare_direct", self.s_id)
        app.take_camera_photo()

    def confirm_delete(self):
        popup = ModalView(size_hint=(0.78, None), height=dp(130))
        c = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        with c.canvas.before:
            Color(1,1,1,1)
            c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        c.add_widget(Label(text=f"Delete {self.s_name}?", font_size=sp(15), color=(0.1,0.1,0.18,1), size_hint_y=None, height=dp(28)))
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        cb = ClickableBox(padding=(dp(8), dp(5)))
        cb.add_widget(Label(text="Cancel", font_size=sp(13)))
        cb.bind(on_release=lambda *a: popup.dismiss())
        db = ClickableBox(padding=(dp(8), dp(5)))
        with db.canvas.before:
            Color(0.9, 0.22, 0.21, 1)
            db._bg = RoundedRectangle(pos=db.pos, size=db.size, radius=[dp(7)])
        db.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        db.add_widget(Label(text="Delete", font_size=sp(13), color=(1,1,1,1), bold=True))
        db.bind(on_release=lambda *a: self._do_delete(popup))
        row.add_widget(cb)
        row.add_widget(db)
        c.add_widget(row)
        popup.add_widget(c)
        popup.open()

    def _do_delete(self, popup):
        app = App.get_running_app()
        app.db.delete_spare_part(self.s_id)
        popup.dismiss()
        self.go_back()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"


class AddPhoneScreen(Screen):
    edit_mode = BooleanProperty(False)
    screen_title = StringProperty("Add Phone")
    image_preview = StringProperty("")
    _selected_image = StringProperty("")

    def on_edit_mode(self, *a):
        self.screen_title = "Edit Phone" if self.edit_mode else "Add Phone"

    def clear_form(self):
        self.image_preview = get_default_image()
        self._selected_image = ""
        Clock.schedule_once(self._clear, 0.1)

    def _clear(self, *a):
        try:
            for fid in ["input_id", "input_name", "input_date", "input_appear", "input_working", "input_remarks"]:
                self.ids[fid].text = ""
        except Exception:
            pass

    def load_for_edit(self, pid):
        app = App.get_running_app()
        phone = app.db.get_phone(pid)
        if not phone:
            return
        self.image_preview = safe_image(phone.get("image_path", ""))
        self._selected_image = phone.get("image_path", "") or ""
        Clock.schedule_once(partial(self._fill, phone), 0.1)

    def _fill(self, phone, *a):
        try:
            self.ids.input_id.text = phone["id"]
            self.ids.input_name.text = phone["name"]
            self.ids.input_date.text = phone.get("release_date", "") or ""
            self.ids.input_appear.text = phone.get("appearance_condition", "") or ""
            self.ids.input_working.text = phone.get("working_condition", "") or ""
            r = phone.get("remarks", "") or ""
            self.ids.input_remarks.text = "" if r == "None" else r
        except Exception:
            pass

    def pick_from_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_phone_screen", None)
        app.open_file_chooser()

    def take_photo(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_phone_screen", None)
        app.take_camera_photo()

    def on_image_selected(self, path):
        self._selected_image = path
        self.image_preview = ""
        Clock.schedule_once(lambda dt: setattr(self, "image_preview", path), 0.1)

    def save_phone(self):
        app = App.get_running_app()
        try:
            pid = self.ids.input_id.text.strip()
            name = self.ids.input_name.text.strip()
        except Exception:
            return
        if not pid or not name:
            app.show_toast("ID and Name required")
            return
        img = self._selected_image
        if img and not img.startswith(get_phone_images_path()):
            img = copy_image_to_storage(img, get_phone_images_path())
        app.db.add_phone(
            phone_id=pid, name=name,
            release_date=self.ids.input_date.text.strip(),
            appearance=self.ids.input_appear.text.strip(),
            working=self.ids.input_working.text.strip(),
            remarks=self.ids.input_remarks.text.strip(),
            image_path=img or "",
        )
        app.show_toast("Phone saved!")
        self.go_back()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"


class AddSpareScreen(Screen):
    image_preview = StringProperty("")
    _selected_image = StringProperty("")

    def clear_form(self):
        self.image_preview = get_default_image()
        self._selected_image = ""
        Clock.schedule_once(self._clear, 0.1)

    def _clear(self, *a):
        try:
            self.ids.spare_input_name.text = ""
            self.ids.spare_input_desc.text = ""
            self.ids.spare_input_phone_id.text = ""
        except Exception:
            pass

    def pick_from_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_spare_screen", None)
        app.open_file_chooser()

    def take_photo(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_spare_screen", None)
        app.take_camera_photo()

    def on_image_selected(self, path):
        self._selected_image = path
        self.image_preview = ""
        Clock.schedule_once(lambda dt: setattr(self, "image_preview", path), 0.1)

    def save_spare(self):
        app = App.get_running_app()
        try:
            name = self.ids.spare_input_name.text.strip()
        except Exception:
            return
        if not name:
            app.show_toast("Name required")
            return
        img = self._selected_image
        if img and not img.startswith(get_spare_images_path()):
            img = copy_image_to_storage(img, get_spare_images_path())
        app.db.add_spare_part(
            name=name,
            phone_id=self.ids.spare_input_phone_id.text.strip(),
            image_path=img or "",
            description=self.ids.spare_input_desc.text.strip(),
        )
        app.show_toast("Spare part saved!")
        self.go_back()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"


class ExportScreen(Screen):
    def do_export(self):
        app = App.get_running_app()
        try:
            out_dir = get_downloads_path()
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            phones_path = os.path.join(out_dir, f"nokia_phones_{ts}.csv")
            phones = app.db.export_phones()
            with open(phones_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ID", "Name", "Release Date", "Appearance", "Working", "Remarks"])
                for p in phones:
                    w.writerow([p["id"], p["name"], p.get("release_date", ""),
                                p.get("appearance_condition", ""), p.get("working_condition", ""),
                                p.get("remarks", "")])
            spares_path = os.path.join(out_dir, f"nokia_spares_{ts}.csv")
            spares = app.db.export_spare_parts()
            with open(spares_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ID", "Name", "Phone ID", "Description"])
                for s in spares:
                    w.writerow([s["id"], s["name"], s.get("phone_id", ""), s.get("description", "")])
            self.ids.export_status.text = f"Saved to Downloads:\\n{os.path.basename(phones_path)}\\n{os.path.basename(spares_path)}"
            self.ids.export_status.color = (0.26, 0.63, 0.28, 1)
            app.show_toast("Exported to Downloads!")
        except Exception as e:
            self.ids.export_status.text = f"Error: {str(e)[:80]}"
            self.ids.export_status.color = (0.9, 0.22, 0.21, 1)

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class BulkImageScreen(Screen):
    target_type = StringProperty("phones")

    def set_target(self, t):
        self.target_type = t

    def select_images(self):
        app = App.get_running_app()
        app.pick_image_for = ("bulk_images", self.target_type)
        app.open_file_chooser(multiple=True)

    def on_images_selected(self, paths):
        grid = self.ids.bulk_grid
        grid.clear_widgets()
        self.ids.bulk_status.text = f"{len(paths)} images selected"
        for path in paths:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(90), spacing=dp(6), padding=dp(3))
            row.add_widget(AsyncImage(source=path, size_hint=(None, 1), width=dp(70), allow_stretch=True, keep_ratio=True))
            form = BoxLayout(orientation="vertical", spacing=dp(3))
            ni = TextInput(hint_text="Name", multiline=False, size_hint_y=None, height=dp(34), font_size=sp(12))
            form.add_widget(ni)
            ii = None
            if self.target_type == "phones":
                ii = TextInput(hint_text="Phone ID", multiline=False, size_hint_y=None, height=dp(34), font_size=sp(12))
                form.add_widget(ii)
            row.add_widget(form)
            row._path, row._name_input, row._id_input = path, ni, ii
            grid.add_widget(row)
        sb = ClickableBox(size_hint_y=None, height=dp(42), padding=(dp(10), dp(7)))
        with sb.canvas.before:
            Color(0, 0.314, 0.784, 1)
            sb._bg = RoundedRectangle(pos=sb.pos, size=sb.size, radius=[dp(8)])
        sb.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        sb.add_widget(Label(text="Save All", color=(1,1,1,1), font_size=sp(14), bold=True))
        sb.bind(on_release=lambda *a: self._save_all())
        grid.add_widget(sb)

    def _save_all(self):
        app = App.get_running_app()
        count = 0
        for child in list(self.ids.bulk_grid.children):
            if not hasattr(child, "_path"):
                continue
            name = child._name_input.text.strip()
            if not name:
                continue
            if self.target_type == "phones":
                pid = child._id_input.text.strip() if child._id_input else f"BULK-{datetime.now().strftime('%H%M%S%f')}"
                img = copy_image_to_storage(child._path, get_phone_images_path())
                app.db.add_phone(phone_id=pid or f"BULK-{count}", name=name, image_path=img)
            else:
                img = copy_image_to_storage(child._path, get_spare_images_path())
                app.db.add_spare_part(name=name, image_path=img)
            count += 1
        self.ids.bulk_status.text = f"Saved {count} items!"
        app.show_toast(f"Saved {count}!")

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class BackupScreen(Screen):
    def create_backup(self):
        app = App.get_running_app()
        try:
            out_dir = get_downloads_path()
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bf = os.path.join(out_dir, f"nokia_backup_{ts}.zip")
            with zipfile.ZipFile(bf, "w", zipfile.ZIP_DEFLATED) as zf:
                dp_ = get_db_path()
                if os.path.exists(dp_):
                    zf.write(dp_, "nokia_storage.db")
                idir = get_images_path()
                if os.path.exists(idir):
                    for rd, ds, fs in os.walk(idir):
                        for f in fs:
                            fp = os.path.join(rd, f)
                            zf.write(fp, os.path.relpath(fp, get_app_path()))
            self.ids.backup_status.text = f"Backup saved to Downloads:\\n{os.path.basename(bf)}"
            self.ids.backup_status.color = (0.26, 0.63, 0.28, 1)
            app.show_toast("Backup created in Downloads!")
        except Exception as e:
            self.ids.backup_status.text = f"Error: {str(e)[:80]}"
            self.ids.backup_status.color = (0.9, 0.22, 0.21, 1)

    def restore_backup(self):
        app = App.get_running_app()
        app.pick_image_for = ("restore_backup", None)
        app.open_file_chooser(filters=["*.zip"])

    def on_backup_selected(self, path):
        app = App.get_running_app()
        try:
            app.db.close()
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(get_app_path())
            app.db = NokiaDatabase(get_db_path())
            self.ids.backup_status.text = "Restore complete!"
            self.ids.backup_status.color = (0.26, 0.63, 0.28, 1)
            app.show_toast("Restored!")
        except Exception as e:
            app.db = NokiaDatabase(get_db_path())
            self.ids.backup_status.text = f"Error: {str(e)[:80]}"
            self.ids.backup_status.color = (0.9, 0.22, 0.21, 1)

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class SearchAllScreen(Screen):
    initial_query = StringProperty("")

    def on_enter(self):
        if self.initial_query:
            Clock.schedule_once(self._set_q, 0.1)

    def _set_q(self, *a):
        try:
            self.ids.search_all_bar.ids.search_input.text = self.initial_query
        except Exception:
            pass
        self.do_search(self.initial_query)

    def do_search(self, text):
        app = App.get_running_app()
        grid = self.ids.results_list
        grid.clear_widgets()
        if not text.strip():
            grid.add_widget(Label(text="Type and press Enter", font_size=sp(13), color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(36)))
            return
        phones, spares = app.db.search_all(text)
        if phones:
            shown = phones[:PAGE_SIZE]
            grid.add_widget(Label(text=f"Phones ({len(phones)})", font_size=sp(14), bold=True, color=(0,0.314,0.784,1), size_hint_y=None, height=dp(26), text_size=(dp(300), None), halign="left"))
            for p in shown:
                card = PhoneCard(phone_id=p["id"], phone_name=p["name"], phone_date=p.get("release_date","") or "", phone_image=safe_image(p.get("image_path","")))
                card.bind(on_release=partial(self._open_phone, p["id"]))
                grid.add_widget(card)
        if spares:
            shown_s = spares[:PAGE_SIZE]
            grid.add_widget(Label(text=f"Spare Parts ({len(spares)})", font_size=sp(14), bold=True, color=(0,0.314,0.784,1), size_hint_y=None, height=dp(26), text_size=(dp(300), None), halign="left"))
            for s in shown_s:
                card = SpareCard(spare_id=s["id"], spare_name=s["name"], spare_desc=s.get("description","") or "", spare_image=safe_image(s.get("image_path","")))
                card.bind(on_release=partial(self._open_spare, s["id"]))
                grid.add_widget(card)
        if not phones and not spares:
            grid.add_widget(Label(text="No results", font_size=sp(13), color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(36)))

    def _open_phone(self, pid, *a):
        app = App.get_running_app()
        app.root.get_screen("phone_detail").load_phone(pid)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "phone_detail"

    def _open_spare(self, sid, *a):
        app = App.get_running_app()
        app.root.get_screen("spare_detail").load_spare(sid)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "spare_detail"

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class ReportScreen(Screen):
    def on_enter(self):
        Clock.schedule_once(lambda dt: self._load_report(), 0.2)

    def _load_report(self):
        app = App.get_running_app()
        grid = self.ids.report_grid
        grid.clear_widgets()
        try:
            r = app.db.get_report()
        except Exception:
            grid.add_widget(Label(text="Error loading report", font_size=sp(14), color=(0.9,0.2,0.2,1), size_hint_y=None, height=dp(30)))
            return

        def section(title):
            grid.add_widget(Label(text=title, font_size=sp(16), bold=True, color=(0,0.314,0.784,1), size_hint_y=None, height=dp(30), text_size=(dp(300), None), halign="left"))

        def stat(label, value):
            row = BoxLayout(size_hint_y=None, height=dp(26), padding=(dp(8), dp(2)))
            row.add_widget(Label(text=label, font_size=sp(13), color=(0.3,0.3,0.3,1), text_size=(dp(220), None), halign="left"))
            row.add_widget(Label(text=str(value), font_size=sp(13), bold=True, color=(0.1,0.1,0.18,1), size_hint_x=None, width=dp(60), halign="right", text_size=(dp(60), None)))
            grid.add_widget(row)

        # Overview
        section("Overview")
        box = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(12), spacing=dp(6))
        box.height = dp(120)
        with box.canvas.before:
            Color(1,1,1,1)
            box._bg = RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(10)])
        box.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        box.add_widget(Label(text=f"Total Phones: {r['total_phones']}", font_size=sp(16), bold=True, color=(0.1,0.1,0.18,1), size_hint_y=None, height=dp(24), text_size=(dp(280), None), halign="left"))
        box.add_widget(Label(text=f"Unique Models: {r['unique_models']}", font_size=sp(14), color=(0.3,0.3,0.3,1), size_hint_y=None, height=dp(22), text_size=(dp(280), None), halign="left"))
        box.add_widget(Label(text=f"With Images: {r['phones_with_images']}", font_size=sp(14), color=(0.3,0.3,0.3,1), size_hint_y=None, height=dp(22), text_size=(dp(280), None), halign="left"))
        box.add_widget(Label(text=f"Total Spare Parts: {r['total_spares']}", font_size=sp(14), color=(0.3,0.3,0.3,1), size_hint_y=None, height=dp(22), text_size=(dp(280), None), halign="left"))
        grid.add_widget(box)

        # By working condition
        section("By Working Condition")
        for name, cnt in r.get("by_working", []):
            stat(name, cnt)

        # By appearance
        section("By Appearance")
        for name, cnt in r.get("by_appearance", []):
            stat(name, cnt)

        # Top models
        section("Top 20 Models (by count)")
        for name, cnt in r.get("by_model", []):
            stat(name, cnt)

        # By year
        section("By Release Year")
        for name, cnt in r.get("by_year", []):
            stat(str(name), cnt)

        grid.add_widget(Widget(size_hint_y=None, height=dp(30)))

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


# ── Main App ────────────────────────────────────────────────────

class NokiaStorageApp(App):
    title = "Nokia Storage"
    db = ObjectProperty(None, allownone=True)
    pick_image_for = None
    _last_back_time = 0

    def build(self):
        Window.clearcolor = (0.94, 0.96, 1, 1)
        try:
            self.db = NokiaDatabase(get_db_path())
        except Exception as e:
            print(f"DB Error: {e}")
        try:
            get_default_image()
        except Exception:
            pass
        if platform == "android":
            Clock.schedule_once(lambda dt: self._request_perms(), 1)
        self._load_initial_data()
        Window.bind(on_keyboard=self._on_keyboard)
        return Builder.load_string(KV)

    def _on_keyboard(self, window, key, *args):
        if key == 27:  # Back / ESC
            if self.root and self.root.current != "main":
                self.root.transition = SlideTransition(direction="right")
                self.root.current = "main"
                return True
            # Double press to exit
            now = time.time()
            if now - self._last_back_time < 2:
                return False  # Exit
            self._last_back_time = now
            self.show_toast("Press back again to exit")
            return True
        return False

    def _request_perms(self):
        if platform == "android":
            try:
                request_permissions([Permission.CAMERA, Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE])
            except Exception:
                pass

    def _load_initial_data(self):
        if not self.db or self.db.get_phone_count() > 0:
            return
        try:
            jp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "initial_data.json")
            if not os.path.exists(jp):
                jp = os.path.join(get_app_path(), "initial_data.json")
            if not os.path.exists(jp):
                return
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
            rows = []
            for item in data:
                code, model, year, appear, cond, comment = item
                rows.append({"id": str(code), "name": str(model), "release_date": str(year),
                             "appearance_condition": str(appear), "working_condition": str(cond),
                             "remarks": str(comment) if comment else ""})
            self.db.import_phones_from_rows(rows)
        except Exception as e:
            print(f"Initial data error: {e}")

    def show_toast(self, text):
        try:
            popup = ModalView(size_hint=(0.8, None), height=dp(46), background_color=(0,0,0,0), pos_hint={"center_x": 0.5, "y": 0.05})
            box = BoxLayout(padding=dp(10))
            with box.canvas.before:
                Color(0.15, 0.15, 0.15, 0.92)
                box._bg = RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(8)])
            box.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
            box.add_widget(Label(text=text, color=(1,1,1,1), font_size=sp(13)))
            popup.add_widget(box)
            popup.open()
            Clock.schedule_once(lambda dt: popup.dismiss(), 2)
        except Exception:
            pass

    def open_file_chooser(self, filters=None, multiple=False):
        if platform == "android":
            self._android_chooser(filters, multiple)
        else:
            self._desktop_chooser(filters, multiple)

    def _desktop_chooser(self, filters=None, multiple=False):
        from kivy.uix.filechooser import FileChooserListView
        fc = FileChooserListView(filters=filters or ["*.png","*.jpg","*.jpeg","*.bmp"], path=os.path.expanduser("~"), multiselect=multiple or False)
        content = BoxLayout(orientation="vertical", spacing=dp(6))
        content.add_widget(fc)
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        popup = Popup(title="Select File", content=content, size_hint=(0.95, 0.85))
        cb = ClickableBox(padding=(dp(6), dp(4)))
        cb.add_widget(Label(text="Cancel", font_size=sp(13)))
        cb.bind(on_release=lambda *a: popup.dismiss())
        sb = ClickableBox(padding=(dp(6), dp(4)))
        sb.add_widget(Label(text="Select", font_size=sp(13), bold=True))
        sb.bind(on_release=lambda *a: self._on_file_selected(fc.selection, popup))
        row.add_widget(cb)
        row.add_widget(sb)
        content.add_widget(row)
        popup.open()

    def _android_chooser(self, filters=None, multiple=False):
        try:
            from plyer import filechooser
            mime = ["image/*"]
            if filters:
                if "*.zip" in filters:
                    mime = ["application/zip"]
            filechooser.open_file(on_selection=lambda s: self._on_file_selected(s), multiple=multiple, filters=mime)
        except Exception as e:
            self.show_toast(f"File picker: {str(e)[:50]}")

    def _on_file_selected(self, selection, popup=None):
        if popup:
            popup.dismiss()
        if not selection or not self.pick_image_for:
            return
        tt, td = self.pick_image_for
        self.pick_image_for = None

        if tt == "add_phone_screen":
            self.root.get_screen("add_phone").on_image_selected(selection[0])
        elif tt == "add_spare_screen":
            self.root.get_screen("add_spare").on_image_selected(selection[0])
        elif tt == "phone":
            img = copy_image_to_storage(selection[0], get_phone_images_path())
            if img:
                self.db.update_phone(td, image_path=img)
                d = self.root.get_screen("phone_detail")
                d.image_source = ""
                Clock.schedule_once(lambda dt: setattr(d, "image_source", img), 0.1)
                self.show_toast("Image updated!")
        elif tt == "phone_gallery":
            gdir = get_phone_gallery_path(td)
            count = 0
            for s in selection:
                r = copy_image_to_storage(s, gdir)
                if r:
                    count += 1
            self.show_toast(f"Added {count} gallery photos!")
            d = self.root.get_screen("phone_detail")
            Clock.schedule_once(lambda dt: d._load_gallery(), 0.3)
        elif tt == "spare_direct":
            img = copy_image_to_storage(selection[0], get_spare_images_path())
            if img:
                self.db.update_spare_part(td, image_path=img)
                d = self.root.get_screen("spare_detail")
                d.s_image = ""
                Clock.schedule_once(lambda dt: setattr(d, "s_image", img), 0.1)
                self.show_toast("Image updated!")
        elif tt == "restore_backup":
            self.root.get_screen("backup").on_backup_selected(selection[0])
        elif tt == "bulk_images":
            self.root.get_screen("bulk_images").on_images_selected(selection)

    def take_camera_photo(self):
        if platform == "android":
            try:
                from jnius import autoclass
                Intent = autoclass("android.content.Intent")
                MediaStore = autoclass("android.provider.MediaStore")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
                PythonActivity.mActivity.startActivityForResult(intent, 1002)
            except Exception as e:
                self.show_toast(f"Camera: {str(e)[:50]}")
        else:
            self.show_toast("Camera on Android only")

    def on_stop(self):
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass


if __name__ == "__main__":
    NokiaStorageApp().run()
