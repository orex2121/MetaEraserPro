import sys
import os
import struct
import json
import re
import ctypes
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QTextEdit, 
                             QFileDialog, QCheckBox, QGroupBox, QProgressBar,
                             QProgressDialog, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PIL import Image, PngImagePlugin
from mutagen import File as MutagenFile
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.id3 import ID3, COMM
from mutagen.mp3 import MP3

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
    progress = pyqtSignal(int, int, str)  # current, total, filename
    finished = pyqtSignal(bool, list)  # success, errors
    log = pyqtSignal(str)
    
    def __init__(self, files, clean_mode=True, add_workflow_json=None):
        super().__init__()
        self.files = files
        self.clean_mode = clean_mode
        self.add_workflow_json = add_workflow_json
        self.errors = []
        
    def clean_single_file(self, file_path):
        """Очистка одного файла"""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.tiff']:
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
        """Добавление workflow в один файл"""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext == '.png':
                with Image.open(file_path) as img:
                    info = PngImagePlugin.PngInfo()
                    info.add_text("prompt", workflow_str)
                    info.add_text("workflow", workflow_str)
                    img.save(file_path, pnginfo=info)
            
            elif ext in ['.jpg', '.jpeg', '.webp']:
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
    def __init__(self):
        super().__init__()
        self.file_path = None
        self.file_list = []  # Список файлов для пакетной обработки
        self.metadata_store = {
            "useful": [],    # Категория: Текст и Модели
            "all": []        # Категория: Все теги
        }
        self.batch_processor = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("MetaEraser Pro - Пакетная обработка | StableDif.ru")
        self.setMinimumSize(1000, 850)
        self.setStyleSheet("background-color: #0b0b0d; color: #e0e0e6; font-family: 'Segoe UI';")

        # Установка иконки
        icon_path = resource_path("logo.ico")
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            self.setWindowIcon(app_icon)
            if os.name == 'nt':
                myappid = 'stabledif.ru.metaeraser.pro.v1'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(30, 30, 30, 30)

        # Хедер приложения
        header = QHBoxLayout()
        title = QLabel("🛡️ META ERASER PRO [Пакетная обработка] | stabledif.ru")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #6c8aff;")
        header.addWidget(title)
        header.addStretch()
        main_layout.addLayout(header)

        # Выбор категорий (фильтры)
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

        # Секция пакетной обработки
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
        
        # Кнопки для пакетной обработки
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
        
        # Список файлов
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
        self.file_list_widget.setPlaceholderText("Выберите файлы или папку для пакетной обработки...\n\nСовет: дважды кликните на файл в списке, чтобы просмотреть его метаданные")
        
        # Прогресс бар
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

        # Текстовое поле вывода
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

        for btn in [self.btn_select, self.btn_clean, self.btn_add_workflow, 
                   self.btn_batch_clean, self.btn_batch_workflow]:
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
            if btn in [self.btn_add_workflow, self.btn_batch_workflow]:
                style = style.replace("#6c8aff", "#bb9af7")
            btn.setStyleSheet(style)
        
        btn_layout.addWidget(self.btn_select)
        btn_layout.addWidget(self.btn_clean)
        btn_layout.addWidget(self.btn_add_workflow)
        btn_layout.addWidget(self.btn_batch_clean)
        btn_layout.addWidget(self.btn_batch_workflow)
        main_layout.addLayout(btn_layout)

        self.setAcceptDrops(True)
    
    def get_supported_files(self, folder_path):
        """Получение всех поддерживаемых файлов из папки и подпапок"""
        supported_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.tiff', 
                               '.mp3', '.mp4', '.m4a', '.wav', '.flac', '.mov', '.m4v'}
        files = []
        for root, dirs, filenames in os.walk(folder_path):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in supported_extensions:
                    files.append(os.path.join(root, filename))
        return files
    
    def select_folder(self):
        """Выбор папки с файлами"""
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с медиафайлами")
        if folder:
            files = self.get_supported_files(folder)
            if files:
                self.file_list = files
                self.update_file_list_display()
                self.btn_batch_clean.setEnabled(True)
                self.btn_batch_workflow.setEnabled(True)
                self.info_box.append(f"<br><b style='color: #9ece6a;'>📁 Добавлено {len(files)} файлов из папки: {folder}</b>")
                
                # Если в папке только один файл, загружаем его для просмотра
                if len(files) == 1:
                    self.load_metadata(files[0])
                else:
                    # Если несколько файлов, очищаем текущий просмотр
                    self.file_path = None
                    self.metadata_store = {"useful": [], "all": []}
                    self.update_display()
                    self.btn_clean.setEnabled(False)
                    self.btn_add_workflow.setEnabled(False)
            else:
                QMessageBox.warning(self, "Предупреждение", "В выбранной папке нет поддерживаемых файлов!")
    
    def select_multiple_files(self):
        """Выбор нескольких файлов"""
        files, _ = QFileDialog.getOpenFileNames(self, "Выберите медиафайлы", "", 
                                                "Media Files (*.png *.jpg *.jpeg *.webp *.tiff *.mp3 *.mp4 *.m4a *.wav *.flac *.mov *.m4v)")
        if files:
            self.file_list.extend(files)
            self.update_file_list_display()
            self.btn_batch_clean.setEnabled(True)
            self.btn_batch_workflow.setEnabled(True)
            self.info_box.append(f"<br><b style='color: #9ece6a;'>📄 Добавлено {len(files)} файлов</b>")
            
            # Если в списке только один файл, загружаем его для просмотра
            if len(self.file_list) == 1:
                self.load_metadata(self.file_list[0])
            else:
                # Если несколько файлов, очищаем текущий просмотр
                self.file_path = None
                self.metadata_store = {"useful": [], "all": []}
                self.update_display()
                self.btn_clean.setEnabled(False)
                self.btn_add_workflow.setEnabled(False)
    
    def clear_file_list(self):
        """Очистка списка файлов"""
        self.file_list = []
        self.update_file_list_display()
        self.btn_batch_clean.setEnabled(False)
        self.btn_batch_workflow.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.info_box.append("<br><b style='color: #f7768e;'>🗑️ Список файлов очищен</b>")
        
        # Очищаем текущий просмотр
        self.file_path = None
        self.metadata_store = {"useful": [], "all": []}
        self.update_display()
        self.btn_clean.setEnabled(False)
        self.btn_add_workflow.setEnabled(False)
    
    def update_file_list_display(self):
        """Обновление отображения списка файлов"""
        if not self.file_list:
            self.file_list_widget.clear()
            self.file_list_widget.setPlaceholderText("Выберите файлы или папку для пакетной обработки...\n\nСовет: дважды кликните на файл в списке, чтобы просмотреть его метаданные")
            return
        
        display_text = f"📋 ВСЕГО ФАЙЛОВ: {len(self.file_list)}\n\n"
        for i, file in enumerate(self.file_list[:20], 1):  # Показываем первые 20
            display_text += f"{i}. {os.path.basename(file)}\n"
        if len(self.file_list) > 20:
            display_text += f"\n... и еще {len(self.file_list) - 20} файлов"
        
        self.file_list_widget.setText(display_text)
    
    def batch_clean(self):
        """Пакетная очистка файлов"""
        if not self.file_list:
            QMessageBox.warning(self, "Предупреждение", "Нет файлов для обработки!")
            return
        
        reply = QMessageBox.question(self, "Подтверждение", 
                                    f"Вы уверены, что хотите удалить метаданные из {len(self.file_list)} файлов?\n\n"
                                    "Это действие необратимо!",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.start_batch_processing(clean_mode=True, add_workflow_json=None)
    
    def batch_add_workflow(self):
        """Пакетное добавление workflow"""
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
        """Запуск пакетной обработки в отдельном потоке"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.btn_batch_clean.setEnabled(False)
        self.btn_batch_workflow.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_clean.setEnabled(False)
        self.btn_add_workflow.setEnabled(False)
        
        self.info_box.clear()
        self.info_box.append("<b style='color: #6c8aff;'>🚀 Начинаем пакетную обработку...</b><br>")
        
        self.batch_processor = BatchProcessor(self.file_list, clean_mode, add_workflow_json)
        self.batch_processor.progress.connect(self.update_batch_progress)
        self.batch_processor.log.connect(self.append_batch_log)
        self.batch_processor.finished.connect(self.batch_processing_finished)
        self.batch_processor.start()
    
    def update_batch_progress(self, current, total, filename):
        """Обновление прогресса обработки"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"Обработка: {current}/{total} - {filename}")
    
    def append_batch_log(self, message):
        """Добавление сообщения в лог"""
        self.info_box.append(message)
        # Автопрокрутка вниз
        scrollbar = self.info_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def batch_processing_finished(self, success, errors):
        """Завершение пакетной обработки"""
        self.progress_bar.setVisible(False)
        self.btn_batch_clean.setEnabled(True)
        self.btn_batch_workflow.setEnabled(True)
        self.btn_select.setEnabled(True)
        
        if success:
            self.info_box.append("<br><b style='color: #9ece6a;'>✅ ПАКЕТНАЯ ОБРАБОТКА УСПЕШНО ЗАВЕРШЕНА!</b>")
            if self.file_list and len(self.file_list) == 1:
                # Если обработан один файл, загружаем его для просмотра
                self.load_metadata(self.file_list[0])
        else:
            self.info_box.append(f"<br><b style='color: #f7768e;'>⚠️ ОБРАБОТКА ЗАВЕРШЕНА С ОШИБКАМИ ({len(errors)})</b>")
            for error in errors[:10]:  # Показываем первые 10 ошибок
                self.info_box.append(f"<span style='color: #f7768e;'>❌ {error}</span>")
            if len(errors) > 10:
                self.info_box.append(f"<span style='color: #f7768e;'>... и еще {len(errors) - 10} ошибок</span>")
        
        self.batch_processor = None

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
            # Проверяем, что было брошено: файлы или папки
            all_files = []
            for file in files:
                if os.path.isdir(file):
                    all_files.extend(self.get_supported_files(file))
                else:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in ['.png', '.jpg', '.jpeg', '.webp', '.tiff', 
                              '.mp3', '.mp4', '.m4a', '.wav', '.flac', '.mov', '.m4v']:
                        all_files.append(file)
            
            if all_files:
                # Добавляем в список для пакетной обработки
                self.file_list = all_files
                self.update_file_list_display()
                self.btn_batch_clean.setEnabled(True)
                self.btn_batch_workflow.setEnabled(True)
                self.info_box.append(f"<br><b style='color: #9ece6a;'>📥 Перетащено {len(all_files)} элементов</b>")
                
                # Если перетащен только один файл, загружаем его для просмотра
                if len(all_files) == 1:
                    self.load_metadata(all_files[0])
                    self.info_box.append(f"<b style='color: #7aa2f7;'>🔍 Загружен для просмотра: {os.path.basename(all_files[0])}</b>")
                else:
                    # Если несколько файлов, очищаем текущий просмотр
                    self.file_path = None
                    self.metadata_store = {"useful": [], "all": []}
                    self.update_display()
                    self.btn_clean.setEnabled(False)
                    self.btn_add_workflow.setEnabled(False)
            else:
                # Если только один файл и нет папок, загружаем его как текущий
                if len(files) == 1 and os.path.isfile(files[0]):
                    self.file_list = [files[0]]
                    self.update_file_list_display()
                    self.load_metadata(files[0])
                    # Также активируем пакетные кнопки для этого одного файла
                    self.btn_batch_clean.setEnabled(True)
                    self.btn_batch_workflow.setEnabled(True)

    def open_file_dialog(self):
        file, _ = QFileDialog.getOpenFileName(self, "Открыть медиафайл")
        if file:
            self.file_list = [file]
            self.update_file_list_display()
            self.load_metadata(file)
            self.btn_batch_clean.setEnabled(True)
            self.btn_batch_workflow.setEnabled(True)

    def deep_extract(self, data):
        """ Рекурсивный поиск тегов """
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
        """ Обработка значений с поддержкой русского языка и списков """
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
                    'comment', 'description', 'artist', 'title', 'comm', '\xa9cmt', 'desc'
                ]
                if any(uk in k_l for uk in useful_keywords):
                    self.metadata_store["useful"].append((str(key), decoded_val))
        except: 
            pass

    def format_value_html(self, val):
        """ Форматирование вывода с поддержкой кириллицы в JSON """
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
                    f.read(4)  # CRC
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
        except Exception as e:
            self.info_box.setHtml(f"<b style='color: #f7768e;'>ОШИБКА ЧТЕНИЯ: {str(e)}</b>")

    def update_display(self):
        if not self.file_path:
            # Показываем заглушку, если файл не загружен
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
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.tiff']:
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
        """ Запись Workflow с максимальной совместимостью для ComfyUI """
        if not self.file_path:
            return
        
        json_path, _ = QFileDialog.getOpenFileName(self, "Выбрать Workflow JSON", "", "JSON Files (*.json)")
        if not json_path:
            return

        try:
            # Сначала очищаем, чтобы не было конфликтов
            self.clean_file(silent=True)

            with open(json_path, 'r', encoding='utf-8') as f:
                workflow_raw = json.load(f)
                # Компактный JSON без лишних пробелов для экономии места в метаданных
                workflow_str = json.dumps(workflow_raw, ensure_ascii=False, separators=(',', ':'))

            ext = os.path.splitext(self.file_path)[1].lower()

            # ИЗОБРАЖЕНИЯ
            if ext == '.png':
                with Image.open(self.file_path) as img:
                    info = PngImagePlugin.PngInfo()
                    info.add_text("prompt", workflow_str)
                    info.add_text("workflow", workflow_str)
                    img.save(self.file_path, pnginfo=info)
            
            elif ext in ['.jpg', '.jpeg', '.webp']:
                with Image.open(self.file_path) as img:
                    exif = img.getexif()
                    # 0x9286 - стандартный тег UserComment для EXIF
                    exif[0x9286] = workflow_str
                    img.save(self.file_path, exif=exif)

            # ВИДЕО (MP4/MOV) - Самая важная часть для ComfyUI
            elif ext in ['.mp4', '.m4v', '.mov']:
                video = MP4(self.file_path)
                
                # 1. Запись в стандартный тег комментария (для общей совместимости)
                video["\xa9cmt"] = [workflow_str]
                
                # 2. Запись в iTunes Freeform атомы (именно их ищет ComfyUI)
                # Данные должны быть байтами в UTF-8
                workflow_bytes = workflow_str.encode('utf-8')
                
                # ComfyUI Video Helper Suite ищет ключи 'prompt' или 'workflow' в iTunes пространстве
                video["----:com.apple.iTunes:prompt"] = [workflow_bytes]
                video["----:com.apple.iTunes:workflow"] = [workflow_bytes]
                
                video.save()

            # АУДИО
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
                # Универсальный метод для прочих форматов через Mutagen
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