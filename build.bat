echo y | rmdir /s dist
set "cwd=%cd%"
pyinstaller.exe connector.py --icon=connector.ico --noconsole --version-file version.txt --add-data "version.txt;." -n python
pyinstaller.exe setting.py --icon=setting.ico --noconsole --version-file version.txt --add-data "version.txt;."
move dist\setting\setting.exe dist\python\
echo y | rmdir /s dist\setting

FOR /F "tokens=* USEBACKQ" %%F IN (`grep filevers version.txt ^| sed "s/filevers=(//" ^| sed "s/, 0),//" ^| sed "s/, /./g"`) DO (
SET version=%%F
)
ECHO %version%

cd dist\python
zip pypbac.zip -r .

move pypbac.zip ..\pypbac-%version%.zip
cd ..\..
