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

        .gpio_oe()

    );

    // =========================================================
    // Bidirectional pins
    //
    // uio_in[0] = UART RX
    //
    // No UART TX currently implemented.
    // =========================================================

    assign uio_out = 8'h00;
    assign uio_oe  = 8'h00;

endmodule