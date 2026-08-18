module cpu8 (

    input logic clk,
    input logic rst_n,
    input logic ena,

    // Instruction programming
    input logic       program_we,
    input logic [7:0] program_address,
    input logic [7:0] program_data,

    // UART start command
    input logic start_cpu,

    // GPIO
    input logic [7:0] gpio_in,
    output logic [7:0] gpio_out,
    output logic [7:0] gpio_oe

);

    // =========================================================
    // CPU state
    // =========================================================

    logic running;
    logic halted;

    // =========================================================
    // PC
    // =========================================================

    logic [7:0] pc;

    logic [7:0] branch_target;
    logic [7:0] jump_target;

    logic branch_taken;
    logic jump_taken;

    // =========================================================
    // Instruction memory
    // =========================================================

    logic [7:0] instruction;

    instruction_memory8 instruction_memory (

        .clk(clk),

        .pc(pc),
        .instruction(instruction),

        .we(program_we),
        .prog_adress(program_address),
        .prog_data(program_data)

    );

    // =========================================================
    // Decoder
    // =========================================================

    logic [3:0] opcode;
    logic [3:0] operand;

    logic reg_write;
    logic [2:0] alu_control;

    logic mem_read;
    logic mem_write;

    logic jump;
    logic branch_zero;
    logic branch_not_zero;

    logic halt;

    decode8 decoder (

        .instruction(instruction),

        .opcode(opcode),
        .operand(operand),

        .reg_write(reg_write),
        .alu_control(alu_control),

        .mem_read(mem_read),
        .mem_write(mem_write),

        .jump(jump),
        .branch_zero(branch_zero),
        .branch_not_zero(branch_not_zero),

        .halt(halt)

    );

    // =========================================================
    // Accumulator
    // =========================================================

    logic [7:0] accumulator;

    // =========================================================
    // ALU
    // =========================================================

    logic [7:0] alu_a;
    logic [7:0] alu_b;
    logic [7:0] alu_result;

    assign alu_a = accumulator;

    // 4-bit instruction operand becomes an 8-bit immediate.
    assign alu_b = {4'b0000, operand};

    alu8 alu (

        .a(alu_a),
        .b(alu_b),

        .alu_control(alu_control),

        .result(alu_result)

    );

    // =========================================================
    // RAM
    // =========================================================

    logic ram_we;
    logic [4:0] ram_address;

    logic [7:0] ram_write_data;
    logic [7:0] ram_read_data;

    // IMPORTANT:
    // New ram8 has rst_n.
    ram8 data_memory (

        .clk(clk),
        .rst_n(rst_n),

        .we(ram_we),
        .address(ram_address),

        .write_data(ram_write_data),
        .read_data(ram_read_data)

    );

    // =========================================================
    // RAM write control
    // =========================================================

    always_comb begin

        ram_we         = 1'b0;
        ram_address    = {1'b0, operand};
        ram_write_data = accumulator;

        if (ena && running && !halted && mem_write) begin

            // C/D/E are GPIO addresses.
            // Everything else is RAM.
            if ((operand != 4'hC) &&
                (operand != 4'hD) &&
                (operand != 4'hE)) begin

                ram_we = 1'b1;

            end

        end

    end

    // =========================================================
    // GPIO
    //
    // C = GPIO output
    // D = GPIO direction
    // E = GPIO input
    // =========================================================

    logic gpio_we;
    logic gpio_re;

    logic [1:0] gpio_address;

    logic [7:0] gpio_write_data;
    logic [7:0] gpio_read_data;

    gpio8 gpio (

        .clk(clk),
        .rst_n(rst_n),

        .we(gpio_we),
        .re(gpio_re),

        .address(gpio_address),

        .write_data(gpio_write_data),
        .read_data(gpio_read_data),

        .gpio_in(gpio_in),

        .gpio_out(gpio_out),
        .gpio_oe(gpio_oe)

    );

    // =========================================================
    // GPIO access control
    // =========================================================

    always_comb begin

        gpio_we         = 1'b0;
        gpio_re         = 1'b0;

        gpio_address    = 2'b00;
        gpio_write_data = accumulator;

        if (ena && running && !halted) begin

            // STORE C = GPIO output
            if (mem_write && (operand == 4'hC)) begin

                gpio_we      = 1'b1;
                gpio_address = 2'b00;

            end

            // STORE D = GPIO direction
            else if (mem_write && (operand == 4'hD)) begin

                gpio_we      = 1'b1;
                gpio_address = 2'b01;

            end

            // LOAD E = GPIO input
            else if (mem_read && (operand == 4'hE)) begin

                gpio_re      = 1'b1;
                gpio_address = 2'b10;

            end

        end

    end

    // =========================================================
    // PC
    // =========================================================

    pc8 pc_unit (

        .clk(clk),
        .rst_n(rst_n),

        .start_cpu(start_cpu),

        .branch_taken(branch_taken),
        .jump_taken(jump_taken),

        .pc(pc),

        .branch_target(branch_target),
        .jump_target(jump_target)

    );

    // =========================================================
    // Branch / jump logic
    // =========================================================

    always_comb begin

        jump_taken   = 1'b0;
        branch_taken = 1'b0;

        jump_target   = {4'b0000, operand};
        branch_target = {4'b0000, operand};

        if (ena && running && !halted) begin

            if (jump) begin

                jump_taken = 1'b1;

            end

            else if (branch_zero &&
                     (accumulator == 8'h00)) begin

                branch_taken = 1'b1;

            end

            else if (branch_not_zero &&
                     (accumulator != 8'h00)) begin

                branch_taken = 1'b1;

            end

        end

    end

    // =========================================================
    // CPU state
    // =========================================================

    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin

            accumulator <= 8'h00;
            running     <= 1'b0;
            halted      <= 1'b0;

        end

        else if (!ena) begin

            accumulator <= 8'h00;
            running     <= 1'b0;
            halted      <= 1'b0;

        end

        else if (start_cpu) begin

            // UART command 55.
            // PC simultaneously returns to zero.

            accumulator <= 8'h00;
            running     <= 1'b1;
            halted      <= 1'b0;

        end

        else if (running && !halted) begin

            case (opcode)

                // =================================================
                // NOP
                // =================================================

                4'b0000: begin
                end

                // =================================================
                // LDI
                // =================================================

                4'b0001: begin

                    accumulator <= {
                        4'b0000,
                        operand
                    };

                end

                // =================================================
                // ADD
                // =================================================

                4'b0010: begin

                    accumulator <= alu_result;

                end

                // =================================================
                // SUB
                // =================================================

                4'b0011: begin

                    accumulator <= alu_result;

                end

                // =================================================
                // AND
                // =================================================

                4'b0100: begin

                    accumulator <= alu_result;

                end

                // =================================================
                // OR
                // =================================================

                4'b0101: begin

                    accumulator <= alu_result;

                end

                // =================================================
                // XOR
                // =================================================

                4'b0110: begin

                    accumulator <= alu_result;

                end

                // =================================================
                // NOT
                // =================================================

                4'b0111: begin

                    accumulator <= alu_result;

                end

                // =================================================
                // INC
                // =================================================

                4'b1000: begin

                    accumulator <= alu_result;

                end

                // =================================================
                // DEC
                // =================================================

                4'b1001: begin

                    accumulator <= alu_result;

                end

                // =================================================
                // LOAD
                // =================================================

                4'b1010: begin

                    if (mem_read) begin

                        // GPIO input
                        if (operand == 4'hE) begin

                            accumulator <= gpio_read_data;

                        end

                        // RAM
                        else begin

                            accumulator <= ram_read_data;

                        end

                    end

                end

                // =================================================
                // STORE
                // =================================================

                4'b1011: begin

                    // RAM/GPIO write logic handles the write.
                    // Nothing additional required here.

                end

                // =================================================
                // JMP
                // =================================================

                4'b1100: begin

                    // PC handles jump.

                end

                // =================================================
                // BZ
                // =================================================

                4'b1101: begin

                    // PC handles branch.

                end

                // =================================================
                // BNZ
                // =================================================

                4'b1110: begin

                    // PC handles branch.

                end

                // =================================================
                // HALT
                // =================================================

                4'b1111: begin

                    halted <= 1'b1;

                end

                default: begin
                end

            endcase

        end

    end

endmodule