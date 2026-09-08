@echo off
REM Rebuild the standalone exe. Run this after changing any source file.
REM Close the app first - Windows locks a running program's file and the
REM build then fails part-way with "Access is denied".
echo Building GST Document Generator...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "GST Document Generator" --icon icon.ico ^
  --add-data "invoicegen/data;invoicegen/data" ^
  --add-data "invoicegen/fonts;invoicegen/fonts" ^
  --add-data "invoicegen/static;invoicegen/static" ^
  --hidden-import PIL._tkinter_finder --hidden-import pymupdf ^
  --collect-all webview --collect-all clr_loader --collect-all pythonnet ^
  --exclude-module matplotlib --exclude-module numpy --exclude-module pandas ^
  --exclude-module pytest --exclude-module setuptools --exclude-module pip ^
  run_app.py
echo.
echo Done. The exe is in the dist folder.
pause
