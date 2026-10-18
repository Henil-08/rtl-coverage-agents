`timescale 1ns/1ps
`include "uvm_macros.svh"

interface dp_if (input logic clk);
  logic       en_a = 0, we_a = 0, en_b = 0, we_b = 0;
  logic       valid = 0;
  logic [3:0] addr_a = '0, addr_b = '0;
  logic [7:0] wdata_a = '0, wdata_b = '0;
  logic [7:0] rdata_a, rdata_b;
  // the scoreboard writes its predictions here so they show up in the waveform
  logic [7:0] exp_a = '0, exp_b = '0;
  int         errors = 0;

  // @ASSERTIONS
endinterface

package dp_tb_pkg;
  import uvm_pkg::*;

  localparam int DEPTH = 16;
  typedef enum logic [1:0] {IDLE, RD, WR} op_e;
  typedef enum logic [2:0] {NO_CONFLICT, RR_SAME, WR_SAME, RW_SAME, WW_SAME} conflict_e;
  typedef enum logic [1:0] {NO_RAW, AFTER_A, AFTER_B} raw_e;

  // One clock cycle on both ports.
  class dp_item extends uvm_sequence_item;
    op_e        op_a = IDLE, op_b = IDLE;
    logic [3:0] addr_a, addr_b;
    logic [7:0] data_a, data_b;
    logic [7:0] rdata_a, rdata_b;
    `uvm_object_utils(dp_item)
    function new(string name = "dp_item"); super.new(name); endfunction
  endclass

  class base_seq extends uvm_sequence #(dp_item);
    `uvm_object_utils(base_seq)
    function new(string name = "base_seq"); super.new(name); endfunction

    task cycle(op_e oa, logic [3:0] aa, logic [7:0] da, op_e ob, logic [3:0] ab, logic [7:0] db);
      dp_item it = dp_item::type_id::create("it");
      start_item(it);
      it.op_a = oa; it.addr_a = aa; it.data_a = da;
      it.op_b = ob; it.addr_b = ab; it.data_b = db;
      finish_item(it);
    endtask

    task write_a(logic [3:0] addr, logic [7:0] data); cycle(WR, addr, data, IDLE, 0, 0); endtask
    task read_a(logic [3:0] addr);                    cycle(RD, addr, 0, IDLE, 0, 0);    endtask
    task write_b(logic [3:0] addr, logic [7:0] data); cycle(IDLE, 0, 0, WR, addr, data); endtask
    task read_b(logic [3:0] addr);                    cycle(IDLE, 0, 0, RD, addr, 0);    endtask
    task idle();                                      cycle(IDLE, 0, 0, IDLE, 0, 0);     endtask
  endclass

  // @SEQUENCES

  class dp_driver extends uvm_driver #(dp_item);
    `uvm_component_utils(dp_driver)
    virtual dp_if vif;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction

    task run_phase(uvm_phase phase);
      forever begin
        @(negedge vif.clk);
        seq_item_port.try_next_item(req);
        vif.valid = (req != null);
        if (req == null) begin
          vif.en_a = 0; vif.we_a = 0; vif.en_b = 0; vif.we_b = 0;
        end else begin
          vif.en_a = (req.op_a != IDLE); vif.we_a = (req.op_a == WR); vif.addr_a = req.addr_a; vif.wdata_a = req.data_a;
          vif.en_b = (req.op_b != IDLE); vif.we_b = (req.op_b == WR); vif.addr_b = req.addr_b; vif.wdata_b = req.data_b;
          seq_item_port.item_done();
        end
      end
    endtask
  endclass

  // Samples the inputs the RAM captures on each rising edge and the read data it returns.
  class dp_monitor extends uvm_monitor;
    `uvm_component_utils(dp_monitor)
    virtual dp_if vif;
    uvm_analysis_port #(dp_item) ap;
    function new(string name, uvm_component parent); super.new(name, parent); ap = new("ap", this); endfunction

    task run_phase(uvm_phase phase);
      forever begin
        dp_item it;
        @(posedge vif.clk);
        if (!vif.valid) continue;
        it = dp_item::type_id::create("mon");
        it.op_a = !vif.en_a ? IDLE : (vif.we_a ? WR : RD);
        it.op_b = !vif.en_b ? IDLE : (vif.we_b ? WR : RD);
        it.addr_a = vif.addr_a; it.data_a = vif.wdata_a;
        it.addr_b = vif.addr_b; it.data_b = vif.wdata_b;
        #1;
        it.rdata_a = vif.rdata_a; it.rdata_b = vif.rdata_b;
        ap.write(it);
      end
    endtask
  endclass

  // Reference model: read-first on both ports, port A wins write collisions, rdata holds while idle.
  class dp_scoreboard extends uvm_subscriber #(dp_item);
    `uvm_component_utils(dp_scoreboard)
    virtual dp_if vif;
    logic [7:0] model [DEPTH];
    bit         written [DEPTH];
    logic [7:0] exp_a, exp_b;
    bit         known_a, known_b;
    int         errors, cycles;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction

    function void write(dp_item t);
      if (t.op_a != IDLE) begin exp_a = model[t.addr_a]; known_a = written[t.addr_a]; end
      if (t.op_b != IDLE) begin exp_b = model[t.addr_b]; known_b = written[t.addr_b]; end
      if (t.op_b == WR && !(t.op_a == WR && t.addr_a == t.addr_b)) begin
        model[t.addr_b] = t.data_b; written[t.addr_b] = 1;
      end
      if (t.op_a == WR) begin model[t.addr_a] = t.data_a; written[t.addr_a] = 1; end
      cycles++;
      vif.exp_a = exp_a;
      vif.exp_b = exp_b;
      if (known_a && t.rdata_a !== exp_a) begin
        errors++;
        $display("CHECK_FAIL t=%0t cycle=%0d port=A op=%s addr=%0d got=%02h exp=%02h", $time, cycles, t.op_a.name(), t.addr_a, t.rdata_a, exp_a);
      end
      if (known_b && t.rdata_b !== exp_b) begin
        errors++;
        $display("CHECK_FAIL t=%0t cycle=%0d port=B op=%s addr=%0d got=%02h exp=%02h", $time, cycles, t.op_b.name(), t.addr_b, t.rdata_b, exp_b);
      end
    endfunction
  endclass

  class dp_coverage extends uvm_subscriber #(dp_item);
    `uvm_component_utils(dp_coverage)
    op_e        op_a = IDLE, op_b = IDLE;
    logic [3:0] addr_a, addr_b;
    logic [7:0] wdata_a, wdata_b;
    conflict_e  conflict = NO_CONFLICT;
    raw_e       raw_a = NO_RAW, raw_b = NO_RAW;
    bit         last_wa, last_wb;
    logic [3:0] last_waddr_a, last_waddr_b;

    covergroup cg_dpram;
      option.per_instance = 1;
      cp_op_a: coverpoint op_a { bins idle = {IDLE}; bins read = {RD}; bins write = {WR}; }
      cp_op_b: coverpoint op_b { bins idle = {IDLE}; bins read = {RD}; bins write = {WR}; }
      cx_ops:  cross cp_op_a, cp_op_b;
      cp_raddr_a: coverpoint addr_a iff (op_a == RD) { bins zero = {0}; bins max = {DEPTH-1}; bins mid = {[1:DEPTH-2]}; }
      cp_waddr_a: coverpoint addr_a iff (op_a == WR) { bins zero = {0}; bins max = {DEPTH-1}; bins mid = {[1:DEPTH-2]}; }
      cp_raddr_b: coverpoint addr_b iff (op_b == RD) { bins zero = {0}; bins max = {DEPTH-1}; bins mid = {[1:DEPTH-2]}; }
      cp_waddr_b: coverpoint addr_b iff (op_b == WR) { bins zero = {0}; bins max = {DEPTH-1}; bins mid = {[1:DEPTH-2]}; }
      cp_wdata_a: coverpoint wdata_a iff (op_a == WR) {
        bins zeros       = {8'h00};
        bins ones        = {8'hFF};
        bins alternating = {8'hAA, 8'h55};
        bins other       = {[8'h01:8'h54], [8'h56:8'hA9], [8'hAB:8'hFE]};
      }
      cp_wdata_b: coverpoint wdata_b iff (op_b == WR) {
        bins zeros       = {8'h00};
        bins ones        = {8'hFF};
        bins alternating = {8'hAA, 8'h55};
        bins other       = {[8'h01:8'h54], [8'h56:8'hA9], [8'hAB:8'hFE]};
      }
      cp_conflict: coverpoint conflict {
        bins none    = {NO_CONFLICT};
        bins rr_same = {RR_SAME};
        bins wr_same = {WR_SAME};
        bins rw_same = {RW_SAME};
        bins ww_same = {WW_SAME};
      }
      cp_raw_a: coverpoint raw_a { bins after_a = {AFTER_A}; bins after_b = {AFTER_B}; }
      cp_raw_b: coverpoint raw_b { bins after_a = {AFTER_A}; bins after_b = {AFTER_B}; }
    endgroup

    function new(string name, uvm_component parent); super.new(name, parent); cg_dpram = new(); endfunction

    function raw_e raw_of(op_e op, logic [3:0] addr);
      if (op != RD) return NO_RAW;
      if (last_wa && last_waddr_a == addr) return AFTER_A;
      if (last_wb && last_waddr_b == addr) return AFTER_B;
      return NO_RAW;
    endfunction

    function void write(dp_item t);
      op_a = t.op_a; op_b = t.op_b;
      addr_a = t.addr_a; addr_b = t.addr_b; wdata_a = t.data_a; wdata_b = t.data_b;
      if (op_a == IDLE || op_b == IDLE || addr_a != addr_b) conflict = NO_CONFLICT;
      else if (op_a == RD && op_b == RD)                    conflict = RR_SAME;
      else if (op_a == WR && op_b == RD)                    conflict = WR_SAME;
      else if (op_a == RD && op_b == WR)                    conflict = RW_SAME;
      else                                                  conflict = WW_SAME;
      raw_a = raw_of(op_a, addr_a);
      raw_b = raw_of(op_b, addr_b);
      cg_dpram.sample();
      last_wa = (op_a == WR); last_waddr_a = addr_a;
      last_wb = (op_b == WR && !(op_a == WR && addr_a == addr_b)); last_waddr_b = addr_b;
    endfunction
  endclass

  class dp_agent extends uvm_agent;
    `uvm_component_utils(dp_agent)
    uvm_sequencer #(dp_item) sqr;
    dp_driver  drv;
    dp_monitor mon;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      sqr = uvm_sequencer#(dp_item)::type_id::create("sqr", this);
      drv = dp_driver::type_id::create("drv", this);
      mon = dp_monitor::type_id::create("mon", this);
    endfunction
    function void connect_phase(uvm_phase phase); drv.seq_item_port.connect(sqr.seq_item_export); endfunction
  endclass

  class dp_env extends uvm_env;
    `uvm_component_utils(dp_env)
    dp_agent      agent;
    dp_scoreboard scb;
    dp_coverage   cov;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      agent = dp_agent::type_id::create("agent", this);
      scb   = dp_scoreboard::type_id::create("scb", this);
      cov   = dp_coverage::type_id::create("cov", this);
    endfunction
    function void connect_phase(uvm_phase phase);
      agent.mon.ap.connect(scb.analysis_export);
      agent.mon.ap.connect(cov.analysis_export);
    endfunction
  endclass

  class dp_test extends uvm_test;
    `uvm_component_utils(dp_test)
    dp_env env;
    virtual dp_if vif;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction

    function void build_phase(uvm_phase phase);
      env = dp_env::type_id::create("env", this);
      if (!uvm_config_db#(virtual dp_if)::get(this, "", "vif", vif)) `uvm_fatal("NOVIF", "no virtual interface")
    endfunction

    function void connect_phase(uvm_phase phase);
      env.agent.drv.vif = vif;
      env.agent.mon.vif = vif;
      env.scb.vif = vif;
    endfunction

    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      // @SEQUENCE_CALLS
      repeat (3) @(posedge vif.clk);
      phase.drop_objection(this);
    endtask

    function void report_phase(uvm_phase phase);
      int errors = env.scb.errors + vif.errors;
      $display("CYCLES %0d", env.scb.cycles);
      $display("CHECK_ERRORS %0d", errors);
      if (errors == 0) $display("TEST PASSED");
      else             $display("TEST FAILED");
    endfunction
  endclass
endpackage

module tb;
  import uvm_pkg::*;
  import dp_tb_pkg::*;

  logic clk = 1'b0;
  always #5 clk = ~clk;

  dp_if vif (clk);

  dpram #(.DATA_W(8), .ADDR_W(4)) dut (
    .clk(clk),
    .en_a(vif.en_a), .we_a(vif.we_a), .addr_a(vif.addr_a), .wdata_a(vif.wdata_a), .rdata_a(vif.rdata_a),
    .en_b(vif.en_b), .we_b(vif.we_b), .addr_b(vif.addr_b), .wdata_b(vif.wdata_b), .rdata_b(vif.rdata_b)
  );

  // flat copies so waveforms use the same names as the plain SystemVerilog bench
  wire       en_a = vif.en_a, we_a = vif.we_a, en_b = vif.en_b, we_b = vif.we_b;
  wire [3:0] addr_a = vif.addr_a, addr_b = vif.addr_b;
  wire [7:0] wdata_a = vif.wdata_a, wdata_b = vif.wdata_b, rdata_a = vif.rdata_a, rdata_b = vif.rdata_b;
  wire [7:0] exp_a = vif.exp_a, exp_b = vif.exp_b;

  initial begin
    $dumpfile("wave.vcd");
    $dumpvars(0, tb);
    uvm_config_db#(virtual dp_if)::set(null, "*", "vif", vif);
    run_test("dp_test");
  end
endmodule
