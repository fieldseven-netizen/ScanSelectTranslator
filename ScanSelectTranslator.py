import os
import sys
import time
import cv2
import mss
import numpy as np
import threading
import json
import ctypes
import psutil
import asyncio
from deep_translator import GoogleTranslator
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                             QHBoxLayout, QWidget, QLabel, QTextEdit, QComboBox, 
                             QTextBrowser)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QTimer, QUrl, QLocale
from PyQt6.QtGui import QFont, QColor, QPainter, QPainterPath, QPen, QImage, QPixmap, QFontMetrics, QGuiApplication, QCursor

import winsdk.windows.media.ocr as ocr
import winsdk.windows.graphics.imaging as imaging
import winsdk.windows.storage.streams as streams
import winsdk.windows.globalization as globalization

# 高優先度設定
try:
    p = psutil.Process(os.getpid())
    p.nice(psutil.HIGH_PRIORITY_CLASS)
except:
    pass

user32 = ctypes.windll.user32
CONFIG_FILE = "config.json"
VERSION = "1.0.0"

class CaptureWorker(QThread):
    """画面キャプチャを担当するスレッド"""
    preview_signal = pyqtSignal(QImage)
    monitor_info_signal = pyqtSignal(dict) 

    def __init__(self):
        super().__init__()
        self.latest_frame = None
        self.lock = threading.Lock()
        with mss.mss() as sct:
            self.monitor_config = sct.monitors[1]

    def get_snapshot(self):
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def capture_once(self):
        with mss.mss() as sct:
            try:
                sct_img = sct.grab(self.monitor_config)
                frame = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
                with self.lock:
                    self.latest_frame = frame
                
                # プレビュー用画像作成
                preview = cv2.resize(frame, (480, 270))
                preview_rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
                h, w, ch = preview_rgb.shape
                q_img = QImage(preview_rgb.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888).copy()
                
                self.preview_signal.emit(q_img)
                self.monitor_info_signal.emit(self.monitor_config)
                return frame
            except:
                return None

    def run(self):
        while True:
            self.msleep(1000)

class TranslationWorker(QThread):
    """OCRおよび翻訳を担当するスレッド"""
    new_text_signal = pyqtSignal(str, str)
    status_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.current_frame = None
        self.overlay_rect = QRect()
        self.lock = threading.Lock()
        self.target_lang = 'ja'
        self.engine = None

    def set_ocr_language(self, lang_tag):
        try:
            lang = globalization.Language(lang_tag)
            self.engine = ocr.OcrEngine.try_create_from_language(lang)
            return True
        except:
            self.engine = ocr.OcrEngine.try_create_from_user_language()
            return False

    def set_target_language(self, lang_code):
        self.target_lang = lang_code

    def request_manual(self, frame):
        with self.lock:
            self.current_frame = frame.copy()

    def update_overlay_rect(self, rect):
        self.overlay_rect = rect

    async def _run_win_ocr(self, frame):
        if not self.engine:
            return "Error: No Engine"
        try:
            bgra = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
            _, buffer = cv2.imencode('.bmp', bgra)
            stream = streams.InMemoryRandomAccessStream()
            writer = streams.DataWriter(stream)
            writer.write_bytes(buffer.tobytes())
            await writer.store_async()
            await writer.flush_async()
            stream.seek(0)
            
            decoder = await imaging.BitmapDecoder.create_async(stream)
            software_bitmap = await decoder.get_software_bitmap_async()
            result = await self.engine.recognize_async(software_bitmap)
            return result.text
        except Exception as e:
            return f"Error: {str(e)}"

    def run(self):
        while True:
            frame = None
            with self.lock:
                if self.current_frame is not None:
                    frame = self.current_frame.copy()
                    self.current_frame = None
            
            if frame is not None:
                self.status_signal.emit("OCR-ing...")
                raw_text = asyncio.run(self._run_win_ocr(frame))
                
                if "Error" in raw_text:
                    self.status_signal.emit(raw_text)
                    continue
                
                raw = raw_text.strip()
                if raw:
                    self.status_signal.emit("Translating...")
                    try:
                        translator = GoogleTranslator(source='auto', target=self.target_lang)
                        res = translator.translate(raw)
                        if res:
                            self.new_text_signal.emit(raw, res.strip())
                            self.status_signal.emit("Done")
                    except:
                        self.status_signal.emit("Translation Error")
                else:
                    self.status_signal.emit("No text detected")
            time.sleep(0.2)

class SelectableLabel(QLabel):
    """プレビュー上での範囲選択を可能にするラベル"""
    roi_selected = pyqtSignal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.origin = QPoint()
        self.current_rect = QRect()
        self.selecting = False
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.origin = e.position().toPoint()
            self.current_rect = QRect(self.origin, self.origin)
            self.selecting = True
            self.update()

    def mouseMoveEvent(self, e):
        if self.selecting:
            self.current_rect = QRect(self.origin, e.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.selecting:
            self.selecting = False
            if self.current_rect.width() > 10 and self.current_rect.height() > 10:
                self.roi_selected.emit(self.current_rect)
            self.current_rect = QRect()
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.selecting:
            painter = QPainter(self)
            painter.setPen(QPen(QColor(0, 255, 0), 2, Qt.PenStyle.SolidLine))
            painter.setBrush(QColor(0, 255, 0, 50))
            painter.drawRect(self.current_rect)

class OverlayLabel(QLabel):
    """縁取り文字を描画するオーバーレイ用ラベル"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.padding = 80
        self.line_spacing = 5
        self.stored_lines = []

    def split_text_smart(self, text, fm, max_w):
        final_lines = []
        for section in text.split('\n'):
            section = section.strip()
            if not section:
                final_lines.append("")
                continue
            while section:
                if fm.horizontalAdvance(section) <= max_w:
                    final_lines.append(section)
                    break
                break_idx = -1
                for i in range(1, len(section) + 1):
                    if fm.horizontalAdvance(section[:i]) > max_w:
                        search_area = section[:i-1]
                        punctuation = "、。！？,.!? 　」』）)]"
                        for j in range(len(search_area)-1, -1, -1):
                            if search_area[j] in punctuation:
                                break_idx = j + 1
                                break
                        if break_idx == -1: break_idx = i - 1
                        break
                if break_idx <= 0: break_idx = 1
                final_lines.append(section[:break_idx].strip())
                section = section[break_idx:].strip()
        return final_lines

    def paintEvent(self, event):
        if not self.text() or not self.stored_lines:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self.font()
        fm = QFontMetrics(font)
        
        line_h = fm.height() + self.line_spacing
        y = (self.height() - (line_h * len(self.stored_lines))) / 2 + fm.ascent()
        
        for line in self.stored_lines:
            if not line:
                y += line_h
                continue
            path = QPainterPath()
            x = (self.width() - fm.horizontalAdvance(line)) / 2
            path.addText(x, y, font, line)
            painter.strokePath(path, QPen(QColor(0, 0, 0), 12))
            painter.fillPath(path, QColor(255, 255, 255))
            y += line_h

class SubtitleOverlay(QWidget):
    """ゲーム画面上に浮かぶ字幕ウィンドウ"""
    pos_signal = pyqtSignal(QRect)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                            Qt.WindowType.WindowStaysOnTopHint | 
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.label = OverlayLabel()
        self.layout.addWidget(self.label)
        
        self.current_font_size = 32
        self.label.setFont(QFont("Meiryo", self.current_font_size, QFont.Weight.Bold))
        
        self.drag_pos = QPoint()
        self.tm = QTimer()
        self.tm.timeout.connect(self.keep_top)
        self.tm.start(1000)
        
        # モニター情報の初期化
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry()
        dpr = screen.devicePixelRatio()
        self.m_config = {
            'left': int(geo.left() * dpr),
            'top': int(geo.top() * dpr),
            'width': int(geo.width() * dpr),
            'height': int(geo.height() * dpr)
        }
        self.set_text("System Active")

    def update_font_size(self, size):
        self.current_font_size = size
        self.label.setFont(QFont("Meiryo", size, QFont.Weight.Bold))
        self.set_text(self.label.text())

    def update_monitor_config(self, config):
        self.m_config = config

    def keep_top(self):
        if not self.isVisible():
            return
        user32.SetWindowPos(int(self.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
        self.pos_signal.emit(self.geometry())

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            new_pos = e.globalPosition().toPoint() - self.drag_pos
            dpr = self.devicePixelRatio()
            l_left, l_top = self.m_config['left'] / dpr, self.m_config['top'] / dpr
            l_width, l_height = self.m_config['width'] / dpr, self.m_config['height'] / dpr
            
            x = max(l_left, min(new_pos.x(), l_left + l_width - self.width()))
            y = max(l_top, min(new_pos.y(), l_top + l_height - self.height()))
            self.move(int(x), int(y))

    def set_text(self, text):
        dpr = self.devicePixelRatio()
        l_left = self.m_config['left'] / dpr
        l_top = self.m_config['top'] / dpr
        l_width = self.m_config['width'] / dpr
        l_height = self.m_config['height'] / dpr
        
        fixed_tw = int(l_width * 0.8)
        fm = QFontMetrics(self.label.font())
        max_text_w = fixed_tw - self.label.padding * 2
        
        self.label.stored_lines = self.label.split_text_smart(text, fm, max_text_w)
        self.label.setText(text)
        th = (fm.height() + self.label.line_spacing) * len(self.label.stored_lines) + 60
        
        # 物理モニターのセンターに配置
        nx = l_left + (l_width / 2) - (fixed_tw / 2)
        ny = l_top + l_height - th - 20
        
        nx = max(l_left, min(nx, l_left + l_width - fixed_tw - 5))
        
        self.setGeometry(int(nx), int(ny), int(fixed_tw), int(th))
        self.label.setFixedWidth(int(fixed_tw))
        self.keep_top()
        self.update()

class LogEdit(QTextBrowser):
    """クリッカブルコピー機能付きのログブラウザ"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMouseTracking(True)
        self.setOpenLinks(False)

    def mouseMoveEvent(self, e):
        anchor = self.anchorAt(e.pos())
        if anchor:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Click to copy")
        else:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
            self.setToolTip("")
        super().mouseMoveEvent(e)

class MainWindow(QMainWindow):
    """メインコントロールパネル"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"ScanSelectTranslator v{VERSION}")
        self.resize(500, 750)
        self.setStyleSheet("background-color: #1e1e1e; color: #ffffff;")
        
        self.log_font_size = 13
        self.log_data = []
        self.auto_show = True
        self.delay_counter = 0
        
        self.init_ui()
        
        self.cap = CaptureWorker()
        self.trans = TranslationWorker()
        self.overlay = SubtitleOverlay()
        
        # 信号接続
        self.cap.preview_signal.connect(self.update_preview)
        self.cap.monitor_info_signal.connect(self.overlay.update_monitor_config)
        self.trans.new_text_signal.connect(self.update_translation)
        self.trans.status_signal.connect(self.update_status)
        self.overlay.pos_signal.connect(self.trans.update_overlay_rect)
        
        self.load_config()
        self.cap.start()
        self.trans.start()
        QTimer.singleShot(500, self.manual_scan)

    def init_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        layout = QVBoxLayout(cw)
        
        # ヘッダー
        hdr = QHBoxLayout()
        layout.addLayout(hdr)
        btn_style = "font-weight: bold; border-radius: 5px; color: white;"
        
        self.btn_s = QPushButton("SCAN")
        self.btn_s.setFixedSize(50, 40)
        self.btn_s.setStyleSheet(f"{btn_style} background-color: #d67a27;")
        self.btn_s.clicked.connect(self.manual_scan)
        hdr.addWidget(self.btn_s)
        
        self.btn_t = QPushButton("T-SCAN")
        self.btn_t.setFixedSize(50, 40)
        self.btn_t.setStyleSheet(f"{btn_style} background-color: #d6b627;")
        self.btn_t.clicked.connect(self.start_delay_scan)
        hdr.addWidget(self.btn_t)
        
        self.btn_as = QPushButton("AS")
        self.btn_as.setFixedSize(35, 40)
        self.btn_as.setStyleSheet(f"{btn_style} background-color: #2d5a27;")
        self.btn_as.clicked.connect(self.toggle_as)
        hdr.addWidget(self.btn_as)
        
        self.btn_ov = QPushButton("OVL")
        self.btn_ov.setFixedSize(45, 40)
        self.btn_ov.setStyleSheet(f"{btn_style} background-color: #274b5a;")
        self.btn_ov.clicked.connect(self.toggle_ov)
        hdr.addWidget(self.btn_ov)
        
        self.combo_ocr = QComboBox()
        self.combo_ocr.setFixedSize(75, 40)
        self.combo_ocr.setStyleSheet("background-color: #333; color: white; border-radius: 5px;")
        for lang in ocr.OcrEngine.available_recognizer_languages:
            self.combo_ocr.addItem(f"{lang.display_name} ({lang.language_tag})")
        self.combo_ocr.currentTextChanged.connect(self.on_ocr_changed)
        hdr.addWidget(self.combo_ocr)
        
        self.combo_to = QComboBox()
        self.combo_to.setFixedSize(50, 40)
        self.combo_to.setStyleSheet("background-color: #333; color: #00ff00; border-radius: 5px;")
        langs = {"JA": "ja", "EN": "en", "ZH": "zh-CN", "KO": "ko", "FR": "fr", "DE": "de", "ES": "es"}
        for k, v in langs.items():
            self.combo_to.addItem(k, v)
        self.combo_to.currentIndexChanged.connect(self.on_target_changed)
        hdr.addWidget(self.combo_to)

        hdr.addStretch()
        
        self.combo_size = QComboBox()
        self.combo_size.setFixedSize(50, 40)
        self.combo_size.addItems(["10","14","18","24","32","42","48"])
        self.combo_size.setStyleSheet("background-color: #444; color: white; border-radius: 5px;")
        self.combo_size.currentTextChanged.connect(self.on_font_size_changed)
        hdr.addWidget(self.combo_size)
        
        # プレビュー
        self.prv_lbl = SelectableLabel()
        self.prv_lbl.setFixedSize(480, 270)
        self.prv_lbl.setStyleSheet("border: 2px solid #444; background: #000;")
        self.prv_lbl.roi_selected.connect(self.process_roi)
        layout.addWidget(self.prv_lbl)
        
        # ログ
        self.log = LogEdit()
        self.log.anchorClicked.connect(self.copy_to_clipboard)
        self.update_log_style()
        layout.addWidget(self.log)
        
        # フッター
        ftr = QHBoxLayout()
        layout.addLayout(ftr)
        ftr.addWidget(QLabel("Log Size:"))
        self.btn_m = QPushButton("－")
        self.btn_m.setFixedSize(25, 25)
        self.btn_m.clicked.connect(lambda: self.change_log_size(-1))
        ftr.addWidget(self.btn_m)
        self.btn_p = QPushButton("＋")
        self.btn_p.setFixedSize(25, 25)
        self.btn_p.clicked.connect(lambda: self.change_log_size(1))
        ftr.addWidget(self.btn_p)
        ftr.addStretch()
        self.status_lbl = QLabel("Status: Idle")
        self.status_lbl.setStyleSheet("color: #888; font-size: 11px;")
        ftr.addWidget(self.status_lbl)

    def load_config(self):
        locale_lang = QLocale.system().name().split('_')[0].lower()
        defaults = {"ocr": "en-US", "target": locale_lang if locale_lang in ["ja", "en", "zh", "ko", "fr", "de", "es"] else "en", "font": "32"}
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    defaults.update(json.load(f))
        except:
            pass
        
        for i in range(self.combo_ocr.count()):
            if defaults["ocr"] in self.combo_ocr.itemText(i):
                self.combo_ocr.setCurrentIndex(i)
                break
        for i in range(self.combo_to.count()):
            if defaults["target"] == self.combo_to.itemData(i):
                self.combo_to.setCurrentIndex(i)
                break
        self.combo_size.setCurrentText(defaults["font"])
        
        self.trans.set_ocr_language(defaults["ocr"])
        self.trans.set_target_language(defaults["target"])
        self.overlay.update_font_size(int(defaults["font"]))

    def save_config(self):
        try:
            config = {
                "ocr": self.combo_ocr.currentText().split('(')[-1].strip(')'),
                "target": self.combo_to.currentData(),
                "font": self.combo_size.currentText()
            }
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f)
        except:
            pass

    def on_ocr_changed(self, text):
        self.trans.set_ocr_language(text.split('(')[-1].strip(')'))
        self.save_config()

    def on_target_changed(self, idx):
        self.trans.set_target_language(self.combo_to.itemData(idx))
        self.save_config()

    def on_font_size_changed(self, text):
        self.overlay.update_font_size(int(text))
        self.save_config()

    def change_log_size(self, d):
        self.log_font_size = max(8, min(30, self.log_font_size + d))
        self.update_log_style()

    def update_log_style(self):
        self.log.setStyleSheet(f"background: #111; color: #aaa; font-family: Consolas; font-size: {self.log_font_size}pt;")

    def copy_to_clipboard(self, url):
        try:
            ctype, idx = url.toString().split(":")
            idx = int(idx)
            text = self.log_data[idx]['jp'] if ctype == "jp" else self.log_data[idx]['en']
            QApplication.clipboard().setText(text)
            self.update_status(f"Copied {ctype.upper()}!")
            QTimer.singleShot(2000, lambda: self.update_status("Idle"))
        except:
            pass

    def manual_scan(self):
        self.cap.capture_once()

    def start_delay_scan(self):
        self.delay_counter = 3
        self.countdown_tick()

    def countdown_tick(self):
        if self.delay_counter > 0:
            self.status_lbl.setText(f"In {self.delay_counter}s...")
            self.delay_counter -= 1
            QTimer.singleShot(1000, self.countdown_tick)
        else:
            self.manual_scan()
            self.status_lbl.setText("Captured!")

    def toggle_as(self):
        self.auto_show = not self.auto_show
        self.btn_as.setText("AS" if self.auto_show else "as")
        self.btn_as.setStyleSheet(f"background-color: {'#2d5a27' if self.auto_show else '#3d3d3d'}; font-weight: bold; border-radius: 5px; color: white;")

    def toggle_ov(self):
        if self.overlay.isVisible():
            self.overlay.hide()
            self.btn_ov.setStyleSheet("background-color: #3d3d3d; font-weight: bold; border-radius: 5px; color: white;")
        else:
            self.overlay.show()
            self.btn_ov.setStyleSheet("background-color: #274b5a; font-weight: bold; border-radius: 5px; color: white;")

    def process_roi(self, rect):
        frame = self.cap.get_snapshot()
        if frame is not None:
            h, w = frame.shape[:2]
            sx, sy = w / 480, h / 270
            roi = frame[int(rect.y()*sy):int(rect.bottom()*sy), int(rect.x()*sx):int(rect.right()*sx)]
            if roi.size > 0:
                self.trans.request_manual(roi)
                self.update_status("Processing...")

    def update_translation(self, en, jp):
        if self.auto_show and not self.overlay.isVisible():
            self.toggle_ov()
        self.overlay.set_text(jp)
        idx = len(self.log_data)
        self.log_data.append({'en': en, 'jp': jp})
        html = f"<a href='jp:{idx}' style='color:white; text-decoration:none;'>{jp}</a><br>"
        html += f"<a href='en:{idx}' style='color:#00ff00; text-decoration:none; font-size: {self.log_font_size-2}pt;'>EN: {en}</a><br>"
        self.log.append(html)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def update_status(self, s):
        self.status_lbl.setText(f"Status: {s}")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.manual_scan()

    def update_preview(self, img):
        self.prv_lbl.setPixmap(QPixmap.fromImage(img).scaled(self.prv_lbl.size(), 
                               Qt.AspectRatioMode.KeepAspectRatio, 
                               Qt.TransformationMode.SmoothTransformation))

if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
