"""Unit tests for the structure-aware chunker (no DB needed)."""

from retrieval.chunking import chunk_sections, estimate_tokens


def test_short_section_is_single_chunk_with_provenance():
    chunks = chunk_sections([("fees", "Annual fee: 1500 BDT.")])
    assert len(chunks) == 1
    assert chunks[0]["field"] == "fees"
    assert chunks[0]["ordinal"] == 0
    assert chunks[0]["token_count"] == estimate_tokens(chunks[0]["text"])


def test_chunks_never_cross_section_boundaries():
    long_text = " ".join(f"Sentence number {i} about fees." for i in range(300))
    chunks = chunk_sections(
        [
            ("fees", long_text),
            ("rewards", "Reward points policy: earn 1 point per 50 BDT."),
        ],
        target_tokens=100,
        max_tokens=120,
        overlap_tokens=20,
    )
    fee_chunks = [c for c in chunks if c["field"] == "fees"]
    reward_chunks = [c for c in chunks if c["field"] == "rewards"]
    assert len(fee_chunks) > 1
    assert len(reward_chunks) == 1
    assert all("Reward points" not in c["text"] for c in fee_chunks)
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))


def test_window_respects_max_tokens_approximately():
    text = " ".join(" ".join(["word"] * 10) + "." for _ in range(100))
    chunks = chunk_sections([("overview", text)], target_tokens=100, max_tokens=120)
    assert chunks
    # A single oversized sentence may exceed, but ordinary windows must not.
    assert all(c["token_count"] <= 130 for c in chunks)


def test_empty_sections_are_skipped():
    assert chunk_sections([("fees", "  "), ("rewards", "")]) == []
