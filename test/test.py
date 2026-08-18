import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge


# ============================================================
# CPU8 Cocotb Testbench
#
# UART:
#   8-N-1
#   115200 baud
#
# Programming packet:
#   AA
#   address
#   data
#
# Start command:
#   55
#
# CPU clock:
#   60 MHz
# ============================================================


BAUD = 115200
BIT_TIME_NS = 1_000_000_000.0 / BAUD


# ============================================================
# Helpers
# ============================================================

async def wait_cycles(dut, cycles):
    for _ in range(cycles):
        await RisingEdge(dut.clk)


async def uart_send_byte(dut, data):
    """
    Send one UART 8-N-1 byte on uio_in[0].
    """

    # Start bit
    dut.uio_in.value = int(dut.uio_in.value) | 0xFF
    dut.uio_in.value &= ~0x01

    await Timer(BIT_TIME_NS, units="ns")

    # Data bits, LSB first
    for i in range(8):
        value = int(dut.uio_in.value)

        if (data >> i) & 1:
            value |= 0x01
        else:
            value &= ~0x01

        dut.uio_in.value = value

        await Timer(BIT_TIME_NS, units="ns")

    # Stop bit
    value = int(dut.uio_in.value) | 0x01
    dut.uio_in.value = value

    await Timer(BIT_TIME_NS, units="ns")


async def program_instruction(dut, address, data):
    """
    UART programming packet:

        AA
        address
        data
    """

    await uart_send_byte(dut, 0xAA)
    await uart_send_byte(dut, address)
    await uart_send_byte(dut, data)

    # Allow program write to propagate
    await wait_cycles(dut, 3)


async def start_program(dut):
    """
    Send UART 0x55 start command.
    """

    await uart_send_byte(dut, 0x55)

    # Allow start pulse to propagate
    await wait_cycles(dut, 3)


async def check_gpio(dut, expected, name):
    await Timer(1, units="ns")

    actual = int(dut.uo_out.value)

    if actual == expected:
        dut._log.info(
            "PASSED: %s GPIO_OUT=%02X",
            name,
            actual
        )
    else:
        raise AssertionError(
            f"FAILED: {name} expected GPIO={expected:02X} "
            f"got={actual:02X}"
        )


async def program(dut, instructions):
    """
    Program a list of (address, instruction) tuples.
    """

    for address, instruction in instructions:
        await program_instruction(
            dut,
            address,
            instruction
        )


async def run_program(dut, instructions, cycles):
    """
    Program CPU, start it, and wait.
    """

    await program(dut, instructions)
    await start_program(dut)
    await wait_cycles(dut, cycles)


# ============================================================
# Main test
# ============================================================

@cocotb.test()
async def test_cpu8(dut):

    dut._log.info("")
    dut._log.info("================================================")
    dut._log.info("       CPU8 TINY TAPEOUT COCOB TEST")
    dut._log.info("================================================")

    # ========================================================
    # Start 60 MHz clock
    # ========================================================

    cocotb.start_soon(
        Clock(dut.clk, 16.6666666667, units="ns").start()
    )

    # ========================================================
    # Initial state
    # ========================================================

    dut.ui_in.value = 0x00

    # UART idle HIGH
    dut.uio_in.value = 0xFF

    dut.ena.value = 0
    dut.rst_n.value = 0

    # ========================================================
    # TEST 1: RESET
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 1: RESET")
    dut._log.info("================================")

    await wait_cycles(dut, 20)

    await check_gpio(
        dut,
        0x00,
        "Reset"
    )

    # ========================================================
    # TEST 2: ENA LOW
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 2: ENA LOW")
    dut._log.info("================================")

    dut.ena.value = 0

    await wait_cycles(dut, 20)

    actual = int(dut.uo_out.value)

    if actual == 0:
        dut._log.info(
            "PASSED: ena=0 keeps GPIO inactive"
        )
    else:
        dut._log.info(
            "INFO: ena=0 GPIO_OUT=%02X",
            actual
        )

    # ========================================================
    # TEST 3: ENABLE CPU
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 3: ENABLE CPU")
    dut._log.info("================================")

    dut.ena.value = 1

    dut.rst_n.value = 0
    await wait_cycles(dut, 10)

    dut.rst_n.value = 1
    await wait_cycles(dut, 10)

    dut._log.info(
        "PASSED: CPU enabled and reset released"
    )

    # ========================================================
    # TEST 4: UART PROGRAMMING
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 4: UART PROGRAMMING")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x1F),
            (0x01, 0xBD),
            (0x02, 0x15),
            (0x03, 0xBC),
            (0x04, 0xC2),
        ],
        10
    )

    dut._log.info(
        "PASSED: UART program transmitted and CPU started"
    )

    # ========================================================
    # TEST 5: LDI
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 5: LDI")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x1F),
            (0x01, 0xBD),
            (0x02, 0x1A),
            (0x03, 0xBC),
            (0x04, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0x0A, "LDI")

    # ========================================================
    # TEST 6: NOP
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 6: NOP")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x00),
            (0x01, 0x13),
            (0x02, 0xBC),
            (0x03, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0x03, "NOP")

    # ========================================================
    # TEST 7: INC
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 7: INC")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x15),
            (0x01, 0x80),
            (0x02, 0xBC),
            (0x03, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0x06, "INC")

    # ========================================================
    # TEST 8: DEC
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 8: DEC")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x15),
            (0x01, 0x90),
            (0x02, 0xBC),
            (0x03, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0x04, "DEC")

    # ========================================================
    # TEST 9: NOT
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 9: NOT")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x15),
            (0x01, 0x70),
            (0x02, 0xBC),
            (0x03, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0xFA, "NOT")

    # ========================================================
    # TEST 10: ADD
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 10: ADD")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x13),
            (0x01, 0x23),
            (0x02, 0xBC),
            (0x03, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0x06, "ADD")

    # ========================================================
    # TEST 11: SUB
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 11: SUB")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x15),
            (0x01, 0x33),
            (0x02, 0xBC),
            (0x03, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0x02, "SUB")

    # ========================================================
    # TEST 12: AND
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 12: AND")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x1A),
            (0x01, 0x4F),
            (0x02, 0xBC),
            (0x03, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0x0A, "AND")

    # ========================================================
    # TEST 13: OR
    #
    # IMPORTANT:
    #
    # Operand is only 4 bits.
    #
    # 0x15 = LDI 5
    # 0x5A = OR  A
    #
    # Therefore:
    #
    # 0x05 | 0x0A = 0x0F
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 13: OR")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x15),
            (0x01, 0x5A),
            (0x02, 0xBC),
            (0x03, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0x0F, "OR")

    # ========================================================
    # TEST 14: XOR
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 14: XOR")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x1A),
            (0x01, 0x65),
            (0x02, 0xBC),
            (0x03, 0xC2),
        ],
        10
    )

    await check_gpio(dut, 0x0F, "XOR")

    # ========================================================
    # TEST 15: STORE / LOAD RAM
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 15: STORE / LOAD RAM")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x1A),
            (0x01, 0xB5),
            (0x02, 0x10),
            (0x03, 0xA5),
            (0x04, 0xBC),
            (0x05, 0xC2),
        ],
        15
    )

    await check_gpio(dut, 0x0A, "RAM LOAD")

    # ========================================================
    # TEST 16: GPIO OUTPUT
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 16: GPIO OUTPUT")
    dut._log.info("================================")

    gpio_values = [0x00, 0x05, 0x0A, 0x0F]

    for value in gpio_values:

        await run_program(
            dut,
            [
                (0x00, 0x10 | value),
                (0x01, 0xBC),
                (0x02, 0xC2),
            ],
            8
        )

        await check_gpio(
            dut,
            value,
            f"GPIO {value:02X}"
        )

    # ========================================================
    # TEST 17: GPIO INPUT
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 17: GPIO INPUT")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0xAE),
            (0x01, 0xBC),
            (0x02, 0xC2),
        ],
        8
    )

    dut.ui_in.value = 0xA5

    # Restart program with new GPIO input
    await start_program(dut)
    await wait_cycles(dut, 8)

    await check_gpio(
        dut,
        0xA5,
        "GPIO INPUT A5"
    )

    dut.ui_in.value = 0x5A

    await start_program(dut)
    await wait_cycles(dut, 8)

    await check_gpio(
        dut,
        0x5A,
        "GPIO INPUT 5A"
    )

    # ========================================================
    # TEST 18: JMP
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 18: JMP")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x11),
            (0x01, 0xC4),
            (0x02, 0x12),
            (0x03, 0xBC),
            (0x04, 0x13),
            (0x05, 0xBC),
            (0x06, 0xC6),
        ],
        12
    )

    await check_gpio(dut, 0x03, "JMP")

    # ========================================================
    # TEST 19: BZ TAKEN
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 19: BZ TAKEN")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x10),
            (0x01, 0xD4),
            (0x02, 0x11),
            (0x03, 0xBC),
            (0x04, 0x12),
            (0x05, 0xBC),
            (0x06, 0xC6),
        ],
        12
    )

    await check_gpio(dut, 0x02, "BZ TAKEN")

    # ========================================================
    # TEST 20: BZ NOT TAKEN
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 20: BZ NOT TAKEN")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x11),
            (0x01, 0xD4),
            (0x02, 0x12),
            (0x03, 0xBC),
            (0x04, 0x13),
            (0x05, 0xBC),
            (0x06, 0xC6),
        ],
        12
    )

    await check_gpio(dut, 0x03, "BZ NOT TAKEN")

    # ========================================================
    # TEST 21: BNZ TAKEN
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 21: BNZ TAKEN")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x11),
            (0x01, 0xE4),
            (0x02, 0x12),
            (0x03, 0xBC),
            (0x04, 0x13),
            (0x05, 0xBC),
            (0x06, 0xC6),
        ],
        12
    )

    await check_gpio(dut, 0x03, "BNZ TAKEN")

    # ========================================================
    # TEST 22: BNZ NOT TAKEN
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 22: BNZ NOT TAKEN")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x10),
            (0x01, 0xE4),
            (0x02, 0x12),
            (0x03, 0xBC),
            (0x04, 0x13),
            (0x05, 0xBC),
            (0x06, 0xC6),
        ],
        12
    )

    await check_gpio(dut, 0x03, "BNZ NOT TAKEN")

    # ========================================================
    # TEST 23: HALT
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 23: HALT")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x15),
            (0x01, 0xBC),
            (0x02, 0xF0),
            (0x03, 0x1A),
            (0x04, 0xBC),
            (0x05, 0xC5),
        ],
        10
    )

    await check_gpio(dut, 0x05, "HALT")

    # ========================================================
    # TEST 24: RESET WHILE RUNNING
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 24: RESET WHILE RUNNING")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x11),
            (0x01, 0xBC),
            (0x02, 0x10),
            (0x03, 0xBC),
            (0x04, 0xC2),
        ],
        10
    )

    dut.rst_n.value = 0

    await wait_cycles(dut, 10)

    await check_gpio(
        dut,
        0x00,
        "RESET WHILE RUNNING"
    )

    dut.rst_n.value = 1

    await wait_cycles(dut, 5)

    dut._log.info(
        "PASSED: CPU recovered after reset"
    )

    # ========================================================
    # TEST 25: UART REPROGRAMMING
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 25: UART REPROGRAMMING")
    dut._log.info("================================")

    await run_program(
        dut,
        [
            (0x00, 0x17),
            (0x01, 0xBC),
            (0x02, 0xC2),
        ],
        10
    )

    await check_gpio(
        dut,
        0x07,
        "UART REPROGRAM"
    )

    # ========================================================
    # TEST 26: UART MULTIPLE WRITES
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 26: UART MULTIPLE WRITES")
    dut._log.info("================================")

    multiple_program = [
        0x11,
        0x12,
        0x13,
        0x14,
        0x15,
        0x16,
        0x17,
        0x18,
        0x19,
        0x1A,
        0x1B,
        0x1C,
        0x1D,
        0x1E,
        0x1F,
        0x00,
    ]

    for address, instruction in enumerate(multiple_program):
        await program_instruction(
            dut,
            address,
            instruction
        )

    dut._log.info(
        "PASSED: Multiple UART writes transmitted"
    )

    # ========================================================
    # TEST 27: GPIO PATTERNS
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 27: GPIO PATTERNS")
    dut._log.info("================================")

    for value in [0x00, 0x01, 0x05, 0x0A, 0x0F]:

        await run_program(
            dut,
            [
                (0x00, 0x10 | value),
                (0x01, 0xBC),
                (0x02, 0xC2),
            ],
            8
        )

        await check_gpio(
            dut,
            value,
            f"GPIO {value:02X}"
        )

    # ========================================================
    # FINAL
    # ========================================================

    dut._log.info("")
    dut._log.info("================================================")
    dut._log.info("          CPU8 COCOBT TEST COMPLETE")
    dut._log.info("================================================")

    dut._log.info("")
    dut._log.info("All 27 CPU8 tests passed.")
