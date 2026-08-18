// Programmable 8-bit GPIO peripheral
module gpio8 (

    // Control
    input logic       clk,
    input logic       rst_n,

    // CPU interface
    input logic       we,
    input logic       re,
    input logic [1:0] address,

    input logic [7:0] write_data,
    output logic [7:0] read_data,

    // Physical GPIO pins
    input  logic [7:0] gpio_in,
    output logic [7:0] gpio_out,
    output logic [7:0] gpio_oe

);

    // =========================================================
    // GPIO Registers
    // =========================================================

    // Output value register
    logic [7:0] output_reg;

    // Direction register
    // 1 = output
    // 0 = input
    logic [7:0] direction_reg;


    // =========================================================
    // Register Addresses
    // =========================================================

    localparam logic [1:0] GPIO_OUTPUT    = 2'b00;
    localparam logic [1:0] GPIO_DIRECTION = 2'b01;
    localparam logic [1:0] GPIO_INPUT     = 2'b10;


    // =========================================================
    // Reset / Write Registers
    // =========================================================

    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin

            output_reg   <= 8'b0;
            direction_reg <= 8'b0;

        end

        else begin

            if (we) begin

                case (address)

                    // GPIO output register
                    GPIO_OUTPUT: begin
                        output_reg <= write_data;
                    end

                    // GPIO direction register
                    GPIO_DIRECTION: begin
                        direction_reg <= write_data;
                    end

                    default: begin
                        // INPUT register is read-only
                    end

                endcase

            end

        end

    end


    // =========================================================
    // Read Registers
    // =========================================================

    always_comb begin

        read_data = 8'b0;

        if (re) begin

            case (address)

                // Read output register
                GPIO_OUTPUT: begin
                    read_data = output_reg;
                end

                // Read direction register
                GPIO_DIRECTION: begin
                    read_data = direction_reg;
                end

                // Read physical GPIO inputs
                GPIO_INPUT: begin
                    read_data = gpio_in;
                end

                default: begin
                    read_data = 8'b0;
                end

            endcase

        end

    end


    // =========================================================
    // Physical GPIO Outputs
    // =========================================================

    assign gpio_out = output_reg;

    assign gpio_oe = direction_reg;


endmodule