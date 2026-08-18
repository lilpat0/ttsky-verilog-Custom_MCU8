module pc8 (

    input logic clk,
    input logic rst_n,

    // CPU start/restart
    input logic start_cpu,

    // Branch/jump
    input logic branch_taken,
    input logic jump_taken,

    input logic [7:0] branch_target,
    input logic [7:0] jump_target,

    output logic [7:0] pc

);

    logic [7:0] next_pc;

    always_comb begin

        if (branch_taken) begin

            next_pc = branch_target;

        end

        else if (jump_taken) begin

            next_pc = jump_target;

        end

        else begin

            next_pc = pc + 8'd1;

        end

    end

    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin

            pc <= 8'h00;

        end

        else if (start_cpu) begin

            pc <= 8'h00;

        end

        else begin

            pc <= next_pc;

        end

    end

endmodule