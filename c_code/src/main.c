#include <stdint.h>
#include <stdbool.h>

// Reset and Clock Control (RCC) and USART2 base addresses
#define RCC_BASE       0x40023800u
#define USART2_BASE    0x40004400u

// register definitions
#define RCC_APB1ENR    (*(volatile uint32_t *)(RCC_BASE + 0x40u))
#define USART2_SR      (*(volatile uint32_t *)(USART2_BASE + 0x00u))
#define USART2_DR      (*(volatile uint32_t *)(USART2_BASE + 0x04u))
#define USART2_BRR     (*(volatile uint32_t *)(USART2_BASE + 0x08u))
#define USART2_CR1     (*(volatile uint32_t *)(USART2_BASE + 0x0Cu))

// simulated NVM for state checkpointing
#define NVM_SIZE 256
#define CHECKPOINT_MAGIC 0x43504B54u

#if defined(__GNUC__) || defined(__clang__)
#define NOINIT_SECTION __attribute__((section(".noinit")))
#else
#define NOINIT_SECTION
#endif

static uint8_t nvm_buffer[NVM_SIZE] NOINIT_SECTION;

typedef struct {
    uint32_t computation_result;
} AppState;

typedef struct {
    uint32_t magic;
    uint32_t computation_result;
} NvmCheckpoint;

static AppState state = {0};

static void uart_init(void) {
    RCC_APB1ENR |= (1u << 17); // enable USART2 clock
    USART2_BRR = 0x008Bu; // 115200 baud rate at 16 MHz
    USART2_CR1 = (1u << 13) | (1u << 3); // enable USART2 and transmitter
}

static void uart_putchar(char c) {
    // wait for TXE (SR bit 7) before writing the next byte.
    while((USART2_SR & (1u << 7)) == 0u) {}
    USART2_DR = (uint32_t)c;
}

void uart_write(const char *str) {
    while(*str != '\0') {
        uart_putchar(*str++);
    }
}

void checkpoint_state(void) {
    const NvmCheckpoint checkpoint = {
        .magic = CHECKPOINT_MAGIC,
        .computation_result = state.computation_result
    };

    const uint8_t *src = (const uint8_t *)&checkpoint;
    for (uint32_t i = 0; i < (uint32_t)sizeof(NvmCheckpoint); i++) {
        nvm_buffer[i] = src[i];
    }
}

bool restore_state(void) {
    NvmCheckpoint checkpoint = {0};
    uint8_t *dst = (uint8_t *)&checkpoint;
    for (uint32_t i = 0; i < (uint32_t)sizeof(NvmCheckpoint); i++) {
        dst[i] = nvm_buffer[i];
    }

    // checkpoint may be corrupted or failed
    if (checkpoint.magic != CHECKPOINT_MAGIC) {
        state.computation_result = 0;
        return false;
    }

    state.computation_result = checkpoint.computation_result;
    return true;
}

uint32_t compute_task(uint32_t input) {
    uint32_t result = 0;
    for (uint32_t i = 0; i < 1000; i++) {
        result += (input * i) / (i + 1);
    }
    return result;
}

void main(void) {
    uart_init();
    uart_write("Intermittent Computing Test Started\n");

    if (restore_state()) {
        uart_write("Restored checkpoint\n");
    } else {
        uart_write("No checkpoint found\n");
    }

    for (uint32_t cycle = 0; cycle < 100; cycle++) {
        state.computation_result = compute_task(cycle);

        if (cycle % 10 == 0) {
            uart_write("Starting checkpoint...\n");
            checkpoint_state();
            uart_write("Checkpoint saved\n");
        }
    }

    uart_write("Test completed\n");

    while (1);
}