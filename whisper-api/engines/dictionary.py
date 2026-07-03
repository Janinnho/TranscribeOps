"""Fuzzy dictionary correction shared by all engines.

The API `prompt` parameter carries a comma-separated list of dictionary
terms (names, acronyms, domain vocabulary). Engines that cannot bias
decoding with a prompt (NeMo/Parakeet, local WhisperX) instead post-process
the word-level output: transcript words that are phonetically/orthographically
close to a dictionary entry are replaced by the entry's exact spelling,
token-for-token, so timestamps stay aligned.
"""
import unicodedata
from difflib import SequenceMatcher

DICT_MIN_LEN = 4        # minimum length for FUZZY matching
DICT_MIN_ENTRY_LEN = 2  # minimum length for dictionary entries (exact match)
DICT_MIN_RATIO = 0.78
DICT_LEN_TOLERANCE = 0.30
_PUNCT_CHARS = ",.!?:;\"'„""—–-…()[]{}«»‚'"

# Marker key set on replaced word dicts so callers can tell which words
# (and hence which segments) were touched. Kept out of API responses by
# the segment builders, which copy explicit keys only.
REPLACED_KEY = "_dict_replaced"


def normalize_for_match(s: str) -> str:
    """Lowercase + strip diacritics + ß→ss for fuzzy comparison."""
    s = unicodedata.normalize("NFKD", s).lower().replace("ß", "ss")
    return "".join(c for c in s if not unicodedata.combining(c))


def split_punct(token: str) -> tuple[str, str, str]:
    """Split (leading_punct, core, trailing_punct)."""
    i = 0
    while i < len(token) and token[i] in _PUNCT_CHARS:
        i += 1
    j = len(token)
    while j > i and token[j - 1] in _PUNCT_CHARS:
        j -= 1
    return token[:i], token[i:j], token[j:]


def parse_prompt(prompt: str) -> list[tuple[str, str | None]]:
    """Split a comma-separated dictionary prompt into (source, target) entries.

    Two entry forms:
      "Jannik Baader"   -> ("Jannik Baader", None): correct similar-sounding
                           transcript words to this canonical spelling.
      "Doppelpunkt=:"   -> ("Doppelpunkt", ":"): transcript words matching
                           the source are REPLACED by the target text
                           (spoken-command style substitution).

    Short sources (2-3 chars, e.g. acronyms like "IuK") are kept — they
    only ever match exactly (case-/diacritic-insensitive), never fuzzily.
    Because "," separates entries, a comma cannot be used as a target.
    """
    if not prompt:
        return []
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for raw in prompt.split(","):
        w = raw.strip()
        target = None
        if "=" in w:
            src, _, tgt = w.partition("=")
            src, tgt = src.strip(), tgt.strip()
            if tgt:
                w, target = src, tgt
            else:
                w = src  # dangling "=": treat as plain dictionary word
        if len(w) < DICT_MIN_ENTRY_LEN:
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((w, target))
    return out


def apply_dictionary(words: list[dict], dict_words: list[tuple[str, str | None]]) -> int:
    """Correct/replace ASR'd words against dictionary entries from parse_prompt().

    Mutates `words` in place (each entry needs a "word" key). Entries with
    target=None correct similar-sounding words to the canonical spelling;
    entries with a target REPLACE the matched word(s) with the target text.
    Multi-token sources (e.g. "Erika Mustermann") are matched against
    sliding N-word windows and replaced token-for-token so timestamps stay
    aligned (with a target, it lands on the first token and the rest are
    blanked — engines skip empty words). A punctuation-only target (":")
    is appended to the preceding word instead, dictation-style. Each
    transcript word is replaced at most once; longer sources take
    precedence (greedy). Preserves outer punctuation. Replaced word dicts
    are flagged with REPLACED_KEY. Returns total number of replacements.
    """
    if not words or not dict_words:
        return 0

    multi: list[tuple[list[str], list[str], str | None]] = []  # (tokens_orig, tokens_norm, target)
    single: list[tuple[str, str, str | None]] = []             # (orig, norm, target)
    for entry, target in dict_words:
        toks = entry.split()
        if len(toks) >= 2:
            multi.append((toks, [normalize_for_match(t) for t in toks], target))
        elif toks:
            single.append((toks[0], normalize_for_match(toks[0]), target))

    replaced: set[int] = set()
    n_repl = 0

    def _attach_to_previous(idx: int, punct: str) -> bool:
        """Append punctuation to the last non-empty word before idx.

        An existing trailing punctuation on that word is dropped — the ASR
        often inserts a comma before a spoken command ("denn, Doppelpunkt"),
        and "denn,:" is never what the speaker meant.
        """
        for j in range(idx - 1, -1, -1):
            if words[j]["word"]:
                leading, core, _trailing = split_punct(words[j]["word"])
                if core:
                    words[j]["word"] = leading + core + punct
                else:
                    words[j]["word"] = words[j]["word"] + punct
                words[j][REPLACED_KEY] = True
                return True
        return False

    def _is_punct_only(s: str) -> bool:
        return bool(s) and not any(ch.isalnum() for ch in s)

    # Multi-word pass first, longer sources first (greedy: a 3-token source
    # mustn't be blocked by a 2-token source consuming the first two words).
    multi.sort(key=lambda x: -len(x[0]))
    for tokens_orig, tokens_norm, target in multi:
        m = len(tokens_orig)
        cand_joined = " ".join(tokens_norm)
        cand_len = len(cand_joined)
        max_diff = max(1, DICT_LEN_TOLERANCE * cand_len)
        for i in range(0, len(words) - m + 1):
            if any((i + k) in replaced for k in range(m)):
                continue
            cores: list[str] = []
            ok = True
            for k in range(m):
                _, core, _ = split_punct(words[i + k]["word"])
                if not core:
                    ok = False
                    break
                cores.append(core)
            if not ok:
                continue
            joined_core = " ".join(normalize_for_match(c) for c in cores)
            if abs(len(joined_core) - cand_len) > max_diff:
                continue
            if target is None and cores == tokens_orig:
                continue  # already correct, including spelling/casing
            score = SequenceMatcher(a=joined_core, b=cand_joined).ratio()
            if score >= DICT_MIN_RATIO:
                if target is None:
                    for k in range(m):
                        leading, _, trailing = split_punct(words[i + k]["word"])
                        words[i + k]["word"] = leading + tokens_orig[k] + trailing
                        words[i + k][REPLACED_KEY] = True
                        replaced.add(i + k)
                else:
                    leading, _, _ = split_punct(words[i]["word"])
                    _, _, trailing = split_punct(words[i + m - 1]["word"])
                    words[i]["word"] = leading + target + trailing
                    for k in range(1, m):
                        words[i + k]["word"] = ""
                    for k in range(m):
                        words[i + k][REPLACED_KEY] = True
                        replaced.add(i + k)
                n_repl += m

    def _short_acronym_match(core_norm: str, cand_norm: str) -> bool:
        """Fuzzy rule for short tokens (acronyms): same length, first and
        last character identical, at most one substitution in between
        (IOK -> IuK matches; 'und' -> IuK does not)."""
        if len(core_norm) != len(cand_norm) or len(core_norm) < 3:
            return False
        if core_norm[0] != cand_norm[0] or core_norm[-1] != cand_norm[-1]:
            return False
        return sum(1 for a, b in zip(core_norm, cand_norm) if a != b) <= 1

    def _best_single(core: str) -> str | None:
        """Replacement text for a single core token, or None.

        For target=None entries the replacement is the canonical spelling;
        for mapping entries it is the target text.
        """
        if len(core) < DICT_MIN_ENTRY_LEN:
            return None
        core_norm = normalize_for_match(core)
        best_repl = None
        best_score = 0.0
        for orig, cand_norm, target in single:
            repl = target if target is not None else orig
            if cand_norm == core_norm:
                # Exact (case-/diacritic-insensitive) match works at any
                # length — this is how short acronyms get their canonical
                # spelling (IUK -> IuK).
                return repl if repl != core else None
            # Below fuzzy length, only the strict acronym rule applies: on a
            # 2-3 char token a free single-character difference would hit
            # unrelated words far too often.
            if len(core_norm) < DICT_MIN_LEN or len(cand_norm) < DICT_MIN_LEN:
                if _short_acronym_match(core_norm, cand_norm) and best_score < 0.85:
                    best_repl, best_score = repl, 0.85
                continue
            if abs(len(core_norm) - len(cand_norm)) > max(1, DICT_LEN_TOLERANCE * len(cand_norm)):
                continue
            score = SequenceMatcher(a=core_norm, b=cand_norm).ratio()
            if score > best_score:
                best_score = score
                best_repl = repl
        if best_repl is not None and best_score >= DICT_MIN_RATIO and best_repl != core:
            return best_repl
        return None

    # Single-word pass — skip indices already touched by the multi-word pass.
    for idx, word_obj in enumerate(words):
        if idx in replaced:
            continue
        leading, core, trailing = split_punct(word_obj["word"])
        if not core:
            continue
        repl = _best_single(core)
        if repl is None and "-" in core:
            # German compounds: match each hyphen component on its own so
            # "IOK-Abteilung" gets corrected to "IuK-Abteilung".
            parts = core.split("-")
            new_parts = [(_best_single(p) or p) for p in parts]
            if new_parts != parts:
                repl = "-".join(new_parts)
        if repl is not None and repl != core:
            if _is_punct_only(repl):
                # Dictation-style: "denn Doppelpunkt" -> "denn:" — the
                # punctuation belongs to the preceding word, the spoken
                # command token disappears (engines skip empty words).
                if _attach_to_previous(idx, repl):
                    word_obj["word"] = ""
                else:
                    word_obj["word"] = repl  # no previous word: stand alone
            else:
                word_obj["word"] = leading + repl + trailing
            word_obj[REPLACED_KEY] = True
            n_repl += 1

    return n_repl
