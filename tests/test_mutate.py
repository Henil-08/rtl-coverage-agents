import pytest

from agent.mutate import generate
from agent.sim import verilator_available
from designs import get_design

pytestmark = pytest.mark.skipif(not verilator_available(), reason="verilator not installed")


@pytest.mark.parametrize("name", ["dpram", "adder4"])
def test_generic_mutants_compile_and_differ(name):
    d = get_design(name)
    src = d.sources()
    ms = generate(src)
    assert 6 <= len(ms) <= 10
    assert len({m.category for m in ms}) >= 3
    texts = set()
    for m in ms:
        out = m.apply(src[m.file])
        assert out != src[m.file]
        texts.add(out)
    assert len(texts) == len(ms)
