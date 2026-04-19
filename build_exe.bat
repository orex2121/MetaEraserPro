@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo.
echo 🛡️  META ERASER BUILDER [stabledif.ru]
echo --------------------------------------
echo.

:: Проверка наличия PyInstaller
where pyinstaller >nul 2>nul
if %errorlevel% neq 0 (
echo [!] PyInstaller не найден. Установка...
pip install pyinstaller PyQt6 Pillow mutagen
)

:: Запрос имен
set /p py_file=">>> Имя .py файла: "
if not exist "%py_file%" (
echo [X] Файл %py_file% не найден.
pause
exit /b
)

set /p exe_name=">>> Имя для .exe: "

:: Важная часть для иконки
set "icon_param="
set "add_data="
if exist "logo.ico" (
set "icon_param=--icon=logo.ico"
:: Параметр --add-data кладет иконку внутрь EXE, чтобы Python ее увидел через sys._MEIPASS
set "add_data=--add-data logo.ico;."
echo [+] logo.ico будет вшит в файл и применен как иконка.
) else (
echo [!] logo.ico не найден! EXE будет со стандартной иконкой.
)

echo.
echo [I] Сборка запущена... Это может занять пару минут.
echo.

:: Сборка с вшиванием иконки
pyinstaller --noconsole --onefile %icon_param% %add_data% --name="%exe_name%" "%py_file%"

if %errorlevel% equ 0 (
echo.
echo ✅ ГОТОВО!
echo [I] Файл создан: dist%exe_name%.exe
echo --------------------------------------
) else (
echo.
echo [X] Ошибка сборки. Проверьте логи выше.
)

pause