module uart_programmer8 #(
    parameter integer CLK_FREQ  = 60_000_000,
    parameter integer BAUD_RATE = 115200
)(
    input logic clk,
    input logic rst_n,
    input logic ena,

    // UART RX
    input logic rx,

    // Instruction programming
    output logic       program_we,
    output logic [7:0] program_address,
    output logic [7:0] program_data,

    // CPU start pulse
    output logic start_cpu
);

    // =========================================================
    // UART timing
    // =========================================================

    localparam integer CLKS_PER_BIT = CLK_FREQ / BAUD_RATE;
    localparam integer BAUD_CNT_W   = $clog2(CLKS_PER_BIT + 1);

    // =========================================================
    // RX synchronizer
    // =========================================================

    logic rx_sync1;
    logic rx_sync2;

    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin

            rx_sync1 <= 1'b1;
            rx_sync2 <= 1'b1;

        end

        else if (!ena) begin

            rx_sync1 <= 1'b1;
            rx_sync2 <= 1'b1;

        end

        else begin

            rx_sync1 <= rx;
            rx_sync2 <= rx_sync1;

        end

    end

    // =========================================================
    // UART RX state machine
    // =========================================================

    localparam logic [1:0]
        RX_IDLE  = 2'd0,
        RX_START = 2'd1,
        RX_DATA  = 2'd2,
        RX_STOP  = 2'd3;

    logic [1:0] rx_state;

    logic [BAUD_CNT_W-1:0] baud_counter;

    logic [2:0] bit_counter;

    logic [7:0] rx_shift;
    logic [7:0] rx_byte;

    logic rx_byte_valid;

    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin

            rx_state      <= RX_IDLE;
            baud_counter  <= '0;
            bit_counter   <= 3'd0;
            rx_shift      <= 8'h00;
            rx_byte       <= 8'h00;
            rx_byte_valid <= 1'b0;

        end

        else if (!ena) begin

            rx_state      <= RX_IDLE;
            baud_counter  <= '0;
            bit_counter   <= 3'd0;
            rx_shift      <= 8'h00;
            rx_byte       <= 8'h00;
            rx_byte_valid <= 1'b0;

        end

        else begin

            rx_byte_valid <= 1'b0;

            case (rx_state)

                RX_IDLE: begin

                    baud_counter <= '0;
                    bit_counter  <= 3'd0;

                    if (rx_sync2 == 1'b0) begin

                        baud_counter <= CLKS_PER_BIT / 2;
                        rx_state <= RX_START;

                    end

                end

                RX_START: begin

                    if (baud_counter == 0) begin

                        if (rx_sync2 == 1'b0) begin

                            baud_counter <= CLKS_PER_BIT - 1;
                            bit_counter  <= 3'd0;

                            rx_state <= RX_DATA;

                        end

                        else begin

                            rx_state <= RX_IDLE;

                        end

                    end

                    else begin

                        baud_counter <= baud_counter - 1'b1;

                    end

                end

                RX_DATA: begin

                    if (baud_counter == 0) begin

                        rx_shift[bit_counter] <= rx_sync2;

                        baud_counter <= CLKS_PER_BIT - 1;

                        if (bit_counter == 3'd7) begin

                            rx_state <= RX_STOP;

                        end

                        else begin

                            bit_counter <= bit_counter + 1'b1;

                        end

                    end

                    else begin

                        baud_counter <= baud_counter - 1'b1;

                    end

                end

                RX_STOP: begin

                    if (baud_counter == 0) begin

                        if (rx_sync2 == 1'b1) begin

                            rx_byte <= rx_shift;
                            rx_byte_valid <= 1'b1;

                        end

                        rx_state <= RX_IDLE;

                    end

                    else begin

                        baud_counter <= baud_counter - 1'b1;

                    end

                end

                default: begin

                    rx_state <= RX_IDLE;

                end

            endcase

        end

    end

    // =========================================================
    // Programming protocol
    //
    // AA address data
    //
    // 55
    //     start CPU
    //
    // =========================================================

    localparam logic [1:0]
        CMD_IDLE    = 2'd0,
        CMD_ADDRESS = 2'd1,
        CMD_DATA    = 2'd2;

    logic [1:0] cmd_state;

    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin

            cmd_state <= CMD_IDLE;

            program_we      <= 1'b0;
            program_address <= 8'h00;
            program_data    <= 8'h00;

            start_cpu <= 1'b0;

        end

        else if (!ena) begin

            cmd_state <= CMD_IDLE;

            program_we <= 1'b0;
            start_cpu  <= 1'b0;

        end

        else begin

            // Both are one-clock pulses.

            program_we <= 1'b0;
            start_cpu  <= 1'b0;

            if (rx_byte_valid) begin

                case (cmd_state)

                    CMD_IDLE: begin

                        if (rx_byte == 8'hAA) begin

                            cmd_state <= CMD_ADDRESS;

                        end

                        else if (rx_byte == 8'h55) begin

                            start_cpu <= 1'b1;

                            cmd_state <= CMD_IDLE;

                        end

                    end

                    CMD_ADDRESS: begin

                        program_address <= rx_byte;

                        cmd_state <= CMD_DATA;

                    end

                    CMD_DATA: begin

                        program_data <= rx_byte;
                        program_we   <= 1'b1;

                        cmd_state <= CMD_IDLE;

                    end

                    default: begin

                        cmd_state <= CMD_IDLE;

                    end

                endcase

            end

        end

    end

endmodule