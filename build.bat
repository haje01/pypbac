echo y | rmdir /s dist
pyinstaller.exe connector.py --icon=pypbac.ico --noconsole --version-file version.txt -n python