@echo off
REM =====================================================================
REM  Jalankan BOT TELEGRAM Scrapper Instagram Kota Cirebon
REM  Klik dua kali file ini. Biarkan jendelanya terbuka selama bot dipakai.
REM  Tutup jendela ini (atau Ctrl+C) = bot berhenti menerima pesan.
REM =====================================================================

REM Pindah ke folder tempat file ini berada. WAJIB, karena bot mengimpor
REM bot_config/telegram_api/menu_bot/job_runner dari folder ini.
cd /d "%~dp0"

REM Pilih Python: yang punya transformers + torch (untuk analisis sentimen).
if exist "C:\Python314\python.exe" (
    set "PY=C:\Python314\python.exe"
) else (
    set "PY=python"
)

echo.
echo =====================================================================
echo   BOT TELEGRAM - SCRAPPER INSTAGRAM MEDIA KOTA CIREBON
echo =====================================================================
echo   Python : %PY%
echo   Folder : %CD%
echo.
echo   Catatan:
echo    - Biarkan jendela ini terbuka. Tutup jendela = bot berhenti.
echo    - Kalau jendela bot yang LAMA masih terbuka, tutup dulu (Ctrl+C di jendela itu).
echo      Kalau tidak, jendela baru ini akan berhenti dengan pesan "token/konflik",
echo      karena satu token Telegram hanya boleh dipakai SATU proses.
echo    - Jangan jalankan uji_telegram.py bersamaan (token hanya boleh 1 proses).
echo    - Hentikan dengan Ctrl+C.
echo    - Setelah bot menyala, buka Telegram dan kirim: /start
echo =====================================================================
echo.

"%PY%" main_bot.py

echo.
echo Bot berhenti. Tekan tombol apa saja untuk menutup jendela ini.
pause >nul
