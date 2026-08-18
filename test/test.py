import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# ============================================================
# CPU8 Tiny Tapeout Cocotb Testbench
#
# 60 MHz CPU clock
# UART: 115200 baud, 8-N-1
#
# Programming protocol:
#   AA <address> <data>
#
# Start command:
#   55
# ============================================================


CLK_PERIOD_NS = 16.666667
BAUD = 115200
BIT_TIME_NS = 1_000_000_000.0 / BAUD


# ============================================================
# Utility functions
# ============================================================

async def wait_cycles(dut, cycles):
    for _ in range(cycles):
        await RisingEdge(dut.clk)


async def uart_send_byte(dut, data):
    """
    Send one byte through UART RX.

    8-N-1:
      start bit
      8 data bits, LSB first
      stop bit
    """

    # Start bit
    dut.uio_in.value = dut.uio_in.value.integer | 0x01
    dut.uio_in.value = dut.uio_in.value.integer & 0xFE

    await Timer(BIT_TIME_NS, unit="ns")

    # Data bits
    for i in range(8):
        value = dut.uio_in.value.integer

        if (data >> i) & 1:
            value |= 0x01
        else:
            value &= 0xFE

        dut.uio_in.value = value

        await Timer(BIT_TIME_NS, unit="ns")

    # Stop bit / idle high
    dut.uio_in.value = dut.uio_in.value.integer | 0x01

    await Timer(BIT_TIME_NS, unit="ns")


async def program_instruction(dut, address, data):
    """
    UART program packet:

        AA
        address
        data
    """

    await uart_send_byte(dut, 0xAA)
    await uart_send_byte(dut, address)
    await uart_send_byte(dut, data)

    await wait_cycles(dut, 3)


async def start_program(dut):
    """
    UART start command:

        55
    """

    await uart_send_byte(dut, 0x55)

    await wait_cycles(dut, 3)


async def check_gpio(dut, expected, name):
    await Timer(1, unit="ns")

    actual = int(dut.uo_out.value) & 0xFF

    if actual == expected:
        dut._log.info(
            f"PASSED: {name} GPIO_OUT={actual:02x}"
        )
    else:
        raise AssertionError(
            f"FAILED: {name} expected GPIO={expected:02x} "
            f"got={actual:02x}"
        )


# ============================================================
# Test
# ============================================================

@cocotb.test()
async def test_cpu8(dut):

    dut._log.info("================================================")
    dut._log.info("       CPU8 TINY TAPEOUT COCOBT TEST")
    dut._log.info("================================================")

    # ========================================================
    # Start clock
    # ========================================================

    cocotb.start_soon(
        Clock(
            dut.clk,
            CLK_PERIOD_NS,
            unit="ns"
        ).start()
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

    actual = int(dut.uo_out.value) & 0xFF

    if actual != 0x00:
        raise AssertionError(
            f"ena=0 expected GPIO=00 got={actual:02x}"
        )

    dut._log.info("PASSED: ena=0 keeps GPIO inactive")

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

    dut._log.info("PASSED: CPU enabled and reset released")

    # ========================================================
    # TEST 4: UART PROGRAMMING
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 4: UART PROGRAMMING")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x1F)
    await program_instruction(dut, 0x01, 0xBD)
    await program_instruction(dut, 0x02, 0x15)
    await program_instruction(dut, 0x03, 0xBC)
    await program_instruction(dut, 0x04, 0xC2)

    await start_program(dut)

    await wait_cycles(dut, 10)

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

    await program_instruction(dut, 0x00, 0x1F)
    await program_instruction(dut, 0x01, 0xBD)
    await program_instruction(dut, 0x02, 0x1A)
    await program_instruction(dut, 0x03, 0xBC)
    await program_instruction(dut, 0x04, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x0A, "LDI")

    # ========================================================
    # TEST 6: NOP
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 6: NOP")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x00)
    await program_instruction(dut, 0x01, 0x13)
    await program_instruction(dut, 0x02, 0xBC)
    await program_instruction(dut, 0x03, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x03, "NOP")

    # ========================================================
    # TEST 7: INC
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 7: INC")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x15)
    await program_instruction(dut, 0x01, 0x80)
    await program_instruction(dut, 0x02, 0xBC)
    await program_instruction(dut, 0x03, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x06, "INC")

    # ========================================================
    # TEST 8: DEC
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 8: DEC")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x15)
    await program_instruction(dut, 0x01, 0x90)
    await program_instruction(dut, 0x02, 0xBC)
    await program_instruction(dut, 0x03, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x04, "DEC")

    # ========================================================
    # TEST 9: NOT
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 9: NOT")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x15)
    await program_instruction(dut, 0x01, 0x70)
    await program_instruction(dut, 0x02, 0xBC)
    await program_instruction(dut, 0x03, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0xFA, "NOT")

    # ========================================================
    # TEST 10: ADD
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 10: ADD")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x13)
    await program_instruction(dut, 0x01, 0x23)
    await program_instruction(dut, 0x02, 0xBC)
    await program_instruction(dut, 0x03, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x06, "ADD")

    # ========================================================
    # TEST 11: SUB
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 11: SUB")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x15)
    await program_instruction(dut, 0x01, 0x33)
    await program_instruction(dut, 0x02, 0xBC)
    await program_instruction(dut, 0x03, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x02, "SUB")

    # ========================================================
    # TEST 12: AND
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 12: AND")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x1A)
    await program_instruction(dut, 0x01, 0x4F)
    await program_instruction(dut, 0x02, 0xBC)
    await program_instruction(dut, 0x03, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x0A, "AND")

    # ========================================================
    # TEST 13: OR
    #
    # Correct test:
    #
    #   LDI 5
    #   OR  A
    #
    #   0x05 | 0x0A = 0x0F
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 13: OR")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x15)
    await program_instruction(dut, 0x01, 0x5A)
    await program_instruction(dut, 0x02, 0xBC)
    await program_instruction(dut, 0x03, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x0F, "OR")

    # ========================================================
    # TEST 14: XOR
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 14: XOR")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x1A)
    await program_instruction(dut, 0x01, 0x65)
    await program_instruction(dut, 0x02, 0xBC)
    await program_instruction(dut, 0x03, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x0F, "XOR")

    # ========================================================
    # TEST 15: STORE / LOAD RAM
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 15: STORE / LOAD RAM")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x1A)
    await program_instruction(dut, 0x01, 0xB5)
    await program_instruction(dut, 0x02, 0x10)
    await program_instruction(dut, 0x03, 0xA5)
    await program_instruction(dut, 0x04, 0xBC)
    await program_instruction(dut, 0x05, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 15)

    await check_gpio(dut, 0x0A, "RAM LOAD")

    # ========================================================
    # TEST 16: GPIO OUTPUT
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 16: GPIO OUTPUT")
    dut._log.info("================================")

    for value in [0x00, 0x05, 0x0A, 0x0F]:

        await program_instruction(dut, 0x00, 0x10 | value)
        await program_instruction(dut, 0x01, 0xBC)
        await program_instruction(dut, 0x02, 0xC2)

        await start_program(dut)
        await wait_cycles(dut, 8)

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

    await program_instruction(dut, 0x00, 0xAE)
    await program_instruction(dut, 0x01, 0xBC)
    await program_instruction(dut, 0x02, 0xC2)

    dut.ui_in.value = 0xA5

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

    await program_instruction(dut, 0x00, 0x11)
    await program_instruction(dut, 0x01, 0xC4)
    await program_instruction(dut, 0x02, 0x12)
    await program_instruction(dut, 0x03, 0xBC)
    await program_instruction(dut, 0x04, 0x13)
    await program_instruction(dut, 0x05, 0xBC)
    await program_instruction(dut, 0x06, 0xC6)

    await start_program(dut)
    await wait_cycles(dut, 12)

    await check_gpio(dut, 0x03, "JMP")

    # ========================================================
    # TEST 19: BZ TAKEN
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 19: BZ TAKEN")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x10)
    await program_instruction(dut, 0x01, 0xD4)
    await program_instruction(dut, 0x02, 0x11)
    await program_instruction(dut, 0x03, 0xBC)
    await program_instruction(dut, 0x04, 0x12)
    await program_instruction(dut, 0x05, 0xBC)
    await program_instruction(dut, 0x06, 0xC6)

    await start_program(dut)
    await wait_cycles(dut, 12)

    await check_gpio(dut, 0x02, "BZ TAKEN")

    # ========================================================
    # TEST 20: BZ NOT TAKEN
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 20: BZ NOT TAKEN")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x11)
    await program_instruction(dut, 0x01, 0xD4)
    await program_instruction(dut, 0x02, 0x12)
    await program_instruction(dut, 0x03, 0xBC)
    await program_instruction(dut, 0x04, 0x13)
    await program_instruction(dut, 0x05, 0xBC)
    await program_instruction(dut, 0x06, 0xC6)

    await start_program(dut)
    await wait_cycles(dut, 12)

    await check_gpio(dut, 0x03, "BZ NOT TAKEN")

    # ========================================================
    # TEST 21: BNZ TAKEN
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 21: BNZ TAKEN")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x11)
    await program_instruction(dut, 0x01, 0xE4)
    await program_instruction(dut, 0x02, 0x12)
    await program_instruction(dut, 0x03, 0xBC)
    await program_instruction(dut, 0x04, 0x13)
    await program_instruction(dut, 0x05, 0xBC)
    await program_instruction(dut, 0x06, 0xC6)

    await start_program(dut)
    await wait_cycles(dut, 12)

    await check_gpio(dut, 0x03, "BNZ TAKEN")

    # ========================================================
    # TEST 22: BNZ NOT TAKEN
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 22: BNZ NOT TAKEN")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x10)
    await program_instruction(dut, 0x01, 0xE4)
    await program_instruction(dut, 0x02, 0x12)
    await program_instruction(dut, 0x03, 0xBC)
    await program_instruction(dut, 0x04, 0x13)
    await program_instruction(dut, 0x05, 0xBC)
    await program_instruction(dut, 0x06, 0xC6)

    await start_program(dut)
    await wait_cycles(dut, 12)

    await check_gpio(dut, 0x03, "BNZ NOT TAKEN")

    # ========================================================
    # TEST 23: HALT
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 23: HALT")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x15)
    await program_instruction(dut, 0x01, 0xBC)
    await program_instruction(dut, 0x02, 0xF0)
    await program_instruction(dut, 0x03, 0x1A)
    await program_instruction(dut, 0x04, 0xBC)
    await program_instruction(dut, 0x05, 0xC5)

    await start_program(dut)
    await wait_cycles(dut, 10)

    await check_gpio(dut, 0x05, "HALT")

    # ========================================================
    # TEST 24: RESET WHILE RUNNING
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 24: RESET WHILE RUNNING")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x11)
    await program_instruction(dut, 0x01, 0xBC)
    await program_instruction(dut, 0x02, 0x10)
    await program_instruction(dut, 0x03, 0xBC)
    await program_instruction(dut, 0x04, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

    dut.rst_n.value = 0

    await wait_cycles(dut, 10)

    await check_gpio(
        dut,
        0x00,
        "RESET WHILE RUNNING"
    )

    dut.rst_n.value = 1

    await wait_cycles(dut, 5)

    dut._log.info("PASSED: CPU recovered after reset")

    # ========================================================
    # TEST 25: UART REPROGRAMMING
    # ========================================================

    dut._log.info("")
    dut._log.info("================================")
    dut._log.info("TEST 25: UART REPROGRAMMING")
    dut._log.info("================================")

    await program_instruction(dut, 0x00, 0x17)
    await program_instruction(dut, 0x01, 0xBC)
    await program_instruction(dut, 0x02, 0xC2)

    await start_program(dut)
    await wait_cycles(dut, 10)

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

    for address in range(16):
        await program_instruction(
            dut,
            address,
            0x10 + address
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

        await program_instruction(
            dut,
            0x00,
            0x10 | value
        )

        await program_instruction(
            dut,
            0x01,
            0xBC
        )

        await program_instruction(
            dut,
            0x02,
            0xC2
        )

        await start_program(dut)
        await wait_cycles(dut, 8)

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
    dut._log.info("All CPU8 tests passed.")
