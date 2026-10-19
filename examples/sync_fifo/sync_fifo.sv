// Synchronous FIFO, single clock, active-low synchronous reset.
// A push when full and a pop when empty are ignored.
module sync_fifo #(
    parameter int WIDTH = 8,
    parameter int DEPTH = 8
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             push,
    input  logic [WIDTH-1:0] din,
    input  logic             pop,
    output logic [WIDTH-1:0] dout,
    output logic             full,
    output logic             empty,
    output logic [3:0]       count
);

    logic [WIDTH-1:0] mem [DEPTH];
    logic [2:0]       wr_ptr, rd_ptr;

    logic do_push, do_pop;
    assign do_push = push && !full;
    assign do_pop  = pop && !empty;

    assign full  = (count == DEPTH);
    assign empty = (count == 0);
    assign dout  = mem[rd_ptr];

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
            count  <= '0;
        end else begin
            if (do_push) begin
                mem[wr_ptr] <= din;
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (do_pop) rd_ptr <= rd_ptr + 1'b1;
            if (do_push && !do_pop) count <= count + 1'b1;
            else if (do_pop && !do_push) count <= count - 1'b1;
        end
    end

endmodule
