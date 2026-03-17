@echo off
REM Compile C code for ARM Cortex-M4

echo ============================================
echo Building C Code for ARM Cortex-M4
echo ============================================

where arm-none-eabi-gcc >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: arm-none-eabi-gcc not found
    pause
    exit /b 1
)

if not exist build mkdir build
cd build

echo Compiling...
arm-none-eabi-gcc ^
    -mcpu=cortex-m4 ^
    -mthumb ^
    -O2 ^
    -Wall ^
    -Wextra ^
    -ffreestanding ^
    -fno-builtin ^
    -nostdlib ^
    -nostartfiles ^
    -Wl,--gc-sections ^
    -T ..\stm32f4.ld ^
    ..\src\startup_stm32f4.c ^
    ..\src\main.c ^
    -o intermittent_c.elf

if exist intermittent_c.elf (
    echo.
    echo BUILD SUCCESSFUL!
    echo Output: intermittent_c.elf
    echo.
    arm-none-eabi-size intermittent_c.elf
) else (
    echo BUILD FAILED!
)

cd ..
pause