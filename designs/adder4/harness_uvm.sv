`timescale 1ns/1ps
`include "uvm_macros.svh"

interface add_if (input logic clk);
  logic [3:0] a = '0, b = '0;
  logic       cin = 1'b0;
  logic       valid = 1'b0;
  logic [3:0] sum;
  logic       cout, overflow;
  logic [3:0] carry;
  // the scoreboard writes its predictions here so they show up in the waveform
  logic [3:0] exp_sum = '0;
  logic       exp_cout = 1'b0, exp_ovf = 1'b0;
  int         errors = 0;

  // @ASSERTIONS
endinterface

package add_tb_pkg;
  import uvm_pkg::*;

  class add_item extends uvm_sequence_item;
    logic [3:0] a, b, sum, carry;
    logic       cin, cout, overflow;
    `uvm_object_utils(add_item)
    function new(string name = "add_item"); super.new(name); endfunction
  endclass

  class base_seq extends uvm_sequence #(add_item);
    `uvm_object_utils(base_seq)
    function new(string name = "base_seq"); super.new(name); endfunction

    task apply(logic [3:0] ia, logic [3:0] ib, logic ic);
      add_item it = add_item::type_id::create("it");
      start_item(it);
      it.a = ia; it.b = ib; it.cin = ic;
      finish_item(it);
    endtask
  endclass

  // @SEQUENCES

  class add_driver extends uvm_driver #(add_item);
    `uvm_component_utils(add_driver)
    virtual add_if vif;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction

    task run_phase(uvm_phase phase);
      forever begin
        @(negedge vif.clk);
        seq_item_port.try_next_item(req);
        vif.valid = (req != null);
        if (req != null) begin
          vif.a = req.a; vif.b = req.b; vif.cin = req.cin;
          seq_item_port.item_done();
        end
      end
    endtask
  endclass

  class add_monitor extends uvm_monitor;
    `uvm_component_utils(add_monitor)
    virtual add_if vif;
    uvm_analysis_port #(add_item) ap;
    function new(string name, uvm_component parent); super.new(name, parent); ap = new("ap", this); endfunction

    task run_phase(uvm_phase phase);
      forever begin
        add_item it;
        @(posedge vif.clk);
        if (!vif.valid) continue;
        #1;
        it = add_item::type_id::create("mon");
        it.a = vif.a; it.b = vif.b; it.cin = vif.cin;
        it.sum = vif.sum; it.cout = vif.cout; it.overflow = vif.overflow; it.carry = vif.carry;
        ap.write(it);
      end
    endtask
  endclass

  class add_scoreboard extends uvm_subscriber #(add_item);
    `uvm_component_utils(add_scoreboard)
    virtual add_if vif;
    int errors, vectors;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction

    function void write(add_item t);
      logic [4:0] exp_full = t.a + t.b + t.cin;
      logic       exp_ovf = (t.a[3] == t.b[3]) && (exp_full[3] != t.a[3]);
      vectors++;
      vif.exp_sum = exp_full[3:0]; vif.exp_cout = exp_full[4]; vif.exp_ovf = exp_ovf;
      if ({t.cout, t.sum} !== exp_full || t.overflow !== exp_ovf) begin
        errors++;
        $display("CHECK_FAIL t=%0t a=%0d b=%0d cin=%0d got sum=%0d cout=%0b ovf=%0b exp sum=%0d cout=%0b ovf=%0b",
                 $time, t.a, t.b, t.cin, t.sum, t.cout, t.overflow, exp_full[3:0], exp_full[4], exp_ovf);
      end
    endfunction
  endclass

  class add_coverage extends uvm_subscriber #(add_item);
    `uvm_component_utils(add_coverage)
    logic [3:0] a, b, carry;
    logic       cin, cout, overflow;

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
      cp_carry: coverpoint carry {
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

    function new(string name, uvm_component parent); super.new(name, parent); cg_adder = new(); endfunction

    function void write(add_item t);
      a = t.a; b = t.b; cin = t.cin; cout = t.cout; overflow = t.overflow; carry = t.carry;
      cg_adder.sample();
    endfunction
  endclass

  class add_agent extends uvm_agent;
    `uvm_component_utils(add_agent)
    uvm_sequencer #(add_item) sqr;
    add_driver  drv;
    add_monitor mon;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      sqr = uvm_sequencer#(add_item)::type_id::create("sqr", this);
      drv = add_driver::type_id::create("drv", this);
      mon = add_monitor::type_id::create("mon", this);
    endfunction
    function void connect_phase(uvm_phase phase); drv.seq_item_port.connect(sqr.seq_item_export); endfunction
  endclass

  class add_env extends uvm_env;
    `uvm_component_utils(add_env)
    add_agent      agent;
    add_scoreboard scb;
    add_coverage   cov;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      agent = add_agent::type_id::create("agent", this);
      scb   = add_scoreboard::type_id::create("scb", this);
      cov   = add_coverage::type_id::create("cov", this);
    endfunction
    function void connect_phase(uvm_phase phase);
      agent.mon.ap.connect(scb.analysis_export);
      agent.mon.ap.connect(cov.analysis_export);
    endfunction
  endclass

  class add_test extends uvm_test;
    `uvm_component_utils(add_test)
    add_env env;
    virtual add_if vif;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction

    function void build_phase(uvm_phase phase);
      env = add_env::type_id::create("env", this);
      if (!uvm_config_db#(virtual add_if)::get(this, "", "vif", vif)) `uvm_fatal("NOVIF", "no virtual interface")
    endfunction

    function void connect_phase(uvm_phase phase);
      env.agent.drv.vif = vif;
      env.agent.mon.vif = vif;
      env.scb.vif = vif;
    endfunction

    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      // @SEQUENCE_CALLS
      repeat (2) @(posedge vif.clk);
      phase.drop_objection(this);
    endtask

    function void report_phase(uvm_phase phase);
      int errors = env.scb.errors + vif.errors;
      $display("VECTORS %0d", env.scb.vectors);
      $display("CHECK_ERRORS %0d", errors);
      if (errors == 0) $display("TEST PASSED");
      else             $display("TEST FAILED");
    endfunction
  endclass
endpackage

module tb;
  import uvm_pkg::*;
  import add_tb_pkg::*;

  logic clk = 1'b0;
  always #5 clk = ~clk;

  add_if vif (clk);

  adder4 dut (.a(vif.a), .b(vif.b), .cin(vif.cin), .sum(vif.sum), .cout(vif.cout), .overflow(vif.overflow));
  assign vif.carry = dut.c[4:1];

  // flat copies so waveforms use the same names as the plain SystemVerilog bench
  wire [3:0] a = vif.a, b = vif.b, sum = vif.sum, exp_sum = vif.exp_sum;
  wire       cin = vif.cin, cout = vif.cout, overflow = vif.overflow, exp_cout = vif.exp_cout, exp_ovf = vif.exp_ovf;

  initial begin
    $dumpfile("wave.vcd");
    $dumpvars(0, tb);
    uvm_config_db#(virtual add_if)::set(null, "*", "vif", vif);
    run_test("add_test");
  end
endmodule
