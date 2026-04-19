@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: Проверка, установлен ли Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] Python не найден. Установите его и добавьте в PATH.
    pause
    exit /b
)

echo Запуск MetadataCleaner...
echo ---------------------------------------

:: Запуск скрипта. %* позволяет передавать аргументы (например, перетаскивать файлы на батник)
python "%~dp0MetadataCleaner.py" %*

echo ---------------------------------------
echo Работа завершена.
pause