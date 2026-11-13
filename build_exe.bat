@echo off
REM ============================================================
REM  Gera dist\ForjaVideo\ForjaVideo.exe (rode no Windows, com Python 3.10+)
REM  Python: https://www.python.org/downloads/  (marque "Add to PATH")
REM ============================================================
setlocal
cd /d "%~dp0"

python -m venv .venv || goto :erro
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto :erro
pip install -r requirements.txt pyinstaller || goto :erro

REM Piper (IA local de voz) e opcional: se instalar, entra no .exe
set PIPER=
pip install piper-tts >nul 2>&1
if %errorlevel%==0 set PIPER=--collect-all piper --collect-all onnxruntime

pyinstaller --noconfirm --clean --windowed --name ForjaVideo ^
  --add-data "assets;assets" ^
  --collect-all imageio_ffmpeg --collect-all edge_tts --collect-all certifi ^
  --hidden-import pyttsx3.drivers --hidden-import pyttsx3.drivers.sapi5 ^
  %PIPER% main.py || goto :erro

echo.
echo Pronto! Abra a pasta dist\ForjaVideo e execute ForjaVideo.exe
echo (se quiser testar antes: dist\ForjaVideo\ForjaVideo.exe --selftest teste_saida)
pause
exit /b 0

:erro
echo.
echo Algo deu errado. Leia a mensagem acima.
pause
exit /b 1
