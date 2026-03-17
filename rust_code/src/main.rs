#![no_std]
#![no_main]

use core::mem;
use core::panic::PanicInfo;
use core::ptr::{addr_of, addr_of_mut};
use cortex_m_rt::entry;

// Reset and Clock Control (RCC) and USART2 base addresses
const RCC_BASE: usize = 0x4002_3800;
const USART2_BASE: usize = 0x4000_4400;

// register definitions
const RCC_APB1ENR: *mut u32 = (RCC_BASE + 0x40) as *mut u32;
const USART2_SR: *mut u32 = (USART2_BASE + 0x00) as *mut u32;
const USART2_DR: *mut u32 = (USART2_BASE + 0x04) as *mut u32;
const USART2_BRR: *mut u32 = (USART2_BASE + 0x08) as *mut u32;
const USART2_CR1: *mut u32 = (USART2_BASE + 0x0C) as *mut u32;

// simulated NVM for state checkpointing
const NVM_SIZE: usize = 256;
static mut NVM_BUFFER: [u8; NVM_SIZE] = [0; NVM_SIZE];

#[derive(Clone, Copy)]
struct AppState {
    computation_result: u32
}

static mut STATE: AppState = AppState {
    computation_result: 0
};

fn uart_init() {
    unsafe {
        *RCC_APB1ENR |= 1 << 17; // enable USART2 clock
        *USART2_BRR = 0x008B; // 115200 baud rate at 16 MHz
        *USART2_CR1 = (1 << 13) | (1 << 3); // enable USART2 and transmitter
    }
}

fn uart_putchar(c: u8) {
    unsafe {
        // wait for TXE (SR bit 7) before writing the next byte.
        while (*USART2_SR & (1 << 7)) == 0 {}
        *USART2_DR = c as u32;
    }
}

fn uart_write(s: &str) {
    for byte in s.bytes() {
        uart_putchar(byte);
    }
}

// using write_votaile so optimizer doesn't treat assignment as dead code
// need the instruction count to be comparable to C version
fn checkpoint_state() {
    unsafe {
        let state_size = mem::size_of::<AppState>();
        let state_bytes = core::slice::from_raw_parts(
            addr_of!(STATE) as *const u8,
            state_size,
        );
        for i in 0..state_size {
            core::ptr::write_volatile((addr_of_mut!(NVM_BUFFER) as *mut u8).add(i), state_bytes[i]);
        }
    }
}

fn compute_task(input: u32) -> u32 {
    let mut result = 0u32;
    for i in 0..1000 {
        result = result.wrapping_add((input.wrapping_mul(i)).wrapping_div(i + 1));
    }
    result
}

#[entry]
fn main() -> ! {
    uart_init();
    uart_write("Rust: Intermittent Computing Test Started\n");

    for cycle in 0..100u32 {
        unsafe {
            let result = compute_task(cycle);
            core::ptr::write_volatile(addr_of_mut!(STATE.computation_result), result);

            if cycle % 10 == 0 {
                checkpoint_state();
                uart_write("Rust: Checkpoint saved\n");
            }
        }
    }

    uart_write("Rust: Test completed\n");

    loop {}
}

// panic handler (required for no_std)
#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {}
}