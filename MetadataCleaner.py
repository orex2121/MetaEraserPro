import sys
import os
import struct
import json
import re
import ctypes
import datetime
from fractions import Fraction
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QTextEdit, 
                             QFileDialog, QCheckBox, QGroupBox, QProgressBar,
                             QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PIL import Image, PngImagePlugin
from mutagen import File as MutagenFile
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.id3 import ID3, COMM
from mutagen.mp3 import MP3
from pillow_heif import register_heif_opener

# Регистрация поддержки HEIC
register_heif_opener()

# ФУНКЦИЯ ДЛЯ ПРАВИЛЬНЫХ ПУТЕЙ В EXE
def resource_path(relative_path):
    """ Получает путь к файлам внутри скомпилированного EXE или в папке разработки """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class BatchProcessor(QThread):
    """Поток для пакетной обработки файлов"""
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(bool, list)
    log = pyqtSignal(str)
    
    def __init__(self, files, clean_mode=True, add_workflow_json=None):
        super().__init__()
        self.files = files
        self.clean_mode = clean_mode
        self.add_workflow_json = add_workflow_json
        self.errors = []
        
    def clean_single_file(self, file_path):
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.tiff', '.heic']:
                with Image.open(file_path) as img:
                    clean = Image.new(img.mode, img.size)
                    clean.putdata(list(img.getdata()))
                    clean.save(file_path, optimize=True)
            elif ext in ['.mp3', '.mp4', '.m4a', '.wav', '.flac', '.mov']:
                media = MutagenFile(file_path)
                if media:
                    media.delete()
                    media.save()
            return True, None
        except Exception as e:
            return False, str(e)
    
    def add_workflow_to_file(self, file_path, workflow_str):
        try:
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext == '.png':
                with Image.open(file_path) as img:
                    info = PngImagePlugin.PngInfo()
                    info.add_text("prompt", workflow_str)
                    info.add_text("workflow", workflow_str)
                    img.save(file_path, pnginfo=info)
            
            elif ext in ['.jpg', '.jpeg', '.webp', '.heic']:
                with Image.open(file_path) as img:
                    exif = img.getexif()
                    exif[0x9286] = workflow_str
                    img.save(file_path, exif=exif)
            
            elif ext in ['.mp4', '.m4v', '.mov']:
                video = MP4(file_path)
                video["\xa9cmt"] = [workflow_str]
                workflow_bytes = workflow_str.encode('utf-8')
                video["----:com.apple.iTunes:prompt"] = [workflow_bytes]
                video["----:com.apple.iTunes:workflow"] = [workflow_bytes]
                video.save()
            
            elif ext == '.mp3':
                try:
                    audio = ID3(file_path)
                except:
                    audio = ID3()
                audio.add(COMM(encoding=3, lang='eng', desc='workflow', text=workflow_str))
                audio.save(file_path)
            
            elif ext == '.wav':
                media = MutagenFile(file_path)
                if media:
                    media['prompt'] = workflow_str
                    media['workflow'] = workflow_str
                    media.save()
            
            else:
                media = MutagenFile(file_path)
                if media:
                    media['comment'] = workflow_str
                    media['prompt'] = workflow_str
                    media['workflow'] = workflow_str
                    media.save()
            
            return True, None
        except Exception as e:
            return False, str(e)
    
    def run(self):
        total = len(self.files)
        
        if self.add_workflow_json:
            with open(self.add_workflow_json, 'r', encoding='utf-8') as f:
                workflow_raw = json.load(f)
                workflow_str = json.dumps(workflow_raw, ensure_ascii=False, separators=(',', ':'))
        
        for i, file_path in enumerate(self.files):
            self.progress.emit(i + 1, total, os.path.basename(file_path))
            
            if self.clean_mode:
                success, error = self.clean_single_file(file_path)
                if not success:
                    self.errors.append(f"{file_path}: {error}")
                    self.log.emit(f"❌ Ошибка очистки: {os.path.basename(file_path)} - {error}")
                else:
                    self.log.emit(f"✅ Очищен: {os.path.basename(file_path)}")
            
            if self.add_workflow_json:
                success, error = self.add_workflow_to_file(file_path, workflow_str)
                if not success:
                    self.errors.append(f"{file_path} (workflow): {error}")
                    self.log.emit(f"❌ Ошибка добавления workflow: {os.path.basename(file_path)} - {error}")
                else:
                    self.log.emit(f"🚀 Workflow добавлен: {os.path.basename(file_path)}")
        
        self.finished.emit(len(self.errors) == 0, self.errors)

class MetaEraserApp(QMainWindow):
    # Словарь для преобразования EXIF-кодов в читаемые названия с эмодзи
    EXIF_NAMES = {
        271: "📱 Модель камеры",
        272: "📷 Устройство",
        305: "🔧 Версия ПО",
        306: "📅 Дата съёмки",
        316: "🏷️ Название устройства",
        34665: "📋 Exif блок (служебный)",
        256: "📐 Ширина",
        257: "📐 Высота",
        258: "🎨 Глубина цвета",
        259: "🗜️ Сжатие",
        262: "🎨 Цветовая модель",
        274: "🔄 Ориентация",
        277: "📊 Количество компонентов",
        282: "📏 X-разрешение",
        283: "📏 Y-разрешение",
        284: "⚙️ Единица разрешения",
        296: "📏 Разрешение",
        33434: "⏱️ Выдержка",
        33437: "🔆 Диафрагма",
        34850: "🔍 Фокусное расстояние",
        34855: "🔆 ISO",
        34856: "🔭 Цифровой зум",
        36864: "🔧 EXIF версия",
        36867: "📅 Дата/Время оригинала",
        36868: "📅 Дата/Время цифрования",
        37121: "📦 Компоненты",
        37377: "⏱️ Скорость затвора",
        37378: "🔆 Диафрагма",
        37379: "🔆 Максимальная диафрагма",
        37380: "📏 Выдержка",
        37381: "🔆 Яркость",
        37382: "📏 Фокусное расстояние",
        37383: "🔍 Экспозиция",
        37384: "🎨 Программа экспозиции",
        37385: "🎨 Режим экспозиции",
        37386: "🎨 Баланс белого",
        41483: "🔍 Фокусное расстояние (35mm экв.)",
        41486: "🔍 Режим съёмки",
        41487: "🔍 Тип сцены",
        41488: "🔍 Режим баланса белого",
        41495: "🔍 Длина волны",
        0x829A: "⏱️ Выдержка",
        0x829D: "🔆 F-число",
        0x8822: "🔆 ISO",
        0x9201: "⏱️ Выдержка",
        0x9202: "🔆 Диафрагма",
        0x9204: "🔆 Экспозиция",
        0x9205: "🔆 ISO",
        0x9207: "🔍 Фокусное расстояние",
        0x9208: "🔆 Яркость",
        0x9209: "🔆 Экспозиция",
        0x920A: "🔍 Фокусное расстояние",
        0x927C: "📝 Комментарий",
        0x9286: "📝 Пользовательский комментарий",
        0xA000: "🎨 Цветовое пространство",
        0xA001: "🎨 Цветовое пространство (sRGB)",
        0xA002: "📏 Эффективная ширина",
        0xA003: "📏 Эффективная высота",
        0xA20E: "🔍 Фокусное расстояние (35mm)",
        0xA210: "🔍 Режим съёмки",
        0xA300: "🔍 Тип сцены",
        0xA401: "🔍 Режим баланса белого",
        0xA402: "🔍 Длина волны",
        0xA405: "🔍 Фокусное расстояние",
        0xA406: "🔍 Режим съёмки",
        0xA408: "🔍 Режим баланса белого",
        41728: "📁 Имя файла",
        41729: "🖼️ Миниатюра",
        41985: "🔧 Совместимость",
        41986: "🔧 Информация о камере",
        41987: "🔧 Информация о фото",
        41988: "🔧 Информация о пользователе",
        41989: "🔧 Информация об объективе",
        41990: "🔧 Информация о вспышке",
        0x010F: "🏷️ Производитель",
        0x0110: "📱 Модель",
        0x0112: "🔄 Ориентация",
        0x011A: "📏 X-разрешение",
        0x011B: "📏 Y-разрешение",
        0x0128: "🎨 Цветовое пространство",
        0x0131: "🔧 ПО",
        0x0132: "📅 Дата",
        0x013E: "📏 Макс диафрагма",
        0x9000: "🔧 EXIF версия",
        0x9003: "📅 Дата оригинала",
        0x9004: "📅 Дата цифрования",
        0x9101: "📦 Компоненты",
        0x9102: "📏 Сжатие",
    }
    
    def __init__(self):
        super().__init__()
        self.file_path = None
        self.file_list = []
        self.metadata_store = {
            "useful": [],
            "all": []
        }
        self.batch_processor = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("MetaEraser Pro - Пакетная обработка + HEIC | StableDif.ru")
        self.setMinimumSize(1000, 850)
        self.setStyleSheet("background-color: #0b0b0d; color: #e0e0e6; font-family: 'Segoe UI';")

        icon_path = resource_path("logo.ico")
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            self.setWindowIcon(app_icon)
            if os.name == 'nt':
                myappid = 'stabledif.ru.metaeraser.pro.v2'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(30, 30, 30, 30)

        # Хедер
        header = QHBoxLayout()
        title = QLabel("🛡️ META ERASER PRO [HEIC + Пакетная] | stabledif.ru")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #6c8aff;")
        header.addWidget(title)
        header.addStretch()
        main_layout.addLayout(header)

        # Фильтры
        filter_group = QGroupBox("ФИЛЬТРЫ ОТОБРАЖЕНИЯ")
        filter_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #2d2d35;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                color: #6c8aff;
            }
        """)
        filter_layout = QHBoxLayout()
        
        self.filters = {
            "useful": QCheckBox("Текст и Модели (AI Prompts / Media Tags)"),
            "all": QCheckBox("Все RAW данные")
        }

        self.filters["useful"].setChecked(True)
        self.filters["useful"].clicked.connect(lambda: self.switch_filter("useful"))
        self.filters["all"].clicked.connect(lambda: self.switch_filter("all"))

        for cb in self.filters.values():
            cb.setStyleSheet("QCheckBox { margin-right: 25px; color: #c3e88d; font-size: 14px; }")
            filter_layout.addWidget(cb)
        
        filter_group.setLayout(filter_layout)
        main_layout.addWidget(filter_group)

        # Пакетная обработка
        batch_group = QGroupBox("ПАКЕТНАЯ ОБРАБОТКА")
        batch_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #2d2d35;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                color: #6c8aff;
            }
        """)
        
        batch_layout = QVBoxLayout()
        batch_buttons = QHBoxLayout()
        
        self.btn_select_folder = QPushButton("📁 ВЫБРАТЬ ПАПКУ")
        self.btn_select_files = QPushButton("📄 ВЫБРАТЬ ФАЙЛЫ")
        self.btn_clear_list = QPushButton("🗑️ ОЧИСТИТЬ СПИСОК")
        
        for btn in [self.btn_select_folder, self.btn_select_files, self.btn_clear_list]:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1a1a1f;
                    border: 1px solid #2d2d35;
                    border-radius: 8px;
                    color: white;
                    padding: 8px 15px;
                    font-weight: bold;
                }
                QPushButton:hover { border-color: #6c8aff; background-color: #25252b; }
            """)
        
        self.btn_select_folder.clicked.connect(self.select_folder)
        self.btn_select_files.clicked.connect(self.select_multiple_files)
        self.btn_clear_list.clicked.connect(self.clear_file_list)
        
        batch_buttons.addWidget(self.btn_select_folder)
        batch_buttons.addWidget(self.btn_select_files)
        batch_buttons.addWidget(self.btn_clear_list)
        batch_buttons.addStretch()
        
        self.file_list_widget = QTextEdit()
        self.file_list_widget.setReadOnly(True)
        self.file_list_widget.setMaximumHeight(150)
        self.file_list_widget.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d12;
                border: 1px solid #1f1f26;
                border-radius: 8px;
                color: #d0d0d5;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                padding: 10px;
            }
        """)
        self.file_list_widget.setPlaceholderText("Выберите файлы или папку для пакетной обработки...")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #2d2d35;
                border-radius: 5px;
                text-align: center;
                background-color: #0d0d12;
            }
            QProgressBar::chunk {
                background-color: #6c8aff;
                border-radius: 5px;
            }
        """)
        self.progress_bar.setVisible(False)
        
        batch_layout.addLayout(batch_buttons)
        batch_layout.addWidget(self.file_list_widget)
        batch_layout.addWidget(self.progress_bar)
        batch_group.setLayout(batch_layout)
        main_layout.addWidget(batch_group)

        # Текстовое поле
        self.info_box = QTextEdit()
        self.info_box.setReadOnly(True)
        self.info_box.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d12;
                border: 1px solid #1f1f26;
                border-radius: 10px;
                color: #d0d0d5;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px;
                padding: 20px;
            }
        """)
        main_layout.addWidget(self.info_box)

        # Кнопки действий
        btn_layout = QHBoxLayout()
        
        self.btn_select = QPushButton("ВЫБРАТЬ ФАЙЛ")
        self.btn_select.clicked.connect(self.open_file_dialog)
        
        self.btn_batch_clean = QPushButton("🧹 ПАКЕТНАЯ СТЕРИЛИЗАЦИЯ")
        self.btn_batch_clean.setEnabled(False)
        self.btn_batch_clean.clicked.connect(self.batch_clean)
        
        self.btn_batch_workflow = QPushButton("⚙️ ПАКЕТНЫЙ ADD WORKFLOW")
        self.btn_batch_workflow.setEnabled(False)
        self.btn_batch_workflow.clicked.connect(self.batch_add_workflow)
        
        self.btn_clean = QPushButton("СТЕРИЛИЗАЦИЯ (текущий)")
        self.btn_clean.setEnabled(False)
        self.btn_clean.clicked.connect(self.clean_file)
        
        self.btn_add_workflow = QPushButton("ADD WORKFLOW (текущий)")
        self.btn_add_workflow.setEnabled(False)
        self.btn_add_workflow.clicked.connect(self.add_workflow)
        
        self.btn_export_json = QPushButton("💾 ЭКСПОРТ JSON")
        self.btn_export_json.setEnabled(False)
        self.btn_export_json.clicked.connect(self.export_metadata_to_json)

        for btn in [self.btn_select, self.btn_clean, self.btn_add_workflow, 
                   self.btn_batch_clean, self.btn_batch_workflow, self.btn_export_json]:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            style = """
                QPushButton {
                    background-color: #1a1a1f;
                    border: 1px solid #2d2d35;
                    border-radius: 8px;
                    color: white;
                    padding: 15px 25px;
                    font-weight: bold;
                }
                QPushButton:hover { border-color: #6c8aff; background-color: #25252b; }
                QPushButton:disabled { color: #3f3f4a; border-color: #1a1a1f; }
            """
            if btn == self.btn_add_workflow or btn == self.btn_batch_workflow:
                style = style.replace("#6c8aff", "#bb9af7")
            if btn == self.btn_export_json:
                style = style.replace("#6c8aff", "#9ece6a")
            btn.setStyleSheet(style)
        
        btn_layout.addWidget(self.btn_select)
        btn_layout.addWidget(self.btn_clean)
        btn_layout.addWidget(self.btn_add_workflow)
        btn_layout.addWidget(self.btn_batch_clean)
        btn_layout.addWidget(self.btn_batch_workflow)
        btn_layout.addWidget(self.btn_export_json)
        main_layout.addLayout(btn_layout)

        self.setAcceptDrops(True)

    # ========== ПАКЕТНАЯ ОБРАБОТКА ==========
    def get_supported_files(self, folder_path):
        supported_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.tiff', '.heic',
                               '.mp3', '.mp4', '.m4a', '.wav', '.flac', '.mov', '.m4v'}
        files = []
        for root, dirs, filenames in os.walk(folder_path):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in supported_extensions:
                    files.append(os.path.join(root, filename))
        return files
    
    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с медиафайлами")
        if folder:
            files = self.get_supported_files(folder)
            if files:
                self.file_list = files
                self.update_file_list_display()
                self.btn_batch_clean.setEnabled(True)
                self.btn_batch_workflow.setEnabled(True)
                self.info_box.append(f"<br><b style='color: #9ece6a;'>📁 Добавлено {len(files)} файлов из папки: {folder}</b>")
                if len(files) == 1:
                    self.load_metadata(files[0])
                else:
                    self.file_path = None
                    self.metadata_store = {"useful": [], "all": []}
                    self.update_display()
                    self.btn_clean.setEnabled(False)
                    self.btn_add_workflow.setEnabled(False)
                    self.btn_export_json.setEnabled(False)
            else:
                QMessageBox.warning(self, "Предупреждение", "В выбранной папке нет поддерживаемых файлов!")
    
    def select_multiple_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Выберите медиафайлы", "", 
                                                "Media Files (*.png *.jpg *.jpeg *.webp *.tiff *.heic *.mp3 *.mp4 *.m4a *.wav *.flac *.mov *.m4v)")
        if files:
            self.file_list.extend(files)
            self.update_file_list_display()
            self.btn_batch_clean.setEnabled(True)
            self.btn_batch_workflow.setEnabled(True)
            self.info_box.append(f"<br><b style='color: #9ece6a;'>📄 Добавлено {len(files)} файлов</b>")
            if len(self.file_list) == 1:
                self.load_metadata(self.file_list[0])
            else:
                self.file_path = None
                self.metadata_store = {"useful": [], "all": []}
                self.update_display()
                self.btn_clean.setEnabled(False)
                self.btn_add_workflow.setEnabled(False)
                self.btn_export_json.setEnabled(False)
    
    def clear_file_list(self):
        self.file_list = []
        self.update_file_list_display()
        self.btn_batch_clean.setEnabled(False)
        self.btn_batch_workflow.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.info_box.append("<br><b style='color: #f7768e;'>🗑️ Список файлов очищен</b>")
        self.file_path = None
        self.metadata_store = {"useful": [], "all": []}
        self.update_display()
        self.btn_clean.setEnabled(False)
        self.btn_add_workflow.setEnabled(False)
        self.btn_export_json.setEnabled(False)
    
    def update_file_list_display(self):
        if not self.file_list:
            self.file_list_widget.clear()
            self.file_list_widget.setPlaceholderText("Выберите файлы или папку для пакетной обработки...")
            return
        display_text = f"📋 ВСЕГО ФАЙЛОВ: {len(self.file_list)}\n\n"
        for i, file in enumerate(self.file_list[:20], 1):
            display_text += f"{i}. {os.path.basename(file)}\n"
        if len(self.file_list) > 20:
            display_text += f"\n... и еще {len(self.file_list) - 20} файлов"
        self.file_list_widget.setText(display_text)
    
    def batch_clean(self):
        if not self.file_list:
            QMessageBox.warning(self, "Предупреждение", "Нет файлов для обработки!")
            return
        reply = QMessageBox.question(self, "Подтверждение", 
                                    f"Вы уверены, что хотите удалить метаданные из {len(self.file_list)} файлов?\n\nЭто действие необратимо!",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.start_batch_processing(clean_mode=True, add_workflow_json=None)
    
    def batch_add_workflow(self):
        if not self.file_list:
            QMessageBox.warning(self, "Предупреждение", "Нет файлов для обработки!")
            return
        json_path, _ = QFileDialog.getOpenFileName(self, "Выбрать Workflow JSON для всех файлов", "", "JSON Files (*.json)")
        if not json_path:
            return
        reply = QMessageBox.question(self, "Подтверждение", 
                                    f"Вы уверены, что хотите добавить workflow в {len(self.file_list)} файлов?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.start_batch_processing(clean_mode=False, add_workflow_json=json_path)
    
    def start_batch_processing(self, clean_mode=True, add_workflow_json=None):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.btn_batch_clean.setEnabled(False)
        self.btn_batch_workflow.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_clean.setEnabled(False)
        self.btn_add_workflow.setEnabled(False)
        self.btn_export_json.setEnabled(False)
        
        self.info_box.clear()
        self.info_box.append("<b style='color: #6c8aff;'>🚀 Начинаем пакетную обработку...</b><br>")
        
        self.batch_processor = BatchProcessor(self.file_list, clean_mode, add_workflow_json)
        self.batch_processor.progress.connect(self.update_batch_progress)
        self.batch_processor.log.connect(self.append_batch_log)
        self.batch_processor.finished.connect(self.batch_processing_finished)
        self.batch_processor.start()
    
    def update_batch_progress(self, current, total, filename):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"Обработка: {current}/{total} - {filename}")
    
    def append_batch_log(self, message):
        self.info_box.append(message)
        scrollbar = self.info_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def batch_processing_finished(self, success, errors):
        self.progress_bar.setVisible(False)
        self.btn_batch_clean.setEnabled(True)
        self.btn_batch_workflow.setEnabled(True)
        self.btn_select.setEnabled(True)
        
        if success:
            self.info_box.append("<br><b style='color: #9ece6a;'>✅ ПАКЕТНАЯ ОБРАБОТКА УСПЕШНО ЗАВЕРШЕНА!</b>")
            if self.file_list and len(self.file_list) == 1:
                self.load_metadata(self.file_list[0])
        else:
            self.info_box.append(f"<br><b style='color: #f7768e;'>⚠️ ОБРАБОТКА ЗАВЕРШЕНА С ОШИБКАМИ ({len(errors)})</b>")
            for error in errors[:10]:
                self.info_box.append(f"<span style='color: #f7768e;'>❌ {error}</span>")
            if len(errors) > 10:
                self.info_box.append(f"<span style='color: #f7768e;'>... и еще {len(errors) - 10} ошибок</span>")
        
        self.batch_processor = None

    # ========== GPS И EXIF (ВАШ КОД) ==========
    def extract_gps_from_exif(self, exif_data):
        """ Извлекает GPS из EXIF с правильной обработкой через get_ifd """
        try:
            gps_ifd = exif_data.get_ifd(0x8825)
            if not gps_ifd:
                return None
            
            lat_dms = gps_ifd.get(2)
            lat_ref = gps_ifd.get(1)
            lon_dms = gps_ifd.get(4)
            lon_ref = gps_ifd.get(3)
            
            if not (lat_dms and lon_dms and lat_ref and lon_ref):
                return None
            
            lat_dec = self._dms_to_decimal(lat_dms, lat_ref)
            lon_dec = self._dms_to_decimal(lon_dms, lon_ref)
            
            return f"{lat_dec:.6f}°, {lon_dec:.6f}°"
        except Exception as e:
            print(f"GPS EXIF parsing error: {e}")
            return None

    def _dms_to_decimal(self, dms_tuple, ref):
        """ Преобразует (градусы, минуты, секунды) в десятичные градусы """
        try:
            degrees = float(Fraction(dms_tuple[0]))
            minutes = float(Fraction(dms_tuple[1]))
            seconds = float(Fraction(dms_tuple[2]))
            decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
            if ref in ('S', 'W'):
                decimal = -decimal
            return decimal
        except:
            return 0.0

    def extract_gps_from_xmp(self, xmp_data):
        """ Извлекает GPS из XMP (резервный метод) """
        if not xmp_data or not isinstance(xmp_data, str):
            return None
        
        try:
            lat_match = re.search(r'<exif:GPSLatitude>(.*?)</exif:GPSLatitude>', xmp_data, re.DOTALL)
            lon_match = re.search(r'<exif:GPSLongitude>(.*?)</exif:GPSLongitude>', xmp_data, re.DOTALL)
            
            if lat_match and lon_match:
                try:
                    lat = float(lat_match.group(1).strip())
                    lon = float(lon_match.group(1).strip())
                    return f"{lat:.6f}°, {lon:.6f}°"
                except:
                    return f"{lat_match.group(1).strip()}°, {lon_match.group(1).strip()}°"
            return None
        except Exception as e:
            print(f"XMP GPS parsing error: {e}")
            return None

    def format_photographic_value(self, key, value):
        """ Форматирует фотографические параметры для красивого отображения """
        if key in [33434, 0x829A, 0x9201]:
            if isinstance(value, tuple) and len(value) == 2:
                if value[1] > 0:
                    return f"{value[0]}/{value[1]} сек"
            elif isinstance(value, (int, float)):
                if value < 1:
                    return f"1/{int(1/value)} сек"
                else:
                    return f"{value} сек"
            return str(value)
        
        if key in [33437, 0x829D, 0x9202, 37378]:
            if isinstance(value, (int, float)):
                return f"f/{value:.2f}"
            return f"f/{value}"
        
        if key in [34855, 0x8822, 0x9205]:
            return f"ISO {value}"
        
        if key in [34850, 37386, 0x920A, 0x9207]:
            return f"{value} мм"
        
        return None

    # ========== ЭКСПОРТ JSON ==========
    def export_metadata_to_json(self):
        """Экспорт метаданных текущего файла в JSON"""
        if not self.file_path:
            QMessageBox.warning(self, "Предупреждение", "Нет загруженного файла!")
            return
        
        if not self.metadata_store["all"] and not self.metadata_store["useful"]:
            QMessageBox.warning(self, "Предупреждение", "В файле нет метаданных для экспорта!")
            return
        
        default_name = f"{os.path.splitext(os.path.basename(self.file_path))[0]}_metadata.json"
        save_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Сохранить метаданные в JSON", 
            default_name,
            "JSON Files (*.json)"
        )
        
        if not save_path:
            return
        
        try:
            export_data = {
                "source_file": os.path.basename(self.file_path),
                "source_path": self.file_path,
                "export_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "metadata": {
                    "useful_tags": [],
                    "all_tags": []
                }
            }
            
            for key, value in self.metadata_store["useful"]:
                export_data["metadata"]["useful_tags"].append({
                    "key": str(key),
                    "value": self._serialize_for_json(value)
                })
            
            for key, value in self.metadata_store["all"]:
                export_data["metadata"]["all_tags"].append({
                    "key": str(key),
                    "value": self._serialize_for_json(value)
                })
            
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.info_box.append(f"<br><b style='color: #9ece6a;'>✅ Метаданные экспортированы в: {os.path.basename(save_path)}</b>")
            
            reply = QMessageBox.question(
                self, 
                "Экспорт завершен", 
                f"Файл сохранен как:\n{os.path.basename(save_path)}\n\nОткрыть папку с файлом?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                os.startfile(os.path.dirname(save_path))
                
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить JSON:\n{str(e)}")
            self.info_box.append(f"<br><b style='color: #f7768e;'>❌ Ошибка экспорта: {str(e)}</b>")

    def _serialize_for_json(self, value):
        """Сериализация значений для JSON (обработка bytes, объектов)"""
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8', 'ignore')
            except:
                return str(value)
        elif hasattr(value, 'decode'):
            try:
                return value.decode('utf-8', 'ignore')
            except:
                return str(value)
        elif isinstance(value, (list, tuple)):
            return [self._serialize_for_json(v) for v in value]
        elif isinstance(value, dict):
            return {str(k): self._serialize_for_json(v) for k, v in value.items()}
        else:
            return str(value)

    # ========== ОСНОВНЫЕ МЕТОДЫ ==========
    def switch_filter(self, active):
        for k, cb in self.filters.items():
            cb.setChecked(k == active)
        self.update_display()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            all_files = []
            for file in files:
                if os.path.isdir(file):
                    all_files.extend(self.get_supported_files(file))
                else:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in ['.png', '.jpg', '.jpeg', '.webp', '.tiff', '.heic',
                              '.mp3', '.mp4', '.m4a', '.wav', '.flac', '.mov', '.m4v']:
                        all_files.append(file)
            
            if all_files:
                self.file_list = all_files
                self.update_file_list_display()
                self.btn_batch_clean.setEnabled(True)
                self.btn_batch_workflow.setEnabled(True)
                self.info_box.append(f"<br><b style='color: #9ece6a;'>📥 Перетащено {len(all_files)} элементов</b>")
                
                if len(all_files) == 1:
                    self.load_metadata(all_files[0])
                    self.info_box.append(f"<b style='color: #7aa2f7;'>🔍 Загружен для просмотра: {os.path.basename(all_files[0])}</b>")
                else:
                    self.file_path = None
                    self.metadata_store = {"useful": [], "all": []}
                    self.update_display()
                    self.btn_clean.setEnabled(False)
                    self.btn_add_workflow.setEnabled(False)
                    self.btn_export_json.setEnabled(False)
            else:
                if len(files) == 1 and os.path.isfile(files[0]):
                    self.file_list = [files[0]]
                    self.update_file_list_display()
                    self.load_metadata(files[0])
                    self.btn_batch_clean.setEnabled(True)
                    self.btn_batch_workflow.setEnabled(True)

    def open_file_dialog(self):
        file, _ = QFileDialog.getOpenFileName(self, "Открыть медиафайл", "", 
                                              "Media Files (*.png *.jpg *.jpeg *.webp *.tiff *.heic *.mp3 *.mp4 *.m4a *.wav *.flac *.mov *.m4v)")
        if file:
            self.file_list = [file]
            self.update_file_list_display()
            self.load_metadata(file)
            self.btn_batch_clean.setEnabled(True)
            self.btn_batch_workflow.setEnabled(True)

    def deep_extract(self, data):
        text_keys = ['text', 'prompt', 'string', 'widgets_values', 'description', 'comment', 'title', 'caption', 'workflow']
        model_keys = ['model_name', 'unet_name', 'vae_name', 'lora_name', 'checkpoint', 'lora']

        if isinstance(data, dict):
            for k, v in data.items():
                k_low = str(k).lower()
                is_useful = any(tk in k_low for tk in text_keys + model_keys)
                if is_useful and v and str(v).strip() and str(v) != "None":
                    self.metadata_store["useful"].append((str(k), v))
                self.deep_extract(v)
        elif isinstance(data, list):
            for item in data:
                self.deep_extract(item)

    def process_and_classify(self, key, val):
        if isinstance(val, (list, tuple)):
            decoded_val = " ".join([str(v) for v in val])
        else:
            decoded_val = str(val)

        if decoded_val.startswith("b'") or decoded_val.startswith('b"'):
            try:
                decoded_val = eval(decoded_val).decode('utf-8', 'ignore')
            except:
                decoded_val = decoded_val[2:-1]

        self.metadata_store["all"].append((str(key), decoded_val))

        try:
            if decoded_val.strip().startswith('{') or decoded_val.strip().startswith('['):
                parsed = json.loads(decoded_val)
                self.deep_extract(parsed)
            else:
                k_l = str(key).lower()
                useful_keywords = [
                    'text', 'prompt', 'workflow', 'model', 'lora', 'unet', 'vae', 
                    'comment', 'description', 'artist', 'title', 'comm', '\xa9cmt', 'desc',
                    'модель', 'устройство', 'дата', 'камера', 'объектив', 'gps',
                    'выдержка', 'iso', 'диафрагма', 'фокусное', 'координаты'
                ]
                if any(uk in k_l for uk in useful_keywords):
                    self.metadata_store["useful"].append((str(key), decoded_val))
        except: 
            pass

    def format_value_html(self, val):
        if isinstance(val, (dict, list)):
            text = json.dumps(val, indent=4, ensure_ascii=False)
        else:
            raw_str = str(val)
            if raw_str.strip().startswith('{') or raw_str.strip().startswith('['):
                try:
                    parsed = json.loads(raw_str)
                    text = json.dumps(parsed, indent=4, ensure_ascii=False)
                except:
                    text = raw_str
            else:
                text = raw_str
        
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        if "{" in text or "[" in text:
            lines = []
            for line in text.split('\n'):
                line = re.sub(r'(".*?")\s*:', r'<span style="color: #ff9e64; font-weight: bold;">\1</span>:', line)
                line = re.sub(r':\s*(".*?")', r': <span style="color: #9ece6a;">\1</span>', line)
                line = re.sub(r':\s*(\d+|true|false|null)', r': <span style="color: #bb9af7;">\1</span>', line)
                lines.append(line)
            return f'<div style="white-space: pre-wrap; margin-left: 15px; margin-bottom: 10px;">{"<br>".join(lines)}</div>'
        
        return f'<div style="white-space: pre-wrap; margin-left: 15px; margin-bottom: 10px; color: #9ece6a;">{text}</div>'

    def read_png_metadata(self, path):
        results = []
        try:
            with open(path, 'rb') as f:
                if f.read(8) != b'\x89PNG\r\n\x1a\n':
                    return []
                while True:
                    chunk_hdr = f.read(8)
                    if len(chunk_hdr) < 8:
                        break
                    length, char_type = struct.unpack('>I4s', chunk_hdr)
                    data = f.read(length)
                    f.read(4)
                    if char_type in [b'tEXt', b'iTXt']:
                        try:
                            parts = data.split(b'\0', 1)
                            if len(parts) == 2:
                                key = parts[0].decode('latin-1')
                                if char_type == b'iTXt':
                                    sub_parts = parts[1].split(b'\0', 4)
                                    val = sub_parts[4].decode('utf-8', 'ignore')
                                else:
                                    val = parts[1].decode('utf-8', 'ignore')
                                results.append((key, val))
                        except:
                            pass
                    if char_type == b'IEND':
                        break
        except:
            pass
        return results

    def load_metadata(self, path):
        self.file_path = path
        self.metadata_store = {"useful": [], "all": []}
        ext = os.path.splitext(path)[1].lower()
        
        try:
            raw_data = []
            
            if ext == '.png':
                raw_data.extend(self.read_png_metadata(path))
            
            # HEIC через Pillow (ВАШ КОД)
            elif ext == '.heic':
                with Image.open(path) as img:
                    exif_data = img.getexif()
                    gps_coords = None
                    
                    if exif_data:
                        gps_coords = self.extract_gps_from_exif(exif_data)
                    
                    if not gps_coords and 'xmp' in img.info:
                        gps_coords = self.extract_gps_from_xmp(img.info['xmp'])
                    
                    if exif_data:
                        for key, value in exif_data.items():
                            if key in [34665, 34853]:
                                continue
                            friendly_name = self.EXIF_NAMES.get(key, f"EXIF_{key}")
                            formatted = self.format_photographic_value(key, value)
                            if formatted:
                                raw_data.append((friendly_name, formatted))
                            else:
                                raw_data.append((friendly_name, value))
                    
                    for key, value in img.info.items():
                        if value and str(value).strip():
                            if key not in ['exif', 'icc_profile']:
                                raw_data.append((key, value))
                    
                    if gps_coords:
                        raw_data.append(("📍 GPS координаты", gps_coords))
            
            else:
                media = MutagenFile(path)
                if media:
                    for key in media.keys():
                        raw_data.append((key, media[key]))

            for k, v in raw_data:
                self.process_and_classify(k, v)
            
            final_useful = []
            seen = set()
            for k, v in self.metadata_store["useful"]:
                uid = (k, str(v))
                if uid not in seen:
                    seen.add(uid)
                    final_useful.append((k, v))
            self.metadata_store["useful"] = final_useful

            self.update_display()
            self.btn_clean.setEnabled(True)
            self.btn_add_workflow.setEnabled(True)
            self.btn_export_json.setEnabled(True)
        except Exception as e:
            self.info_box.setHtml(f"<b style='color: #f7768e;'>ОШИБКА ЧТЕНИЯ: {str(e)}</b>")

    def update_display(self):
        if not self.file_path:
            self.info_box.setHtml("<div style='color: #565f89; text-align: center; margin-top: 50px;'>📁 НЕТ ВЫБРАННОГО ФАЙЛА ДЛЯ ПРОСМОТРА<br><br>Выберите файл кнопкой выше или перетащите его в окно</div>")
            return
        
        html = f"<h2 style='color: #7aa2f7;'>ФАЙЛ: {os.path.basename(self.file_path)}</h2><hr color='#1f1f26'>"
        
        if self.filters["useful"].isChecked():
            html += self.render_section("useful", "AI TEXT / MEDIA TAGS", "#e0af68")
        else:
            html += self.render_section("all", "RAW METADATA (ВСЕ ТЕГИ)", "#565f89")
        
        self.info_box.setHtml(html)

    def render_section(self, cat_id, title, color):
        data = self.metadata_store.get(cat_id, [])
        if not data:
            return f"<div style='color: #444; margin-top: 10px;'>Теги не найдены.</div>"
        
        res = f"<div style='background-color: #16161e; padding: 10px; margin-top: 20px; color: {color}; font-weight: bold; border-left: 5px solid {color};'>📁 {title}</div>"
        for k, v in data:
            res += f"<div style='margin-top: 12px; color: #7dcfff; font-size: 11px;'>[ KEY: {k} ]</div>"
            res += self.format_value_html(v)
        return res

    def clean_file(self, silent=False):
        if not self.file_path:
            return False
        try:
            ext = os.path.splitext(self.file_path)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.tiff', '.heic']:
                with Image.open(self.file_path) as img:
                    clean = Image.new(img.mode, img.size)
                    clean.putdata(list(img.getdata()))
                    clean.save(self.file_path, optimize=True)
            elif ext in ['.mp3', '.mp4', '.m4a', '.wav', '.flac', '.mov']:
                media = MutagenFile(self.file_path)
                if media:
                    media.delete()
                    media.save()
            
            if not silent:
                self.info_box.append("<br><b style='color: #9ece6a;'>✅ СТЕРИЛИЗОВАН.</b>")
                self.btn_clean.setEnabled(False)
                self.load_metadata(self.file_path)
            return True
        except Exception as e:
            if not silent:
                self.info_box.append(f"<br><b style='color: #f7768e;'>❌ ОШИБКА: {str(e)}</b>")
            return False

    def add_workflow(self):
        if not self.file_path:
            return
        
        json_path, _ = QFileDialog.getOpenFileName(self, "Выбрать Workflow JSON", "", "JSON Files (*.json)")
        if not json_path:
            return

        try:
            self.clean_file(silent=True)

            with open(json_path, 'r', encoding='utf-8') as f:
                workflow_raw = json.load(f)
                workflow_str = json.dumps(workflow_raw, ensure_ascii=False, separators=(',', ':'))

            ext = os.path.splitext(self.file_path)[1].lower()

            if ext == '.png':
                with Image.open(self.file_path) as img:
                    info = PngImagePlugin.PngInfo()
                    info.add_text("prompt", workflow_str)
                    info.add_text("workflow", workflow_str)
                    img.save(self.file_path, pnginfo=info)
            
            elif ext in ['.jpg', '.jpeg', '.webp', '.heic']:
                with Image.open(self.file_path) as img:
                    exif = img.getexif()
                    exif[0x9286] = workflow_str
                    img.save(self.file_path, exif=exif)

            elif ext in ['.mp4', '.m4v', '.mov']:
                video = MP4(self.file_path)
                video["\xa9cmt"] = [workflow_str]
                workflow_bytes = workflow_str.encode('utf-8')
                video["----:com.apple.iTunes:prompt"] = [workflow_bytes]
                video["----:com.apple.iTunes:workflow"] = [workflow_bytes]
                video.save()

            elif ext == '.mp3':
                try:
                    audio = ID3(self.file_path)
                except:
                    audio = ID3()
                audio.add(COMM(encoding=3, lang='eng', desc='workflow', text=workflow_str))
                audio.save(self.file_path)

            elif ext == '.wav':
                media = MutagenFile(self.file_path)
                if media:
                    media['prompt'] = workflow_str
                    media['workflow'] = workflow_str
                    media.save()

            else:
                media = MutagenFile(self.file_path)
                if media:
                    media['comment'] = workflow_str
                    media['prompt'] = workflow_str
                    media['workflow'] = workflow_str
                    media.save()

            self.info_box.append(f"<br><b style='color: #bb9af7;'>🚀 ПОДГОТОВЛЕНО ДЛЯ COMFYUI: {os.path.basename(json_path)}</b>")
            self.load_metadata(self.file_path)

        except Exception as e:
            self.info_box.append(f"<br><b style='color: #f7768e;'>❌ ОШИБКА ЗАПИСИ: {str(e)}</b>")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MetaEraserApp()
    window.show()
    sys.exit(app.exec())