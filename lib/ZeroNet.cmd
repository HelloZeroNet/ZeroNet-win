@echo off
cd /d "%~dp0"
copy ZeroNet-cli.dat ..\ZeroNet.com >NUL
..\ZeroNet.com %*
del ..\ZeroNet.com