from app.rag import chunk_text


def test_chunking():
    assert chunk_text("") == []
    assert chunk_text("hello", size=10) == ["hello"]
    chunks = chunk_text("a" * 25, size=10)
    assert chunks == ["a" * 10, "a" * 10, "a" * 5]


if __name__ == "__main__":
    test_chunking()
    print("ok")
