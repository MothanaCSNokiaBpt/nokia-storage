"""
Nokia Storage Manager - Android Application
Images stored as BLOB in DB, displayed via cached files.
"""

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
    StringProperty, ObjectProperty, NumericProperty, BooleanProperty, ListProperty
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
from kivy.uix.spinner import Spinner, SpinnerOption
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

# -- Paths ---------------------------------------------------------
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

# -- Share helpers (proven working pattern from pyjnius docs) ------
def _share_text_android(text):
    if platform != "android":
        return
    try:
        from androidstorage4kivy import ShareSheet
        ShareSheet().share_plain_text(text)
    except Exception as e:
        App.get_running_app().show_toast(f"Share: {str(e)[:50]}")

def _share_file_android(filepath, mime_type="*/*"):
    if platform != "android":
        return
    try:
        from androidstorage4kivy import SharedStorage, ShareSheet
        # Copy to shared storage first so other apps can access it
        shared_path = SharedStorage().copy_to_shared(filepath)
        if shared_path:
            ShareSheet().share_file(shared_path)
        else:
            App.get_running_app().show_toast("Could not share file")
    except Exception as e:
        App.get_running_app().show_toast(f"Share: {str(e)[:50]}")

# -- Image System: File-based via imghelper ------------------------
from imghelper import (
    get_default_image_path, write_blob_to_file, clear_item_cache,
    smart_read, get_cache_dir
)

def get_img_path_for_phone(phone_id, db):
    """Get displayable image file path for a phone."""
    app_path = get_app_path()
    img_data = db.get_phone_image(phone_id)
    if img_data:
        return write_blob_to_file(img_data, f"p_{phone_id}", app_path)
    return get_default_image_path(app_path)

def get_img_path_for_spare(spare_id, db):
    """Get displayable image file path for a spare part."""
    app_path = get_app_path()
    img_data = db.get_spare_image(spare_id)
    if img_data:
        return write_blob_to_file(img_data, f"s_{spare_id}", app_path)
    return get_default_image_path(app_path)

def get_img_path_for_wall(item_id, db):
    """Get displayable image file path for a wall item."""
    app_path = get_app_path()
    img_data = db.get_wall_image(item_id)
    if img_data:
        return write_blob_to_file(img_data, f"w_{item_id}", app_path)
    return get_default_image_path(app_path)


# -- Rarity helpers ------------------------------------------------
def rarity_label(score):
    if score <= 0: return "Unknown"
    elif score <= 1: return "Very common"
    elif score <= 1.5: return "Common"
    elif score <= 2: return "Average"
    elif score <= 2.5: return "Above average"
    elif score <= 3: return "Uncommon"
    elif score <= 3.5: return "Limited"
    elif score <= 4: return "Rare"
    elif score <= 4.5: return "Very rare"
    else: return "Extremely rare"

def rarity_stars(score):
    if score <= 0: return ""
    full = int(score)
    return "*" * full

def rarity_color(score):
    if score <= 1: return [0.5, 0.5, 0.5, 1]
    elif score <= 2: return [0.3, 0.6, 0.3, 1]
    elif score <= 3: return [0.8, 0.6, 0.1, 1]
    elif score <= 4: return [0.8, 0.2, 0.2, 1]
    else: return [0.6, 0.1, 0.6, 1]


# -- XLSX Creator (pure Python, no openpyxl) -----------------------
def create_xlsx(sheets_data, filepath):
    import zipfile as zf_mod
    with zf_mod.ZipFile(filepath, 'w', zf_mod.ZIP_DEFLATED) as zf:
        ct = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        ct += '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        ct += '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        ct += '<Default Extension="xml" ContentType="application/xml"/>'
        for i in range(len(sheets_data)):
            ct += f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        ct += '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        ct += '</Types>'
        zf.writestr('[Content_Types].xml', ct)
        rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        zf.writestr('_rels/.rels', rels)
        wb_rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        for i in range(len(sheets_data)):
            wb_rels += f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>'
        wb_rels += '</Relationships>'
        zf.writestr('xl/_rels/workbook.xml.rels', wb_rels)
        wb = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        for i, name in enumerate(sheets_data.keys(), 1):
            wb += f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
        wb += '</sheets></workbook>'
        zf.writestr('xl/workbook.xml', wb)
        def esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        for i, (name, rows) in enumerate(sheets_data.items(), 1):
            ws = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            for r, row in enumerate(rows, 1):
                ws += f'<row r="{r}">'
                for c, val in enumerate(row):
                    col = chr(65+c) if c < 26 else chr(64+c//26)+chr(65+c%26)
                    ws += f'<c r="{col}{r}" t="inlineStr"><is><t>{esc(val)}</t></is></c>'
                ws += '</row>'
            ws += '</sheetData></worksheet>'
            zf.writestr(f'xl/worksheets/sheet{i}.xml', ws)


# -- Custom Widgets ------------------------------------------------
class ClickableBox(ButtonBehavior, BoxLayout):
    pass

class ClickableLabel(ButtonBehavior, Label):
    pass

class BlueSpinnerOption(SpinnerOption):
    pass

class PhoneCard(ButtonBehavior, BoxLayout):
    phone_id = StringProperty("")
    phone_name = StringProperty("")
    phone_date = StringProperty("")
    phone_appear = StringProperty("")
    phone_working = StringProperty("")
    phone_image = StringProperty("")
    phone_price = StringProperty("")

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


# -- KV Layout -----------------------------------------------------
KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<ClickableBox>:
<ClickableLabel>:

<BlueSpinnerOption>:
    background_normal: ''
    background_color: 0, 0.275, 0.69, 1
    color: 1, 1, 1, 1
    font_size: sp(13)
    height: dp(40)

<PhoneCard>:
    size_hint_y: None
    height: dp(108)
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
        nocache: True
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
        Label:
            text: root.phone_price
            font_size: sp(10)
            color: 0.1, 0.5, 0.3, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            size_hint_y: None
            height: dp(14)

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
        nocache: True
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
    SplashScreen:
        name: 'splash'
    DashboardScreen:
        name: 'dashboard'
    MainScreen:
        name: 'main'
    PhoneDetailScreen:
        name: 'phone_detail'
    SpareDetailScreen:
        name: 'spare_detail'
    WallDetailScreen:
        name: 'wall_detail'
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
    PhotoGalleryScreen:
        name: 'photo_gallery'

<SplashScreen>:
    BoxLayout:
        orientation: 'vertical'
        canvas.before:
            Color:
                rgba: 1, 1, 1, 1
            Rectangle:
                pos: self.pos
                size: self.size
        Widget:
        Label:
            text: 'NOKIA'
            font_size: sp(48)
            bold: True
            color: 0, 0.314, 0.784, 1
            size_hint_y: None
            height: dp(60)
        Widget:

<DashboardScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(10), dp(6)
            spacing: dp(6)
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
        ScrollView:
            do_scroll_x: False
            GridLayout:
                id: dash_grid
                cols: 1
                spacing: dp(8)
                padding: dp(14)
                size_hint_y: None
                height: self.minimum_height

<MainScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(10), dp(6)
            spacing: dp(6)
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
            Button:
                text: 'Home'
                size_hint_x: None
                width: dp(58)
                font_size: sp(12)
                bold: True
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 1, 1, 1, 1
                canvas.before:
                    Color:
                        rgba: 0.15, 0.4, 0.85, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(14)]
                on_press: root.go_dashboard()
            Button:
                text: 'Reset'
                size_hint_x: None
                width: dp(50)
                font_size: sp(11)
                bold: True
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 1, 1, 1, 1
                canvas.before:
                    Color:
                        rgba: 0.2, 0.55, 0.2, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(14)]
                on_press: root.refresh_home()
            Button:
                text: 'Gallery'
                size_hint_x: None
                width: dp(58)
                font_size: sp(12)
                bold: True
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 1, 1, 1, 1
                canvas.before:
                    Color:
                        rgba: 0.15, 0.4, 0.85, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(14)]
                on_press: root.open_gallery()
        SearchBar:
            id: search_bar
        # Sort & Filter bar
        BoxLayout:
            size_hint_y: None
            height: dp(38)
            padding: dp(8), dp(3)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0.94, 0.95, 0.98, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            Spinner:
                id: sort_spinner
                text: 'Sort: Name'
                values: ['Sort: Name', 'Sort: ID Asc', 'Sort: ID Desc', 'Sort: Year Asc', 'Sort: Year Desc', 'Sort: Price Asc', 'Sort: Price Desc']
                size_hint_x: None
                width: dp(110)
                font_size: sp(11)
                background_color: 0, 0.314, 0.784, 1
                color: 1, 1, 1, 1
                option_cls: 'BlueSpinnerOption'
                on_text: root.apply_sort_filter()
            Spinner:
                id: filter_field
                text: 'All'
                values: ['All', 'Name', 'Year', 'Appearance', 'Working', 'With Images', 'Without Images', 'Unique Models']
                size_hint_x: None
                width: dp(100)
                font_size: sp(11)
                background_color: 0.2, 0.2, 0.25, 1
                color: 1, 1, 1, 1
                option_cls: 'BlueSpinnerOption'
                on_text: root.on_filter_field_change()
            Spinner:
                id: filter_value_spinner
                text: 'All'
                values: ['All']
                font_size: sp(11)
                background_color: 0.3, 0.3, 0.35, 1
                color: 1, 1, 1, 1
                option_cls: 'BlueSpinnerOption'
                on_text: root.apply_sort_filter()
        # Tabs
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
            ClickableBox:
                padding: dp(6)
                on_release: root.switch_tab('wall')
                canvas.before:
                    Color:
                        rgba: (0, 0.314, 0.784, 1) if root.current_tab == 'wall' else (0.92, 0.92, 0.92, 1)
                    Rectangle:
                        pos: self.pos
                        size: self.size
                Label:
                    text: 'Wall'
                    bold: True
                    font_size: sp(13)
                    color: (1,1,1,1) if root.current_tab == 'wall' else (0.3,0.3,0.3,1)
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
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(14)
                spacing: dp(10)
                # Phone Image - tap to view full size
                ClickableBox:
                    size_hint_y: None
                    height: dp(220)
                    padding: dp(16)
                    on_release: root.view_main_image()
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(14)]
                    Image:
                        id: detail_img
                        nocache: True
                        allow_stretch: True
                        keep_ratio: True
                Button:
                    text: 'Add More Images'
                    size_hint_y: None
                    height: dp(40)
                    font_size: sp(13)
                    bold: True
                    background_color: 0, 0.314, 0.784, 1
                    color: 1, 1, 1, 1
                    on_press: root.add_image()
                # Action buttons - centered row with icons
                AnchorLayout:
                    anchor_x: 'center'
                    size_hint_y: None
                    height: dp(54)
                    BoxLayout:
                        size_hint: None, None
                        size: dp(310), dp(48)
                        spacing: dp(8)
                        Button:
                            size_hint: None, None
                            size: dp(44), dp(44)
                            background_normal: 'assets/icons/Info.png'
                            background_down: 'assets/icons/Info.png'
                            border: [0, 0, 0, 0]
                            on_press: root.show_summary()
                        Button:
                            size_hint: None, None
                            size: dp(44), dp(44)
                            background_normal: 'assets/icons/Web.png'
                            background_down: 'assets/icons/Web.png'
                            border: [0, 0, 0, 0]
                            on_press: root.google_search()
                        Button:
                            size_hint: None, None
                            size: dp(44), dp(44)
                            background_normal: 'assets/icons/eBay.png'
                            background_down: 'assets/icons/eBay.png'
                            border: [0, 0, 0, 0]
                            on_press: root.ebay_search()
                        Button:
                            size_hint: None, None
                            size: dp(44), dp(44)
                            background_normal: 'assets/icons/Youtube.png'
                            background_down: 'assets/icons/Youtube.png'
                            border: [0, 0, 0, 0]
                            on_press: root.youtube_search()
                        Button:
                            size_hint: None, None
                            size: dp(44), dp(44)
                            background_normal: 'assets/icons/Edit.png'
                            background_down: 'assets/icons/Edit.png'
                            border: [0, 0, 0, 0]
                            on_press: root.edit_phone()
                        Button:
                            size_hint: None, None
                            size: dp(44), dp(44)
                            background_normal: 'assets/icons/Delete.png'
                            background_down: 'assets/icons/Delete.png'
                            border: [0, 0, 0, 0]
                            on_press: root.confirm_delete()
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
                    BoxLayout:
                        size_hint_y: None
                        height: dp(30)
                        spacing: dp(6)
                        Label:
                            text: root.p_name
                            font_size: sp(20)
                            bold: True
                            color: 0.1, 0.1, 0.18, 1
                            size_hint_x: None
                            width: self.texture_size[0] + dp(4)
                            text_size: None, self.height
                        Label:
                            text: root.p_rarity_stars
                            font_size: sp(16)
                            color: 0.85, 0.65, 0.1, 1
                            text_size: self.size
                            halign: 'left'
                            valign: 'middle'
                        BoxLayout:
                            size_hint_x: None
                            width: dp(100) if root.p_rarity_text else dp(0)
                            size_hint_y: None
                            height: dp(22) if root.p_rarity_text else dp(0)
                            padding: dp(6), dp(2)
                            canvas.before:
                                Color:
                                    rgba: root.p_rarity_color
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [dp(11)]
                            Label:
                                text: root.p_rarity_text
                                font_size: sp(10)
                                bold: True
                                color: 1, 1, 1, 1
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
                        text: root.dup_count_text
                        font_size: sp(12)
                        bold: True
                        color: 0, 0.314, 0.784, 1
                        size_hint_y: None
                        height: dp(22) if root.dup_count_text else dp(0)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: root.no_fw_text
                        font_size: sp(13)
                        bold: True
                        color: 0.9, 0.2, 0.2, 1
                        size_hint_y: None
                        height: dp(22) if root.no_fw_text else dp(0)
                        text_size: self.size
                        halign: 'left'
                    BoxLayout:
                        size_hint_y: None
                        height: dp(28) if root.p_avg_price else dp(0)
                        padding: dp(8), dp(4)
                        canvas.before:
                            Color:
                                rgba: 0.1, 0.5, 0.3, 0.12
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(5)]
                        Label:
                            text: 'Average Price: ' + root.p_avg_price
                            font_size: sp(12)
                            bold: True
                            color: 0.1, 0.5, 0.3, 1
                            text_size: self.size
                            halign: 'left'
                            valign: 'middle'
                    Label:
                        text: 'Description:'
                        font_size: sp(12)
                        bold: True
                        color: 0.3, 0.3, 0.3, 1
                        size_hint_y: None
                        height: dp(18) if root.p_description else dp(0)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: root.p_description or ''
                        font_size: sp(12)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: (self.texture_size[1] + dp(6)) if root.p_description else dp(0)
                        text_size: self.width, None
                        halign: 'left'
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
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(14)
                spacing: dp(10)
                ClickableBox:
                    size_hint_y: None
                    height: dp(220)
                    padding: dp(16)
                    on_release: root.view_main_image()
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(14)]
                    Image:
                        id: detail_img
                        nocache: True
                        allow_stretch: True
                        keep_ratio: True
                Button:
                    text: 'Add More Images'
                    size_hint_y: None
                    height: dp(40)
                    font_size: sp(13)
                    bold: True
                    background_color: 0, 0.314, 0.784, 1
                    color: 1, 1, 1, 1
                    on_press: root.add_image()
                # Action buttons - centered
                AnchorLayout:
                    anchor_x: 'center'
                    size_hint_y: None
                    height: dp(70)
                    BoxLayout:
                        size_hint: None, None
                        size: dp(124), dp(56)
                        spacing: dp(12)
                        Button:
                            text: 'Edit'
                            size_hint: None, None
                            size: dp(56), dp(56)
                            font_size: sp(11)
                            bold: True
                            background_normal: ''
                            background_down: ''
                            background_color: 0, 0, 0, 0
                            color: 1, 1, 1, 1
                            canvas.before:
                                Color:
                                    rgba: 0, 0.314, 0.784, 1
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [100]
                            on_press: root.edit_spare()
                        Button:
                            text: 'Del'
                            size_hint: None, None
                            size: dp(56), dp(56)
                            font_size: sp(11)
                            bold: True
                            background_normal: ''
                            background_down: ''
                            background_color: 0, 0, 0, 0
                            color: 1, 1, 1, 1
                            canvas.before:
                                Color:
                                    rgba: 0.8, 0.15, 0.15, 1
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [100]
                            on_press: root.confirm_delete()
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
                # Gallery section
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
                    id: spare_gallery_grid
                    cols: 1
                    spacing: dp(6)
                    size_hint_y: None
                    height: self.minimum_height
                Widget:
                    size_hint_y: None
                    height: dp(30)

<WallDetailScreen>:
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
                text: 'Wall Item Details'
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
                spacing: dp(10)
                ClickableBox:
                    size_hint_y: None
                    height: dp(220)
                    padding: dp(16)
                    on_release: root.view_main_image()
                    canvas.before:
                        Color:
                            rgba: 0.94, 0.96, 1, 1
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(14)]
                    Image:
                        id: detail_img
                        nocache: True
                        allow_stretch: True
                        keep_ratio: True
                AnchorLayout:
                    anchor_x: 'center'
                    size_hint_y: None
                    height: dp(70)
                    BoxLayout:
                        size_hint: None, None
                        size: dp(124), dp(56)
                        spacing: dp(12)
                        Button:
                            text: 'Edit'
                            size_hint: None, None
                            size: dp(56), dp(56)
                            font_size: sp(11)
                            bold: True
                            background_normal: ''
                            background_down: ''
                            background_color: 0, 0, 0, 0
                            color: 1, 1, 1, 1
                            canvas.before:
                                Color:
                                    rgba: 0, 0.314, 0.784, 1
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [100]
                            on_press: root.edit_wall_item()
                        Button:
                            text: 'Del'
                            size_hint: None, None
                            size: dp(56), dp(56)
                            font_size: sp(11)
                            bold: True
                            background_normal: ''
                            background_down: ''
                            background_color: 0, 0, 0, 0
                            color: 1, 1, 1, 1
                            canvas.before:
                                Color:
                                    rgba: 0.8, 0.15, 0.15, 1
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [100]
                            on_press: root.confirm_delete()
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
                        text: root.w_name
                        font_size: sp(20)
                        bold: True
                        color: 0.1, 0.1, 0.18, 1
                        size_hint_y: None
                        height: dp(28)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: 'ID: ' + root.w_id
                        font_size: sp(13)
                        color: 0.4, 0.4, 0.4, 1
                        size_hint_y: None
                        height: dp(20)
                        text_size: self.size
                        halign: 'left'
                    Label:
                        text: 'Release: ' + root.w_date
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
                            text: 'Appearance: ' + root.w_appear
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
                            text: 'Working: ' + root.w_working
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
                        text: root.w_remarks or '-'
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
                        nocache: True
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
                        on_release: root.take_camera()
                        Label:
                            text: 'Camera'
                            color: 0, 0.314, 0.784, 1
                            font_size: sp(12)
                            bold: True
                TextInput:
                    id: input_id
                    hint_text: 'Phone ID (4 digits) *'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                    on_focus: if self.focus and self.text: self.select_all()
                TextInput:
                    id: input_name
                    hint_text: 'Phone Name *'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                    on_text_validate: root.auto_fill_from_name()
                    on_focus: if self.focus and self.text: self.select_all()
                Spinner:
                    id: input_date
                    text: 'Select Year'
                    values: []
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    background_color: 0, 0.314, 0.784, 1
                    color: 1, 1, 1, 1
                    option_cls: 'BlueSpinnerOption'
                BoxLayout:
                    size_hint_y: None
                    height: dp(42)
                    spacing: dp(4)
                    Spinner:
                        id: appear_spinner
                        text: 'Select...'
                        values: []
                        size_hint_x: 0.4
                        font_size: sp(12)
                        background_color: 0, 0.314, 0.784, 1
                        color: 1, 1, 1, 1
                        option_cls: 'BlueSpinnerOption'
                        on_text: if self.text != 'Select...': root.ids.input_appear.text = self.text
                    TextInput:
                        id: input_appear
                        hint_text: 'Appearance Condition'
                        multiline: False
                        font_size: sp(14)
                        padding: dp(10), dp(9)
                        on_focus: if self.focus and self.text: self.select_all()
                BoxLayout:
                    size_hint_y: None
                    height: dp(42)
                    spacing: dp(4)
                    Spinner:
                        id: working_spinner
                        text: 'Select...'
                        values: []
                        size_hint_x: 0.4
                        font_size: sp(12)
                        background_color: 0, 0.314, 0.784, 1
                        color: 1, 1, 1, 1
                        option_cls: 'BlueSpinnerOption'
                        on_text: if self.text != 'Select...': root.ids.input_working.text = self.text
                    TextInput:
                        id: input_working
                        hint_text: 'Working Condition'
                        multiline: False
                        font_size: sp(14)
                        padding: dp(10), dp(9)
                        on_focus: if self.focus and self.text: self.select_all()
                TextInput:
                    id: input_remarks
                    hint_text: 'Remarks'
                    multiline: True
                    size_hint_y: None
                    height: dp(70)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                    on_focus: if self.focus and self.text: self.select_all()
                TextInput:
                    id: input_description
                    hint_text: 'Description'
                    multiline: True
                    size_hint_y: None
                    height: dp(70)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                    on_focus: if self.focus and self.text: self.select_all()
                TextInput:
                    id: input_price
                    hint_text: 'Average Price (AED)'
                    multiline: False
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    padding: dp(10), dp(9)
                    input_filter: 'int'
                    on_focus: if self.focus and self.text: self.select_all()
                Spinner:
                    id: input_rarity
                    text: 'Select Rarity'
                    values: ['Select Rarity', '1', '1.5', '2', '2.5', '3', '3.5', '4', '4.5', '5']
                    size_hint_y: None
                    height: dp(42)
                    font_size: sp(14)
                    background_color: 0, 0.314, 0.784, 1
                    color: 1, 1, 1, 1
                    option_cls: 'BlueSpinnerOption'
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
                        nocache: True
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
                        on_release: root.take_camera()
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
        Label:
            id: export_status
            text: ''
            font_size: sp(13)
            color: 0.26, 0.63, 0.28, 1
            size_hint_y: None
            height: dp(30)
            text_size: self.width, None
            halign: 'center'
        ScrollView:
            do_scroll_x: False
            GridLayout:
                id: export_grid
                cols: 6
                spacing: dp(1)
                padding: dp(6)
                size_hint_y: None
                height: self.minimum_height
        ClickableBox:
            size_hint_y: None
            height: dp(50)
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
                text: 'Export & Share as Excel'
                color: 1, 1, 1, 1
                font_size: sp(15)
                bold: True

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

<PhotoGalleryScreen>:
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
                text: 'Photo Gallery'
                font_size: sp(17)
                bold: True
                color: 1, 1, 1, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
        Button:
            text: '+ Add Photos'
            size_hint_y: None
            height: dp(42)
            font_size: sp(14)
            bold: True
            background_color: 0, 0.314, 0.784, 1
            color: 1, 1, 1, 1
            on_press: root.add_photos()
        ScrollView:
            do_scroll_x: False
            GridLayout:
                id: gallery_grid
                cols: 2
                spacing: dp(6)
                padding: dp(8)
                size_hint_y: None
                height: self.minimum_height
"""


# -- Screen Classes ------------------------------------------------


class SplashScreen(Screen):
    def on_enter(self):
        Clock.schedule_once(self._go_main, 2)

    def _go_main(self, *args):
        app = App.get_running_app()
        if app.root:
            app.root.transition = SlideTransition(direction="left")
            app.root.current = "dashboard"


class DashboardScreen(Screen):
    def on_enter(self):
        Clock.schedule_once(lambda dt: self._load_dashboard(), 0.2)

    def _load_dashboard(self):
        app = App.get_running_app()
        if not app.db:
            return
        g = self.ids.dash_grid
        g.clear_widgets()

        # Gather stats
        total_phones = 0
        unique_models = 0
        total_spares = 0
        wall_count = 0
        total_value = 0
        try:
            total_phones = app.db.get_phone_count()
        except Exception:
            pass
        try:
            cur = app.db.conn.execute("SELECT COUNT(DISTINCT TRIM(name)) FROM phones")
            unique_models = cur.fetchone()[0]
        except Exception:
            pass
        try:
            cur = app.db.conn.execute("SELECT COUNT(*) FROM spare_parts")
            total_spares = cur.fetchone()[0]
        except Exception:
            pass
        try:
            wall_count = app.db.get_wall_count()
        except Exception:
            pass
        try:
            cur = app.db.conn.execute("SELECT COALESCE(SUM(avg_price), 0) FROM phones")
            total_value = cur.fetchone()[0] or 0
        except Exception:
            pass

        def stat_card(title, value, bg_color):
            card = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(70), padding=dp(10))
            with card.canvas.before:
                Color(*bg_color)
                card._bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(10)])
            card.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                      size=lambda w, v: setattr(w._bg, "size", v))
            card.add_widget(Label(text=str(value), font_size=sp(24), bold=True,
                color=(1, 1, 1, 1), size_hint_y=0.6))
            card.add_widget(Label(text=title, font_size=sp(12),
                color=(1, 1, 1, 0.8), size_hint_y=0.4))
            return card

        def stat_row(cards):
            row = BoxLayout(size_hint_y=None, height=dp(70), spacing=dp(6))
            for c in cards:
                row.add_widget(c)
            return row

        # Section title
        sec_lbl = Label(text="Overview", font_size=sp(16), bold=True,
            color=(0, 0.314, 0.784, 1), size_hint_y=None, height=dp(30),
            text_size=(dp(300), None), halign="left")
        g.add_widget(sec_lbl)

        # Stat cards in 2x2 grid
        g.add_widget(stat_row([
            stat_card("Total Phones", total_phones, (0, 0.314, 0.784, 1)),
            stat_card("Unique Models", unique_models, (0.4, 0.3, 0.6, 1))
        ]))
        g.add_widget(stat_row([
            stat_card("Spare Parts", total_spares, (0.26, 0.63, 0.28, 1)),
            stat_card("Wall Items", wall_count, (0.35, 0.25, 0.15, 1))
        ]))

        # Average value card
        avg_value = (total_value / total_phones) if total_phones > 0 else 0
        g.add_widget(stat_card("Avg. Phone Value", f"AED {avg_value:,.0f}",
            (0.1, 0.5, 0.3, 1)))

        # Quick actions section
        sec_lbl2 = Label(text="Quick Actions", font_size=sp(16), bold=True,
            color=(0, 0.314, 0.784, 1), size_hint_y=None, height=dp(30),
            text_size=(dp(300), None), halign="left")
        g.add_widget(sec_lbl2)

        from kivy.uix.button import Button as KBtn

        def action_btn(text, callback, bg_color):
            b = KBtn(text=text, size_hint_y=None, height=dp(46), font_size=sp(14),
                background_normal='', background_color=bg_color, color=(1, 1, 1, 1), bold=True)
            b.bind(on_press=callback)
            return b

        g.add_widget(action_btn("Browse Phones", lambda *a: self._go_tab("phones"),
            (0, 0.314, 0.784, 1)))
        g.add_widget(action_btn("Browse Spare Parts", lambda *a: self._go_tab("spares"),
            (0.2, 0.2, 0.25, 1)))
        g.add_widget(action_btn("Browse Wall Items", lambda *a: self._go_tab("wall"),
            (0.35, 0.25, 0.15, 1)))

        btn_row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        btn_row.add_widget(action_btn("Gallery", lambda *a: self._nav("photo_gallery"),
            (0.8, 0.4, 0.1, 1)))
        btn_row.add_widget(action_btn("Report", lambda *a: self._nav("report"),
            (0.4, 0.3, 0.6, 1)))
        g.add_widget(btn_row)

        g.add_widget(action_btn("Backup & Restore", lambda *a: self._nav("backup"),
            (0.26, 0.63, 0.28, 1)))
        g.add_widget(action_btn("Export Data", lambda *a: self._nav("export_data"),
            (0.2, 0.45, 0.25, 1)))

        # Recently Added section
        try:
            cur = app.db.conn.execute(
                "SELECT id, name, release_date, working_condition FROM phones ORDER BY created_at DESC LIMIT 5")
            recent = cur.fetchall()
            if recent:
                sec_lbl3 = Label(text="Recently Added", font_size=sp(16), bold=True,
                    color=(0, 0.314, 0.784, 1), size_hint_y=None, height=dp(30),
                    text_size=(dp(300), None), halign="left")
                g.add_widget(sec_lbl3)
                for row in recent:
                    r_box = BoxLayout(size_hint_y=None, height=dp(28), padding=(dp(8), dp(2)))
                    with r_box.canvas.before:
                        Color(0.95, 0.96, 0.98, 1)
                        r_box._bg = RoundedRectangle(pos=r_box.pos, size=r_box.size, radius=[dp(5)])
                    r_box.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                               size=lambda w, v: setattr(w._bg, "size", v))
                    r_box.add_widget(Label(
                        text="%s (%s)" % (str(row[1] or ""), str(row[0] or "")),
                        font_size=sp(12), color=(0.15, 0.15, 0.15, 1),
                        text_size=(dp(200), None), halign="left"))
                    r_box.add_widget(Label(
                        text=str(row[3] or ""), font_size=sp(11), color=(0.4, 0.4, 0.4, 1),
                        size_hint_x=None, width=dp(60)))
                    g.add_widget(r_box)
        except Exception:
            pass

        g.add_widget(Widget(size_hint_y=None, height=dp(20)))

    def _go_tab(self, tab):
        app = App.get_running_app()
        main = app.root.get_screen("main")
        main.current_tab = tab
        main._data_loaded = False
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "main"

    def _nav(self, screen_name):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="left")
        app.root.current = screen_name

    def show_menu(self):
        popup = ModalView(size_hint=(0.75, None), height=dp(260))
        c = BoxLayout(orientation="vertical", spacing=dp(1), padding=dp(12))
        with c.canvas.before:
            Color(1, 1, 1, 1)
            c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(12)])
        c.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
               size=lambda w, v: setattr(w._bg, "size", v))
        c.add_widget(Label(text="Menu", font_size=sp(16), bold=True,
            color=(0, 0.314, 0.784, 1), size_hint_y=None, height=dp(30)))
        for t, n in [("Export Data", "export_data"),
                      ("Backup & Restore", "backup"),
                      ("Storage Report", "report"),
                      ("Photo Gallery", "photo_gallery")]:
            from kivy.uix.button import Button as KBtn
            b = KBtn(text=t, size_hint_y=None, height=dp(44), font_size=sp(14),
                background_normal='', background_color=(0, 0.314, 0.784, 1),
                color=(1, 1, 1, 1), bold=True)
            b.bind(on_press=lambda *a, nm=n, p=popup: (p.dismiss(), self._nav(nm)))
            c.add_widget(b)
        popup.add_widget(c)
        popup.open()


class MainScreen(Screen):
    current_tab = StringProperty("phones")
    _raw_items = []  # Original unfiltered/unsorted data
    _all_items = []  # After sort/filter applied
    _current_page = 0
    _total_items = 0
    _is_search = False
    _data_loaded = False
    _sort_ascending = True
    _last_sort_text = ""
    _pending_filter = ""
    _pending_search = ""

    def on_enter(self):
        if not self._data_loaded:
            Clock.schedule_once(lambda dt: self._do_enter(), 0.2)
        else:
            self._render_page()

    def _do_enter(self):
        if self._pending_search:
            q = self._pending_search
            self._pending_search = ""
            try: self.ids.search_bar.ids.search_input.text = q
            except: pass
            self.do_search(q)
        elif self._pending_filter:
            f = self._pending_filter
            self._pending_filter = ""
            # Load all data first without applying filters
            app = App.get_running_app()
            if app.db:
                self._raw_items = app.db.get_all_phones() if self.current_tab == "phones" else (app.db.get_all_spare_parts() if self.current_tab == "spares" else app.db.get_all_wall_items())
                self._data_loaded = True
            # Now set the filter field - this triggers on_filter_field_change
            # which populates filter_value_spinner, then we apply
            try:
                self.ids.sort_spinner.text = "Sort: Name"
                self.ids.search_bar.ids.search_input.text = ""
            except: pass
            # For simple filters (With Images, Without Images, Unique Models, All)
            # just set filter_field and apply
            if f in ('All', 'With Images', 'Without Images', 'Unique Models', 'No FW Models'):
                try:
                    self.ids.filter_field.text = f
                    self.ids.filter_value_spinner.values = ['All']
                    self.ids.filter_value_spinner.text = 'All'
                except: pass
                self._apply_sort_filter_internal()
            else:
                # For field-based filters like "Appearance:Excellent Condition"
                # parse field:value
                if ':' in f:
                    fld, fval = f.split(':', 1)
                    try:
                        self.ids.filter_field.text = fld
                    except: pass
                    # Wait a tick for on_filter_field_change to populate values
                    Clock.schedule_once(lambda dt, fv=fval: self._apply_pending_value(fv), 0.15)
                else:
                    try: self.ids.filter_field.text = f
                    except: pass
                    self._apply_sort_filter_internal()
        else:
            self.refresh_list()

    def _apply_pending_value(self, fval):
        try:
            self.ids.filter_value_spinner.text = fval
        except: pass
        self._apply_sort_filter_internal()

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
        if self.current_tab == "phones":
            self._raw_items = app.db.get_all_phones()
        elif self.current_tab == "spares":
            self._raw_items = app.db.get_all_spare_parts()
        elif self.current_tab == "wall":
            self._raw_items = app.db.get_all_wall_items()
        else:
            self._raw_items = []
        self._is_search = False
        self._data_loaded = True
        self._apply_sort_filter_internal()

    def do_search(self, text):
        app = App.get_running_app()
        if not text.strip():
            self._data_loaded = False
            self.refresh_list()
            return
        self._current_page = 0
        if self.current_tab == "phones":
            self._raw_items = app.db.search_phones(text)
        elif self.current_tab == "spares":
            self._raw_items = app.db.search_spare_parts(text)
        elif self.current_tab == "wall":
            self._raw_items = app.db.search_wall_items(text)
        else:
            self._raw_items = []
        self._is_search = True
        self._data_loaded = True
        self._apply_sort_filter_internal()

    def apply_sort_filter(self, *a):
        """Called from KV when sort/filter changes."""
        self._current_page = 0
        self._apply_sort_filter_internal()

    def on_filter_field_change(self, *a):
        try:
            field = self.ids.filter_field.text
            app = App.get_running_app()
            spinner = self.ids.filter_value_spinner
            if field in ('All', 'With Images', 'Without Images', 'Unique Models', 'No FW Models'):
                spinner.values = ['All']
                spinner.text = 'All'
                self.apply_sort_filter()
            elif field == 'Appearance' and app.db:
                cur = app.db.conn.execute(
                    "SELECT DISTINCT appearance_condition FROM phones WHERE appearance_condition IS NOT NULL AND appearance_condition != '' ORDER BY appearance_condition")
                vals = ['All'] + [str(r[0]) for r in cur.fetchall()]
                spinner.values = vals
                spinner.text = 'All'
            elif field == 'Working' and app.db:
                cur = app.db.conn.execute(
                    "SELECT DISTINCT working_condition FROM phones WHERE working_condition IS NOT NULL AND working_condition != '' ORDER BY working_condition")
                vals = ['All'] + [str(r[0]) for r in cur.fetchall()]
                spinner.values = vals
                spinner.text = 'All'
            elif field == 'Year' and app.db:
                cur = app.db.conn.execute(
                    "SELECT DISTINCT release_date FROM phones WHERE release_date IS NOT NULL AND release_date != '' ORDER BY release_date")
                vals = ['All'] + [str(r[0]) for r in cur.fetchall()][:50]
                spinner.values = vals
                spinner.text = 'All'
            elif field == 'Name' and app.db:
                cur = app.db.conn.execute(
                    "SELECT DISTINCT TRIM(name) FROM phones WHERE name IS NOT NULL AND name != '' ORDER BY TRIM(name) LIMIT 50")
                vals = ['All'] + [str(r[0]) for r in cur.fetchall()]
                spinner.values = vals
                spinner.text = 'All'
            else:
                spinner.values = ['All']
                spinner.text = 'All'
        except Exception:
            pass

    def _apply_sort_filter_internal(self):
        items = list(self._raw_items)

        # Filter
        try:
            field = self.ids.filter_field.text
            val = self.ids.filter_value_spinner.text.strip()
            if field != 'All' and self.current_tab == "phones":
                if field == 'With Images':
                    items = [i for i in items if i.get('has_image')]
                elif field == 'Without Images':
                    items = [i for i in items if not i.get('has_image')]
                elif field == 'Unique Models':
                    seen = {}
                    for i in items:
                        n = (i.get('name', '') or '').strip()
                        if n not in seen:
                            seen[n] = i
                        elif 'FW' in (i.get('working_condition', '') or '') and 'FW' not in (seen[n].get('working_condition', '') or ''):
                            seen[n] = i
                    items = list(seen.values())
                elif field == 'No FW Models':
                    # Find model names that have NO FW unit
                    app = App.get_running_app()
                    no_fw_names = set()
                    try:
                        cur = app.db.conn.execute(
                            "SELECT DISTINCT TRIM(name) FROM phones GROUP BY TRIM(name) "
                            "HAVING SUM(CASE WHEN TRIM(working_condition)='FW' THEN 1 ELSE 0 END) = 0")
                        no_fw_names = {r[0] for r in cur.fetchall()}
                    except: pass
                    items = [i for i in items if (i.get('name', '') or '').strip() in no_fw_names]
                elif val and val != 'All':
                    key_map = {'Name': 'name', 'Year': 'release_date', 'Appearance': 'appearance_condition', 'Working': 'working_condition'}
                    key = key_map.get(field, '')
                    if key:
                        items = [i for i in items if val.lower() in (i.get(key, '') or '').lower()]
        except Exception:
            pass

        # Sort - parse direction from sort text
        try:
            sort_text = self.ids.sort_spinner.text.replace('Sort: ', '')
            ascending = True
            if sort_text.endswith(' Desc'):
                ascending = False
                sort_by = sort_text[:-5]
            elif sort_text.endswith(' Asc'):
                ascending = True
                sort_by = sort_text[:-4]
            else:
                sort_by = sort_text
            if self.current_tab == "phones":
                if sort_by == 'Name':
                    items.sort(key=lambda x: (x.get('name', '') or '').lower(), reverse=not ascending)
                elif sort_by == 'ID':
                    items.sort(key=lambda x: x.get('id', '') or '', reverse=not ascending)
                elif sort_by == 'Year':
                    items.sort(key=lambda x: x.get('release_date', '') or '', reverse=not ascending)
                elif sort_by == 'Price':
                    items.sort(key=lambda x: float(x.get('avg_price', 0) or 0), reverse=not ascending)
            else:
                items.sort(key=lambda x: (x.get('name', '') or '').lower(), reverse=not ascending)
        except Exception:
            pass

        self._all_items = items
        self._total_items = len(items)
        self._render_page()

    def _pgbtn(self, text, cb):
        from kivy.uix.button import Button as KBtn
        b = KBtn(text=text, size_hint_x=None, width=dp(56), font_size=sp(11),
            bold=True, background_color=(0, 0.314, 0.784, 1), color=(1,1,1,1))
        b.bind(on_press=cb)
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
        tab_labels = {"phones": "phones", "spares": "parts", "wall": "wall items"}
        lt = "found" if self._is_search else tab_labels.get(self.current_tab, "items")
        self.ids.count_label.text = f"{self._total_items} {lt} | Page {cp}/{tp}"
        defimg = get_default_image_path(get_app_path())

        if self.current_tab == "phones":
            for p in items:
                img = get_img_path_for_phone(p["id"], app.db) if p.get("has_image") else defimg
                price = p.get("avg_price", 0) or 0
                rscore = p.get("rarity_score", 0) or 0
                price_parts = []
                if price > 0:
                    price_parts.append("AED %d" % int(price))
                if rscore > 0:
                    price_parts.append(rarity_label(rscore))
                card = PhoneCard(phone_id=p["id"], phone_name=p["name"],
                    phone_date=p.get("release_date","") or "",
                    phone_appear=p.get("appearance_condition","") or "",
                    phone_working=p.get("working_condition","") or "",
                    phone_image=img or defimg,
                    phone_price=" | ".join(price_parts) if price_parts else "")
                card.bind(on_release=partial(self._open_phone, p["id"]))
                grid.add_widget(card)
        elif self.current_tab == "spares":
            for s in items:
                img = get_img_path_for_spare(s["id"], app.db) if s.get("has_image") else defimg
                card = SpareCard(spare_id=s["id"], spare_name=s["name"],
                    spare_desc=s.get("description","") or "",
                    spare_image=img or defimg)
                card.bind(on_release=partial(self._open_spare, s["id"]))
                grid.add_widget(card)
        elif self.current_tab == "wall":
            for w in items:
                img = get_img_path_for_wall(w["id"], app.db) if w.get("has_image") else defimg
                card = PhoneCard(phone_id=w["id"], phone_name=w["name"],
                    phone_date=w.get("release_date","") or "",
                    phone_appear=w.get("appearance_condition","") or "",
                    phone_working=w.get("working_condition","") or "",
                    phone_image=img or defimg, phone_price="")
                card.bind(on_release=partial(self._open_wall, w["id"]))
                grid.add_widget(card)

        # Pagination
        if self._total_items > PAGE_SIZE:
            pg = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(4), padding=(dp(6),dp(4)))

            # Prev buttons
            if self._current_page > 0:
                pg.add_widget(self._pgbtn("<<", lambda *a: self._goto(0)))
                pg.add_widget(self._pgbtn("< Prev", lambda *a: self._goto(self._current_page-1)))

            pg.add_widget(Widget())  # spacer left

            # Page dropdown - styled blue
            page_values = [f"Page {i+1}" for i in range(tp)]
            page_spinner = Spinner(text=f"Page {cp}", values=page_values,
                size_hint_x=None, width=dp(90), font_size=sp(12),
                background_color=(0, 0.314, 0.784, 1), color=(1,1,1,1),
                option_cls=BlueSpinnerOption)
            page_spinner.bind(text=lambda w, t: self._goto(int(t.replace('Page ',''))-1) if 'Page' in t else None)
            pg.add_widget(page_spinner)
            pg.add_widget(Label(text=f"of {tp}", font_size=sp(12), color=(0.4,0.4,0.4,1), size_hint_x=None, width=dp(36)))

            pg.add_widget(Widget())  # spacer right

            # Next buttons
            if end < self._total_items:
                pg.add_widget(self._pgbtn("Next >", lambda *a: self._goto(self._current_page+1)))
                pg.add_widget(self._pgbtn(">>", lambda *a: self._goto(tp-1)))

            grid.add_widget(pg)

        try: self.ids.scroll_view.scroll_y = 1
        except: pass

    def _goto(self, p):
        self._current_page = max(0, min(p, (self._total_items + PAGE_SIZE - 1) // PAGE_SIZE - 1))
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

    def _open_wall(self, wid, *a):
        app = App.get_running_app()
        app.root.get_screen("wall_detail").load_wall_item(wid)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "wall_detail"

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

    def go_dashboard(self):
        """Navigate back to the dashboard."""
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "dashboard"

    def refresh_home(self):
        """Reset everything and go to main screen."""
        self._data_loaded = False
        self._current_page = 0
        try:
            self.ids.search_bar.ids.search_input.text = ""
            self.ids.filter_value_spinner.text = "All"
            self.ids.filter_value_spinner.values = ["All"]
            self.ids.filter_field.text = "All"
            self.ids.sort_spinner.text = "Sort: Name"
        except Exception:
            pass
        self.refresh_list()

    def open_gallery(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "photo_gallery"

    def show_menu(self):
        popup = ModalView(size_hint=(0.75, None), height=dp(260))
        c = BoxLayout(orientation="vertical", spacing=dp(1), padding=dp(12))
        with c.canvas.before:
            Color(1,1,1,1)
            c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(12)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        # Title
        c.add_widget(Label(text="Menu", font_size=sp(16), bold=True, color=(0,0.314,0.784,1),
            size_hint_y=None, height=dp(30)))
        for t, n in [("Export Data","export_data"),
                      ("Backup & Restore","backup"),
                      ("Storage Report","report"),
                      ("Photo Gallery","photo_gallery")]:
            from kivy.uix.button import Button as KBtn
            b = KBtn(text=t, size_hint_y=None, height=dp(44), font_size=sp(14),
                background_normal='', background_color=(0, 0.314, 0.784, 1),
                color=(1,1,1,1), bold=True)
            b.bind(on_press=lambda *a, nm=n, p=popup: (p.dismiss(), self._nav(nm)))
            c.add_widget(b)
        popup.add_widget(c); popup.open()

    def _nav(self, n):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="left"); app.root.current = n


class PhoneDetailScreen(Screen):
    p_id = StringProperty(""); p_name = StringProperty(""); p_date = StringProperty("")
    p_appear = StringProperty(""); p_working = StringProperty(""); p_remarks = StringProperty("")
    p_description = StringProperty("")
    p_rarity_stars = StringProperty(""); p_rarity_text = StringProperty("")
    p_avg_price = StringProperty(""); p_rarity_color = ListProperty([0.5, 0.5, 0.5, 1])
    no_fw_text = StringProperty("")
    dup_count_text = StringProperty("")

    def load_phone(self, pid):
        app = App.get_running_app()
        p = app.db.get_phone(pid)
        if not p: return
        self.p_id = p["id"]; self.p_name = p["name"]
        self.p_date = p.get("release_date","") or ""
        self.p_appear = p.get("appearance_condition","") or ""
        self.p_working = p.get("working_condition","") or ""
        r = p.get("remarks","") or ""; self.p_remarks = "" if r in ("None","none") else r
        d = p.get("description","") or ""; self.p_description = "" if d in ("None","none") else d
        avg_p = p.get("avg_price", 0) or 0
        rscore = p.get("rarity_score", 0) or 0
        self.p_avg_price = f"AED {avg_p:.0f}" if avg_p > 0 else "N/A"
        self.p_rarity_stars = rarity_stars(rscore)
        self.p_rarity_text = rarity_label(rscore)
        self.p_rarity_color = rarity_color(rscore) if rscore > 0 else [0.5, 0.5, 0.5, 1]
        # Duplicate count
        try:
            cur = app.db.conn.execute(
                "SELECT COUNT(*) FROM phones WHERE TRIM(name) = TRIM(?)", (self.p_name,))
            dup_count = cur.fetchone()[0]
            self.dup_count_text = f"{dup_count} phone(s) with same name" if dup_count > 1 else ""
        except Exception:
            self.dup_count_text = ""
        # No FW warning
        try:
            cur = app.db.conn.execute(
                "SELECT COUNT(*) FROM phones WHERE TRIM(name) = TRIM(?) AND TRIM(working_condition) = 'FW'",
                (self.p_name,))
            fw_count = cur.fetchone()[0]
            self.no_fw_text = "!! No Fully Working Phone !!" if fw_count == 0 else ""
        except Exception:
            self.no_fw_text = ""
        img = get_img_path_for_phone(pid, app.db)
        Clock.schedule_once(lambda dt: self._set_img(img), 0.1)
        Clock.schedule_once(lambda dt: self._load_gallery(), 0.15)
        Clock.schedule_once(lambda dt: self._load_spares(), 0.2)

    _current_img_path = ""

    def _set_img(self, path):
        try:
            src = path or get_default_image_path(get_app_path())
            self._current_img_path = src
            self.ids.detail_img.source = src
            self.ids.detail_img.reload()
        except: pass

    def view_main_image(self):
        """Open main phone image in full screen."""
        if self._current_img_path:
            self._show_fullscreen(self._current_img_path)

    _gallery_paths = []  # list of image paths for viewer navigation
    _viewer_index = 0
    _viewer_popup = None

    def _load_gallery(self):
        """Load gallery images from phone_gallery table with delete buttons."""
        app = App.get_running_app()
        grid = self.ids.gallery_grid
        grid.clear_widgets()
        self._gallery_paths = []
        images = app.db.get_gallery_images(self.p_id)
        if not images:
            grid.add_widget(Label(text="No gallery photos", font_size=sp(12),
                color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(24)))
            return
        from kivy.uix.button import Button as KBtn
        for gal_id, img_data in images:
            img_path = write_blob_to_file(img_data, f"gal_{gal_id}", get_app_path())
            if img_path:
                idx = len(self._gallery_paths)
                self._gallery_paths.append(img_path)
                box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(230), padding=dp(2))
                img_btn = ClickableBox(size_hint_y=None, height=dp(200))
                img_widget = Image(source=img_path, nocache=True,
                    allow_stretch=True, keep_ratio=True)
                img_btn.add_widget(img_widget)
                img_btn.bind(on_release=partial(self._open_gallery_viewer, idx))
                box.add_widget(img_btn)
                del_btn = KBtn(text="Delete", size_hint_y=None, height=dp(26),
                    font_size=sp(10), background_color=(0.85, 0.2, 0.2, 1), color=(1,1,1,1))
                del_btn.bind(on_press=partial(self._confirm_gallery_delete, gal_id))
                box.add_widget(del_btn)
                grid.add_widget(box)

    def _confirm_gallery_delete(self, gal_id, *a):
        """Show confirmation before deleting a gallery image."""
        from kivy.uix.button import Button as KBtn
        popup = ModalView(size_hint=(0.78, None), height=dp(130))
        c = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        with c.canvas.before:
            Color(1,1,1,1); c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        c.add_widget(Label(text="Delete this photo?", font_size=sp(15), color=(0.1,0.1,0.18,1),
            size_hint_y=None, height=dp(28)))
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(42))
        cancel = KBtn(text="Cancel", font_size=sp(13), background_color=(0.7,0.7,0.7,1))
        cancel.bind(on_press=lambda *a: popup.dismiss())
        delete = KBtn(text="Delete", font_size=sp(13), background_color=(0.85,0.2,0.2,1), color=(1,1,1,1))
        delete.bind(on_press=lambda *a: self._do_gallery_delete(gal_id, popup))
        row.add_widget(cancel); row.add_widget(delete)
        c.add_widget(row)
        popup.add_widget(c); popup.open()

    def _do_gallery_delete(self, gal_id, popup):
        app = App.get_running_app()
        app.db.delete_gallery_image(gal_id)
        clear_item_cache(f"gal_{gal_id}", get_app_path())
        popup.dismiss()
        app.show_toast("Photo deleted")
        self._load_gallery()

    def _open_gallery_viewer(self, index, *a):
        """Open full-screen gallery viewer at given index."""
        if not self._gallery_paths:
            return
        self._viewer_index = index
        self._show_gallery_viewer()

    def _show_gallery_viewer(self):
        from kivy.uix.button import Button as KBtn
        if self._viewer_popup:
            try: self._viewer_popup.dismiss()
            except Exception: pass

        idx = self._viewer_index
        if idx < 0 or idx >= len(self._gallery_paths):
            return
        img_path = self._gallery_paths[idx]
        total = len(self._gallery_paths)

        self._viewer_popup = ModalView(size_hint=(1, 1), background_color=(0, 0, 0, 0.95))
        c = BoxLayout(orientation="vertical", padding=dp(4), spacing=dp(4))

        # Counter
        c.add_widget(Label(text=f"{idx+1} / {total}", font_size=sp(14), color=(1,1,1,1),
            size_hint_y=None, height=dp(28)))

        # Image
        c.add_widget(Image(source=img_path, nocache=True, allow_stretch=True, keep_ratio=True))

        # Navigation buttons
        nav = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        prev_btn = KBtn(text="< Prev", font_size=sp(14), background_color=(0.3,0.3,0.3,1),
            disabled=(idx == 0))
        prev_btn.bind(on_press=lambda *a: self._nav_gallery_viewer(-1))
        close_btn = KBtn(text="Close", font_size=sp(14), background_color=(0.5,0.1,0.1,1))
        close_btn.bind(on_press=lambda *a: self._viewer_popup.dismiss())
        next_btn = KBtn(text="Next >", font_size=sp(14), background_color=(0.3,0.3,0.3,1),
            disabled=(idx >= total - 1))
        next_btn.bind(on_press=lambda *a: self._nav_gallery_viewer(1))
        nav.add_widget(prev_btn); nav.add_widget(close_btn); nav.add_widget(next_btn)
        c.add_widget(nav)

        self._viewer_popup.add_widget(c)
        self._viewer_popup.open()

    def _nav_gallery_viewer(self, direction):
        self._viewer_index += direction
        self._viewer_index = max(0, min(self._viewer_index, len(self._gallery_paths) - 1))
        self._viewer_popup.dismiss()
        Clock.schedule_once(lambda dt: self._show_gallery_viewer(), 0.1)

    def _show_fullscreen(self, img_path, *args):
        """Show image in full-screen overlay (for main image)."""
        from kivy.uix.button import Button as KButton
        popup = ModalView(size_hint=(1, 1), background_color=(0, 0, 0, 0.95))
        content = BoxLayout(orientation="vertical", padding=dp(4))
        img = Image(source=img_path, nocache=True, allow_stretch=True, keep_ratio=True)
        content.add_widget(img)
        close_btn = KButton(text="Close", size_hint_y=None, height=dp(44),
            font_size=sp(14), background_color=(0.3, 0.3, 0.3, 1))
        close_btn.bind(on_press=lambda *a: popup.dismiss())
        content.add_widget(close_btn)
        popup.add_widget(content)
        popup.open()

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
        app = App.get_running_app()
        popup = ModalView(size_hint=(0.75, None), height=dp(130))
        c = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(10))
        with c.canvas.before:
            Color(1,1,1,1); c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        gb = ClickableBox(size_hint_y=None, height=dp(44), padding=(dp(10),dp(6)))
        gb.add_widget(Label(text="Pick from Gallery", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        gb.bind(on_release=lambda *a: (popup.dismiss(), self._do_gallery_add()))
        cb = ClickableBox(size_hint_y=None, height=dp(44), padding=(dp(10),dp(6)))
        cb.add_widget(Label(text="Take Photo", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        cb.bind(on_release=lambda *a: (popup.dismiss(), self._do_camera_add()))
        c.add_widget(gb); c.add_widget(cb)
        popup.add_widget(c); popup.open()

    def _do_gallery_add(self):
        app = App.get_running_app()
        app.pick_image_for = ("phone_gallery", self.p_id)
        app.open_file_chooser(multiple=True)

    def _do_camera_add(self):
        app = App.get_running_app()
        app.pick_image_for = ("phone_gallery", self.p_id)
        app._launch_camera()

    def share_phone(self):
        """Share phone info as plain text via Android share."""
        text = f"Nokia {self.p_name}\nID: {self.p_id}\nRelease: {self.p_date}\nAppearance: {self.p_appear}\nWorking: {self.p_working}"
        if self.p_remarks and self.p_remarks != '-':
            text += f"\nRemarks: {self.p_remarks}"
        _share_text_android(text)

    def google_search(self):
        """Open Google search for this phone model."""
        import webbrowser
        webbrowser.open(f"https://www.google.com/search?q=Nokia+{self.p_name}")

    def ebay_search(self):
        """Open eBay search for this phone model."""
        import webbrowser
        webbrowser.open(f"https://www.ebay.com/sch/i.html?_nkw=Nokia+{self.p_name}")

    def youtube_search(self):
        """Open YouTube search for this phone model."""
        import webbrowser
        webbrowser.open(f"https://www.youtube.com/results?search_query=Nokia+{self.p_name}")

    def show_summary(self):
        """Show a summary popup for all phones with the same name."""
        app = App.get_running_app()

        # Count all phones with same name using TRIM
        total_same = 0
        try:
            cur = app.db.conn.execute(
                "SELECT COUNT(*) FROM phones WHERE TRIM(name) = TRIM(?)", (self.p_name,))
            total_same = cur.fetchone()[0]
        except Exception:
            pass

        # Working condition breakdown via SQL
        working_counts = []
        try:
            cur = app.db.conn.execute(
                "SELECT working_condition, COUNT(*) as cnt FROM phones WHERE TRIM(name) = TRIM(?) GROUP BY working_condition ORDER BY cnt DESC",
                (self.p_name,))
            working_counts = [(r[0] or "Unknown", r[1]) for r in cur.fetchall()]
        except Exception:
            pass

        # Appearance breakdown via SQL
        appear_counts = []
        try:
            cur = app.db.conn.execute(
                "SELECT appearance_condition, COUNT(*) as cnt FROM phones WHERE TRIM(name) = TRIM(?) GROUP BY appearance_condition ORDER BY cnt DESC",
                (self.p_name,))
            appear_counts = [(r[0] or "Unknown", r[1]) for r in cur.fetchall()]
        except Exception:
            pass

        # Related spare parts
        spare_names = []
        try:
            spares = app.db.get_spare_parts_for_phone(self.p_name)
            spare_names = [s.get('name', '') for s in spares if s.get('name')]
        except Exception:
            pass

        # Build popup with scrollable content
        from kivy.uix.button import Button as KBtn
        popup = ModalView(size_hint=(0.9, 0.7))
        outer = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(14))
        with outer.canvas.before:
            Color(1, 1, 1, 1)
            outer._bg = RoundedRectangle(pos=outer.pos, size=outer.size, radius=[dp(12)])
        outer.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                   size=lambda w, v: setattr(w._bg, "size", v))

        # Title
        outer.add_widget(Label(text=self.p_name, font_size=sp(18), bold=True,
            color=(0, 0.314, 0.784, 1), size_hint_y=None, height=dp(30)))

        # Scrollable body
        sv = ScrollView(do_scroll_x=False)
        body = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None,
                         padding=(dp(4), dp(4)))
        body.bind(minimum_height=body.setter("height"))

        def add_line(text, bold_f=False, color_c=(0.15, 0.15, 0.15, 1), fs=13):
            lbl = Label(text=text, font_size=sp(fs), bold=bold_f, color=color_c,
                size_hint_y=None, height=dp(22), text_size=(dp(280), None), halign="left")
            body.add_widget(lbl)

        add_line(f"{total_same} phone(s) with this name", bold_f=True, fs=14)
        add_line("")

        add_line("Working Condition:", bold_f=True, color_c=(0, 0.28, 0.7, 1))
        for wk, cnt in working_counts:
            add_line(f"  {wk}: {cnt}")

        add_line("")
        add_line("Appearance:", bold_f=True, color_c=(0.2, 0.5, 0.22, 1))
        for ap, cnt in appear_counts:
            add_line(f"  {ap}: {cnt}")

        add_line("")
        add_line("Spare Parts:", bold_f=True, color_c=(0.5, 0.2, 0.5, 1))
        if spare_names:
            for sn in spare_names:
                add_line(f"  - {sn}")
        else:
            add_line("  None")

        sv.add_widget(body)
        outer.add_widget(sv)

        # Close button
        close = KBtn(text="Close", size_hint_y=None, height=dp(42), font_size=sp(14),
            background_color=(0, 0.314, 0.784, 1), color=(1, 1, 1, 1))
        close.bind(on_press=lambda *a: popup.dismiss())
        outer.add_widget(close)
        popup.add_widget(outer)
        popup.open()

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
        Clock.schedule_once(lambda dt: self._load_gallery(), 0.15)

    _current_img_path = ""

    def _set_img(self, path):
        try:
            src = path or get_default_image_path(get_app_path())
            self._current_img_path = src
            self.ids.detail_img.source = src
            self.ids.detail_img.reload()
        except: pass

    def view_main_image(self):
        if self._current_img_path:
            self._show_fullscreen(self._current_img_path)

    def _show_fullscreen(self, img_path, *args):
        from kivy.uix.button import Button as KButton
        popup = ModalView(size_hint=(1, 1), background_color=(0, 0, 0, 0.95))
        content = BoxLayout(orientation="vertical", padding=dp(4))
        img = Image(source=img_path, nocache=True, allow_stretch=True, keep_ratio=True)
        content.add_widget(img)
        close_btn = KButton(text="Close", size_hint_y=None, height=dp(44),
            font_size=sp(14), background_color=(0.3, 0.3, 0.3, 1))
        close_btn.bind(on_press=lambda *a: popup.dismiss())
        content.add_widget(close_btn)
        popup.add_widget(content)
        popup.open()

    def _load_gallery(self):
        """Load spare part gallery images."""
        app = App.get_running_app()
        grid = self.ids.spare_gallery_grid
        grid.clear_widgets()
        images = app.db.get_spare_gallery_images(self.s_id)
        if not images:
            grid.add_widget(Label(text="No gallery photos", font_size=sp(12),
                color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(24)))
            return
        for gal_id, img_data in images:
            img_path = write_blob_to_file(img_data, f"sgal_{gal_id}", get_app_path())
            if img_path:
                btn = ClickableBox(size_hint_y=None, height=dp(200), padding=dp(2))
                img_widget = Image(source=img_path, nocache=True,
                    allow_stretch=True, keep_ratio=True)
                btn.add_widget(img_widget)
                btn.bind(on_release=partial(self._show_fullscreen, img_path))
                grid.add_widget(btn)

    def edit_spare(self):
        """Open edit screen for this spare part."""
        app = App.get_running_app()
        s = app.root.get_screen("add_spare")
        s.load_for_edit(self.s_id)
        app.root.transition = SlideTransition(direction="left")
        app.root.current = "add_spare"

    def add_image(self):
        """Show popup with Gallery and Camera for adding to spare gallery."""
        app = App.get_running_app()
        popup = ModalView(size_hint=(0.75, None), height=dp(130))
        c = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(10))
        with c.canvas.before:
            Color(1,1,1,1); c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        gb = ClickableBox(size_hint_y=None, height=dp(44), padding=(dp(10),dp(6)))
        gb.add_widget(Label(text="Pick from Gallery", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        gb.bind(on_release=lambda *a: (popup.dismiss(), self._do_gallery()))
        cb = ClickableBox(size_hint_y=None, height=dp(44), padding=(dp(10),dp(6)))
        cb.add_widget(Label(text="Take Photo", font_size=sp(14), color=(0.1,0.1,0.18,1)))
        cb.bind(on_release=lambda *a: (popup.dismiss(), self._do_camera()))
        c.add_widget(gb); c.add_widget(cb)
        popup.add_widget(c); popup.open()

    def _do_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("spare_gallery", self.s_id)
        app.open_file_chooser(multiple=True)

    def _do_camera(self):
        app = App.get_running_app()
        app.pick_image_for = ("spare_gallery", self.s_id)
        app._launch_camera()

    def share_spare(self):
        """Share spare part info as plain text via Android share."""
        text = f"Nokia Spare: {self.s_name}\nID: {self.s_id_str}\nLinked Phone: {self.s_phone_id or '-'}\nDescription: {self.s_desc or '-'}"
        _share_text_android(text)

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


class WallDetailScreen(Screen):
    w_id = StringProperty("")
    w_name = StringProperty("")
    w_date = StringProperty("")
    w_appear = StringProperty("")
    w_working = StringProperty("")
    w_remarks = StringProperty("")

    _current_img_path = ""

    def load_wall_item(self, wid):
        app = App.get_running_app()
        w = app.db.get_wall_item(wid)
        if not w:
            return
        self.w_id = w["id"]
        self.w_name = w["name"]
        self.w_date = w.get("release_date", "") or ""
        self.w_appear = w.get("appearance_condition", "") or ""
        self.w_working = w.get("working_condition", "") or ""
        r = w.get("remarks", "") or ""
        self.w_remarks = "" if r in ("None", "none") else r
        img = get_img_path_for_wall(wid, app.db)
        Clock.schedule_once(lambda dt: self._set_img(img), 0.1)

    def _set_img(self, path):
        try:
            src = path or get_default_image_path(get_app_path())
            self._current_img_path = src
            self.ids.detail_img.source = src
            self.ids.detail_img.reload()
        except Exception:
            pass

    def view_main_image(self):
        if self._current_img_path:
            self._show_fullscreen(self._current_img_path)

    def _show_fullscreen(self, img_path, *args):
        from kivy.uix.button import Button as KButton
        popup = ModalView(size_hint=(1, 1), background_color=(0, 0, 0, 0.95))
        content = BoxLayout(orientation="vertical", padding=dp(4))
        img = Image(source=img_path, nocache=True, allow_stretch=True, keep_ratio=True)
        content.add_widget(img)
        close_btn = KButton(text="Close", size_hint_y=None, height=dp(44),
            font_size=sp(14), background_color=(0.3, 0.3, 0.3, 1))
        close_btn.bind(on_press=lambda *a: popup.dismiss())
        content.add_widget(close_btn)
        popup.add_widget(content)
        popup.open()

    def edit_wall_item(self):
        App.get_running_app().show_toast("Wall item editing not yet implemented")

    def confirm_delete(self):
        popup = ModalView(size_hint=(0.78, None), height=dp(130))
        c = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        with c.canvas.before:
            Color(1, 1, 1, 1)
            c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
               size=lambda w, v: setattr(w._bg, "size", v))
        c.add_widget(Label(text=f"Delete {self.w_name}?", font_size=sp(15),
            color=(0.1, 0.1, 0.18, 1), size_hint_y=None, height=dp(28)))
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        cb = ClickableBox(padding=(dp(8), dp(5)))
        cb.add_widget(Label(text="Cancel", font_size=sp(13), color=(0.4, 0.4, 0.4, 1)))
        cb.bind(on_release=lambda *a: popup.dismiss())
        db = ClickableBox(padding=(dp(8), dp(5)))
        with db.canvas.before:
            Color(0.9, 0.22, 0.21, 1)
            db._bg = RoundedRectangle(pos=db.pos, size=db.size, radius=[dp(7)])
        db.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                size=lambda w, v: setattr(w._bg, "size", v))
        db.add_widget(Label(text="Delete", font_size=sp(13), color=(1, 1, 1, 1), bold=True))
        db.bind(on_release=lambda *a: (
            App.get_running_app().db.delete_wall_item(self.w_id),
            setattr(App.get_running_app().root.get_screen("main"), "_data_loaded", False),
            popup.dismiss(), self.go_back()))
        row.add_widget(cb)
        row.add_widget(db)
        c.add_widget(row)
        popup.add_widget(c)
        popup.open()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"


class AddPhoneScreen(Screen):
    edit_mode = BooleanProperty(False)
    screen_title = StringProperty("Add Phone")
    _image_bytes = None  # Store raw bytes in memory
    _auto_price = 0
    _auto_rarity = 0

    def on_edit_mode(self, *a):
        self.screen_title = "Edit Phone" if self.edit_mode else "Add Phone"

    def _populate_condition_spinners(self):
        """Populate appearance and working condition spinners from DB values."""
        app = App.get_running_app()
        try:
            cur = app.db.conn.execute(
                "SELECT DISTINCT appearance_condition FROM phones WHERE appearance_condition IS NOT NULL AND appearance_condition != '' ORDER BY appearance_condition")
            appear_vals = ['Select...'] + [str(r[0]) for r in cur.fetchall()]
            self.ids.appear_spinner.values = appear_vals
            self.ids.appear_spinner.text = 'Select...'
        except Exception:
            pass
        try:
            cur = app.db.conn.execute(
                "SELECT DISTINCT working_condition FROM phones WHERE working_condition IS NOT NULL AND working_condition != '' ORDER BY working_condition")
            working_vals = ['Select...'] + [str(r[0]) for r in cur.fetchall()]
            self.ids.working_spinner.values = working_vals
            self.ids.working_spinner.text = 'Select...'
        except Exception:
            pass

    def clear_form(self):
        self._image_bytes = None
        self._auto_price = 0
        self._auto_rarity = 0
        Clock.schedule_once(self._clear, 0.1)

    def _clear(self, *a):
        try:
            for fid in ["input_id","input_name","input_appear","input_working","input_remarks","input_description","input_price"]:
                self.ids[fid].text = ""
            self.ids.input_id.readonly = False
            self.ids.input_id.disabled = False
            self.ids.input_id.background_color = (1, 1, 1, 1)
            self.ids.input_date.values = ['Select Year'] + [str(y) for y in range(2026, 1984, -1)]
            self.ids.input_date.text = 'Select Year'
            self.ids.input_rarity.text = 'Select Rarity'
            self.ids.preview_img.source = get_default_image_path(get_app_path())
        except: pass
        self._populate_condition_spinners()

    def load_for_edit(self, pid):
        app = App.get_running_app()
        p = app.db.get_phone(pid)
        if not p: return
        self._image_bytes = app.db.get_phone_image(pid)
        img = get_img_path_for_phone(pid, app.db)
        self._populate_condition_spinners()
        Clock.schedule_once(partial(self._fill, p, img), 0.1)

    def _fill(self, p, img_path, *a):
        try:
            self.ids.input_id.text = p["id"]; self.ids.input_name.text = p["name"]
            self.ids.input_date.values = ['Select Year'] + [str(y) for y in range(2026, 1984, -1)]
            self.ids.input_date.text = p.get("release_date","") or "Select Year"
            self.ids.input_appear.text = p.get("appearance_condition","") or ""
            self.ids.input_working.text = p.get("working_condition","") or ""
            r = p.get("remarks","") or ""; self.ids.input_remarks.text = "" if r in ("None","none") else r
            d = p.get("description","") or ""; self.ids.input_description.text = "" if d in ("None","none") else d
            avg_p = p.get("avg_price", 0) or 0
            rar = p.get("rarity_score", 0) or 0
            self.ids.input_price.text = str(int(avg_p)) if avg_p > 0 else ""
            self.ids.input_rarity.text = str(rar) if rar > 0 else "Select Rarity"
            self._auto_price = avg_p
            self._auto_rarity = rar
            # Make ID readonly in edit mode
            if self.edit_mode:
                self.ids.input_id.readonly = True
                self.ids.input_id.background_color = (0.9, 0.9, 0.9, 1)
            self.ids.preview_img.source = img_path or get_default_image_path(get_app_path())
        except: pass

    def auto_fill_from_name(self):
        app = App.get_running_app()
        name = self.ids.input_name.text.strip()
        if not name or self.edit_mode:
            return
        try:
            cur = app.db.conn.execute(
                "SELECT release_date, avg_price, rarity_score, description FROM phones WHERE TRIM(name) = TRIM(?) LIMIT 1",
                (name,))
            row = cur.fetchone()
            if row:
                if row[0] and (self.ids.input_date.text == 'Select Year' or not self.ids.input_date.text.strip()):
                    self.ids.input_date.text = str(row[0])
                self._auto_price = float(row[1] or 0)
                self._auto_rarity = float(row[2] or 0)
                if self._auto_price > 0 and not self.ids.input_price.text.strip():
                    self.ids.input_price.text = str(int(self._auto_price))
                if self._auto_rarity > 0 and (self.ids.input_rarity.text == 'Select Rarity'):
                    self.ids.input_rarity.text = str(self._auto_rarity)
                desc = str(row[3] or "")
                if desc and desc != "None" and not self.ids.input_description.text.strip():
                    self.ids.input_description.text = desc
        except: pass

    def pick_from_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_phone_screen", None); app.open_file_chooser()

    def take_camera(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_phone_screen", None); app._launch_camera()

    def on_image_selected(self, img_bytes):
        """Called with raw image bytes."""
        self._image_bytes = img_bytes
        if img_bytes:
            # Write to temp file with correct extension for Kivy
            ext = ".png" if img_bytes[:4] == b'\x89PNG' else ".jpg"
            tmp = os.path.join(get_cache_dir(get_app_path()), f"_preview_phone{ext}")
            try:
                with open(tmp, "wb") as f:
                    f.write(img_bytes)
                self.ids.preview_img.source = ""
                Clock.schedule_once(lambda dt: setattr(self.ids.preview_img, "source", tmp), 0.15)
            except Exception as e:
                App.get_running_app().show_toast(f"Preview err: {str(e)[:40]}")

    def save_phone(self):
        app = App.get_running_app()
        try: pid = self.ids.input_id.text.strip(); name = self.ids.input_name.text.strip()
        except: return
        if not pid or not name:
            app.show_toast("ID and Name required"); return
        if not pid.isdigit():
            app.show_toast("ID must be numbers only"); return
        if len(pid) > 4:
            app.show_toast("ID must be max 4 digits"); return
        # Duplicate ID check (only when adding, not editing)
        if not self.edit_mode:
            try:
                cur = app.db.conn.execute("SELECT COUNT(*) FROM phones WHERE id = ?", (pid,))
                if cur.fetchone()[0] > 0:
                    app.show_toast("ID already exists!"); return
            except: pass
        try:
            price_text = self.ids.input_price.text.strip()
            price_val = float(price_text) if price_text else self._auto_price
        except: price_val = self._auto_price
        try:
            rarity_text = self.ids.input_rarity.text.strip()
            if rarity_text and rarity_text != 'Select Rarity':
                rarity_val = float(rarity_text)
            else:
                rarity_val = self._auto_rarity
        except: rarity_val = self._auto_rarity
        desc_text = ""
        try: desc_text = self.ids.input_description.text.strip()
        except: pass
        date_text = self.ids.input_date.text.strip()
        if date_text == 'Select Year':
            date_text = ""
        app.db.add_phone(phone_id=pid, name=name,
            release_date=date_text,
            appearance=self.ids.input_appear.text.strip(),
            working=self.ids.input_working.text.strip(),
            remarks=self.ids.input_remarks.text.strip(),
            description=desc_text,
            image_bytes=self._image_bytes,
            avg_price=price_val, rarity_score=rarity_val)
        clear_item_cache(f"p_{pid}", get_app_path())
        app.root.get_screen("main")._data_loaded = False
        app.show_toast("Phone saved!"); self.go_back()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right"); app.root.current = "main"


class AddSpareScreen(Screen):
    _image_bytes = None
    edit_mode = BooleanProperty(False)
    _edit_id = None

    def clear_form(self):
        self._image_bytes = None
        self.edit_mode = False
        self._edit_id = None
        Clock.schedule_once(self._clear, 0.1)

    def _clear(self, *a):
        try:
            self.ids.spare_input_name.text = ""; self.ids.spare_input_desc.text = ""
            self.ids.spare_input_phone_id.text = ""
            self.ids.preview_img.source = get_default_image_path(get_app_path())
        except: pass

    def load_for_edit(self, spare_id):
        """Load spare part data for editing."""
        app = App.get_running_app()
        self.edit_mode = True
        self._edit_id = spare_id
        spare = app.db.get_spare_part(spare_id)
        if not spare:
            return
        self._image_bytes = app.db.get_spare_image(spare_id)
        img = get_img_path_for_spare(spare_id, app.db)
        Clock.schedule_once(partial(self._fill_edit, spare, img), 0.1)

    def _fill_edit(self, spare, img_path, *a):
        try:
            self.ids.spare_input_name.text = spare["name"]
            d = spare.get("description", "") or ""
            self.ids.spare_input_desc.text = "" if d == "None" else d
            self.ids.spare_input_phone_id.text = spare.get("phone_id", "") or ""
            if img_path:
                self.ids.preview_img.source = img_path
        except: pass

    def pick_from_gallery(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_spare_screen", None); app.open_file_chooser()

    def take_camera(self):
        app = App.get_running_app()
        app.pick_image_for = ("add_spare_screen", None); app._launch_camera()

    def on_image_selected(self, img_bytes):
        self._image_bytes = img_bytes
        if img_bytes:
            ext = ".png" if img_bytes[:4] == b'\x89PNG' else ".jpg"
            tmp = os.path.join(get_cache_dir(get_app_path()), f"_preview_spare{ext}")
            try:
                with open(tmp, "wb") as f:
                    f.write(img_bytes)
                self.ids.preview_img.source = ""
                Clock.schedule_once(lambda dt: setattr(self.ids.preview_img, "source", tmp), 0.15)
            except Exception as e:
                App.get_running_app().show_toast(f"Preview err: {str(e)[:40]}")

    def save_spare(self):
        app = App.get_running_app()
        try: name = self.ids.spare_input_name.text.strip()
        except: return
        if not name: app.show_toast("Name required"); return
        if self.edit_mode and self._edit_id:
            # Update existing spare part
            app.db.update_spare_part(self._edit_id,
                name=name,
                phone_id=self.ids.spare_input_phone_id.text.strip(),
                description=self.ids.spare_input_desc.text.strip())
            if self._image_bytes:
                app.db.update_spare_part(self._edit_id, image_data=self._image_bytes)
            clear_item_cache(f"s_{self._edit_id}", get_app_path())
        else:
            # Create new spare part
            app.db.add_spare_part(name=name, phone_id=self.ids.spare_input_phone_id.text.strip(),
                image_bytes=self._image_bytes, description=self.ids.spare_input_desc.text.strip())
        app.root.get_screen("main")._data_loaded = False
        app.show_toast("Spare part saved!"); self.go_back()

    def go_back(self):
        app = App.get_running_app()
        app.root.transition = SlideTransition(direction="right"); app.root.current = "main"


class ExportScreen(Screen):
    _last_export_path = ""

    def on_enter(self):
        Clock.schedule_once(lambda dt: self._load_preview(), 0.2)

    def _load_preview(self):
        """Load phone data into the grid as a preview (first 50 rows)."""
        app = App.get_running_app()
        grid = self.ids.export_grid
        grid.clear_widgets()

        # Header row
        headers = ["ID", "Name", "Year", "Appear.", "Working", "Price"]
        for h in headers:
            lbl = Label(text=h, font_size=sp(11), bold=True, color=(1, 1, 1, 1),
                size_hint_y=None, height=dp(30), text_size=(None, None), halign='center')
            with lbl.canvas.before:
                Color(0, 0.314, 0.784, 1)
                lbl._bg = Rectangle(pos=lbl.pos, size=lbl.size)
            lbl.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                     size=lambda w, v: setattr(w._bg, "size", v))
            grid.add_widget(lbl)

        # Data rows (first 50 as preview)
        phones = []
        try:
            phones = app.db.export_phones()
        except:
            pass

        preview = phones[:50]
        for i, p in enumerate(preview):
            bg = (0.95, 0.96, 0.98, 1) if i % 2 == 0 else (1, 1, 1, 1)
            ap = p.get("avg_price", 0) or 0
            row_data = [
                str(p.get("id", "")),
                str(p.get("name", "")),
                str(p.get("release_date", "") or ""),
                str(p.get("appearance_condition", "") or ""),
                str(p.get("working_condition", "") or ""),
                f"AED {ap:.0f}" if ap > 0 else "",
            ]
            for val in row_data:
                lbl = Label(text=val, font_size=sp(10), color=(0.15, 0.15, 0.15, 1),
                    size_hint_y=None, height=dp(26), text_size=(None, None), halign='center')
                with lbl.canvas.before:
                    Color(*bg)
                    lbl._bg = Rectangle(pos=lbl.pos, size=lbl.size)
                lbl.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                         size=lambda w, v: setattr(w._bg, "size", v))
                grid.add_widget(lbl)

        total = len(phones)
        shown = len(preview)
        self.ids.export_status.text = f"Showing {shown} of {total} phones"
        self.ids.export_status.color = (0.4, 0.4, 0.4, 1)

    def do_export(self):
        app = App.get_running_app()
        try:
            # Use external files dir so other apps (WhatsApp etc) can access it
            if platform == "android":
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    context = PythonActivity.mActivity
                    ext_dir = context.getExternalFilesDir(None)
                    od = ext_dir.getAbsolutePath()
                except:
                    od = os.path.join(get_app_path(), "exports")
            else:
                od = os.path.join(get_app_path(), "exports")
            os.makedirs(od, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            phones = app.db.export_phones()
            spares = app.db.export_spare_parts()

            # Build XLSX data
            phone_rows = [["ID", "Name", "Release Date", "Appearance", "Working", "Remarks", "Description", "Avg Price (AED)", "Rarity"]]
            for p in phones:
                phone_rows.append([
                    str(p["id"]), str(p["name"]),
                    str(p.get("release_date","") or ""),
                    str(p.get("appearance_condition","") or ""),
                    str(p.get("working_condition","") or ""),
                    str(p.get("remarks","") or ""),
                    str(p.get("description","") or ""),
                    str(p.get("avg_price","") or ""),
                    str(p.get("rarity_score","") or "")
                ])

            spare_rows = [["ID", "Name", "Phone ID", "Description"]]
            for s in spares:
                spare_rows.append([
                    str(s["id"]), str(s["name"]),
                    str(s.get("phone_id","") or ""),
                    str(s.get("description","") or "")
                ])

            # Wall items sheet
            wall_rows = [["ID", "Name", "Release Date", "Appearance", "Working", "Remarks"]]
            try:
                walls = app.db.get_all_wall_items()
                for w in walls:
                    wall_rows.append([
                        str(w["id"]), str(w["name"]),
                        str(w.get("release_date","") or ""),
                        str(w.get("appearance_condition","") or ""),
                        str(w.get("working_condition","") or ""),
                        str(w.get("remarks","") or "")
                    ])
            except: pass

            sheets = {"Phones": phone_rows, "Spare Parts": spare_rows, "Wall": wall_rows}
            filepath = os.path.join(od, f"nokia_export_{ts}.xlsx")
            create_xlsx(sheets, filepath)

            self._last_export_path = filepath
            wall_cnt = len(wall_rows) - 1
            self.ids.export_status.text = f"Exported {len(phones)} phones, {len(spares)} spares, {wall_cnt} wall"
            self.ids.export_status.color = (0.26,0.63,0.28,1)
            app.show_toast("Export saved!")

            # Share the file
            _share_file_android(filepath, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            self.ids.export_status.text = f"Error: {str(e)}"
            self.ids.export_status.color = (0.9,0.22,0.21,1)

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class BackupScreen(Screen):
    def create_backup(self):
        app = App.get_running_app()
        try:
            # Use external dir so sharing works
            if platform == "android":
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    context = PythonActivity.mActivity
                    ext_dir = context.getExternalFilesDir(None)
                    od = ext_dir.getAbsolutePath()
                except:
                    od = os.path.join(get_app_path(), "backups")
            else:
                od = os.path.join(get_app_path(), "backups")
            os.makedirs(od, exist_ok=True)
            bf = os.path.join(od, f"nokia_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
            # DB contains ALL data: phones, spares, images (BLOBs), gallery
            with zipfile.ZipFile(bf, "w", zipfile.ZIP_DEFLATED) as zf:
                dbp = get_db_path()
                if os.path.exists(dbp):
                    zf.write(dbp, "nokia_storage.db")
            fsize = os.path.getsize(bf) // 1024
            self.ids.backup_status.text = f"Backup created ({fsize}KB)\nTap Share to save/send"
            self.ids.backup_status.color = (0.26,0.63,0.28,1)
            self._backup_path = bf
            app.show_toast(f"Backup: {fsize}KB")
            # Auto-share on Android
            if platform == "android":
                self._share_backup(bf)
        except Exception as e:
            self.ids.backup_status.text = f"Error: {str(e)}"
            self.ids.backup_status.color = (0.9,0.22,0.21,1)

    def _share_backup(self, filepath):
        _share_file_android(filepath, "application/zip")

    def restore_backup(self):
        app = App.get_running_app()
        app.pick_image_for = ("restore_backup", None)
        app.open_file_chooser(filters=["*.zip"])

    def on_backup_selected(self, path):
        """Restore: read zip, extract DB, reopen. All images are inside the DB as BLOBs."""
        app = App.get_running_app()
        try:
            # Read the zip (might be a content:// URI on Android)
            from imghelper import smart_read
            zip_bytes = smart_read(path)
            if not zip_bytes:
                app.show_toast("Cannot read backup file")
                return
            # Write to temp location
            tmp_zip = os.path.join(get_app_path(), "_restore_tmp.zip")
            with open(tmp_zip, "wb") as f:
                f.write(zip_bytes)
            # Close DB, extract, reopen
            app.db.close()
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(get_app_path())
            try: os.remove(tmp_zip)
            except: pass
            app.db = NokiaDatabase(get_db_path())
            # Clear image cache so images reload from new DB
            try:
                import shutil
                cd = get_cache_dir(get_app_path())
                if os.path.isdir(cd):
                    shutil.rmtree(cd, ignore_errors=True)
            except: pass
            app.root.get_screen("main")._data_loaded = False
            cnt = app.db.get_phone_count()
            self.ids.backup_status.text = f"Restored! {cnt} phones loaded."
            self.ids.backup_status.color = (0.26,0.63,0.28,1)
            app.show_toast(f"Restored {cnt} phones!")
        except Exception as e:
            app.db = NokiaDatabase(get_db_path())
            self.ids.backup_status.text = f"Error: {str(e)}"
            self.ids.backup_status.color = (0.9,0.22,0.21,1)

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
        phones, spares, wall_items = app.db.search_all(text)
        defimg = get_default_image_path(get_app_path())
        if phones:
            grid.add_widget(Label(text=f"Phones ({len(phones)})", font_size=sp(14), bold=True, color=(0,0.314,0.784,1), size_hint_y=None, height=dp(26), text_size=(dp(300),None), halign="left"))
            for p in phones[:PAGE_SIZE]:
                img = get_img_path_for_phone(p["id"], app.db) if p.get("has_image") else defimg
                pr = p.get("avg_price", 0) or 0
                rs = p.get("rarity_score", 0) or 0
                pp = []
                if pr > 0:
                    pp.append("AED %d" % int(pr))
                if rs > 0:
                    pp.append(rarity_label(rs))
                card = PhoneCard(phone_id=p["id"], phone_name=p["name"], phone_date=p.get("release_date","") or "",
                    phone_appear=p.get("appearance_condition","") or "", phone_working=p.get("working_condition","") or "",
                    phone_image=img or defimg, phone_price=" | ".join(pp) if pp else "")
                card.bind(on_release=partial(self._op, p["id"])); grid.add_widget(card)
        if spares:
            grid.add_widget(Label(text=f"Spare Parts ({len(spares)})", font_size=sp(14), bold=True, color=(0,0.314,0.784,1), size_hint_y=None, height=dp(26), text_size=(dp(300),None), halign="left"))
            for s in spares[:PAGE_SIZE]:
                img = get_img_path_for_spare(s["id"], app.db) if s.get("has_image") else defimg
                card = SpareCard(spare_id=s["id"], spare_name=s["name"], spare_desc=s.get("description","") or "",
                    spare_image=img or defimg)
                card.bind(on_release=partial(self._os, s["id"])); grid.add_widget(card)
        if wall_items:
            grid.add_widget(Label(text=f"Wall Items ({len(wall_items)})", font_size=sp(14), bold=True, color=(0,0.314,0.784,1), size_hint_y=None, height=dp(26), text_size=(dp(300),None), halign="left"))
            for w in wall_items[:PAGE_SIZE]:
                img = get_img_path_for_wall(w["id"], app.db) if w.get("has_image") else defimg
                card = PhoneCard(phone_id=w["id"], phone_name=w["name"], phone_date=w.get("release_date","") or "",
                    phone_appear=w.get("appearance_condition","") or "", phone_working=w.get("working_condition","") or "",
                    phone_image=img or defimg, phone_price="")
                card.bind(on_release=partial(self._ow, w["id"])); grid.add_widget(card)
        if not phones and not spares and not wall_items:
            grid.add_widget(Label(text="No results", font_size=sp(13), color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(36)))

    def _op(self, pid, *a):
        app = App.get_running_app()
        app.root.get_screen("phone_detail").load_phone(pid)
        app.root.transition = SlideTransition(direction="left"); app.root.current = "phone_detail"
    def _os(self, sid, *a):
        app = App.get_running_app()
        app.root.get_screen("spare_detail").load_spare(sid)
        app.root.transition = SlideTransition(direction="left"); app.root.current = "spare_detail"
    def _ow(self, wid, *a):
        app = App.get_running_app()
        app.root.get_screen("wall_detail").load_wall_item(wid)
        app.root.transition = SlideTransition(direction="left"); app.root.current = "wall_detail"
    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class ReportScreen(Screen):
    def on_enter(self):
        Clock.schedule_once(lambda dt: self._load(), 0.2)

    def _go_main_filtered(self, filter_text, *a):
        app = App.get_running_app()
        main = app.root.get_screen("main")
        main.current_tab = "phones"
        main._data_loaded = False
        main._current_page = 0
        main._is_search = False
        main._pending_filter = filter_text
        main._pending_search = ""
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"

    def _go_main_search(self, query, *a):
        app = App.get_running_app()
        main = app.root.get_screen("main")
        main.current_tab = "phones"
        main._data_loaded = False
        main._current_page = 0
        main._is_search = False
        main._pending_search = query
        main._pending_filter = ""
        app.root.transition = SlideTransition(direction="right")
        app.root.current = "main"

    def _load(self):
        app = App.get_running_app()
        g = self.ids.report_grid; g.clear_widgets()
        try: r = app.db.get_report()
        except Exception: g.add_widget(Label(text="Error", size_hint_y=None, height=dp(30))); return

        total_phones = r.get('total_phones', 0)
        with_images = r.get('phones_with_images', 0)
        without_images = total_phones - with_images
        unique_models = r.get('unique_models', 0)
        total_spares = r.get('total_spares', 0)

        # Wall count
        try:
            wall_count = app.db.get_wall_count()
        except Exception:
            wall_count = 0

        # Find most common model
        by_model = r.get('by_model', [])
        most_common = by_model[0] if by_model else ("N/A", 0)

        # Year range
        all_phones = app.db.get_all_phones() if app.db else []
        years = []
        for p in all_phones:
            rd = p.get('release_date', '') or ''
            for part in rd.replace('-', ' ').replace('/', ' ').split():
                if len(part) == 4 and part.isdigit():
                    years.append(int(part))
                    break
        year_range = f"{min(years)} - {max(years)}" if years else "N/A"

        # Helper to create a colored stat card with optional on_tap callback
        def stat_card(title, value, bg_color, on_tap=None):
            if on_tap:
                card = ClickableBox(orientation="vertical", size_hint_y=None, height=dp(70), padding=dp(10))
                card.bind(on_release=on_tap)
            else:
                card = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(70), padding=dp(10))
            with card.canvas.before:
                Color(*bg_color)
                card._bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(10)])
            card.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
            num_label = Label(text=str(value), font_size=sp(24), bold=True, color=(1,1,1,1), size_hint_y=0.6)
            desc_label = Label(text=title, font_size=sp(12), color=(1,1,1,0.8), size_hint_y=0.4)
            card.add_widget(num_label)
            card.add_widget(desc_label)
            return card

        def stat_row(cards):
            row = BoxLayout(size_hint_y=None, height=dp(70), spacing=dp(6))
            for c in cards:
                row.add_widget(c)
            return row

        def sec(t):
            g.add_widget(Label(text=t, font_size=sp(16), bold=True, color=(0,0.314,0.784,1),
                size_hint_y=None, height=dp(30), text_size=(dp(300),None), halign="left"))

        # Key stat cards - 2 per row layout
        sec("Overview")
        # Row 1: Total Phones | Unique Models
        g.add_widget(stat_row([
            stat_card("Total Phones", total_phones, (0, 0.314, 0.784, 1),
                on_tap=lambda *a: self._go_main_filtered('All')),
            stat_card("Unique Models", unique_models, (0.4, 0.3, 0.6, 1),
                on_tap=lambda *a: self._go_main_filtered('Unique Models'))
        ]))
        # Row 2: With Images | Without Images
        g.add_widget(stat_row([
            stat_card("With Images", with_images, (0.26, 0.63, 0.28, 1),
                on_tap=lambda *a: self._go_main_filtered('With Images')),
            stat_card("Without Images", without_images, (0.85, 0.4, 0.1, 1),
                on_tap=lambda *a: self._go_main_filtered('Without Images'))
        ]))
        # Row 3: Spare Parts | Wall Items
        g.add_widget(stat_row([
            stat_card("Spare Parts", total_spares, (0.2, 0.2, 0.25, 1)),
            stat_card("Wall Items", wall_count, (0.35, 0.25, 0.15, 1))
        ]))
        # Row 4: Year Range | Most Common Model
        g.add_widget(stat_row([
            stat_card("Year Range", year_range, (0.6, 0.2, 0.4, 1)),
            stat_card("Most Common", f"{most_common[0]} ({most_common[1]})", (0, 0.44, 1, 1),
                on_tap=lambda *a, m=most_common[0]: self._go_main_filtered(f"Name:{m}"))
        ]))

        # Collection Value section
        total_value = 0
        priced_count = 0
        no_price_models = []
        no_rarity_models = []
        rarity_sum = 0
        rarity_count = 0
        for p in all_phones:
            ap = float(p.get('avg_price', 0) or 0)
            rs = float(p.get('rarity_score', 0) or 0)
            total_value += ap
            if ap > 0:
                priced_count += 1
            else:
                pname = p.get('name', '') or 'Unknown'
                if pname not in no_price_models:
                    no_price_models.append(pname)
            if rs > 0:
                rarity_sum += rs
                rarity_count += 1
            else:
                pname = p.get('name', '') or 'Unknown'
                if pname not in no_rarity_models:
                    no_rarity_models.append(pname)
        avg_phone_price = (total_value / priced_count) if priced_count else 0
        avg_rarity = (rarity_sum / rarity_count) if rarity_count > 0 else 0

        sec("Collection Value")
        g.add_widget(stat_card("Total Collection Value", f"AED {total_value:,.0f}", (0.1, 0.5, 0.3, 1)))
        g.add_widget(stat_card("Avg Phone Price", f"AED {avg_phone_price:,.0f}" if avg_phone_price > 0 else "N/A", (0.2, 0.45, 0.25, 1)))

        # Condition breakdown with percentages - clickable rows using filter
        def condition_section(title, data, color_base, filter_field):
            sec(title)
            for n, c in data:
                pct = (c / total_phones * 100) if total_phones > 0 else 0
                cond_name = str(n or "Unknown")
                row = ClickableBox(size_hint_y=None, height=dp(28), padding=(dp(8),dp(2)), spacing=dp(4))
                row.bind(on_release=partial(self._go_main_filtered, f"{filter_field}:{cond_name}"))
                with row.canvas.before:
                    Color(*color_base, 0.1)
                    row._bg = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(5)])
                row.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
                row.add_widget(Label(text=cond_name, font_size=sp(12), color=(0.15,0.15,0.15,1),
                    text_size=(dp(180),None), halign="left"))
                row.add_widget(Label(text=f"{c}", font_size=sp(12), bold=True, color=(0.1,0.1,0.18,1),
                    size_hint_x=None, width=dp(36), halign="right", text_size=(dp(36),None)))
                row.add_widget(Label(text=f"({pct:.1f}%)", font_size=sp(11), color=(0.4,0.4,0.4,1),
                    size_hint_x=None, width=dp(56), halign="right", text_size=(dp(56),None)))
                g.add_widget(row)

        condition_section("By Working Condition", r.get("by_working",[]), (0, 0.314, 0.784), "Working")
        condition_section("By Appearance", r.get("by_appearance",[]), (0.26, 0.63, 0.28), "Appearance")

        # Collection Timeline - horizontal bar chart by year
        years_data = r.get("by_year", [])
        valid_years = []
        for y_val, c_val in years_data:
            ys = str(y_val or "")
            # Extract 4-digit year from release_date string
            found_year = ""
            for part in ys.replace("-", " ").replace("/", " ").split():
                if len(part) == 4 and part.isdigit():
                    found_year = part
                    break
            if found_year:
                valid_years.append((found_year, c_val))
        # Aggregate by year (release_date may group differently)
        year_counts = {}
        for ystr, cnt in valid_years:
            year_counts[ystr] = year_counts.get(ystr, 0) + cnt
        sorted_years = sorted(year_counts.items(), key=lambda x: x[0])
        if sorted_years:
            sec("Collection Timeline")
            max_count = max(c for _, c in sorted_years)
            for year_str, count in sorted_years:
                bar_pct = count / max_count if max_count > 0 else 0
                row = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(4), padding=(dp(4), 0))
                row.add_widget(Label(text=year_str, font_size=sp(10), color=(0.3, 0.3, 0.3, 1),
                    size_hint_x=None, width=dp(36), halign="right", text_size=(dp(36), None)))
                bar = BoxLayout(size_hint_x=bar_pct if bar_pct > 0.02 else 0.02)
                with bar.canvas.before:
                    Color(0, 0.314, 0.784, 0.8)
                    bar._bg = Rectangle(pos=bar.pos, size=bar.size)
                bar.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                         size=lambda w, v: setattr(w._bg, "size", v))
                bar.add_widget(Label(text=str(count), font_size=sp(9), color=(1, 1, 1, 1)))
                row.add_widget(bar)
                row.add_widget(Widget(size_hint_x=1 - bar_pct if bar_pct < 0.98 else 0.02))
                g.add_widget(row)

        # Spare parts breakdown by name (top 10)
        try:
            all_spares = app.db.get_all_spare_parts()
            spare_counts = {}
            for sp_item in all_spares:
                sname = sp_item.get('name', '') or 'Unknown'
                spare_counts[sname] = spare_counts.get(sname, 0) + 1
            sorted_spares = sorted(spare_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            if sorted_spares:
                sec("Top Spare Parts")
                for sname, scount in sorted_spares:
                    row = BoxLayout(size_hint_y=None, height=dp(24), padding=(dp(8),dp(1)))
                    row.add_widget(Label(text=str(sname), font_size=sp(12), color=(0.3,0.3,0.3,1),
                        text_size=(dp(220),None), halign="left"))
                    row.add_widget(Label(text=str(scount), font_size=sp(12), bold=True, color=(0.1,0.1,0.18,1),
                        size_hint_x=None, width=dp(50), halign="right", text_size=(dp(50),None)))
                    g.add_widget(row)
        except Exception:
            pass

        # Top 20 Models - clickable rows
        sec("Top 20 Models")
        for n, c in r.get("by_model",[]):
            model_name = str(n)
            row = ClickableBox(size_hint_y=None, height=dp(24), padding=(dp(8),dp(1)))
            row.bind(on_release=partial(self._go_main_filtered, f"Name:{model_name}"))
            row.add_widget(Label(text=model_name, font_size=sp(12), color=(0.3,0.3,0.3,1), text_size=(dp(220),None), halign="left"))
            row.add_widget(Label(text=str(c), font_size=sp(12), bold=True, color=(0.1,0.1,0.18,1), size_hint_x=None, width=dp(50), halign="right", text_size=(dp(50),None)))
            g.add_widget(row)

        # No Fully Working Phone section - clickable rows
        try:
            cur = app.db.conn.execute(
                "SELECT DISTINCT TRIM(name) as n, COUNT(*) as c FROM phones "
                "GROUP BY TRIM(name) "
                "HAVING SUM(CASE WHEN TRIM(working_condition)='FW' THEN 1 ELSE 0 END) = 0 "
                "ORDER BY n LIMIT 30")
            no_fw_models = [(row[0], row[1]) for row in cur.fetchall()]
            sec("No Fully Working Phone")
            g.add_widget(stat_card("Models Without FW", len(no_fw_models), (0.85, 0.2, 0.2, 1),
                on_tap=lambda *a: self._go_main_filtered('No FW Models')))
            for nm, cnt in no_fw_models:
                nm_str = str(nm)
                row = ClickableBox(size_hint_y=None, height=dp(28), padding=(dp(8), dp(2)), spacing=dp(4))
                row.bind(on_release=partial(self._go_main_filtered, f"Name:{nm_str}"))
                with row.canvas.before:
                    Color(1, 0.96, 0.9, 1)
                    row._bg = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(5)])
                row.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                         size=lambda w, v: setattr(w._bg, "size", v))
                row.add_widget(Label(text=nm_str, font_size=sp(12), color=(0.15, 0.15, 0.15, 1),
                    text_size=(dp(200), None), halign="left"))
                row.add_widget(Label(text=str(cnt), font_size=sp(12), bold=True,
                    color=(0.1, 0.1, 0.18, 1), size_hint_x=None, width=dp(40),
                    halign="right", text_size=(dp(40), None)))
                g.add_widget(row)
        except Exception:
            pass

        # Phones without pricing section
        if no_price_models:
            sec("Phones Without Pricing")
            g.add_widget(stat_card("No Price Info", len(no_price_models), (0.85, 0.55, 0.1, 1)))
            for nm in no_price_models[:30]:
                nm_str = str(nm)
                row = ClickableBox(size_hint_y=None, height=dp(28), padding=(dp(8), dp(2)), spacing=dp(4))
                row.bind(on_release=partial(self._go_main_filtered, f"Name:{nm_str}"))
                with row.canvas.before:
                    Color(1, 0.96, 0.88, 1)
                    row._bg = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(5)])
                row.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                         size=lambda w, v: setattr(w._bg, "size", v))
                row.add_widget(Label(text=nm_str, font_size=sp(12), color=(0.15, 0.15, 0.15, 1),
                    text_size=(dp(280), None), halign="left"))
                g.add_widget(row)

        # Phones without rarity section
        if no_rarity_models:
            sec("Phones Without Rarity")
            g.add_widget(stat_card("No Rarity Info", len(no_rarity_models), (0.5, 0.3, 0.6, 1)))
            for nm in no_rarity_models[:30]:
                nm_str = str(nm)
                row = ClickableBox(size_hint_y=None, height=dp(28), padding=(dp(8), dp(2)), spacing=dp(4))
                row.bind(on_release=partial(self._go_main_filtered, f"Name:{nm_str}"))
                with row.canvas.before:
                    Color(0.95, 0.92, 1, 1)
                    row._bg = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(5)])
                row.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                         size=lambda w, v: setattr(w._bg, "size", v))
                row.add_widget(Label(text=nm_str, font_size=sp(12), color=(0.15, 0.15, 0.15, 1),
                    text_size=(dp(280), None), halign="left"))
                g.add_widget(row)

        g.add_widget(Widget(size_hint_y=None, height=dp(30)))

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


class PhotoGalleryScreen(Screen):
    _image_paths = []  # List of (gal_id, img_path) for navigation

    def on_enter(self):
        Clock.schedule_once(lambda dt: self._load(), 0.2)

    def _load(self):
        app = App.get_running_app()
        grid = self.ids.gallery_grid
        grid.clear_widgets()
        images = app.db.get_general_gallery()
        self._image_paths = []
        if not images:
            grid.add_widget(Label(text="No photos yet.\nTap '+ Add Photos' to start.",
                font_size=sp(14), color=(0.5,0.5,0.5,1), size_hint_y=None, height=dp(60),
                halign="center"))
            return
        for gal_id, img_data, caption in images:
            img_path = write_blob_to_file(img_data, f"gg_{gal_id}", get_app_path())
            if img_path:
                self._image_paths.append((gal_id, img_path))
                idx = len(self._image_paths) - 1
                box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(190), padding=dp(3))
                with box.canvas.before:
                    Color(1,1,1,1)
                    box._bg = RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(8)])
                box.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
                # Image - tappable
                img_btn = ClickableBox(size_hint_y=None, height=dp(155))
                img_widget = Image(source=img_path, nocache=True, allow_stretch=True, keep_ratio=True)
                img_btn.add_widget(img_widget)
                img_btn.bind(on_release=partial(self._open_viewer, idx))
                box.add_widget(img_btn)
                # Delete button
                from kivy.uix.button import Button as KBtn
                del_btn = KBtn(text="Delete", size_hint_y=None, height=dp(28),
                    font_size=sp(11), background_color=(0.85,0.2,0.2,1), color=(1,1,1,1))
                del_btn.bind(on_press=partial(self._delete_photo, gal_id))
                box.add_widget(del_btn)
                grid.add_widget(box)

    def _delete_photo(self, gal_id, *a):
        """Show confirmation before deleting."""
        from kivy.uix.button import Button as KBtn
        popup = ModalView(size_hint=(0.78, None), height=dp(130))
        c = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        with c.canvas.before:
            Color(1,1,1,1); c._bg = RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(10)])
        c.bind(pos=lambda w,v: setattr(w._bg,"pos",v), size=lambda w,v: setattr(w._bg,"size",v))
        c.add_widget(Label(text="Delete this photo?", font_size=sp(15), color=(0.1,0.1,0.18,1),
            size_hint_y=None, height=dp(28)))
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(42))
        cancel = KBtn(text="Cancel", font_size=sp(13), background_color=(0.7,0.7,0.7,1))
        cancel.bind(on_press=lambda *a: popup.dismiss())
        delete = KBtn(text="Delete", font_size=sp(13), background_color=(0.85,0.2,0.2,1), color=(1,1,1,1))
        delete.bind(on_press=lambda *a: self._confirm_delete(gal_id, popup))
        row.add_widget(cancel); row.add_widget(delete)
        c.add_widget(row)
        popup.add_widget(c); popup.open()

    def _confirm_delete(self, gal_id, popup):
        app = App.get_running_app()
        app.db.delete_general_gallery(gal_id)
        clear_item_cache(f"gg_{gal_id}", get_app_path())
        popup.dismiss()
        app.show_toast("Photo deleted")
        self._load()

    def _open_viewer(self, index, *a):
        """Open full-screen image viewer with left/right navigation."""
        if not self._image_paths:
            return
        self._viewer_index = index
        self._show_viewer()

    def _show_viewer(self):
        from kivy.uix.button import Button as KBtn
        if hasattr(self, '_viewer_popup') and self._viewer_popup:
            try: self._viewer_popup.dismiss()
            except: pass

        idx = self._viewer_index
        if idx < 0 or idx >= len(self._image_paths):
            return
        gal_id, img_path = self._image_paths[idx]
        total = len(self._image_paths)

        self._viewer_popup = ModalView(size_hint=(1, 1), background_color=(0, 0, 0, 0.95))
        c = BoxLayout(orientation="vertical", padding=dp(4), spacing=dp(4))

        # Counter
        c.add_widget(Label(text=f"{idx+1} / {total}", font_size=sp(14), color=(1,1,1,1),
            size_hint_y=None, height=dp(28)))

        # Image
        c.add_widget(Image(source=img_path, nocache=True, allow_stretch=True, keep_ratio=True))

        # Navigation buttons
        nav = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        prev_btn = KBtn(text="< Prev", font_size=sp(14), background_color=(0.3,0.3,0.3,1),
            disabled=(idx == 0))
        prev_btn.bind(on_press=lambda *a: self._nav_viewer(-1))
        close_btn = KBtn(text="Close", font_size=sp(14), background_color=(0.5,0.1,0.1,1))
        close_btn.bind(on_press=lambda *a: self._viewer_popup.dismiss())
        next_btn = KBtn(text="Next >", font_size=sp(14), background_color=(0.3,0.3,0.3,1),
            disabled=(idx >= total - 1))
        next_btn.bind(on_press=lambda *a: self._nav_viewer(1))
        nav.add_widget(prev_btn); nav.add_widget(close_btn); nav.add_widget(next_btn)
        c.add_widget(nav)

        self._viewer_popup.add_widget(c)
        self._viewer_popup.open()

    def _nav_viewer(self, direction):
        self._viewer_index += direction
        self._viewer_index = max(0, min(self._viewer_index, len(self._image_paths) - 1))
        self._viewer_popup.dismiss()
        Clock.schedule_once(lambda dt: self._show_viewer(), 0.1)

    def add_photos(self):
        app = App.get_running_app()
        app.pick_image_for = ("general_gallery", None)
        app.open_file_chooser(multiple=True)

    def go_back(self):
        App.get_running_app().root.transition = SlideTransition(direction="right")
        App.get_running_app().root.current = "main"


# -- Main App ------------------------------------------------------

class NokiaStorageApp(App):
    title = "Nokia Storage"
    db = ObjectProperty(None, allownone=True)
    pick_image_for = None
    _last_back = 0

    def build(self):
        Window.clearcolor = (1, 1, 1, 1)
        Window.softinput_mode = 'below_target'
        try: self.db = NokiaDatabase(get_db_path())
        except Exception as e: print(f"DB: {e}")
        if platform == "android":
            Clock.schedule_once(lambda dt: self._perms(), 1)
            # Bind activity result ONCE at startup (like official Kivy example)
            try:
                from android import activity as android_activity
                android_activity.bind(on_activity_result=self._on_android_activity_result)
            except Exception as e:
                print(f"Activity bind error: {e}")
        self._load_initial()
        Window.bind(on_keyboard=self._kb)
        root = Builder.load_string(KV)
        root.current = "splash"
        return root

    def _kb(self, win, key, *a):
        if key == 27:
            if self.root and self.root.current == "main":
                self.root.transition = SlideTransition(direction="right"); self.root.current = "dashboard"
                return True
            if self.root and self.root.current not in ("dashboard", "splash"):
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
                    phone_rows = []
                    wall_rows = []
                    for i in data:
                        desc = str(i[8]) if len(i) > 8 and i[8] else ""
                        if desc in ("None","none"): desc = ""
                        row = {"id":str(i[0]),"name":str(i[1]),"release_date":str(i[2]),
                               "appearance_condition":str(i[3]),"working_condition":str(i[4]),
                               "remarks":str(i[5]) if i[5] else "",
                               "avg_price":float(i[6]) if len(i) > 6 else 0,
                               "rarity_score":float(i[7]) if len(i) > 7 else 0,
                               "description": desc}
                        if str(i[0]).startswith("XXXX"):
                            wall_rows.append(row)
                        else:
                            phone_rows.append(row)
                    self.db.import_phones_from_rows(phone_rows)
                    if wall_rows:
                        self.db.import_wall_from_rows(wall_rows)
                    break
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

    def _read_uri_bytes(self, uri):
        """Read bytes from an Android content URI using file descriptor."""
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        context = PythonActivity.mActivity
        pfd = context.getContentResolver().openFileDescriptor(uri, "r")
        fd = pfd.detachFd()
        with os.fdopen(fd, "rb") as f:
            return f.read()

    def _on_android_activity_result(self, request_code, result_code, data):
        """Activity result handler - bound ONCE at startup."""
        # Use Clock.schedule_once to defer processing (official Kivy pattern)
        Clock.schedule_once(lambda dt: self._process_activity_result(request_code, result_code, data), 0)

    def _process_activity_result(self, request_code, result_code, data):
        """Process activity result on main thread."""
        if request_code == 42:
            self._process_picker(result_code, data)
        elif request_code == 43:
            self._process_camera(result_code, data)

    def _process_picker(self, result_code, data):
        if result_code != -1 or not data:
            return
        try:
            uris = []
            clip = data.getClipData()
            if clip:
                for i in range(clip.getItemCount()):
                    uris.append(clip.getItemAt(i).getUri())
            else:
                single = data.getData()
                if single:
                    uris.append(single)
            if not uris:
                return

            # Handle restore_backup BEFORE image processing
            if self.pick_image_for and self.pick_image_for[0] == "restore_backup":
                try:
                    zip_bytes = self._read_uri_bytes(uris[0])
                    if zip_bytes and len(zip_bytes) > 100:
                        self.pick_image_for = None
                        # Write to temp file and restore
                        tmp_zip = os.path.join(get_app_path(), "_restore_tmp.zip")
                        with open(tmp_zip, "wb") as f:
                            f.write(zip_bytes)
                        self.db.close()
                        with zipfile.ZipFile(tmp_zip, "r") as zf:
                            zf.extractall(get_app_path())
                        try: os.remove(tmp_zip)
                        except: pass
                        self.db = NokiaDatabase(get_db_path())
                        try:
                            cd = get_cache_dir(get_app_path())
                            if os.path.isdir(cd):
                                shutil.rmtree(cd, ignore_errors=True)
                        except: pass
                        self.root.get_screen("main")._data_loaded = False
                        cnt = self.db.get_phone_count()
                        self.show_toast(f"Restored {cnt} phones!")
                        try:
                            self.root.get_screen("backup").ids.backup_status.text = f"Restored! {cnt} phones loaded."
                            self.root.get_screen("backup").ids.backup_status.color = (0.26,0.63,0.28,1)
                        except: pass
                    else:
                        self.show_toast("Cannot read backup file")
                except Exception as e:
                    self.db = NokiaDatabase(get_db_path())
                    self.show_toast(f"Restore error: {str(e)[:40]}")
                return

            all_bytes = []
            for uri in uris:
                try:
                    b = self._read_uri_bytes(uri)
                    if b and len(b) > 100:
                        all_bytes.append(b)
                except:
                    pass
            if all_bytes:
                self._handle_selected_images(all_bytes)
            else:
                self.show_toast("Could not read images")
        except Exception as e:
            self.show_toast(f"Error: {str(e)[:40]}")

    def _process_camera(self, result_code, data):
        if result_code != -1:
            return
        if not data:
            self.show_toast("Camera: no data returned")
            return
        try:
            from jnius import autoclass, cast
            extras = data.getExtras()
            if not extras:
                self.show_toast("Camera: no extras")
                return
            # Cast Parcelable to Bitmap explicitly
            Bitmap = autoclass("android.graphics.Bitmap")
            parcel = extras.get("data")
            if not parcel:
                self.show_toast("Camera: no data in extras")
                return
            bitmap = cast(Bitmap, parcel)
            if not bitmap:
                self.show_toast("Camera: cast failed")
                return
            # Compress to JPEG
            BitmapCF = autoclass("android.graphics.Bitmap$CompressFormat")
            BAOS = autoclass("java.io.ByteArrayOutputStream")
            baos = BAOS()
            bitmap.compress(BitmapCF.JPEG, 95, baos)
            img_bytes = bytes(bytearray(baos.toByteArray()))
            baos.close()
            if img_bytes and len(img_bytes) > 100:
                self._handle_selected_images([img_bytes])
            else:
                self.show_toast("Camera: empty image")
        except Exception as e:
            self.show_toast(f"Camera error: {str(e)[:50]}")

    def _ac(self, filters=None, multiple=False):
        """Android file chooser - just launch Intent, callback already bound."""
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            mime = "image/*"
            if filters and "*.zip" in filters:
                mime = "application/zip"
            intent = Intent(Intent.ACTION_GET_CONTENT)
            intent.setType(mime)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            if multiple:
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, True)
            PythonActivity.mActivity.startActivityForResult(intent, 42)
        except Exception as e:
            self.show_toast(f"Picker error: {str(e)[:50]}")

    _camera_temp_file = ""

    def _launch_camera(self):
        """Launch camera - no EXTRA_OUTPUT, get thumbnail from extras.
        This is the simplest approach that works on all Android versions."""
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            MediaStore = autoclass("android.provider.MediaStore")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
            PythonActivity.mActivity.startActivityForResult(intent, 43)
        except Exception as e:
            self.show_toast(f"Camera error: {str(e)[:50]}")

    def _resize_image(self, img_bytes, max_dim=2000):
        """Resize image to max_dim using Android Bitmap API. Returns valid JPEG."""
        if not img_bytes or platform != "android":
            return img_bytes
        try:
            from jnius import autoclass
            BitmapFactory = autoclass("android.graphics.BitmapFactory")
            Bitmap = autoclass("android.graphics.Bitmap")
            BitmapCF = autoclass("android.graphics.Bitmap$CompressFormat")
            BAOS = autoclass("java.io.ByteArrayOutputStream")
            bitmap = BitmapFactory.decodeByteArray(img_bytes, 0, len(img_bytes))
            if not bitmap:
                return img_bytes
            w, h = bitmap.getWidth(), bitmap.getHeight()
            if w > max_dim or h > max_dim:
                if w > h:
                    nw, nh = max_dim, int(h * max_dim / w)
                else:
                    nh, nw = max_dim, int(w * max_dim / h)
                bitmap = Bitmap.createScaledBitmap(bitmap, nw, nh, True)
            baos = BAOS()
            bitmap.compress(BitmapCF.JPEG, 95, baos)
            result = bytes(bytearray(baos.toByteArray()))
            baos.close()
            return result
        except:
            return img_bytes

    def _handle_selected_images(self, images_bytes_list):
        """Handle one or more selected images."""
        if not self.pick_image_for:
            return
        tt, td = self.pick_image_for
        self.pick_image_for = None

        # Resize all images for performance
        images_bytes_list = [self._resize_image(b) for b in images_bytes_list]

        if tt in ("add_phone_screen", "add_spare_screen"):
            # For add/edit screens, use first image only
            sn = "add_phone" if tt == "add_phone_screen" else "add_spare"
            self.root.get_screen(sn).on_image_selected(images_bytes_list[0])

        elif tt == "phone_direct":
            # Set first image as main phone image
            self.db.update_phone(td, image_data=images_bytes_list[0])
            clear_item_cache(f"p_{td}", get_app_path())
            new_img = get_img_path_for_phone(td, self.db)
            d = self.root.get_screen("phone_detail")
            d.ids.detail_img.source = new_img
            d.ids.detail_img.reload()
            self.root.get_screen("main")._data_loaded = False
            self.show_toast("Image saved!")

        elif tt == "phone_gallery":
            # Add ALL images to phone gallery DB table
            count = 0
            for img_bytes in images_bytes_list:
                try:
                    self.db.add_gallery_image(td, img_bytes)
                    count += 1
                except Exception as e:
                    self.show_toast(f"Gallery save err: {str(e)[:40]}")
            self.show_toast(f"Added {count} gallery images!")
            # Refresh gallery on detail screen
            d = self.root.get_screen("phone_detail")
            Clock.schedule_once(lambda dt: d._load_gallery(), 0.2)

        elif tt == "spare_direct":
            self.db.update_spare_part(td, image_data=images_bytes_list[0])
            clear_item_cache(f"s_{td}", get_app_path())
            new_img = get_img_path_for_spare(td, self.db)
            d = self.root.get_screen("spare_detail")
            d.ids.detail_img.source = new_img
            d.ids.detail_img.reload()
            self.root.get_screen("main")._data_loaded = False
            self.show_toast("Image saved!")

        elif tt == "spare_gallery":
            count = 0
            for img_bytes in images_bytes_list:
                try:
                    self.db.add_spare_gallery_image(td, img_bytes)
                    count += 1
                except: pass
            self.show_toast(f"Added {count} images!")
            d = self.root.get_screen("spare_detail")
            Clock.schedule_once(lambda dt: d._load_gallery(), 0.2)

        elif tt == "general_gallery":
            count = 0
            for img_bytes in images_bytes_list:
                try:
                    self.db.add_general_gallery(img_bytes)
                    count += 1
                except: pass
            self.show_toast(f"Added {count} photos!")
            d = self.root.get_screen("photo_gallery")
            Clock.schedule_once(lambda dt: d._load(), 0.2)

        elif tt == "restore_backup":
            pass  # Handled in _fsel

    def _fsel(self, sel, popup=None):
        """Desktop file selection handler + restore backup."""
        if popup: popup.dismiss()
        if not sel or not self.pick_image_for: return
        tt, td = self.pick_image_for

        if tt == "restore_backup":
            self.pick_image_for = None
            self.root.get_screen("backup").on_backup_selected(sel[0])
            return

        # Desktop: read bytes from all selected files
        all_bytes = []
        for path in sel:
            data = smart_read(path)
            if data and len(data) > 100:
                all_bytes.append(data)
        if all_bytes:
            self._handle_selected_images(all_bytes)
        else:
            self.show_toast("Could not read file")

    def on_stop(self):
        if self.db:
            try: self.db.close()
            except: pass


if __name__ == "__main__":
    NokiaStorageApp().run()
