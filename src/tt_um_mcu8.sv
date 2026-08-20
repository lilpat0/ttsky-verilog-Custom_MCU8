module tt_um_cpu8 (

    input wire [7:0] ui_in,
    output wire [7:0] uo_out,

    input wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,

    input wire ena,
    input wire clk,
    input wire rst_n

);

    // =========================================================
    // UART programming signals
    // =========================================================

    wire       program_we;
    wire [7:0] program_address;
    wire [7:0] program_data;

    wire start_cpu;

    // Value written via STORE 0xD (the fixed uio output port).
    // Only 4 bits -- this is the upper nibble of the accumulator,
    // driving the only output-direction half of the fixed
    // 4-out/4-in uio split.
    wire [3:0] uio_store_data;

    // =========================================================
    // UART
    //
    // uio_in[0] = UART RX
    // =========================================================

    uart_programmer8 #(
        .CLK_FREQ  (60_000_000),
        .BAUD_RATE (115200)
    ) uart_programmer (

        .clk(clk),
        .rst_n(rst_n),
        .ena(ena),

        .rx(uio_in[0]),

        .program_we(program_we),
        .program_address(program_address),
        .program_data(program_data),

        .start_cpu(start_cpu)

    );

    // =========================================================
    // CPU
    // =========================================================

    cpu8 cpu (

        .clk(clk),
        .rst_n(rst_n),
        .ena(ena),

        .program_we(program_we),
        .program_address(program_address),
        .program_data(program_data),

        .start_cpu(start_cpu),

        .gpio_in(ui_in),

        .gpio_out(uo_out),

        .gpio_oe(),

        .uio_store(uio_store_data)

    );

    // =========================================================
    // Bidirectional pins
    //
    // Fixed 4-out/4-in split, hardwired (not reset-dependent):
    //   uio_out[7:4] / uio_oe[7:4] = output, driven by STORE 0xD
    //   uio_in[3:0]  / uio_oe[3:0] = input  (uio_in[0] = UART RX)
    //
    // No UART TX currently implemented.
    // =========================================================

    assign uio_out = {uio_store_data, 4'b0000};
    assign uio_oe  = 8'hF0;

endmodule
