import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chunking import CHILD_MAX, chunk_document, est_tokens, parse_blocks  # noqa: E402

FRONT = """---
title: "Test Sat"
url: "https://en.wikipedia.org/wiki/Test_Sat"
pageid: 42
revid: 7
keywords: ["test"]
wikipedia_categories: ["Satellites of India"]
---

# Test Sat

_Indian test satellite_

Test Sat is a satellite.

"""


def doc(body: str) -> str:
    return FRONT + body


def para(n_words: int, word: str = "word") -> str:
    return " ".join([word] * n_words) + "."


def test_parse_blocks_types_and_paths():
    blocks = parse_blocks("Lead text.\n\n## Key facts\n\n- Mass: 1 kg\n- Rocket: PSLV\n\n"
                          "## Launch\n\nTable: Flights\n| A | B |\n|---|---|\n| 1 | 2 |\n\n### Delay\n\n- one\n- two\n")
    kinds = [(b.kind, b.path) for b in blocks]
    assert kinds == [
        ("paragraph", ()),
        ("facts", ("Key facts",)),
        ("table", ("Launch",)),
        ("list", ("Launch", "Delay")),
    ]
    assert blocks[2].caption == "Flights"


def test_facts_chunk_and_breadcrumb():
    chunks, _ = chunk_document(doc("## Key facts\n\n- Mass: 1 kg\n- Rocket: PSLV\n\n## History\n\n" + para(50) + "\n"))
    facts = [c for c in chunks if c.chunk_type == "facts"]
    assert len(facts) == 1
    assert facts[0].breadcrumb == "Test Sat > Key facts"
    assert "Rocket: PSLV" in facts[0].content
    assert facts[0].url.endswith("Test_Sat") and facts[0].revid == 7


def test_small_sections_are_merged_with_inline_heading():
    body = "## History\n\n### Early\n\n" + para(45) + "\n\n### Later\n\n" + para(45) + "\n"
    chunks, _ = chunk_document(doc(body))
    hist = [c for c in chunks if c.section_path[0] == "History"]
    assert len(hist) == 1
    assert hist[0].section_path == ["History"]
    assert "### Early" in hist[0].content and "### Later" in hist[0].content


def test_long_section_is_split_with_parent():
    body = "## History\n\n" + "\n\n".join(para(120, f"w{i}") for i in range(8)) + "\n"
    chunks, parents = chunk_document(doc(body))
    hist = [c for c in chunks if c.section_path == ["History"]]
    assert len(hist) > 1
    assert all(c.token_count <= CHILD_MAX for c in hist)
    assert len({c.parent_id for c in hist}) == 1 and hist[0].parent_id is not None
    assert any(p.parent_id == hist[0].parent_id for p in parents)


def test_oversized_parent_not_stored():
    body = "## History\n\n" + "\n\n".join(para(250, f"w{i}") for i in range(12)) + "\n"
    chunks, parents = chunk_document(doc(body))
    hist = [c for c in chunks if c.section_path == ["History"]]
    assert all(c.parent_id is None for c in hist)
    assert hist[1].prev_id == hist[0].chunk_id  # neighbours still available


def test_large_table_repeats_header():
    rows = "\n".join(f"| PSLV-C{i} | 2017-01-{i:02d} | Cartosat payload number {i} |" for i in range(1, 80))
    body = "## Launches\n\nTable: Launch history\n| Flight | Date | Payload |\n|---|---|---|\n" + rows + "\n"
    chunks, _ = chunk_document(doc(body))
    tables = [c for c in chunks if c.chunk_type == "table"]
    assert len(tables) > 1
    for t in tables:
        lines = t.content.splitlines()
        assert lines[0] == "Table: Launch history"
        assert lines[1] == "| Flight | Date | Payload |"
    all_rows = [l for t in tables for l in t.content.splitlines()[3:]]
    assert len(all_rows) == 79  # no row lost or duplicated


def test_long_paragraph_split_at_sentences():
    long_para = " ".join(f"Sentence number {i} talks about the launch." for i in range(150))
    chunks, _ = chunk_document(doc("## History\n\n" + long_para + "\n"))
    hist = [c for c in chunks if c.section_path == ["History"]]
    assert len(hist) > 1
    assert all(c.content.rstrip().endswith(".") for c in hist)


def test_ids_are_sequential_and_linked():
    body = "## A\n\n" + para(300) + "\n\n## B\n\n" + para(300) + "\n"
    chunks, _ = chunk_document(doc(body))
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].prev_id is None and chunks[-1].next_id is None
    assert all(c.chunk_id.startswith("42:") for c in chunks)


def test_wrapped_fact_values_stay_in_one_facts_chunk():
    chunks, _ = chunk_document(doc("## Key facts\n\n- Born: 1931\n\nMadras Institute (MEng)\n\n- Party: None\n\n"
                                   "## Life\n\n" + para(80) + "\n"))
    facts = [c for c in chunks if c.section_path == ["Key facts"]]
    assert len(facts) == 1 and facts[0].chunk_type == "facts"
    assert "Madras Institute" in facts[0].content and "Party: None" in facts[0].content


def test_tiny_lead_is_merged_into_next_chunk():
    md = FRONT.replace("Test Sat is a satellite.\n", "") + "## Key facts\n\n- Mass: 1 kg\n\n## Life\n\n" + para(80) + "\n"
    chunks, _ = chunk_document(md)
    assert not any(c.chunk_type == "text" and c.token_count < 15 for c in chunks)
    assert "_Indian test satellite_" in chunks[0].content and chunks[0].chunk_type == "facts"


def test_est_tokens():
    assert est_tokens("abcd" * 100) == 100
