from app.security import hash_password, verify_password


def test_verify_correct_password():
    h = hash_password("s3cret")
    assert verify_password("s3cret", h)


def test_reject_wrong_password():
    h = hash_password("s3cret")
    assert not verify_password("wrong", h)


def test_salt_differs_per_call():
    assert hash_password("s3cret") != hash_password("s3cret")


def test_malformed_hash_fails_closed():
    assert not verify_password("s3cret", "garbage")
    assert not verify_password("s3cret", "")


def test_stored_format():
    h = hash_password("pw")
    algo, iterations, salt, digest = h.split("$")
    assert algo == "pbkdf2_sha256"
    assert int(iterations) >= 100_000
    assert salt and digest
