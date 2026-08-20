module tt_um_cpu8 (

    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,

    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,

    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n

);

    // =========================================================
    // UART programming interface
    //
    // uio_in[0] = UART RX
    // =========================================================

    wire       program_we;
    wire [7:0] program_address;
    wire [7:0] program_data;
    wire       start_cpu;

    // =========================================================
    // UIO fixed mapping
    //
    // uio_in[3:1]  = 3 general-purpose inputs
    // uio_in[0]    = UART RX
    //
    // uio_out[7:4] = 4 general-purpose outputs
    // uio_out[3:0] = 0
    //
    // uio_oe[7:4]  = outputs
    // uio_oe[3:0]  = inputs
    // =========================================================

    wire [3:0] uio_store_data;

    // =========================================================
    // UART programmer
    // =========================================================

    uart_programmer8 #(
        .CLK_FREQ  (60_000_000),
        .BAUD_RATE (115200)
    ) uart_programmer (
        .clk              (clk),
        .rst_n            (rst_n),
        .ena              (ena),

        .rx               (uio_in[0]),

        .program_we       (program_we),
        .program_address  (program_address),
        .program_data     (program_data),

        .start_cpu        (start_cpu)
    );

    // =========================================================
    // CPU
    // =========================================================

    cpu8 cpu (
        .clk              (clk),
        .rst_n            (rst_n),
        .ena              (ena),

        .program_we       (program_we),
        .program_address  (program_address),
        .program_data     (program_data),

        .start_cpu        (start_cpu),

        .gpio_in          (ui_in),
        .gpio_out         (uo_out),
        .gpio_oe          (),

        .uio_store        (uio_store_data),
        .uio_general_in   (uio_in[3:1])
    );

    // =========================================================
    // Physical UIO outputs
    //
    // STORE 0xD -> uio_store_data
    //
    // Four output pins:
    //     uio_out[7:4]
    //
    // Four input pins:
    //     uio_in[3:0]
    // =========================================================

    assign uio_out[7:4] = uio_store_data;
    assign uio_out[3:0] = 4'b0000;

    // Upper four UIO pins are outputs.
    // Lower four UIO pins are inputs.
    assign uio_oe[7:4] = 4'b1111;
    assign uio_oe[3:0] = 4'b0000;

endmodule
