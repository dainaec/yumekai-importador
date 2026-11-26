"""Compare SD codes and recognize valid ISBN-10/ISBN-13 equivalents."""
import re


_SD_SEPARATORS = re.compile(r"[\s\-\u2010-\u2015\u2212]+")


def normalize_sd_code(value: object) -> str | None:
    text = "" if value is None else str(value)
    code = _SD_SEPARATORS.sub("", text).casefold()
    return code or None


def sd_code_variants(value: object) -> tuple[str, ...]:
    code = normalize_sd_code(value)
    if code is None:
        return ()

    variants = [code]

    if re.fullmatch(r"[0-9]{9}[0-9x]", code):
        digits = [int(c) for c in code[:9]]
        last = 10 if code[-1] == "x" else int(code[-1])

        if (
            sum((10 - i) * n for i, n in enumerate(digits)) + last
        ) % 11 == 0:
            base = "978" + code[:9]
            check = (-sum(
                int(c) * (1 if i % 2 == 0 else 3)
                for i, c in enumerate(base)
            )) % 10
            variants.append(base + str(check))

    elif re.fullmatch(r"978[0-9]{10}", code):
        if sum(
            int(c) * (1 if i % 2 == 0 else 3)
            for i, c in enumerate(code)
        ) % 10 == 0:
            base = code[3:12]
            check = (-sum(
                (10 - i) * int(c)
                for i, c in enumerate(base)
            )) % 11
            variants.append(base + ("x" if check == 10 else str(check)))

    return tuple(dict.fromkeys(variants))


def sd_codes_match(first: object, second: object) -> bool:
    return bool(
        set(sd_code_variants(first)) & set(sd_code_variants(second))
    )