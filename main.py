"""
Nokia Storage Manager - Android Application
Images stored as BLOB in DB, displayed via cached files.
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
from kivy.uix.image import Image
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

# ── Paths ───────────────────────────────────────────────────────
def get_app_path():
    if platform == "android":
        try:
            return app_storage_path()
        except Exception:
            return os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.abspath(__file__))

def get_db_path():
    return os.path.join(get_app_path(), "nokia_storage.db")

def get_downloads_path():
    if platform == "android":
        try:
            return os.path.join(primary_external_storage_path(), "Download")
        except Exception:
            pass
    return os.path.join(get_app_path(), "exports")

# ── Image System: File-based via imghelper ──────────────────────
from imghelper import (
    get_default_image_path, blob_to_file, clear_cached_image,
    read_image_from_path, get_cache_dir
)

def get_img_path_for_phone(phone_id, db):
    """Get displayable image file path for a phone."""
    app_path = get_app_path()
    img_data = db.get_phone_image(phone_id)
    if img_data:
        return blob_to_file(img_data, f"p_{phone_id}", app_path)
    return get_default_image_path(app_path)

def get_img_path_for_spare(spare_id, db):
    """Get displayable image file path for a spare part."""
    app_path = get_app_path()
    img_data = db.get_spare_image(spare_id)
    if img_data:
        return blob_to_file(img_data, f"s_{spare_id}", app_path)
    return get_default_image_path(app_path)


# ── Custom Widgets ──────────────────────────────────────────────
class ClickableBox(ButtonBehavior, BoxLayout):
    pass

class ClickableLabel(ButtonBehavior, Label):
    pass

class PhoneCard(ButtonBehavior, BoxLayout):
    phone_id = StringProperty("")
    phone_name = StringProperty("")
    phone_date = StringProperty("")
    phone_appear = StringProperty("")
    phone_working = StringProperty("")
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
    height: dp(94)
    padding: dp(6)
    spacing: dp(8)
    orientation: 'horizontal'
    canvas.before:
        Color:
            rgba: 1, 1, 1, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
    Image:
        source: root.phone_image
        size_hint: None, None
        size: dp(64), dp(78)
        pos_hint: {'center_y': .5}
        allow_stretch: True
        keep_ratio: True
    BoxLayout:
        orientation: 'vertical'
        spacing: dp(1)
        padding: 0, dp(2)
        Label:
            text: root.phone_name
            font_size: sp(14)
            bold: True
            color: 0.1, 0.1, 0.18, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: None
            height: dp(20)
        Label:
            text: 'ID: ' + root.phone_id + '  |  ' + root.phone_date
            font_size: sp(10)
            color: 0.45, 0.45, 0.45, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: None
            height: dp(16)
        Label:
            text: root.phone_appear
            font_size: sp(10)
            color: 0.2, 0.5, 0.22, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: None
            height: dp(16)
        Label:
            text: root.phone_working
            font_size: sp(10)
            color: 0, 0.28, 0.7, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: None
            height: dp(16)

<SpareCard>:
    size_hint_y: None
    height: dp(74)
    padding: dp(6)
    spacing: dp(8)
    orientation: 'horizontal'
    canvas.before:
        Color:
            rgba: 1, 1, 1, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
    Image:
        source: root.spare_image
        size_hint: None, None
        size: dp(56), dp(60)
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
                width: dp(80)
                padding: dp(8), dp(5)
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
                width: dp(86)
                padding: dp(8), dp(5)
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
                # Phone Image - using Image widget, texture set from Python
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
                    Image:
                        id: detail_img
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
                    on_release: root.add_image()
                    Label:
                        text: 'Add / Change Image'
                        color: 0, 0.314, 0.784, 1
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
                            color: 0.2, 0.5, 0.22, 1
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
                            color: 0, 0.28, 0.7, 1
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
                    Image:
                        id: detail_img
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
                    on_release: root.add_image()
                    Label:
                        text: 'Add / Change Image'
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
                    Image:
                        id: preview_img
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
                    Image:
                        id: preview_img
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
                text: 'Export all data as CSV to Downloads.'
                font_size: sp(14)
                color: 0.3, 0.3, 0.3, 1
                size_hint_y: None
                height: dp(30)
                halign: 'left'
                text_size: self.size
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

<BackupScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6)
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
    _data_loaded = False

    def on_enter(self):
        if not self._data_loaded:
            Clock.schedule_once(lambda dt: self.refresh_list(), 0.2)
        else:
            self._render_page()

    def switch_tab(self, tab):
        self.current_tab = tab
        self._current_page = 0
        self._is_search = False
        self._data_loaded = False
        try: self.ids.search_bar.ids.search_input.text = ""
        except: pass
        self.refresh_list()

    def refresh_list(self):
        app = App.get_running_app()
        if not app.db: return
        self._current_page = 0
        self._all_items = app.db.get_all_phones() if self.current_tab == "phones" else app.db.get_all_spare_parts()
        self._total_items = len(self._all_items)
        self._is_search = False
        self._data_loaded = True
        self._render_page()

    def do_search(self, text):
        app = App.get_running_app()
        if not text.strip():
            self._data_loaded = False
            self.refresh_list()
            return
        self._current_page = 0
        self._all_items = app.db.search_phones(text) if self.current_tab == "phones" else app.db.search_spare_parts(text)
        self._total_items = len(self._all_items)
        self._is_search = True
        self._data_loaded = True
        self._render_page()

    def _pgbtn(self, text, cb):
        b = ClickableBox(padding=(dp(6), dp(3)), size_hint_x=None, width=dp(50))
        with b.canvas.before:
            Color(0, 0.314, 0.784, 1)
            b._bg = RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(6)])
        b.bind(pos=lambda w, v: setattr(w._bg, "pos", v), size=lambda w, v: setattr(w._bg, "size", v))
        b.add_widget(Label(text=text, color=(1,1,1,1), font_size=sp(11), bold=True))
        b.bind(on_release=cb)
        return b

    def _render_page(self):
        app = App.get_running_app()
        grid = self.ids.content_list
        grid.clear_widgets()
        start = self._current_page * PAGE_SIZE
        end = min(start + PAGE_SIZE, self._total_items)
        items = self._all_items[start:end]
        tp = max(1, (self._total_items + PAGE_SIZE - 1) // PAGE_SIZE)
        cp = self._current_page + 1
        lt = "found" if self._is_search else ("phones" if self.current_tab == "phones" else "parts")
        self.ids.count_label.text = f"{self._total_items} {lt} | {cp}/{tp}"
        defimg = get_default_image_path(get_app_path())

        if self.current_tab == "phones":
            for p in items:
                img = get_img_path_for_phone(p["id"], app.db) if p.get("has_image") else defimg
                card = PhoneCard(phone_id=p["id"], phone_name=p["name"],
                    phone_date=p.get("release_date","") or "",
                    phone_appear=p.get("appearance_condition","") or "",
                    phone_working=p.get("working_condition","") or "",
                    phone_image=img or defimg)
                card.bind(on_release=partial(self._open_phone, p["id"]))
                grid.add_widget(card)
        else:
            for s in items:
                img = get_img_path_for_spare(s["id"], app.db) if s.get("has_image") else defimg
                card = SpareCard(spare_id=s["id"], spare_name=s["name"],
                    spare_desc=s.get("description","") or "",
                    spare_image=img or defimg)
                card.bind(on_release=partial(self._open_spare, s["id"]))
                grid.add_widget(card)

        if self._total_items > PAGE_SIZE:
            pg = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(3), padding=(dp(2),dp(2)))
            if self._current_page > 1: pg.add_widget(self._pgbtn("|<", lambda *a: self._goto(0)))
            if self._current_page > 0: pg.add_widget(self._pgbtn("< Prev", lambda *a: self._goto(self._current_page-1)))
            pi = TextInput(text=str(cp), multiline=False, size_hint_x=None, width=dp(40),
                font_size=sp(11), halign="center", padding=(dp(3),dp(5)), input_filter="int")
            pi.bind(on_text_validate=lambda w: self._goto(max(0, min(tp-1, int(w.text)-1)) if w.text.isdigit() else 0))
            pg.add_widget(pi)
            pg.add_widget(Label(text=f"/{tp}", font_size=sp(11), color=(0.4,0.4,0.4,1), size_hint_x=None, width=dp(30)))
            if end < self._total_items: pg.add_widget(self._pgbtn("Next >", lambda *a: self._goto(self._current_page+1)))
            if self._current_page < tp-2: pg.add_widget(self._pgbtn(">|", lambda *a: self._goto(tp-1)))
            grid.add_widget(pg)
        try: self.ids.scroll_view.scroll_y = 1
        except: pass

    def _goto(self, p):
        self._current_page = p
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
            s = app.root.get_screen("add_phone"); s.edit_mode = False; s.clear_form()
            app.root.current = "add_phone"
        else:
            s = app.root.get_screen("add_spare"); s.clear_form()
            app.root.current = "add_spare"

    def search_all(self):
        app = App.get_running_app()
        try: q = self.ids.search_bar.ids.search_input.text
        except: q = ""
        app.root.get_screen("search_all").initial_query = q
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "search_all"

    def show_menu(self):
        popup = ModalView(size_hint=(0.72, None), height=dp(230))
        c = BoxLayout(orientation="vertical", spacing=dp(2), padding=dp(10))
        with c.canvas.before:
            Color(1,1,1,1)
            c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        for t, n in [("Export Data","export_data"),("Backup & Restore","backup"),("Storage Report","report")]:
            b = ClickableBox(size_hint_y=None, height=dp(46), padding=(dp(14),dp(8)))
            b.add_widget(Label(text=t, font_size=sp(14), color=(0.1,0.1,0.18,1), text_size=(dp(200),None), halign="left"))
            b.bind(on_release=lambda *a, nm=n, p=popup: (p.dismiss(), self._nav(nm)))
            c.add_widget(b)
        popup.add_widget(c); popup.open()

    def _nav(self, n):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="left"); app.root.current = n


class PhoneDetailScreen(Screen):
    p_id = StringProperty(""); p_name = StringProperty(""); p_date = StringProperty("")
    p_appear = StringProperty(""); p_working = StringProperty(""); p_remarks = StringProperty("")

    def load_phone(self, pid):
        app = App.get_running_app()
        p = app.db.get_phone(pid)
        if not p: return
        self.p_id = p["id"]; self.p_name = p["name"]
        self.p_date = p.get("release_date","") or ""
        self.p_appear = p.get("appearance_condition","") or ""
        self.p_working = p.get("working_condition","") or ""
        r = p.get("remarks","") or ""; self.p_remarks = "" if r in ("None","none") else r
        img = get_img_path_for_phone(pid, app.db)
        Clock.schedule_once(lambda dt: self._set_img(img), 0.1)
        Clock.schedule_once(lambda dt: self._load_spares(), 0.15)

    def _set_img(self, path):
        try:
            self.ids.detail_img.source = path or get_default_image_path(get_app_path())
        except: pass

    def _load_spares(self):
        app = App.get_running_app()
        grid = self.ids.spare_parts_grid; grid.clear_widgets()
        spares = app.db.get_spare_parts_for_phone(self.p_name)
        defimg = get_default_image_path(get_app_path())
        if not spares:
            grid.add_widget(Label(text="No spare parts", font_size=sp(12), color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(24)))
            return
        for s in spares:
            img = get_img_path_for_spare(s["id"], app.db) if s.get("has_image") else defimg
            card = SpareCard(spare_id=s["id"], spare_name=s["name"],
                spare_desc=s.get("description","") or "", spare_image=img or defimg)
            card.bind(on_release=partial(self._open_spare, s["id"]))
            grid.add_widget(card)

    def _open_spare(self, sid, *a):
        app = App.get_running_app()
        app.root.get_screen("spare_detail").load_spare(sid)
        app.root.transition = SlideTransition(direction="left"); app.root.current = "spare_detail"

    def add_image(self):
        """Show popup with Gallery and Camera options."""
        popup = ModalView(size_hint=(0.72, None), height=dp(120))
        c = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(10))
        with c.canvas.before:
            Color(1,1,1,1); c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        gb = ClickableBox(size_hint_y=None, height=dp(42), padding=(dp(10),dp(6)))
        gb.add_widget(Label(text="Pick from Gallery", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        gb.bind(on_release=lambda *a: (popup.dismiss(), self._pick_gallery()))
        cb = ClickableBox(size_hint_y=None, height=dp(42), padding=(dp(10),dp(6)))
        cb.add_widget(Label(text="Take Photo", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        cb.bind(on_release=lambda *a: (popup.dismiss(), self._pick_camera()))
        c.add_widget(gb); c.add_widget(cb)
        popup.add_widget(c); popup.open()

    def _pick_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("phone_direct", self.p_id)
        app.open_file_chooser()

    def _pick_camera(self):
        app = App.get_running_app()
        app.pick_image_for = ("phone_direct", self.p_id)
        app.take_camera_photo()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right"); app.root.current = "main"

    def edit_phone(self):
        app = App.get_running_app()
        s = app.root.get_screen("add_phone"); s.edit_mode = True; s.load_for_edit(self.p_id)
        app.root.transition = SlideTransition(direction="left"); app.root.current = "add_phone"

    def confirm_delete(self):
        popup = ModalView(size_hint=(0.78, None), height=dp(130))
        c = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        with c.canvas.before:
            Color(1,1,1,1); c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        c.add_widget(Label(text=f"Delete {self.p_name}?", font_size=sp(15), color=(0.1,0.1,0.18,1), size_hint_y=None, height=dp(28)))
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        cb = ClickableBox(padding=(dp(8),dp(5))); cb.add_widget(Label(text="Cancel", font_size=sp(13), color=(0.4,0.4,0.4,1)))
        cb.bind(on_release=lambda *a: popup.dismiss())
        db = ClickableBox(padding=(dp(8),dp(5)))
        with db.canvas.before:
            Color(0.9,0.22,0.21,1); db._bg = RoundedRectangle(pos=db.pos, size=db.size, radius=[dp(7)])
        db.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        db.add_widget(Label(text="Delete", font_size=sp(13), color=(1,1,1,1), bold=True))
        db.bind(on_release=lambda *a: (App.get_running_app().db.delete_phone(self.p_id),
            setattr(App.get_running_app().root.get_screen("main"), "_data_loaded", False),
            popup.dismiss(), self.go_back()))
        row.add_widget(cb); row.add_widget(db); c.add_widget(row)
        popup.add_widget(c); popup.open()

    def add_spare_for_phone(self):
        app = App.get_running_app()
        s = app.root.get_screen("add_spare"); s.clear_form()
        Clock.schedule_once(lambda dt: self._prefill(s), 0.2)
        app.root.transition = SlideTransition(direction="left"); app.root.current = "add_spare"

    def _prefill(self, s):
        try: s.ids.spare_input_name.text = self.p_name; s.ids.spare_input_phone_id.text = self.p_id
        except: pass


class SpareDetailScreen(Screen):
    s_id = NumericProperty(0); s_id_str = StringProperty(""); s_name = StringProperty("")
    s_desc = StringProperty(""); s_phone_id = StringProperty("")

    def load_spare(self, sid):
        app = App.get_running_app()
        s = app.db.get_spare_part(sid)
        if not s: return
        self.s_id = s["id"]; self.s_id_str = str(s["id"]); self.s_name = s["name"]
        d = s.get("description","") or ""; self.s_desc = "" if d=="None" else d
        self.s_phone_id = s.get("phone_id","") or ""
        img = get_img_path_for_spare(sid, app.db)
        Clock.schedule_once(lambda dt: self._set_img(img), 0.1)

    def _set_img(self, path):
        try:
            self.ids.detail_img.source = path or get_default_image_path(get_app_path())
        except: pass

    def add_image(self):
        popup = ModalView(size_hint=(0.72, None), height=dp(120))
        c = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(10))
        with c.canvas.before:
            Color(1,1,1,1); c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        gb = ClickableBox(size_hint_y=None, height=dp(42), padding=(dp(10),dp(6)))
        gb.add_widget(Label(text="Pick from Gallery", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        gb.bind(on_release=lambda *a: (popup.dismiss(), self._pick_gallery()))
        cb = ClickableBox(size_hint_y=None, height=dp(42), padding=(dp(10),dp(6)))
        cb.add_widget(Label(text="Take Photo", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        cb.bind(on_release=lambda *a: (popup.dismiss(), self._pick_camera()))
        c.add_widget(gb); c.add_widget(cb)
        popup.add_widget(c); popup.open()

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
            Color(1,1,1,1); c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        c.add_widget(Label(text=f"Delete {self.s_name}?", font_size=sp(15), color=(0.1,0.1,0.18,1), size_hint_y=None, height=dp(28)))
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        cb = ClickableBox(padding=(dp(8),dp(5))); cb.add_widget(Label(text="Cancel", font_size=sp(13)))
        cb.bind(on_release=lambda *a: popup.dismiss())
        db = ClickableBox(padding=(dp(8),dp(5)))
        with db.canvas.before:
            Color(0.9,0.22,0.21,1); db._bg = RoundedRectangle(pos=db.pos, size=db.size, radius=[dp(7)])
        db.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        db.add_widget(Label(text="Delete", font_size=sp(13), color=(1,1,1,1), bold=True))
        db.bind(on_release=lambda *a: (App.get_running_app().db.delete_spare_part(self.s_id),
            setattr(App.get_running_app().root.get_screen("main"), "_data_loaded", False),
            popup.dismiss(), self.go_back()))
        row.add_widget(cb); row.add_widget(db); c.add_widget(row)
        popup.add_widget(c); popup.open()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right"); app.root.current = "main"


class AddPhoneScreen(Screen):
    edit_mode = BooleanProperty(False)
    screen_title = StringProperty("Add Phone")
    _image_bytes = None  # Store raw bytes in memory

    def on_edit_mode(self, *a):
        self.screen_title = "Edit Phone" if self.edit_mode else "Add Phone"

    def clear_form(self):
        self._image_bytes = None
        Clock.schedule_once(self._clear, 0.1)

    def _clear(self, *a):
        try:
            for fid in ["input_id","input_name","input_date","input_appear","input_working","input_remarks"]:
                self.ids[fid].text = ""
            self.ids.preview_img.source = get_default_image_path(get_app_path())
        except: pass

    def load_for_edit(self, pid):
        app = App.get_running_app()
        p = app.db.get_phone(pid)
        if not p: return
        self._image_bytes = app.db.get_phone_image(pid)
        img = get_img_path_for_phone(pid, app.db)
        Clock.schedule_once(partial(self._fill, p, img), 0.1)

    def _fill(self, p, img_path, *a):
        try:
            self.ids.input_id.text = p["id"]; self.ids.input_name.text = p["name"]
            self.ids.input_date.text = p.get("release_date","") or ""
            self.ids.input_appear.text = p.get("appearance_condition","") or ""
            self.ids.input_working.text = p.get("working_condition","") or ""
            r = p.get("remarks","") or ""; self.ids.input_remarks.text = "" if r in ("None","none") else r
            self.ids.preview_img.source = img_path or get_default_image_path(get_app_path())
        except: pass

    def pick_from_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_phone_screen", None); app.open_file_chooser()

    def take_photo(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_phone_screen", None); app.take_camera_photo()

    def on_image_selected(self, img_bytes):
        """Called with raw image bytes."""
        self._image_bytes = img_bytes
        if img_bytes:
            # Write to temp file for preview
            tmp = os.path.join(get_cache_dir(get_app_path()), "_preview_phone.tmp")
            try:
                with open(tmp, "wb") as f:
                    f.write(img_bytes)
                self.ids.preview_img.source = ""  # force reload
                Clock.schedule_once(lambda dt: setattr(self.ids.preview_img, "source", tmp), 0.1)
            except: pass

    def save_phone(self):
        app = App.get_running_app()
        try: pid = self.ids.input_id.text.strip(); name = self.ids.input_name.text.strip()
        except: return
        if not pid or not name:
            app.show_toast("ID and Name required"); return
        app.db.add_phone(phone_id=pid, name=name,
            release_date=self.ids.input_date.text.strip(),
            appearance=self.ids.input_appear.text.strip(),
            working=self.ids.input_working.text.strip(),
            remarks=self.ids.input_remarks.text.strip(),
            image_bytes=self._image_bytes)
        clear_cached_image(f"p_{pid}", get_app_path())
        app.root.get_screen("main")._data_loaded = False
        app.show_toast("Phone saved!"); self.go_back()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right"); app.root.current = "main"


class AddSpareScreen(Screen):
    _image_bytes = None

    def clear_form(self):
        self._image_bytes = None
        Clock.schedule_once(self._clear, 0.1)

    def _clear(self, *a):
        try:
            self.ids.spare_input_name.text = ""; self.ids.spare_input_desc.text = ""
            self.ids.spare_input_phone_id.text = ""
            self.ids.preview_img.source = get_default_image_path(get_app_path())
        except: pass

    def pick_from_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_spare_screen", None); app.open_file_chooser()

    def take_photo(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_spare_screen", None); app.take_camera_photo()

    def on_image_selected(self, img_bytes):
        self._image_bytes = img_bytes
        if img_bytes:
            tmp = os.path.join(get_cache_dir(get_app_path()), "_preview_spare.tmp")
            try:
                with open(tmp, "wb") as f:
                    f.write(img_bytes)
                self.ids.preview_img.source = ""
                Clock.schedule_once(lambda dt: setattr(self.ids.preview_img, "source", tmp), 0.1)
            except: pass

    def save_spare(self):
        app = App.get_running_app()
        try: name = self.ids.spare_input_name.text.strip()
        except: return
        if not name: app.show_toast("Name required"); return
        app.db.add_spare_part(name=name, phone_id=self.ids.spare_input_phone_id.text.strip(),
            image_bytes=self._image_bytes, description=self.ids.spare_input_desc.text.strip())
        app.root.get_screen("main")._data_loaded = False
        app.show_toast("Spare part saved!"); self.go_back()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right"); app.root.current = "main"


class ExportScreen(Screen):
    def do_export(self):
        app = App.get_running_app()
        try:
            od = get_downloads_path(); os.makedirs(od, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fp = os.path.join(od, f"nokia_phones_{ts}.csv")
            phones = app.db.export_phones()
            with open(fp, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ID","Name","Release Date","Appearance","Working","Remarks"])
                for p in phones:
                    w.writerow([p["id"],p["name"],p.get("release_date",""),p.get("appearance_condition",""),p.get("working_condition",""),p.get("remarks","")])
            sp2 = os.path.join(od, f"nokia_spares_{ts}.csv")
            spares = app.db.export_spare_parts()
            with open(sp2, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ID","Name","Phone ID","Description"])
                for s in spares: w.writerow([s["id"],s["name"],s.get("phone_id",""),s.get("description","")])
            self.ids.export_status.text = f"Saved to Downloads!"; self.ids.export_status.color = (0.26,0.63,0.28,1)
            app.show_toast("Exported!")
        except Exception as e:
            self.ids.export_status.text = f"Error: {str(e)[:80]}"; self.ids.export_status.color = (0.9,0.22,0.21,1)

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class BackupScreen(Screen):
    def create_backup(self):
        app = App.get_running_app()
        try:
            od = get_downloads_path(); os.makedirs(od, exist_ok=True)
            bf = os.path.join(od, f"nokia_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
            with zipfile.ZipFile(bf, "w", zipfile.ZIP_DEFLATED) as zf:
                dbp = get_db_path()
                if os.path.exists(dbp): zf.write(dbp, "nokia_storage.db")
            self.ids.backup_status.text = f"Saved to Downloads!"; self.ids.backup_status.color = (0.26,0.63,0.28,1)
            app.show_toast("Backup created!")
        except Exception as e:
            self.ids.backup_status.text = f"Error: {str(e)[:80]}"; self.ids.backup_status.color = (0.9,0.22,0.21,1)

    def restore_backup(self):
        app = App.get_running_app()
        app.pick_image_for = ("restore_backup", None); app.open_file_chooser(filters=["*.zip"])

    def on_backup_selected(self, path):
        app = App.get_running_app()
        try:
            app.db.close()
            with zipfile.ZipFile(path, "r") as zf: zf.extractall(get_app_path())
            app.db = NokiaDatabase(get_db_path())
            # Clear image cache
            try:
                import shutil
                cd = get_cache_dir(get_app_path())
                if os.path.isdir(cd):
                    shutil.rmtree(cd, ignore_errors=True)
            except: pass
            self.ids.backup_status.text = "Restored!"; app.show_toast("Restored!")
        except Exception as e:
            app.db = NokiaDatabase(get_db_path())
            self.ids.backup_status.text = f"Error: {str(e)[:80]}"

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class SearchAllScreen(Screen):
    initial_query = StringProperty("")
    def on_enter(self):
        if self.initial_query: Clock.schedule_once(self._sq, 0.1)
    def _sq(self, *a):
        try: self.ids.search_all_bar.ids.search_input.text = self.initial_query
        except: pass
        self.do_search(self.initial_query)

    def do_search(self, text):
        app = App.get_running_app()
        grid = self.ids.results_list; grid.clear_widgets()
        if not text.strip():
            grid.add_widget(Label(text="Type and press Enter", font_size=sp(13), color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(36)))
            return
        phones, spares = app.db.search_all(text)
        defimg = get_default_image_path(get_app_path())
        if phones:
            grid.add_widget(Label(text=f"Phones ({len(phones)})", font_size=sp(14), bold=True, color=(0,0.314,0.784,1), size_hint_y=None, height=dp(26), text_size=(dp(300),None), halign="left"))
            for p in phones[:PAGE_SIZE]:
                img = get_img_path_for_phone(p["id"], app.db) if p.get("has_image") else defimg
                card = PhoneCard(phone_id=p["id"], phone_name=p["name"], phone_date=p.get("release_date","") or "",
                    phone_appear=p.get("appearance_condition","") or "", phone_working=p.get("working_condition","") or "",
                    phone_image=img or defimg)
                card.bind(on_release=partial(self._op, p["id"])); grid.add_widget(card)
        if spares:
            grid.add_widget(Label(text=f"Spare Parts ({len(spares)})", font_size=sp(14), bold=True, color=(0,0.314,0.784,1), size_hint_y=None, height=dp(26), text_size=(dp(300),None), halign="left"))
            for s in spares[:PAGE_SIZE]:
                img = get_img_path_for_spare(s["id"], app.db) if s.get("has_image") else defimg
                card = SpareCard(spare_id=s["id"], spare_name=s["name"], spare_desc=s.get("description","") or "",
                    spare_image=img or defimg)
                card.bind(on_release=partial(self._os, s["id"])); grid.add_widget(card)
        if not phones and not spares:
            grid.add_widget(Label(text="No results", font_size=sp(13), color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(36)))

    def _op(self, pid, *a):
        app = App.get_running_app()
        app.root.get_screen("phone_detail").load_phone(pid)
        app.root.transition = SlideTransition(direction="left"); app.root.current = "phone_detail"
    def _os(self, sid, *a):
        app = App.get_running_app()
        app.root.get_screen("spare_detail").load_spare(sid)
        app.root.transition = SlideTransition(direction="left"); app.root.current = "spare_detail"
    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class ReportScreen(Screen):
    def on_enter(self):
        Clock.schedule_once(lambda dt: self._load(), 0.2)
    def _load(self):
        app = App.get_running_app()
        g = self.ids.report_grid; g.clear_widgets()
        try: r = app.db.get_report()
        except: g.add_widget(Label(text="Error", size_hint_y=None, height=dp(30))); return
        def sec(t):
            g.add_widget(Label(text=t, font_size=sp(16), bold=True, color=(0,0.314,0.784,1), size_hint_y=None, height=dp(30), text_size=(dp(300),None), halign="left"))
        def st(l, v):
            row = BoxLayout(size_hint_y=None, height=dp(24), padding=(dp(8),dp(1)))
            row.add_widget(Label(text=l, font_size=sp(12), color=(0.3,0.3,0.3,1), text_size=(dp(220),None), halign="left"))
            row.add_widget(Label(text=str(v), font_size=sp(12), bold=True, color=(0.1,0.1,0.18,1), size_hint_x=None, width=dp(50), halign="right", text_size=(dp(50),None)))
            g.add_widget(row)
        sec("Overview")
        bx = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(100), padding=dp(12), spacing=dp(4))
        with bx.canvas.before:
            Color(1,1,1,1); bx._bg = RoundedRectangle(pos=bx.pos, size=bx.size, radius=[dp(10)])
        bx.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        for t in [f"Total Phones: {r['total_phones']}", f"Unique Models: {r['unique_models']}",
                  f"With Images: {r['phones_with_images']}", f"Total Spare Parts: {r['total_spares']}"]:
            bx.add_widget(Label(text=t, font_size=sp(14), color=(0.1,0.1,0.18,1), size_hint_y=None, height=dp(20), text_size=(dp(280),None), halign="left"))
        g.add_widget(bx)
        sec("By Working Condition")
        for n, c in r.get("by_working",[]): st(n, c)
        sec("By Appearance")
        for n, c in r.get("by_appearance",[]): st(n, c)
        sec("Top 20 Models")
        for n, c in r.get("by_model",[]): st(n, c)
        g.add_widget(Widget(size_hint_y=None, height=dp(30)))
    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


# ── Main App ────────────────────────────────────────────────────

class NokiaStorageApp(App):
    title = "Nokia Storage"
    db = ObjectProperty(None, allownone=True)
    pick_image_for = None
    _last_back = 0

    def build(self):
        Window.clearcolor = (0.94, 0.96, 1, 1)
        try: self.db = NokiaDatabase(get_db_path())
        except Exception as e: print(f"DB: {e}")
        if platform == "android":
            Clock.schedule_once(lambda dt: self._perms(), 1)
        self._load_initial()
        Window.bind(on_keyboard=self._kb)
        return Builder.load_string(KV)

    def _kb(self, win, key, *a):
        if key == 27:
            if self.root and self.root.current != "main":
                self.root.transition = SlideTransition(direction="right"); self.root.current = "main"
                return True
            now = time.time()
            if now - self._last_back < 2: return False
            self._last_back = now; self.show_toast("Press back again to exit"); return True
        return False

    def _perms(self):
        if platform == "android":
            try: request_permissions([Permission.CAMERA, Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE])
            except: pass

    def _load_initial(self):
        if not self.db or self.db.get_phone_count() > 0: return
        try:
            for jp in [os.path.join(os.path.dirname(os.path.abspath(__file__)), "initial_data.json"),
                       os.path.join(get_app_path(), "initial_data.json")]:
                if os.path.exists(jp):
                    with open(jp, "r", encoding="utf-8") as f: data = json.load(f)
                    rows = [{"id":str(i[0]),"name":str(i[1]),"release_date":str(i[2]),
                             "appearance_condition":str(i[3]),"working_condition":str(i[4]),
                             "remarks":str(i[5]) if i[5] else ""} for i in data]
                    self.db.import_phones_from_rows(rows); break
        except Exception as e: print(f"Init: {e}")

    def show_toast(self, text):
        try:
            p = ModalView(size_hint=(0.8,None), height=dp(46), background_color=(0,0,0,0), pos_hint={"center_x":0.5,"y":0.05})
            bx = BoxLayout(padding=dp(10))
            with bx.canvas.before:
                Color(0.15,0.15,0.15,0.92); bx._bg = RoundedRectangle(pos=bx.pos, size=bx.size, radius=[dp(8)])
            bx.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
            bx.add_widget(Label(text=text, color=(1,1,1,1), font_size=sp(13)))
            p.add_widget(bx); p.open(); Clock.schedule_once(lambda dt: p.dismiss(), 2)
        except: pass

    def open_file_chooser(self, filters=None, multiple=False):
        if platform == "android": self._ac(filters, multiple)
        else: self._dc(filters, multiple)

    def _dc(self, filters=None, multiple=False):
        from kivy.uix.filechooser import FileChooserListView
        fc = FileChooserListView(filters=filters or ["*.png","*.jpg","*.jpeg"], path=os.path.expanduser("~"), multiselect=multiple or False)
        c = BoxLayout(orientation="vertical", spacing=dp(6)); c.add_widget(fc)
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        popup = Popup(title="Select File", content=c, size_hint=(0.95, 0.85))
        cb = ClickableBox(padding=(dp(6),dp(4))); cb.add_widget(Label(text="Cancel", font_size=sp(13)))
        cb.bind(on_release=lambda *a: popup.dismiss())
        sb = ClickableBox(padding=(dp(6),dp(4))); sb.add_widget(Label(text="Select", font_size=sp(13), bold=True))
        sb.bind(on_release=lambda *a: self._fsel(fc.selection, popup))
        row.add_widget(cb); row.add_widget(sb); c.add_widget(row); popup.open()

    def _ac(self, filters=None, multiple=False):
        try:
            from plyer import filechooser
            mime = ["image/*"]
            if filters and "*.zip" in filters: mime = ["application/zip"]
            filechooser.open_file(on_selection=lambda s: self._fsel(s), multiple=multiple, filters=mime)
        except Exception as e: self.show_toast(f"Picker: {str(e)[:50]}")

    def _fsel(self, sel, popup=None):
        if popup: popup.dismiss()
        if not sel or not self.pick_image_for: return
        tt, td = self.pick_image_for; self.pick_image_for = None

        if tt in ("add_phone_screen", "add_spare_screen"):
            # Read bytes immediately from selected file
            img_bytes = read_image_from_path(sel[0])
            if img_bytes:
                img_bytes = NokiaDatabase.make_thumbnail(img_bytes, 400)
            screen_name = "add_phone" if tt == "add_phone_screen" else "add_spare"
            s = self.root.get_screen(screen_name)
            if img_bytes:
                s.on_image_selected(img_bytes)
            else:
                self.show_toast("Could not read image")
        elif tt == "phone_direct":
            # Directly update phone image from detail page
            img_bytes = read_image_from_path(sel[0])
            if img_bytes:
                self.db.update_phone(td, image_path=sel[0])
                clear_cached_image(f"p_{td}", get_app_path())
                new_img = get_img_path_for_phone(td, self.db)
                d = self.root.get_screen("phone_detail")
                d.ids.detail_img.source = ""
                Clock.schedule_once(lambda dt: setattr(d.ids.detail_img, "source", new_img), 0.15)
                self.root.get_screen("main")._data_loaded = False
                self.show_toast("Image updated!")
            else:
                self.show_toast("Could not read image")
        elif tt == "spare_direct":
            img_bytes = read_image_from_path(sel[0])
            if img_bytes:
                self.db.update_spare_part(td, image_path=sel[0])
                clear_cached_image(f"s_{td}", get_app_path())
                new_img = get_img_path_for_spare(td, self.db)
                d = self.root.get_screen("spare_detail")
                d.ids.detail_img.source = ""
                Clock.schedule_once(lambda dt: setattr(d.ids.detail_img, "source", new_img), 0.15)
                self.root.get_screen("main")._data_loaded = False
                self.show_toast("Image updated!")
            else:
                self.show_toast("Could not read image")
        elif tt == "restore_backup":
            self.root.get_screen("backup").on_backup_selected(sel[0])

    def take_camera_photo(self):
        if platform == "android":
            try:
                from jnius import autoclass
                Intent = autoclass("android.content.Intent")
                MediaStore = autoclass("android.provider.MediaStore")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
                PythonActivity.mActivity.startActivityForResult(intent, 1002)
            except Exception as e: self.show_toast(f"Camera: {str(e)[:50]}")
        else: self.show_toast("Camera on Android only")

    def on_stop(self):
        if self.db:
            try: self.db.close()
            except: pass


if __name__ == "__main__":
    NokiaStorageApp().run()
