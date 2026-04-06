#!/bin/bash

# Compile Rust code for ARM Cortex-M4
echo "============================================"
echo "Building Rust Code for ARM Cortex-M4"
echo "============================================"

cargo build --release --target=thumbv7em-none-eabihf

OUTPUT_PATH="target/thumbv7em-none-eabihf/release/intermittent_rust"

echo "Checking build output..."

if [ -f "$OUTPUT_PATH" ]; then
    echo -e "\nBUILD SUCCESSFUL!"
    echo "Output: $OUTPUT_PATH"
    echo ""
    arm-none-eabi-size "$OUTPUT_PATH"
else
    echo "BUILD FAILED! Binary not found at $OUTPUT_PATH"
    exit 1
fi