from app.rag import _cosine, mmr_select


def test_cosine_basics():
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0  # zero vector -> 0, no divide-by-zero


def test_mmr_picks_most_relevant_first():
    # candidate 1 is the most similar to the query
    query_sims = [0.2, 0.9, 0.5]
    embeddings = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    assert mmr_select(query_sims, embeddings, k=1, lambda_mult=0.5)[0] == 1


def test_mmr_prefers_diverse_over_near_duplicate():
    # 0 and 1 are near-identical and both relevant; 2 is relevant but different.
    query_sims = [0.9, 0.88, 0.8]
    embeddings = [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]]
    picked = mmr_select(query_sims, embeddings, k=2, lambda_mult=0.5)
    assert picked[0] == 0            # most relevant first
    assert picked[1] == 2            # then the diverse one, not the near-duplicate (1)


def test_mmr_pure_relevance_when_lambda_one():
    query_sims = [0.9, 0.88, 0.8]
    embeddings = [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]]
    # lambda=1 ignores diversity -> ranks purely by query similarity
    assert mmr_select(query_sims, embeddings, k=3, lambda_mult=1.0) == [0, 1, 2]


def test_mmr_respects_k_and_returns_unique():
    query_sims = [0.5, 0.4, 0.3, 0.2]
    embeddings = [[1, 0], [0, 1], [1, 1], [0.5, 0.5]]
    picked = mmr_select(query_sims, embeddings, k=2, lambda_mult=0.5)
    assert len(picked) == 2
    assert len(set(picked)) == 2
