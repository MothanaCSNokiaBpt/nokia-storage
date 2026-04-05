"""
Nokia Storage Manager - Complete Android Application
Manage Nokia phones inventory and spare parts with images,
Excel import/export, search, and backup/restore.
"""

import json
import os
import shutil
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
    StringProperty, ListProperty, ObjectProperty,
    NumericProperty, BooleanProperty
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

# ── Platform-specific imports (lazy - no autoclass at module level) ──
if platform == "android":
    try:
        from android.permissions import request_permissions, Permission
        from android.storage import primary_external_storage_path, app_storage_path
    except Exception:
        pass


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


def get_db_path():
    return os.path.join(get_app_path(), "nokia_storage.db")


def get_backup_path():
    if platform == "android":
        try:
            return os.path.join(primary_external_storage_path(), "Download")
        except Exception:
            return os.path.join(get_app_path(), "backups")
    return os.path.join(get_app_path(), "backups")


DEFAULT_IMG = ""


def get_default_image():
    global DEFAULT_IMG
    if DEFAULT_IMG and os.path.exists(DEFAULT_IMG):
        return DEFAULT_IMG
    p = os.path.join(get_app_path(), "default_phone.png")
    if not os.path.exists(p):
        try:
            from PIL import Image as PILImage, ImageDraw
            img = PILImage.new("RGB", (200, 200), (230, 238, 255))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle([50, 20, 150, 170], radius=12,
                                    fill=(200, 215, 240), outline=(160, 175, 200), width=2)
            draw.rounded_rectangle([65, 45, 135, 115], radius=4, fill=(175, 195, 225))
            draw.ellipse([88, 130, 112, 150], fill=(175, 195, 225))
            img.save(p)
        except Exception:
            # Create a tiny valid PNG manually
            try:
                import struct, zlib
                def create_minimal_png(path):
                    width, height = 4, 4
                    raw = b''
                    for y in range(height):
                        raw += b'\x00'
                        for x in range(width):
                            raw += b'\xe6\xee\xff'
                    compressed = zlib.compress(raw)
                    def chunk(ctype, data):
                        c = ctype + data
                        crc = struct.pack('>I', zlib.crc32(c) & 0xffffffff)
                        return struct.pack('>I', len(data)) + c + crc
                    with open(path, 'wb') as f:
                        f.write(b'\x89PNG\r\n\x1a\n')
                        f.write(chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)))
                        f.write(chunk(b'IDAT', compressed))
                        f.write(chunk(b'IEND', b''))
                create_minimal_png(p)
            except Exception:
                return ""
    DEFAULT_IMG = p
    return p


def safe_image(path):
    """Return path if valid, else default image."""
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
    def on_search(self, text):
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
    height: dp(90)
    padding: dp(8)
    spacing: dp(10)
    orientation: 'horizontal'
    canvas.before:
        Color:
            rgba: 1, 1, 1, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]

    AsyncImage:
        source: root.phone_image or ''
        size_hint: None, None
        size: dp(70), dp(70)
        pos_hint: {'center_y': .5}
        allow_stretch: True
        keep_ratio: True

    BoxLayout:
        orientation: 'vertical'
        spacing: dp(2)
        padding: 0, dp(4)
        Label:
            text: root.phone_name
            font_size: sp(16)
            bold: True
            color: 0.1, 0.1, 0.18, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.4
        Label:
            text: 'ID: ' + root.phone_id
            font_size: sp(12)
            color: 0.4, 0.4, 0.4, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.3
        Label:
            text: root.phone_date
            font_size: sp(11)
            color: 0.5, 0.5, 0.5, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.3

<SpareCard>:
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
            radius: [dp(12)]

    AsyncImage:
        source: root.spare_image or ''
        size_hint: None, None
        size: dp(60), dp(60)
        pos_hint: {'center_y': .5}
        allow_stretch: True
        keep_ratio: True

    BoxLayout:
        orientation: 'vertical'
        spacing: dp(2)
        padding: 0, dp(4)
        Label:
            text: root.spare_name
            font_size: sp(15)
            bold: True
            color: 0.1, 0.1, 0.18, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.5
        Label:
            text: root.spare_desc
            font_size: sp(12)
            color: 0.5, 0.5, 0.5, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: 0.5

<SearchBar>:
    size_hint_y: None
    height: dp(50)
    padding: dp(12), dp(6)
    spacing: dp(8)
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
                radius: [dp(22)]
        padding: dp(14), dp(4)
        spacing: dp(8)
        Label:
            text: 'Search'
            size_hint_x: None
            width: dp(55)
            font_size: sp(13)
            color: 0.5, 0.5, 0.5, 1
        TextInput:
            id: search_input
            hint_text: 'by name, ID, or date...'
            multiline: False
            background_color: 0, 0, 0, 0
            foreground_color: 0.1, 0.1, 0.1, 1
            hint_text_color: 0.6, 0.6, 0.6, 1
            cursor_color: 0, 0.314, 0.784, 1
            font_size: sp(14)
            padding: 0, dp(8)
            on_text: root.on_search(self.text)

ScreenManager:
    id: sm
    MainScreen:
        name: 'main'
    PhoneDetailScreen:
        name: 'phone_detail'
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

<MainScreen>:
    BoxLayout:
        orientation: 'vertical'

        # Header
        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(16), dp(8)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            Label:
                text: 'N O K I A  Storage'
                font_size: sp(20)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            ClickableLabel:
                text: 'Menu'
                size_hint_x: None
                width: dp(50)
                font_size: sp(13)
                color: 1, 1, 1, 1
                on_release: root.show_menu()

        SearchBar:
            id: search_bar

        # Tab Buttons
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            canvas.before:
                Color:
                    rgba: 1, 1, 1, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableBox:
                id: tab_phones
                padding: dp(8)
                on_release: root.switch_tab('phones')
                canvas.before:
                    Color:
                        rgba: (0, 0.314, 0.784, 1) if root.current_tab == 'phones' else (0.95, 0.95, 0.95, 1)
                    Rectangle:
                        pos: self.pos
                        size: self.size
                Label:
                    text: 'Nokia Phones'
                    bold: True
                    font_size: sp(14)
                    color: (1,1,1,1) if root.current_tab == 'phones' else (0.3,0.3,0.3,1)
            ClickableBox:
                id: tab_spares
                padding: dp(8)
                on_release: root.switch_tab('spares')
                canvas.before:
                    Color:
                        rgba: (0, 0.314, 0.784, 1) if root.current_tab == 'spares' else (0.95, 0.95, 0.95, 1)
                    Rectangle:
                        pos: self.pos
                        size: self.size
                Label:
                    text: 'Spare Parts'
                    bold: True
                    font_size: sp(14)
                    color: (1,1,1,1) if root.current_tab == 'spares' else (0.3,0.3,0.3,1)

        # Content
        ScrollView:
            id: scroll_view
            do_scroll_x: False
            GridLayout:
                id: content_list
                cols: 1
                spacing: dp(8)
                padding: dp(12)
                size_hint_y: None
                height: self.minimum_height

        # Bottom Bar
        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(12), dp(6)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 1, 1, 1, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            Label:
                id: count_label
                text: '0 items'
                font_size: sp(12)
                color: 0.5, 0.5, 0.5, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            ClickableBox:
                size_hint_x: None
                width: dp(100)
                padding: dp(12), dp(6)
                canvas.before:
                    Color:
                        rgba: 0, 0.314, 0.784, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(22)]
                on_release: root.add_item()
                Label:
                    text: '+ Add'
                    color: 1, 1, 1, 1
                    font_size: sp(14)
                    bold: True
            ClickableBox:
                size_hint_x: None
                width: dp(100)
                padding: dp(12), dp(6)
                canvas.before:
                    Color:
                        rgba: 0, 0.44, 1, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(22)]
                on_release: root.search_all()
                Label:
                    text: 'Search All'
                    color: 1, 1, 1, 1
                    font_size: sp(13)
                    bold: True

<PhoneDetailScreen>:
    BoxLayout:
        orientation: 'vertical'

        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(8)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(40)
                text: '<'
                font_size: sp(24)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Phone Details'
                font_size: sp(18)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            ClickableLabel:
                size_hint_x: None
                width: dp(50)
                text: 'Edit'
                font_size: sp(14)
                color: 1, 1, 1, 1
                on_release: root.edit_phone()
            ClickableLabel:
                size_hint_x: None
                width: dp(50)
                text: 'Del'
                font_size: sp(14)
                color: 1, 0.6, 0.6, 1
                on_release: root.confirm_delete()

        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(16)
                spacing: dp(12)

                # Phone Image
                BoxLayout:
                    size_hint_y: None
                    height: dp(250)
                    padding: dp(20)
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(16)]
                    AsyncImage:
                        id: phone_image
                        source: root.image_source or ''
                        allow_stretch: True
                        keep_ratio: True

                ClickableBox:
                    size_hint_y: None
                    height: dp(38)
                    padding: dp(12), dp(6)
                    canvas.before:
                        Color:
                            rgba: 0, 0.314, 0.784, 0.1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(8)]
                    on_release: root.change_image()
                    Label:
                        text: 'Change Image'
                        color: 0, 0.314, 0.784, 1
                        font_size: sp(13)
                        bold: True

                # Info Card
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(16)
                    spacing: dp(10)
                    canvas.before:
                        Color:
                            rgba: 1, 1, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]

                    Label:
                        text: root.p_name
                        font_size: sp(22)
                        bold: True
                        color: 0.1, 0.1, 0.18, 1
                        size_hint_y: None
                        height: dp(32)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: 'ID: ' + root.p_id
                        font_size: sp(14)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: dp(22)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: 'Release: ' + root.p_date
                        font_size: sp(14)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: dp(22)
                        text_size: self.size
                        halign: 'left'
                    BoxLayout:
                        size_hint_y: None
                        height: dp(30)
                        spacing: dp(8)
                        BoxLayout:
                            padding: dp(8), dp(4)
                            canvas.before:
                                Color:
                                    rgba: 0.26, 0.63, 0.28, 0.15
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [dp(6)]
                            Label:
                                text: 'Look: ' + root.p_appear
                                font_size: sp(12)
                                color: 0.26, 0.63, 0.28, 1
                                bold: True
                        BoxLayout:
                            padding: dp(8), dp(4)
                            canvas.before:
                                Color:
                                    rgba: 0, 0.314, 0.784, 0.15
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [dp(6)]
                            Label:
                                text: 'Work: ' + root.p_working
                                font_size: sp(12)
                                color: 0, 0.314, 0.784, 1
                                bold: True
                    Label:
                        text: 'Remarks:'
                        font_size: sp(13)
                        bold: True
                        color: 0.3, 0.3, 0.3, 1
                        size_hint_y: None
                        height: dp(20)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: root.p_remarks or 'None'
                        font_size: sp(13)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: self.texture_size[1] + dp(10)
                        text_size: self.width, None
                        halign: 'left'

                Label:
                    text: 'Related Spare Parts'
                    font_size: sp(16)
                    bold: True
                    color: 0.1, 0.1, 0.18, 1
                    size_hint_y: None
                    height: dp(30)
                    text_size: self.size
                    halign: 'left'

                GridLayout:
                    id: spare_parts_grid
                    cols: 1
                    spacing: dp(8)
                    size_hint_y: None
                    height: self.minimum_height

                ClickableBox:
                    size_hint_y: None
                    height: dp(40)
                    padding: dp(12), dp(8)
                    canvas.before:
                        Color:
                            rgba: 0, 0.314, 0.784, 0.1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(8)]
                    on_release: root.add_spare_for_phone()
                    Label:
                        text: '+ Add Spare Part'
                        color: 0, 0.314, 0.784, 1
                        font_size: sp(14)
                        bold: True

                Widget:
                    size_hint_y: None
                    height: dp(40)

<AddPhoneScreen>:
    BoxLayout:
        orientation: 'vertical'

        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(8)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(40)
                text: '<'
                font_size: sp(24)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: root.screen_title
                font_size: sp(18)
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
                padding: dp(16)
                spacing: dp(14)

                BoxLayout:
                    size_hint_y: None
                    height: dp(180)
                    padding: dp(16)
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                    AsyncImage:
                        id: preview_image
                        source: root.image_preview or ''
                        allow_stretch: True
                        keep_ratio: True

                BoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    spacing: dp(8)
                    ClickableBox:
                        padding: dp(8), dp(6)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.15
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(8)]
                        on_release: root.pick_from_gallery()
                        Label:
                            text: 'Gallery'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(13)
                            bold: True
                    ClickableBox:
                        padding: dp(8), dp(6)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.15
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(8)]
                        on_release: root.take_photo()
                        Label:
                            text: 'Camera'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(13)
                            bold: True

                Label:
                    text: 'Phone ID *'
                    font_size: sp(13)
                    color: 0.3, 0.3, 0.3, 1
                    size_hint_y: None
                    height: dp(20)
                    text_size: self.size
                    halign: 'left'
                TextInput:
                    id: input_id
                    hint_text: 'e.g. NOKIA-3310-001'
                    multiline: False
                    size_hint_y: None
                    height: dp(44)
                    font_size: sp(14)
                    padding: dp(12), dp(10)

                Label:
                    text: 'Phone Name *'
                    font_size: sp(13)
                    color: 0.3, 0.3, 0.3, 1
                    size_hint_y: None
                    height: dp(20)
                    text_size: self.size
                    halign: 'left'
                TextInput:
                    id: input_name
                    hint_text: 'e.g. Nokia 3310'
                    multiline: False
                    size_hint_y: None
                    height: dp(44)
                    font_size: sp(14)
                    padding: dp(12), dp(10)

                Label:
                    text: 'Release Date'
                    font_size: sp(13)
                    color: 0.3, 0.3, 0.3, 1
                    size_hint_y: None
                    height: dp(20)
                    text_size: self.size
                    halign: 'left'
                TextInput:
                    id: input_date
                    hint_text: 'e.g. 2000'
                    multiline: False
                    size_hint_y: None
                    height: dp(44)
                    font_size: sp(14)
                    padding: dp(12), dp(10)

                Label:
                    text: 'Appearance Condition'
                    font_size: sp(13)
                    color: 0.3, 0.3, 0.3, 1
                    size_hint_y: None
                    height: dp(20)
                    text_size: self.size
                    halign: 'left'
                TextInput:
                    id: input_appear
                    hint_text: 'Excellent / Good / Fair / Poor'
                    multiline: False
                    size_hint_y: None
                    height: dp(44)
                    font_size: sp(14)
                    padding: dp(12), dp(10)

                Label:
                    text: 'Working Condition'
                    font_size: sp(13)
                    color: 0.3, 0.3, 0.3, 1
                    size_hint_y: None
                    height: dp(20)
                    text_size: self.size
                    halign: 'left'
                TextInput:
                    id: input_working
                    hint_text: 'Working / Not Working / Partial'
                    multiline: False
                    size_hint_y: None
                    height: dp(44)
                    font_size: sp(14)
                    padding: dp(12), dp(10)

                Label:
                    text: 'Remarks'
                    font_size: sp(13)
                    color: 0.3, 0.3, 0.3, 1
                    size_hint_y: None
                    height: dp(20)
                    text_size: self.size
                    halign: 'left'
                TextInput:
                    id: input_remarks
                    hint_text: 'Any notes...'
                    multiline: True
                    size_hint_y: None
                    height: dp(80)
                    font_size: sp(14)
                    padding: dp(12), dp(10)

                ClickableBox:
                    size_hint_y: None
                    height: dp(48)
                    padding: dp(16), dp(10)
                    canvas.before:
                        Color:
                            rgba: 0, 0.314, 0.784, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(10)]
                    on_release: root.save_phone()
                    Label:
                        text: 'Save Phone'
                        color: 1, 1, 1, 1
                        font_size: sp(16)
                        bold: True

                Widget:
                    size_hint_y: None
                    height: dp(30)

<AddSpareScreen>:
    BoxLayout:
        orientation: 'vertical'

        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(8)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(40)
                text: '<'
                font_size: sp(24)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Add Spare Part'
                font_size: sp(18)
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
                padding: dp(16)
                spacing: dp(14)

                BoxLayout:
                    size_hint_y: None
                    height: dp(180)
                    padding: dp(16)
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                    AsyncImage:
                        id: spare_preview_image
                        source: root.image_preview or ''
                        allow_stretch: True
                        keep_ratio: True

                BoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    spacing: dp(8)
                    ClickableBox:
                        padding: dp(8), dp(6)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.15
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(8)]
                        on_release: root.pick_from_gallery()
                        Label:
                            text: 'Gallery'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(13)
                            bold: True
                    ClickableBox:
                        padding: dp(8), dp(6)
                        canvas.before:
                            Color:
                                rgba: 0, 0.314, 0.784, 0.15
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(8)]
                        on_release: root.take_photo()
                        Label:
                            text: 'Camera'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(13)
                            bold: True

                Label:
                    text: 'Spare Part Name *'
                    font_size: sp(13)
                    color: 0.3, 0.3, 0.3, 1
                    size_hint_y: None
                    height: dp(20)
                    text_size: self.size
                    halign: 'left'
                TextInput:
                    id: spare_input_name
                    hint_text: 'Same as phone name (e.g. Nokia 3310)'
                    multiline: False
                    size_hint_y: None
                    height: dp(44)
                    font_size: sp(14)
                    padding: dp(12), dp(10)

                Label:
                    text: 'Description'
                    font_size: sp(13)
                    color: 0.3, 0.3, 0.3, 1
                    size_hint_y: None
                    height: dp(20)
                    text_size: self.size
                    halign: 'left'
                TextInput:
                    id: spare_input_desc
                    hint_text: 'e.g. Battery cover, Screen, etc.'
                    multiline: True
                    size_hint_y: None
                    height: dp(80)
                    font_size: sp(14)
                    padding: dp(12), dp(10)

                Label:
                    text: 'Link to Phone ID (optional)'
                    font_size: sp(13)
                    color: 0.3, 0.3, 0.3, 1
                    size_hint_y: None
                    height: dp(20)
                    text_size: self.size
                    halign: 'left'
                TextInput:
                    id: spare_input_phone_id
                    hint_text: 'e.g. NOKIA-3310-001'
                    multiline: False
                    size_hint_y: None
                    height: dp(44)
                    font_size: sp(14)
                    padding: dp(12), dp(10)

                ClickableBox:
                    size_hint_y: None
                    height: dp(48)
                    padding: dp(16), dp(10)
                    canvas.before:
                        Color:
                            rgba: 0, 0.314, 0.784, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(10)]
                    on_release: root.save_spare()
                    Label:
                        text: 'Save Spare Part'
                        color: 1, 1, 1, 1
                        font_size: sp(16)
                        bold: True

                Widget:
                    size_hint_y: None
                    height: dp(30)

<ExportScreen>:
    BoxLayout:
        orientation: 'vertical'

        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(8)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(40)
                text: '<'
                font_size: sp(24)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Export Data'
                font_size: sp(18)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'

        BoxLayout:
            orientation: 'vertical'
            padding: dp(20)
            spacing: dp(16)

            Label:
                text: 'Export all data as CSV files.\\n\\nTwo files will be created:\\n1. nokia_phones.csv\\n2. nokia_spare_parts.csv'
                font_size: sp(14)
                color: 0.3, 0.3, 0.3, 1
                text_size: self.width - dp(20), None
                size_hint_y: None
                height: self.texture_size[1] + dp(20)
                halign: 'left'

            Label:
                id: export_status
                text: ''
                font_size: sp(14)
                color: 0.26, 0.63, 0.28, 1
                size_hint_y: None
                height: dp(50)
                text_size: self.width, None
                halign: 'left'

            ClickableBox:
                size_hint_y: None
                height: dp(50)
                padding: dp(16), dp(12)
                canvas.before:
                    Color:
                        rgba: 0, 0.314, 0.784, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]
                on_release: root.do_export()
                Label:
                    text: 'Export to CSV'
                    color: 1, 1, 1, 1
                    font_size: sp(16)
                    bold: True

            ClickableBox:
                size_hint_y: None
                height: dp(50)
                padding: dp(16), dp(12)
                canvas.before:
                    Color:
                        rgba: 0.26, 0.63, 0.28, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]
                on_release: root.share_export()
                Label:
                    text: 'Share via Email'
                    color: 1, 1, 1, 1
                    font_size: sp(16)
                    bold: True

            Widget:

<BulkImageScreen>:
    BoxLayout:
        orientation: 'vertical'

        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(8)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(40)
                text: '<'
                font_size: sp(24)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Bulk Image Import'
                font_size: sp(18)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'

        BoxLayout:
            orientation: 'vertical'
            padding: dp(16)
            spacing: dp(12)

            BoxLayout:
                size_hint_y: None
                height: dp(40)
                spacing: dp(8)
                ClickableBox:
                    padding: dp(12), dp(6)
                    canvas.before:
                        Color:
                            rgba: (0, 0.314, 0.784, 1) if root.target_type == 'phones' else (0.9, 0.9, 0.9, 1)
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(8)]
                    on_release: root.set_target('phones')
                    Label:
                        text: 'For Phones'
                        color: (1,1,1,1) if root.target_type == 'phones' else (0.3,0.3,0.3,1)
                        font_size: sp(13)
                        bold: True
                ClickableBox:
                    padding: dp(12), dp(6)
                    canvas.before:
                        Color:
                            rgba: (0, 0.314, 0.784, 1) if root.target_type == 'spares' else (0.9, 0.9, 0.9, 1)
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(8)]
                    on_release: root.set_target('spares')
                    Label:
                        text: 'For Spare Parts'
                        color: (1,1,1,1) if root.target_type == 'spares' else (0.3,0.3,0.3,1)
                        font_size: sp(13)
                        bold: True

            ClickableBox:
                size_hint_y: None
                height: dp(44)
                padding: dp(12), dp(8)
                canvas.before:
                    Color:
                        rgba: 0, 0.314, 0.784, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]
                on_release: root.select_images()
                Label:
                    text: 'Select Images from Gallery'
                    color: 1, 1, 1, 1
                    font_size: sp(14)
                    bold: True

            Label:
                id: bulk_status
                text: 'Select images to assign to phones or spare parts'
                font_size: sp(13)
                color: 0.5, 0.5, 0.5, 1
                size_hint_y: None
                height: dp(24)

            ScrollView:
                do_scroll_x: False
                GridLayout:
                    id: bulk_grid
                    cols: 1
                    spacing: dp(10)
                    size_hint_y: None
                    height: self.minimum_height

<BackupScreen>:
    BoxLayout:
        orientation: 'vertical'

        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(8)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(40)
                text: '<'
                font_size: sp(24)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Backup & Restore'
                font_size: sp(18)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'

        BoxLayout:
            orientation: 'vertical'
            padding: dp(20)
            spacing: dp(16)

            Label:
                text: 'Create a full backup of all\\ndata and images. Restore on\\na new device after installing.'
                font_size: sp(14)
                color: 0.3, 0.3, 0.3, 1
                text_size: self.width - dp(20), None
                size_hint_y: None
                height: self.texture_size[1] + dp(10)
                halign: 'left'

            ClickableBox:
                size_hint_y: None
                height: dp(50)
                padding: dp(16), dp(12)
                canvas.before:
                    Color:
                        rgba: 0.26, 0.63, 0.28, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]
                on_release: root.create_backup()
                Label:
                    text: 'Create Backup'
                    color: 1, 1, 1, 1
                    font_size: sp(16)
                    bold: True

            ClickableBox:
                size_hint_y: None
                height: dp(50)
                padding: dp(16), dp(12)
                canvas.before:
                    Color:
                        rgba: 1, 0.6, 0, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]
                on_release: root.restore_backup()
                Label:
                    text: 'Restore from Backup'
                    color: 1, 1, 1, 1
                    font_size: sp(16)
                    bold: True

            ClickableBox:
                size_hint_y: None
                height: dp(50)
                padding: dp(16), dp(12)
                canvas.before:
                    Color:
                        rgba: 0, 0.314, 0.784, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]
                on_release: root.share_backup()
                Label:
                    text: 'Share Backup (Email)'
                    color: 1, 1, 1, 1
                    font_size: sp(16)
                    bold: True

            Label:
                id: backup_status
                text: ''
                font_size: sp(13)
                color: 0.26, 0.63, 0.28, 1
                size_hint_y: None
                height: dp(50)
                text_size: self.width, None
                halign: 'left'

            Widget:

<SearchAllScreen>:
    BoxLayout:
        orientation: 'vertical'

        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(8)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0.314, 0.784, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            ClickableLabel:
                size_hint_x: None
                width: dp(40)
                text: '<'
                font_size: sp(24)
                bold: True
                color: 1, 1, 1, 1
                on_release: root.go_back()
            Label:
                text: 'Search All'
                font_size: sp(18)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'

        SearchBar:
            id: search_all_bar

        ScrollView:
            do_scroll_x: False
            GridLayout:
                id: results_list
                cols: 1
                spacing: dp(8)
                padding: dp(12)
                size_hint_y: None
                height: self.minimum_height
"""


# ── Screen Classes ──────────────────────────────────────────────

class MainScreen(Screen):
    current_tab = StringProperty("phones")

    def on_enter(self):
        Clock.schedule_once(lambda dt: self.refresh_list(), 0.2)

    def switch_tab(self, tab):
        self.current_tab = tab
        try:
            self.ids.search_bar.ids.search_input.text = ""
        except Exception:
            pass
        self.refresh_list()

    def refresh_list(self):
        app = App.get_running_app()
        if not app.db:
            return
        grid = self.ids.content_list
        grid.clear_widgets()
        default_img = get_default_image()

        if self.current_tab == "phones":
            items = app.db.get_all_phones()
            self.ids.count_label.text = f"{len(items)} phones"
            for p in items:
                img = safe_image(p.get("image_path", ""))
                card = PhoneCard(
                    phone_id=p["id"], phone_name=p["name"],
                    phone_date=p.get("release_date", "") or "",
                    phone_image=img,
                )
                card.bind(on_release=partial(self._open_phone, p["id"]))
                grid.add_widget(card)
        else:
            items = app.db.get_all_spare_parts()
            self.ids.count_label.text = f"{len(items)} spare parts"
            for s in items:
                img = safe_image(s.get("image_path", ""))
                card = SpareCard(
                    spare_id=s["id"], spare_name=s["name"],
                    spare_desc=s.get("description", "") or "",
                    spare_image=img,
                )
                grid.add_widget(card)

    def do_search(self, text):
        app = App.get_running_app()
        if not text.strip():
            self.refresh_list()
            return
        grid = self.ids.content_list
        grid.clear_widgets()

        if self.current_tab == "phones":
            results = app.db.search_phones(text)
            self.ids.count_label.text = f"{len(results)} found"
            for p in results:
                img = safe_image(p.get("image_path", ""))
                card = PhoneCard(
                    phone_id=p["id"], phone_name=p["name"],
                    phone_date=p.get("release_date", "") or "",
                    phone_image=img,
                )
                card.bind(on_release=partial(self._open_phone, p["id"]))
                grid.add_widget(card)
        else:
            results = app.db.search_spare_parts(text)
            self.ids.count_label.text = f"{len(results)} found"
            for s in results:
                img = safe_image(s.get("image_path", ""))
                card = SpareCard(
                    spare_id=s["id"], spare_name=s["name"],
                    spare_desc=s.get("description", "") or "",
                    spare_image=img,
                )
                grid.add_widget(card)

    def _open_phone(self, phone_id, *args):
        app = App.get_running_app()
        detail = app.root.get_screen("phone_detail")
        detail.load_phone(phone_id)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "phone_detail"

    def add_item(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="left")
        if self.current_tab == "phones":
            screen = app.root.get_screen("add_phone")
            screen.edit_mode = False
            screen.clear_form()
            app.root.current = "add_phone"
        else:
            screen = app.root.get_screen("add_spare")
            screen.clear_form()
            app.root.current = "add_spare"

    def search_all(self):
        app = App.get_running_app()
        try:
            query = self.ids.search_bar.ids.search_input.text
        except Exception:
            query = ""
        s = app.root.get_screen("search_all")
        s.initial_query = query
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "search_all"

    def show_menu(self):
        app = App.get_running_app()
        content = BoxLayout(orientation="vertical", spacing=dp(2), padding=dp(8))
        popup = ModalView(size_hint=(0.7, None), height=dp(220))

        items = [
            ("Export Data", "export_data"),
            ("Bulk Image Import", "bulk_images"),
            ("Backup & Restore", "backup"),
        ]
        for label_text, target in items:
            btn = ClickableBox(size_hint_y=None, height=dp(44), padding=(dp(12), dp(6)))
            btn.add_widget(Label(
                text=label_text, font_size=sp(14), color=(0.1, 0.1, 0.18, 1),
                text_size=(dp(200), None), halign="left",
            ))
            btn.bind(on_release=lambda *a, t=target: (
                popup.dismiss(), self._goto(t)))
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
        self.p_remarks = phone.get("remarks", "") or ""
        self.image_source = safe_image(phone.get("image_path", ""))
        Clock.schedule_once(lambda dt: self._load_spares(phone["name"]), 0.1)

    def _load_spares(self, phone_name):
        app = App.get_running_app()
        grid = self.ids.spare_parts_grid
        grid.clear_widgets()
        spares = app.db.get_spare_parts_for_phone(phone_name)
        if not spares:
            grid.add_widget(Label(
                text="No spare parts found", font_size=sp(13),
                color=(0.5, 0.5, 0.5, 1), size_hint_y=None, height=dp(30),
            ))
            return
        for s in spares:
            img = safe_image(s.get("image_path", ""))
            card = SpareCard(
                spare_id=s["id"], spare_name=s["name"],
                spare_desc=s.get("description", "") or "",
                spare_image=img,
            )
            grid.add_widget(card)

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"

    def edit_phone(self):
        app = App.get_running_app()
        screen = app.root.get_screen("add_phone")
        screen.edit_mode = True
        screen.load_for_edit(self.p_id)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "add_phone"

    def confirm_delete(self):
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(16))
        content.add_widget(Label(
            text=f"Delete {self.p_name}?", font_size=sp(16),
            color=(0.1, 0.1, 0.18, 1), size_hint_y=None, height=dp(30),
        ))
        btn_row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(44))
        popup = ModalView(size_hint=(0.8, None), height=dp(140))

        cancel = ClickableBox(padding=(dp(8), dp(6)))
        cancel.add_widget(Label(text="Cancel", font_size=sp(14), color=(0.4, 0.4, 0.4, 1)))
        cancel.bind(on_release=lambda *a: popup.dismiss())

        delete = ClickableBox(padding=(dp(8), dp(6)))
        with delete.canvas.before:
            Color(0.9, 0.22, 0.21, 1)
            delete._bg = RoundedRectangle(pos=delete.pos, size=delete.size, radius=[dp(8)])
        delete.bind(pos=lambda w, v: setattr(w._bg, "pos", v))
        delete.bind(size=lambda w, v: setattr(w._bg, "size", v))
        delete.add_widget(Label(text="Delete", font_size=sp(14), color=(1, 1, 1, 1), bold=True))
        delete.bind(on_release=lambda *a: self._do_delete(popup))

        btn_row.add_widget(cancel)
        btn_row.add_widget(delete)
        content.add_widget(btn_row)
        popup.add_widget(content)
        popup.open()

    def _do_delete(self, popup):
        app = App.get_running_app()
        phone = app.db.get_phone(self.p_id)
        if phone and phone.get("image_path"):
            try:
                os.remove(phone["image_path"])
            except Exception:
                pass
        app.db.delete_phone(self.p_id)
        popup.dismiss()
        self.go_back()

    def change_image(self):
        app = App.get_running_app()
        app.pick_image_for = ("phone", self.p_id)
        app.open_file_chooser()

    def add_spare_for_phone(self):
        app = App.get_running_app()
        screen = app.root.get_screen("add_spare")
        screen.clear_form()
        Clock.schedule_once(lambda dt: self._prefill_spare(screen), 0.2)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "add_spare"

    def _prefill_spare(self, screen):
        try:
            screen.ids.spare_input_name.text = self.p_name
            screen.ids.spare_input_phone_id.text = self.p_id
        except Exception:
            pass


class AddPhoneScreen(Screen):
    edit_mode = BooleanProperty(False)
    screen_title = StringProperty("Add Phone")
    image_preview = StringProperty("")
    _selected_image = StringProperty("")

    def on_edit_mode(self, *args):
        self.screen_title = "Edit Phone" if self.edit_mode else "Add Phone"

    def clear_form(self):
        self.image_preview = get_default_image()
        self._selected_image = ""
        Clock.schedule_once(self._clear_inputs, 0.1)

    def _clear_inputs(self, *args):
        try:
            for fid in ["input_id", "input_name", "input_date",
                        "input_appear", "input_working", "input_remarks"]:
                self.ids[fid].text = ""
        except Exception:
            pass

    def load_for_edit(self, phone_id):
        app = App.get_running_app()
        phone = app.db.get_phone(phone_id)
        if not phone:
            return
        self.image_preview = safe_image(phone.get("image_path", ""))
        self._selected_image = phone.get("image_path", "") or ""
        Clock.schedule_once(partial(self._fill, phone), 0.1)

    def _fill(self, phone, *args):
        try:
            self.ids.input_id.text = phone["id"]
            self.ids.input_name.text = phone["name"]
            self.ids.input_date.text = phone.get("release_date", "") or ""
            self.ids.input_appear.text = phone.get("appearance_condition", "") or ""
            self.ids.input_working.text = phone.get("working_condition", "") or ""
            self.ids.input_remarks.text = phone.get("remarks", "") or ""
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
        self.image_preview = path

    def save_phone(self):
        app = App.get_running_app()
        try:
            phone_id = self.ids.input_id.text.strip()
            name = self.ids.input_name.text.strip()
        except Exception:
            return
        if not phone_id or not name:
            app.show_toast("ID and Name required")
            return
        image_path = self._selected_image
        if image_path and not image_path.startswith(get_phone_images_path()):
            image_path = copy_image_to_storage(image_path, get_phone_images_path())
        app.db.add_phone(
            phone_id=phone_id, name=name,
            release_date=self.ids.input_date.text.strip(),
            appearance=self.ids.input_appear.text.strip(),
            working=self.ids.input_working.text.strip(),
            remarks=self.ids.input_remarks.text.strip(),
            image_path=image_path or "",
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

    def _clear(self, *args):
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
        self.image_preview = path

    def save_spare(self):
        app = App.get_running_app()
        try:
            name = self.ids.spare_input_name.text.strip()
        except Exception:
            return
        if not name:
            app.show_toast("Name is required")
            return
        image_path = self._selected_image
        if image_path and not image_path.startswith(get_spare_images_path()):
            image_path = copy_image_to_storage(image_path, get_spare_images_path())
        app.db.add_spare_part(
            name=name,
            phone_id=self.ids.spare_input_phone_id.text.strip(),
            image_path=image_path or "",
            description=self.ids.spare_input_desc.text.strip(),
        )
        app.show_toast("Spare part saved!")
        self.go_back()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"


class ExportScreen(Screen):
    _last_export_path = StringProperty("")

    def do_export(self):
        app = App.get_running_app()
        try:
            import csv
            out_dir = get_backup_path()
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Phones CSV
            phones_path = os.path.join(out_dir, f"nokia_phones_{ts}.csv")
            phones = app.db.export_phones()
            with open(phones_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ID", "Name", "Release Date", "Appearance", "Working", "Remarks"])
                for p in phones:
                    w.writerow([p["id"], p["name"], p.get("release_date", ""),
                                p.get("appearance_condition", ""),
                                p.get("working_condition", ""),
                                p.get("remarks", "")])

            # Spare Parts CSV
            spares_path = os.path.join(out_dir, f"nokia_spares_{ts}.csv")
            spares = app.db.export_spare_parts()
            with open(spares_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ID", "Name", "Phone ID", "Description"])
                for s in spares:
                    w.writerow([s["id"], s["name"], s.get("phone_id", ""),
                                s.get("description", "")])

            self._last_export_path = phones_path
            self.ids.export_status.text = f"Exported {len(phones)} phones, {len(spares)} parts\n{out_dir}"
            self.ids.export_status.color = (0.26, 0.63, 0.28, 1)
            app.show_toast("Exported!")
        except Exception as e:
            self.ids.export_status.text = f"Error: {str(e)[:80]}"
            self.ids.export_status.color = (0.9, 0.22, 0.21, 1)

    def share_export(self):
        if not self._last_export_path:
            self.do_export()
        app = App.get_running_app()
        if platform == "android" and self._last_export_path:
            try:
                from jnius import autoclass, cast
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Intent = autoclass("android.content.Intent")
                FileProvider = autoclass("androidx.core.content.FileProvider")
                ctx = PythonActivity.mActivity.getApplicationContext()
                pkg = ctx.getPackageName()
                jf = autoclass("java.io.File")(self._last_export_path)
                uri = FileProvider.getUriForFile(ctx, f"{pkg}.fileprovider", jf)
                intent = Intent(Intent.ACTION_SEND)
                intent.setType("text/csv")
                intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
                intent.putExtra(Intent.EXTRA_SUBJECT, "Nokia Storage Export")
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                chooser = Intent.createChooser(intent, "Share Export")
                PythonActivity.mActivity.startActivity(chooser)
            except Exception as e:
                self.ids.export_status.text = f"Share error: {str(e)[:60]}"
        else:
            app.show_toast(f"File: {self._last_export_path}")

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"


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
            row = BoxLayout(
                orientation="horizontal", size_hint_y=None,
                height=dp(100), spacing=dp(8), padding=dp(4),
            )
            img = AsyncImage(
                source=path, size_hint=(None, 1), width=dp(80),
                allow_stretch=True, keep_ratio=True,
            )
            row.add_widget(img)
            form = BoxLayout(orientation="vertical", spacing=dp(4))
            name_input = TextInput(
                hint_text="Name (e.g. Nokia 3310)",
                multiline=False, size_hint_y=None, height=dp(36), font_size=sp(13),
            )
            form.add_widget(name_input)
            if self.target_type == "phones":
                id_input = TextInput(
                    hint_text="Phone ID", multiline=False,
                    size_hint_y=None, height=dp(36), font_size=sp(13),
                )
                form.add_widget(id_input)
            else:
                id_input = None
            row.add_widget(form)
            row._path = path
            row._name_input = name_input
            row._id_input = id_input
            grid.add_widget(row)

        save_btn = ClickableBox(size_hint_y=None, height=dp(48), padding=(dp(12), dp(8)))
        with save_btn.canvas.before:
            Color(0, 0.314, 0.784, 1)
            save_btn._bg = RoundedRectangle(pos=save_btn.pos, size=save_btn.size, radius=[dp(10)])
        save_btn.bind(pos=lambda w, v: setattr(w._bg, "pos", v))
        save_btn.bind(size=lambda w, v: setattr(w._bg, "size", v))
        save_btn.add_widget(Label(text="Save All", color=(1, 1, 1, 1), font_size=sp(16), bold=True))
        save_btn.bind(on_release=lambda *a: self._save_all())
        grid.add_widget(save_btn)

    def _save_all(self):
        app = App.get_running_app()
        grid = self.ids.bulk_grid
        count = 0
        for child in list(grid.children):
            if not hasattr(child, "_path"):
                continue
            name = child._name_input.text.strip()
            if not name:
                continue
            if self.target_type == "phones":
                pid = child._id_input.text.strip() if child._id_input else ""
                if not pid:
                    pid = f"BULK-{datetime.now().strftime('%H%M%S%f')}"
                img = copy_image_to_storage(child._path, get_phone_images_path())
                app.db.add_phone(phone_id=pid, name=name, image_path=img)
            else:
                img = copy_image_to_storage(child._path, get_spare_images_path())
                app.db.add_spare_part(name=name, image_path=img)
            count += 1
        self.ids.bulk_status.text = f"Saved {count} items!"
        app.show_toast(f"Saved {count} items!")

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"


class BackupScreen(Screen):
    def create_backup(self):
        app = App.get_running_app()
        try:
            backup_dir = get_backup_path()
            os.makedirs(backup_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"nokia_backup_{ts}.zip")
            with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
                db_path = get_db_path()
                if os.path.exists(db_path):
                    zf.write(db_path, "nokia_storage.db")
                images_dir = get_images_path()
                if os.path.exists(images_dir):
                    for root_dir, dirs, files in os.walk(images_dir):
                        for f in files:
                            full = os.path.join(root_dir, f)
                            arc = os.path.relpath(full, get_app_path())
                            zf.write(full, arc)
            self.ids.backup_status.text = f"Backup saved:\n{backup_file}"
            app._last_backup = backup_file
            app.show_toast("Backup created!")
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

    def share_backup(self):
        app = App.get_running_app()
        bp = getattr(app, "_last_backup", None)
        if not bp or not os.path.exists(bp):
            self.create_backup()
            bp = getattr(app, "_last_backup", None)
        if not bp:
            return
        if platform == "android":
            try:
                from jnius import autoclass, cast
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Intent = autoclass("android.content.Intent")
                FileProvider = autoclass("androidx.core.content.FileProvider")
                context = PythonActivity.mActivity.getApplicationContext()
                pkg = context.getPackageName()
                jfile = autoclass("java.io.File")(bp)
                uri = FileProvider.getUriForFile(context, f"{pkg}.fileprovider", jfile)
                intent = Intent(Intent.ACTION_SEND)
                intent.setType("application/zip")
                intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
                intent.putExtra(Intent.EXTRA_SUBJECT, "Nokia Storage Backup")
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                chooser = Intent.createChooser(intent, "Share Backup")
                PythonActivity.mActivity.startActivity(chooser)
            except Exception as e:
                self.ids.backup_status.text = f"Share error: {str(e)[:60]}"
        else:
            app.show_toast(f"Backup: {bp}")

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"


class SearchAllScreen(Screen):
    initial_query = StringProperty("")

    def on_enter(self):
        if self.initial_query:
            Clock.schedule_once(self._set_query, 0.1)

    def _set_query(self, *args):
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
            grid.add_widget(Label(
                text="Type to search phones and spare parts",
                font_size=sp(14), color=(0.5, 0.5, 0.5, 1),
                size_hint_y=None, height=dp(40),
            ))
            return
        phones, spares = app.db.search_all(text)
        if phones:
            grid.add_widget(Label(
                text=f"Phones ({len(phones)})", font_size=sp(15), bold=True,
                color=(0, 0.314, 0.784, 1), size_hint_y=None, height=dp(30),
                text_size=(dp(300), None), halign="left",
            ))
            for p in phones:
                card = PhoneCard(
                    phone_id=p["id"], phone_name=p["name"],
                    phone_date=p.get("release_date", "") or "",
                    phone_image=safe_image(p.get("image_path", "")),
                )
                card.bind(on_release=partial(self._open_phone, p["id"]))
                grid.add_widget(card)
        if spares:
            grid.add_widget(Label(
                text=f"Spare Parts ({len(spares)})", font_size=sp(15), bold=True,
                color=(0, 0.314, 0.784, 1), size_hint_y=None, height=dp(30),
                text_size=(dp(300), None), halign="left",
            ))
            for s in spares:
                card = SpareCard(
                    spare_id=s["id"], spare_name=s["name"],
                    spare_desc=s.get("description", "") or "",
                    spare_image=safe_image(s.get("image_path", "")),
                )
                grid.add_widget(card)
        if not phones and not spares:
            grid.add_widget(Label(
                text="No results found", font_size=sp(14),
                color=(0.5, 0.5, 0.5, 1), size_hint_y=None, height=dp(40),
            ))

    def _open_phone(self, phone_id, *args):
        app = App.get_running_app()
        detail = app.root.get_screen("phone_detail")
        detail.load_phone(phone_id)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "phone_detail"

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"


# ── Main App ────────────────────────────────────────────────────

class NokiaStorageApp(App):
    title = "Nokia Storage"
    db = ObjectProperty(None, allownone=True)
    pick_image_for = None

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
        return Builder.load_string(KV)

    def _request_perms(self):
        if platform == "android":
            try:
                perms = [Permission.CAMERA, Permission.READ_EXTERNAL_STORAGE,
                         Permission.WRITE_EXTERNAL_STORAGE]
                request_permissions(perms)
            except Exception:
                pass

    def show_toast(self, text):
        try:
            popup = ModalView(
                size_hint=(0.8, None), height=dp(50),
                background_color=(0, 0, 0, 0),
                pos_hint={"center_x": 0.5, "y": 0.05},
            )
            box = BoxLayout(padding=dp(12))
            with box.canvas.before:
                Color(0.2, 0.2, 0.2, 0.9)
                box._bg = RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(8)])
            box.bind(pos=lambda w, v: setattr(w._bg, "pos", v))
            box.bind(size=lambda w, v: setattr(w._bg, "size", v))
            box.add_widget(Label(text=text, color=(1, 1, 1, 1), font_size=sp(14)))
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
        fc = FileChooserListView(
            filters=filters or ["*.png", "*.jpg", "*.jpeg", "*.bmp"],
            path=os.path.expanduser("~"),
            multiselect=multiple or False,
        )
        content = BoxLayout(orientation="vertical", spacing=dp(8))
        content.add_widget(fc)
        btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(title="Select File", content=content, size_hint=(0.95, 0.85))
        cancel = ClickableBox(padding=(dp(8), dp(6)))
        cancel.add_widget(Label(text="Cancel", font_size=sp(14)))
        cancel.bind(on_release=lambda *a: popup.dismiss())
        select = ClickableBox(padding=(dp(8), dp(6)))
        select.add_widget(Label(text="Select", font_size=sp(14), bold=True))
        select.bind(on_release=lambda *a: (self._on_file_selected(fc.selection, popup)))
        btn_row.add_widget(cancel)
        btn_row.add_widget(select)
        content.add_widget(btn_row)
        popup.open()

    def _android_chooser(self, filters=None, multiple=False):
        try:
            from plyer import filechooser
            mime = ["image/*"]
            if filters:
                if "*.zip" in filters:
                    mime = ["application/zip"]
                elif "*.xlsx" in filters or "*.xls" in filters:
                    mime = ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            "application/vnd.ms-excel"]
            filechooser.open_file(
                on_selection=self._on_android_sel,
                multiple=multiple, filters=mime,
            )
        except Exception as e:
            self.show_toast(f"File picker: {str(e)[:50]}")

    def _on_android_sel(self, selection):
        if selection:
            self._on_file_selected(selection)

    def _on_file_selected(self, selection, popup=None):
        if popup:
            popup.dismiss()
        if not selection or not self.pick_image_for:
            return
        target_type, target_data = self.pick_image_for
        self.pick_image_for = None

        if target_type == "add_phone_screen":
            s = self.root.get_screen("add_phone")
            s.on_image_selected(selection[0])
        elif target_type == "add_spare_screen":
            s = self.root.get_screen("add_spare")
            s.on_image_selected(selection[0])
        elif target_type == "phone":
            img = copy_image_to_storage(selection[0], get_phone_images_path())
            if img:
                self.db.update_phone(target_data, image_path=img)
                d = self.root.get_screen("phone_detail")
                d.image_source = img
                self.show_toast("Image updated!")
        elif target_type == "restore_backup":
            s = self.root.get_screen("backup")
            s.on_backup_selected(selection[0])
        elif target_type == "bulk_images":
            s = self.root.get_screen("bulk_images")
            s.on_images_selected(selection)

    def take_camera_photo(self):
        if platform == "android":
            try:
                from jnius import autoclass, cast
                Intent = autoclass("android.content.Intent")
                MediaStore = autoclass("android.provider.MediaStore")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
                PythonActivity.mActivity.startActivityForResult(intent, 1002)
            except Exception as e:
                self.show_toast(f"Camera: {str(e)[:50]}")
        else:
            self.show_toast("Camera on Android only")

    def _load_initial_data(self):
        """Load initial phone data from bundled JSON on first run."""
        if not self.db:
            return
        if self.db.get_phone_count() > 0:
            return  # Data already exists
        try:
            # Try multiple locations for the JSON file
            json_paths = [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "initial_data.json"),
                os.path.join(get_app_path(), "initial_data.json"),
            ]
            data = None
            for jp in json_paths:
                if os.path.exists(jp):
                    with open(jp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    break
            if not data:
                return
            rows = []
            for item in data:
                code, model, year, appear, cond, comment = item
                rows.append({
                    "id": str(code),
                    "name": str(model),
                    "release_date": str(year),
                    "appearance_condition": str(appear),
                    "working_condition": str(cond),
                    "remarks": str(comment) if comment else "",
                })
            count = self.db.import_phones_from_rows(rows)
            print(f"Loaded {count} phones from initial data")
        except Exception as e:
            print(f"Initial data load error: {e}")

    def on_stop(self):
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass


if __name__ == "__main__":
    NokiaStorageApp().run()
