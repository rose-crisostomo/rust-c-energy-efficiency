#![no_std]
#![no_main]

use core::mem;
use core::mem::MaybeUninit;
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
const CHECKPOINT_MAGIC: u32 = 0x4350_4B54;
#[link_section = ".uninit.NVM_BUFFER"]
static mut NVM_BUFFER: MaybeUninit<[u8; NVM_SIZE]> = MaybeUninit::uninit();

#[derive(Clone, Copy)]
struct AppState {
    computation_result: u32
}

#[derive(Clone, Copy)]
struct NvmCheckpoint {
    magic: u32,
    computation_result: u32,
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
        let checkpoint = NvmCheckpoint {
            magic: CHECKPOINT_MAGIC,
            computation_result: core::ptr::read_volatile(addr_of!(STATE.computation_result)),
        };
        let checkpoint_size = mem::size_of::<NvmCheckpoint>();
        let checkpoint_bytes = core::slice::from_raw_parts(
            addr_of!(checkpoint) as *const u8,
            checkpoint_size,
        );
        for i in 0..checkpoint_size {
            let nvm_ptr = (*addr_of_mut!(NVM_BUFFER)).as_mut_ptr() as *mut u8;
            core::ptr::write_volatile(nvm_ptr.add(i), checkpoint_bytes[i]);
        }
    }
}

fn restore_state() -> bool {
    unsafe {

        let mut checkpoint = NvmCheckpoint {
            magic: 0,
            computation_result: 0,
        };
        let checkpoint_size = mem::size_of::<NvmCheckpoint>();
        let checkpoint_bytes = core::slice::from_raw_parts_mut(
            addr_of_mut!(checkpoint) as *mut u8,
            checkpoint_size,
        );

        for i in 0..checkpoint_size {
            let nvm_ptr = (*addr_of!(NVM_BUFFER)).as_ptr() as *const u8;
            checkpoint_bytes[i] = core::ptr::read_volatile(nvm_ptr.add(i));
        }

        if checkpoint.magic != CHECKPOINT_MAGIC {
            core::ptr::write_volatile(addr_of_mut!(STATE.computation_result), 0);
            return false;
        }

        core::ptr::write_volatile(addr_of_mut!(STATE.computation_result), checkpoint.computation_result);
        true
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
    uart_write("Intermittent Computing Test Started\n");

    if restore_state() {
        uart_write("Restored checkpoint\n");
    } else {
        uart_write("No checkpoint found\n");
    }

    for cycle in 0..100u32 {
        unsafe {
            let result = compute_task(cycle);
            core::ptr::write_volatile(addr_of_mut!(STATE.computation_result), result);

            if cycle % 10 == 0 {
                uart_write("Starting checkpoint...\n");
                checkpoint_state();
                uart_write("Checkpoint saved\n");
            }
        }
    }

    uart_write("Test completed\n");

    loop {}
}

// panic handler (required for no_std)
#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {}
}