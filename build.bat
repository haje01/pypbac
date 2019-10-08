echo y | rmdir /s dist
pyinstaller.exe connector.py --icon=connector.ico --noconsole --version-file version.txt -n python
pyinstaller.exe setting.py --icon=setting.ico --noconsole --version-file version.txt
move dist\setting\setting.exe dist\python\
echo y | rmdir /s dist\setting