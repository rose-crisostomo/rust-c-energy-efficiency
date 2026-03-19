@echo off
REM Compile Rust code for ARM Cortex-M4

echo ============================================
echo Building Rust Code for ARM Cortex-M4
echo ============================================

cargo build --release --target=thumbv7em-none-eabihf

echo Compiling...
if exist target\thumbv7em-none-eabihf\release\intermittent_rust (
    echo.
    echo BUILD SUCCESSFUL!
    echo Output: target\thumbv7em-none-eabihf\release\intermittent_rust
    echo.
    arm-none-eabi-size target\thumbv7em-none-eabihf\release\intermittent_rust
) else (
    echo BUILD FAILED!
)