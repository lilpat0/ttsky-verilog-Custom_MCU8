module pc8 (

    input logic clk,
    input logic rst_n,
    input logic ena,

    // CPU start/restart
    input logic start_cpu,

    // Freeze the PC while the CPU is halted (chip still enabled,
    // execution stopped). Keeps PC parked at the halt address
    // instead of free-running through instruction memory.
    input logic halted,

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

        else if (!ena) begin

            pc <= 8'h00;

        end

        else if (start_cpu) begin

            pc <= 8'h00;

        end

        else if (halted) begin

            // Hold: don't keep fetching past a HALT.
            pc <= pc;

        end

        else begin

            pc <= next_pc;

        end

    end

endmodule
