"""한국어 조사 붙이기."""


def _final(word):
    """마지막 글자의 받침 번호(0 = 받침 없음). 한글이 아니면 0."""
    last = word[-1:] if word else ""
    return (ord(last) - 0xAC00) % 28 if "가" <= last <= "힣" else 0


def josa(word, with_final, without_final):
    """받침에 맞는 조사. josa("토토", "을", "를") -> "토토를"."""
    return word + (with_final if _final(word) else without_final)


def josa_ro(word):
    """"로/으로": 받침이 없거나 ㄹ 받침이면 "로"."""
    return word + ("로" if _final(word) in (0, 8) else "으로")
