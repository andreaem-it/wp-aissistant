from app.rag import chunk_text


def test_chunking():
    assert chunk_text("") == []

    # short text stays a single chunk
    assert chunk_text("Ciao.", size=100) == ["Ciao."]

    # sentences are packed without being cut mid-sentence
    text = "Uno due tre. Quattro cinque sei. Sette otto nove dieci."
    chunks = chunk_text(text, size=30, overlap=0)
    assert chunks[0] == "Uno due tre."
    assert all(sentence in "".join(chunks) for sentence in ["Uno due tre.", "Quattro cinque sei.", "Sette otto nove dieci."])

    # a single sentence longer than `size` becomes its own chunk rather than being cut
    long_sentence = "a" * 50 + "."
    assert chunk_text(long_sentence, size=10) == [long_sentence]

    # consecutive chunks overlap by the tail of the previous one
    text2 = "Prima frase qui. Seconda frase qui. Terza frase qui. Quarta frase qui."
    chunks2 = chunk_text(text2, size=35, overlap=15)
    assert len(chunks2) > 1
    assert chunks2[1].startswith(chunks2[0][-15:].lstrip())


if __name__ == "__main__":
    test_chunking()
    print("ok")
