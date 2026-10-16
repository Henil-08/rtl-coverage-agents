`timescale 1ns/1ps
module tb;
  logic [3:0] a, b;
  logic       cin;
  logic [3:0] sum;
  logic       cout, overflow;
  logic       clk = 1'b0;
  int         errors = 0;
  int         vectors = 0;

  adder4 dut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout), .overflow(overflow));

  always #5 clk = ~clk;

  covergroup cg_adder;
    option.per_instance = 1;
    cp_a: coverpoint a {
      bins zero = {4'd0};
      bins max  = {4'd15};
      bins low  = {[4'd1:4'd7]};
      bins high = {[4'd8:4'd14]};
    }
    cp_b: coverpoint b {
      bins zero = {4'd0};
      bins max  = {4'd15};
      bins low  = {[4'd1:4'd7]};
      bins high = {[4'd8:4'd14]};
    }
    cp_cin:  coverpoint cin      { bins c0 = {1'b0}; bins c1 = {1'b1}; }
    cp_cout: coverpoint cout     { bins no_carry = {1'b0}; bins carry = {1'b1}; }
    cp_ovf:  coverpoint overflow { bins no_ovf = {1'b0}; bins ovf = {1'b1}; }
    cp_ovf_sign: coverpoint {a[3], b[3], overflow} {
      bins pos_ovf = {3'b001};
      bins neg_ovf = {3'b111};
    }
    cp_prop: coverpoint (a ^ b) {
      bins none_prop    = {4'h0};
      bins partial_prop = {[4'h1:4'hE]};
      bins all_prop     = {4'hF};
    }
    cp_carry: coverpoint dut.c[4:1] {
      bins          none        = {4'b0000};
      wildcard bins c1          = {4'b???1};
      wildcard bins c2          = {4'b??1?};
      wildcard bins c3          = {4'b?1??};
      wildcard bins c4          = {4'b1???};
      bins          full_ripple = {4'b1111};
    }
    cx_a_b:      cross cp_a, cp_b;
    cx_cin_cout: cross cp_cin, cp_cout;
  endgroup
  cg_adder cg = new();

  // drive on negedge so the SVA at posedge sees settled values
  task automatic apply(input logic [3:0] ia, input logic [3:0] ib, input logic ic);
    logic [4:0] exp_full;
    logic       exp_ovf;
    @(negedge clk);
    a = ia; b = ib; cin = ic;
    @(posedge clk);
    #1;
    exp_full = ia + ib + ic;
    exp_ovf  = (ia[3] == ib[3]) && (exp_full[3] != ia[3]);
    vectors++;
    if ({cout, sum} !== exp_full || overflow !== exp_ovf) begin
      errors++;
      $display("CHECK_FAIL a=%0d b=%0d cin=%0d got sum=%0d cout=%0b ovf=%0b exp sum=%0d cout=%0b ovf=%0b",
               ia, ib, ic, sum, cout, overflow, exp_full[3:0], exp_full[4], exp_ovf);
    end
    cg.sample();
  endtask

  // @ASSERTIONS

  // @STIMULUS_TASKS

  initial begin
    a = '0; b = '0; cin = 1'b0;
    // @STIMULUS_CALLS
    @(negedge clk);
    $display("VECTORS %0d", vectors);
    $display("CHECK_ERRORS %0d", errors);
    if (errors == 0) $display("TEST PASSED");
    else             $display("TEST FAILED");
    $finish;
  end
endmodule
