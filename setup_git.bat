@echo off
echo ================================
echo  CASB Git Identity Setup
echo ================================
echo.

set /p NAME="Enter your name (e.g. Amruta): "
set /p EMAIL="Enter your email (e.g. amruta.l@versa-networks.com): "

git config user.name "%NAME%"
git config user.email "%EMAIL%"

echo.
echo ================================
echo  Git identity set!
echo  Name  : %NAME%
echo  Email : %EMAIL%
echo ================================
echo.
pause
