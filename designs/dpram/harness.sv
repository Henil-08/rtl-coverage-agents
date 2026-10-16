`timescale 1ns/1ps
module tb;
  localparam int DW    = 8;
  localparam int AW    = 4;
  localparam int DEPTH = 1 << AW;

  typedef enum logic [1:0] {IDLE, RD, WR} op_e;
  typedef enum logic [2:0] {NO_CONFLICT, RR_SAME, WR_SAME, RW_SAME, WW_SAME} conflict_e;
  typedef enum logic [1:0] {NO_RAW, AFTER_A, AFTER_B} raw_e;

  logic          clk = 1'b0;
  logic          en_a = 0, we_a = 0, en_b = 0, we_b = 0;
  logic [AW-1:0] addr_a = '0, addr_b = '0;
  logic [DW-1:0] wdata_a = '0, wdata_b = '0;
  logic [DW-1:0] rdata_a, rdata_b;
  int            errors = 0;
  int            cycles = 0;

  dpram #(.DATA_W(DW), .ADDR_W(AW)) dut (.*);

  always #5 clk = ~clk;

  // reference model
  logic [DW-1:0] model [DEPTH];
  bit            written [DEPTH];
  logic [DW-1:0] exp_a, exp_b;
  bit            known_a = 0, known_b = 0;

  // what the covergroup looks at for the current cycle
  op_e           op_a = IDLE, op_b = IDLE;
  conflict_e     conflict = NO_CONFLICT;
  raw_e          raw_a = NO_RAW, raw_b = NO_RAW;
  bit            last_wa = 0, last_wb = 0;
  logic [AW-1:0] last_waddr_a, last_waddr_b;

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
      bins zeros   = {8'h00};
      bins ones    = {8'hFF};
      bins alternating = {8'hAA, 8'h55};
      bins other   = {[8'h01:8'h54], [8'h56:8'hA9], [8'hAB:8'hFE]};
    }
    cp_wdata_b: coverpoint wdata_b iff (op_b == WR) {
      bins zeros   = {8'h00};
      bins ones    = {8'hFF};
      bins alternating = {8'hAA, 8'h55};
      bins other   = {[8'h01:8'h54], [8'h56:8'hA9], [8'hAB:8'hFE]};
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
  cg_dpram cg = new();

  function automatic raw_e raw_of(op_e op, logic [AW-1:0] addr);
    if (op != RD) return NO_RAW;
    if (last_wa && last_waddr_a == addr) return AFTER_A;
    if (last_wb && last_waddr_b == addr) return AFTER_B;
    return NO_RAW;
  endfunction

  // One clock cycle. Inputs change on negedge; outputs are checked just after posedge.
  task automatic cycle(op_e oa, logic [AW-1:0] aa, logic [DW-1:0] da,
                       op_e ob, logic [AW-1:0] ab, logic [DW-1:0] db);
    bit b_write_lost;
    @(negedge clk);
    en_a = (oa != IDLE); we_a = (oa == WR); addr_a = aa; wdata_a = da;
    en_b = (ob != IDLE); we_b = (ob == WR); addr_b = ab; wdata_b = db;

    op_a = oa; op_b = ob;
    if (oa == IDLE || ob == IDLE || aa != ab) conflict = NO_CONFLICT;
    else if (oa == RD && ob == RD)            conflict = RR_SAME;
    else if (oa == WR && ob == RD)            conflict = WR_SAME;
    else if (oa == RD && ob == WR)            conflict = RW_SAME;
    else                                      conflict = WW_SAME;
    raw_a = raw_of(oa, aa);
    raw_b = raw_of(ob, ab);
    cg.sample();

    if (oa != IDLE) begin exp_a = model[aa]; known_a = written[aa]; end
    if (ob != IDLE) begin exp_b = model[ab]; known_b = written[ab]; end
    b_write_lost = (oa == WR && ob == WR && aa == ab);
    if (ob == WR && !b_write_lost) begin model[ab] = db; written[ab] = 1; end
    if (oa == WR) begin model[aa] = da; written[aa] = 1; end
    last_wa = (oa == WR);                 last_waddr_a = aa;
    last_wb = (ob == WR && !b_write_lost); last_waddr_b = ab;

    @(posedge clk);
    #1;
    cycles++;
    if (known_a && rdata_a !== exp_a) begin
      errors++;
      $display("CHECK_FAIL cycle=%0d port=A op=%s addr=%0d got=%02h exp=%02h", cycles, oa.name(), aa, rdata_a, exp_a);
    end
    if (known_b && rdata_b !== exp_b) begin
      errors++;
      $display("CHECK_FAIL cycle=%0d port=B op=%s addr=%0d got=%02h exp=%02h", cycles, ob.name(), ab, rdata_b, exp_b);
    end
  endtask

  task automatic write_a(logic [AW-1:0] addr, logic [DW-1:0] data); cycle(WR, addr, data, IDLE, 0, 0); endtask
  task automatic read_a(logic [AW-1:0] addr);                       cycle(RD, addr, 0, IDLE, 0, 0);    endtask
  task automatic write_b(logic [AW-1:0] addr, logic [DW-1:0] data); cycle(IDLE, 0, 0, WR, addr, data); endtask
  task automatic read_b(logic [AW-1:0] addr);                       cycle(IDLE, 0, 0, RD, addr, 0);    endtask
  task automatic idle();                                            cycle(IDLE, 0, 0, IDLE, 0, 0);     endtask

  // @ASSERTIONS

  // @STIMULUS_TASKS

  initial begin
    // @STIMULUS_CALLS
    idle();
    $display("CYCLES %0d", cycles);
    $display("CHECK_ERRORS %0d", errors);
    if (errors == 0) $display("TEST PASSED");
    else             $display("TEST FAILED");
    $finish;
  end
endmodule
