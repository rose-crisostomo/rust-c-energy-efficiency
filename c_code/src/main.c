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

static volatile uint8_t nvm_buffer[NVM_SIZE] NOINIT_SECTION;
static volatile uint32_t nvm_write_count;

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
    while ((USART2_SR & (1u << 7)) == 0u) {}
    USART2_DR = (uint32_t)c;
}

void uart_write(const char *str) {
    while (*str != '\0') {
        uart_putchar(*str++);
    }
}

static void uart_write_u32(uint32_t val) {
    if (val == 0u) {
        uart_putchar('0');
        return;
    }
    char buf[10]; // max 10 digits for uint32_t
    uint32_t len = 0u;
    while (val > 0u) {
        buf[len++] = (char)('0' + (val % 10u));
        val /= 10u;
    }
    // digits stored least-significant-first; emit in reverse
    while (len > 0u) {
        uart_putchar(buf[--len]);
    }
}


static void nvm_write_byte(uint32_t index, uint8_t value) {
    nvm_buffer[index] = value;
    nvm_write_count++;
}

void checkpoint_state(void) {
    nvm_write_count = 0u;

    const uint32_t magic = CHECKPOINT_MAGIC;
    const uint32_t result = state.computation_result;
    uint8_t checkpoint_bytes[sizeof(NvmCheckpoint)] = {0};

    checkpoint_bytes[0] = (uint8_t)(magic & 0xFFu);
    checkpoint_bytes[1] = (uint8_t)((magic >> 8) & 0xFFu);
    checkpoint_bytes[2] = (uint8_t)((magic >> 16) & 0xFFu);
    checkpoint_bytes[3] = (uint8_t)((magic >> 24) & 0xFFu);

    checkpoint_bytes[4] = (uint8_t)(result & 0xFFu);
    checkpoint_bytes[5] = (uint8_t)((result >> 8) & 0xFFu);
    checkpoint_bytes[6] = (uint8_t)((result >> 16) & 0xFFu);
    checkpoint_bytes[7] = (uint8_t)((result >> 24) & 0xFFu);

    for (uint32_t i = 0u; i < (uint32_t)sizeof(NvmCheckpoint); i++) {
        nvm_write_byte(i, checkpoint_bytes[i]);
    }

    uart_write("NVM_WRITES=");
    uart_write_u32(nvm_write_count);
    uart_putchar('\n');
}

bool restore_state(void) {
    uint8_t checkpoint_bytes[sizeof(NvmCheckpoint)] = {0};
    for (uint32_t i = 0u; i < (uint32_t)sizeof(NvmCheckpoint); i++) {
        checkpoint_bytes[i] = nvm_buffer[i];
    }

    const uint32_t magic =
        ((uint32_t)checkpoint_bytes[0]) |
        ((uint32_t)checkpoint_bytes[1] << 8) |
        ((uint32_t)checkpoint_bytes[2] << 16) |
        ((uint32_t)checkpoint_bytes[3] << 24);

    const uint32_t computation_result =
        ((uint32_t)checkpoint_bytes[4]) |
        ((uint32_t)checkpoint_bytes[5] << 8) |
        ((uint32_t)checkpoint_bytes[6] << 16) |
        ((uint32_t)checkpoint_bytes[7] << 24);

    if (magic != CHECKPOINT_MAGIC) {
        state.computation_result = 0u;
        return false;
    }

    state.computation_result = computation_result;
    return true;
}

uint32_t compute_task(uint32_t input) {
    uint32_t result = 0u;
    for (uint32_t i = 0u; i < 1000u; i++) {
        result += (input * i) / (i + 1u);
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

    for (uint32_t cycle = 0u; cycle < 100u; cycle++) {
        state.computation_result = compute_task(cycle);

        if (cycle % 10u == 0u) {
            uart_write("Starting checkpoint...\n");
            checkpoint_state();
            uart_write("Checkpoint saved\n");
        }
    }

    uart_write("Test completed\n");

    while (1);
}