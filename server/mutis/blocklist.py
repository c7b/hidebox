# SPDX-License-Identifier: MIT
"""Words a shop's or a listing's public text may not carry (security pass, 2026-11-21).

Our server can't see inside a file, but a shop's name, bio and each listing's title and line are public text the owner
typed. A small list of terms that only advertise child sexual abuse material is refused there, with a neutral message
that names no term. It is deliberately short: reports and takedowns stay the main tool (docs/shop.md, fine-print), and
this list only stops the plainest adverts from reaching the market. The text is folded first (case, accents, digits and
signs that pass for letters, separators), so "P.T.H.C" and "ch1ld-p0rn" are caught too.
"""
import re
import unicodedata

# Whole words of the folded text.
WORDS = frozenset("""
    pthc ptsc hussyfan raygold babyshivid kingpass jailbait preteen preteens pedophile pedophiles pedophilia
    paedophile paedophilia lolicon shotacon csam
""".split())
# Runs of words of the folded text.
PHRASES = ("child porn", "kiddie porn", "kid porn", "child sex", "child abuse material", "kinder porno", "baby porn",
           "teen porn")
# Inside the text with every separator dropped (long enough not to occur by chance in other words).
JOINED = ("childporn", "kiddieporn", "kinderporn", "babyporn", "hussyfan", "babyshivid", "pedophil", "paedophil",
          "lolicon", "shotacon", "jailbait", "pthcvid")
# An age under 18, or "underage", next to a sexual word. (Short words that are also names or other words, "loli",
# "pedo", are left out on purpose.)
_AGE = re.compile(r"\b(?:[1-9]|1[0-7]) ?(?:y ?o|yr|yrs|years? old)\b")
_SEXUAL = frozenset("nude nudes naked sex sexy porn nsfw xxx lewd erotic topless".split())
_FOLD = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


def _folded(text: str) -> tuple[str, str, str]:
    """(words with digits kept, words with look-alike digits folded, everything joined), all lower case ASCII."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    spaced = " ".join(re.sub(r"[^a-z0-9@$!]+", " ", plain).split())
    letters = " ".join(re.sub(r"[^a-z]+", " ", spaced.translate(_FOLD)).split())
    return spaced, letters, letters.replace(" ", "")


def banned(text: str) -> bool:
    """True when `text` carries one of the terms above."""
    spaced, letters, joined = _folded(text)
    words = set(letters.split())
    if words & WORDS:
        return True
    padded = f" {letters} "
    if any(f" {p} " in padded for p in PHRASES) or any(j in joined for j in JOINED):
        return True
    # Single letters between dots or spaces ("p t h c"): the joined run of one-letter words.
    singles = "".join(w for w in letters.split() if len(w) == 1)
    if len(singles) >= 4 and any(w in singles for w in WORDS if len(w) >= 4):
        return True
    return (bool(_AGE.search(spaced)) or "underage" in words) and bool(words & _SEXUAL)
