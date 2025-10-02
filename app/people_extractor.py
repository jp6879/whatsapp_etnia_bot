import re
from typing import Dict, Optional

# Basic Spanish number words (small set, extend as needed)
NUM_WORDS = {
    "uno": 1,
    "una": 1,
    "un": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
}


def normalize_text(text: str) -> str:
    return re.sub(r"[^a-záéíóúñ0-9 ]", " ", text.lower())


def word_to_num(token: str) -> Optional[int]:
    return NUM_WORDS.get(token.lower())


def _find_word_numbers(text: str):
    # returns list of tuples (num, span_start, span_end)
    words_pattern = "|".join(
        sorted((re.escape(w) for w in NUM_WORDS.keys()), key=len, reverse=True)
    )
    pattern = re.compile(r"\b(" + words_pattern + r")\b")
    results = []
    for m in pattern.finditer(text):
        num = word_to_num(m.group(1))
        if num is not None:
            results.append((num, m.start(), m.end()))
    return results


def _num_near_keyword(text: str, keyword_pattern: str):
    """Sum explicit digit mentions that directly precede a keyword (e.g., '2 adultos')."""
    results = 0
    digit_pattern = re.compile(r"(\d+)\s*(?:" + keyword_pattern + r")")
    for m in digit_pattern.finditer(text):
        # m.group(1) should always be a string of digits
        results += int(m.group(1))
    return results


def _word_numbers_near_keywords(text: str, max_dist: int = 25):
    """Assign word-number occurrences to the nearest adult or minor keyword.

    Returns tuple (adults_sum, minors_sum)
    """
    words = _find_word_numbers(text)
    if not words:
        return 0, 0

    adult_kw = list(re.finditer(r"adultos?|mayores|adulto", text))
    minor_kw = list(re.finditer(r"niñ[oa]s?|menores?|menor", text))

    adults_sum = 0
    minors_sum = 0

    for num, s, e in words:
        # compute nearest adult/minor distance
        best_adult_dist = None
        for m in adult_kw:
            dist = min(abs(s - m.start()), abs(e - m.end()))
            if best_adult_dist is None or dist < best_adult_dist:
                best_adult_dist = dist

        best_minor_dist = None
        for m in minor_kw:
            dist = min(abs(s - m.start()), abs(e - m.end()))
            if best_minor_dist is None or dist < best_minor_dist:
                best_minor_dist = dist

        # decide assignment based on nearest distance and a max distance threshold
        if (
            best_adult_dist is not None
            and (best_minor_dist is None or best_adult_dist < best_minor_dist)
            and best_adult_dist <= max_dist
        ):
            adults_sum += num
        elif (
            best_minor_dist is not None
            and (best_adult_dist is None or best_minor_dist < best_adult_dist)
            and best_minor_dist <= max_dist
        ):
            minors_sum += num
        # else: skip (could be total or unrelated)

    return adults_sum, minors_sum


def _find_total(text: str) -> Optional[int]:
    # patterns like "somos 5 personas", "viajan 3", "viajamos tres"
    # digits: "somos 5 personas" or "somos 4," or just "somos 4"
    m = re.search(r"somos\s+(\d+)\b", text)
    if m:
        return int(m.group(1))

    # digits for travel verb: "viajan 3", "viajamos 2"
    m = re.search(r"viaj\w*\s+(\d+)\b", text)
    if m:
        return int(m.group(1))

    # word-number variants e.g., "somos tres personas", "viajamos tres"
    words = _find_word_numbers(text)
    for num, s, e in words:
        # look after the word for keywords
        window_after = text[e : e + 25]
        if (
            re.search(r"personas?", window_after)
            or re.search(r"viaj", window_after)
            or re.search(r"somos", window_after)
        ):
            return num
        # or look before the word for 'somos'/'viajamos'
        window_before = text[max(0, s - 20) : s]
        if re.search(r"somos", window_before) or re.search(r"viaj", window_before):
            return num

    return None


def extract_people_info(text: str) -> Dict[str, int]:
    """Extract number of adults, minors and total from a short Spanish travel text.

    Returns a dict: {"adults": int, "minors": int, "total": int}

    Strategy (in order):
    - Find digit mentions (e.g., "5", "3")
    - Find explicit word-numbers like "tres", "cinco"
    - Find explicit mentions like "2 adultos", "1 menor", including word-numbers (tres)
    - Find total mentions like "somos 4", "viajamos 3"
    - If adults not explicitly present but total and minors found -> adults = total - minors
    - Optionally fallback to spaCy NER counting PERSON entities when nothing else found
    """
    if not text or not text.strip():
        return {"adults": 0, "minors": 0, "total": 0}

    text_norm = normalize_text(text)

    if len(text_norm.split()) == 1:
        # Single word, could be a number word or digit
        if text_norm.isdigit():
            n = int(text_norm)
            return {"adults": n, "minors": 0, "total": n}
        else:
            n = word_to_num(text_norm)
            if n is not None:
                return {"adults": n, "minors": 0, "total": n}
            else:
                return {"adults": 0, "minors": 0, "total": 0}

    # explicit counts
    adults = 0
    minors = 0

    # patterns: digits attached to keywords
    adults += _num_near_keyword(text_norm, r"adultos?|mayores|adulto")
    minors += _num_near_keyword(text_norm, r"niñ[oa]s?|menores?|menor")

    # sometimes 'personas' is used without specifying minors/adults; count as total later

    total = _find_total(text_norm)

    # Now assign word-numbers to nearest adult/minor keywords (e.g., 'tres adultos y un niño')
    a_add, m_add = _word_numbers_near_keywords(text_norm)
    adults += a_add
    minors += m_add

    # If we found 'somos X personas' but no minors/adults, try to split by keywords
    if total and adults == 0 and minors > 0:
        adults = max(total - minors, 0)

    # If no explicit adults/minors but total exists -> assume all adults
    if total and adults == 0 and minors == 0:
        adults = total

    if total is None:
        total = adults + minors
    else:
        # If parsed explicit parts sum to more than a detected 'total', trust the explicit sum
        if (adults + minors) > total:
            total = adults + minors

    return {"adults": int(adults), "minors": int(minors), "total": int(total)}
