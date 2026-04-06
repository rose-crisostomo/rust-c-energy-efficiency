#![no_std]
#![no_main]

use core::mem;
use core::mem::MaybeUninit;
use core::panic::PanicInfo;
use core::ptr::{addr_of, addr_of_mut};
use core::sync::atomic::{AtomicU32, Ordering};
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
struct NvmCheckpoint {
    magic: u32,
    computation_result: u32,
}

static COMPUTATION_RESULT: AtomicU32 = AtomicU32::new(0);
static NVM_WRITE_COUNT: AtomicU32 = AtomicU32::new(0);

#[inline(always)]
fn mmio_read32(addr: *mut u32) -> u32 {
    unsafe { core::ptr::read_volatile(addr) }
}

#[inline(always)]
fn mmio_write32(addr: *mut u32, value: u32) {
    unsafe { core::ptr::write_volatile(addr, value) }
}

#[inline(always)]
fn nvm_write_byte(index: usize, value: u8) {
    unsafe {
        let nvm_ptr = (*addr_of_mut!(NVM_BUFFER)).as_mut_ptr() as *mut u8;
        core::ptr::write_volatile(nvm_ptr.add(index), value);
    }
    NVM_WRITE_COUNT.fetch_add(1, Ordering::Relaxed);
}

#[inline(always)]
fn nvm_read_byte(index: usize) -> u8 {
    unsafe {
        let nvm_ptr = (*addr_of!(NVM_BUFFER)).as_ptr() as *const u8;
        core::ptr::read_volatile(nvm_ptr.add(index))
    }
}

fn uart_init() {
    let apb1enr = mmio_read32(RCC_APB1ENR);
    mmio_write32(RCC_APB1ENR, apb1enr | (1 << 17)); // enable USART2 clock
    mmio_write32(USART2_BRR, 0x008B); // 115200 baud rate at 16 MHz
    mmio_write32(USART2_CR1, (1 << 13) | (1 << 3)); // enable USART2 and transmitter
}

fn uart_putchar(c: u8) {
    // wait for TXE (SR bit 7) before writing the next byte.
    while (mmio_read32(USART2_SR) & (1 << 7)) == 0 {}
    mmio_write32(USART2_DR, c as u32);
}

fn uart_write(s: &str) {
    for byte in s.bytes() {
        uart_putchar(byte);
    }
}

fn uart_write_u32(mut val: u32) {
    if val == 0 {
        uart_putchar(b'0');
        return;
    }
    let mut buf = [0u8; 10]; // max 10 digits for u32
    let mut len = 0usize;
    while val > 0 {
        buf[len] = (val % 10) as u8 + b'0';
        val /= 10;
        len += 1;
    }
    // digits were stored least-significant-first; emit in reverse
    for i in (0..len).rev() {
        uart_putchar(buf[i]);
    }
}

fn checkpoint_state() {
    NVM_WRITE_COUNT.store(0, Ordering::Relaxed);

    let checkpoint = NvmCheckpoint {
        magic: CHECKPOINT_MAGIC,
        computation_result: COMPUTATION_RESULT.load(Ordering::Relaxed),
    };

    let mut checkpoint_bytes = [0u8; mem::size_of::<NvmCheckpoint>()];
    checkpoint_bytes[0..4].copy_from_slice(&checkpoint.magic.to_le_bytes());
    checkpoint_bytes[4..8].copy_from_slice(&checkpoint.computation_result.to_le_bytes());

    for (i, byte) in checkpoint_bytes.iter().enumerate() {
        nvm_write_byte(i, *byte);
    }

    uart_write("NVM_WRITES=");
    uart_write_u32(NVM_WRITE_COUNT.load(Ordering::Relaxed));
    uart_write("\n");
}

fn restore_state() -> bool {
    let mut checkpoint_bytes = [0u8; mem::size_of::<NvmCheckpoint>()];
    for (i, byte) in checkpoint_bytes.iter_mut().enumerate() {
        *byte = nvm_read_byte(i);
    }

    let checkpoint = NvmCheckpoint {
        magic: u32::from_le_bytes([
            checkpoint_bytes[0],
            checkpoint_bytes[1],
            checkpoint_bytes[2],
            checkpoint_bytes[3],
        ]),
        computation_result: u32::from_le_bytes([
            checkpoint_bytes[4],
            checkpoint_bytes[5],
            checkpoint_bytes[6],
            checkpoint_bytes[7],
        ]),
    };

    if checkpoint.magic != CHECKPOINT_MAGIC {
        COMPUTATION_RESULT.store(0, Ordering::Relaxed);
        return false;
    }

    COMPUTATION_RESULT.store(checkpoint.computation_result, Ordering::Relaxed);
    true
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
        let result = compute_task(cycle);
        COMPUTATION_RESULT.store(result, Ordering::Relaxed);

        if cycle % 10 == 0 {
            uart_write("Starting checkpoint...\n");
            checkpoint_state();
            uart_write("Checkpoint saved\n");
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