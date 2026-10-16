# dpram

True dual-port RAM. Two independent ports, A and B, share one clock and one memory array.
Defaults: 8-bit data, 16 words (`DATA_W = 8`, `ADDR_W = 4`).

## Ports (per port, X = a or b)

| Port | Dir | Width | Meaning |
|------|-----|-------|---------|
| clk | in | 1 | shared clock, rising edge |
| en_X | in | 1 | port enable |
| we_X | in | 1 | write enable, only matters when en_X = 1 |
| addr_X | in | ADDR_W | word address |
| wdata_X | in | DATA_W | write data |
| rdata_X | out | DATA_W | read data |

## Behaviour

- **Read.** With `en_X = 1`, `rdata_X` shows `mem[addr_X]` one clock after the edge that sampled the address.
- **Write.** With `en_X = 1` and `we_X = 1`, `wdata_X` is stored at `addr_X` on the rising edge.
- **Read-first.** Every enabled cycle also reads. A port that writes returns the *old* contents of
  that address. A port that reads an address the other port writes in the same cycle also gets the
  *old* contents.
- **Hold.** With `en_X = 0`, `rdata_X` keeps its last value.
- **Write collision.** If both ports write the same address in the same cycle, port A's data is stored
  and port B's write is dropped.
- **Different addresses** never interact: the two ports can read or write any mix of addresses at once.
- **No reset.** Memory contents are undefined until written, so reads of never-written words are not checked.

## Interesting cases

- every combination of idle / read / write on the two ports
- first and last address on both ports
- data patterns 0x00, 0xFF, 0xAA, 0x55
- both ports on the same address: read/read, write/read, read/write, write/write
- read an address in the cycle right after it was written, from the same port and from the other port
- write collisions where the addresses differ only in the top bit
