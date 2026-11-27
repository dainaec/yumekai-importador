"""Public MangaUpdates metadata: exact title/alias plus author verification."""
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import hashlib
import json
import re
import ssl
from threading import Event
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import truststore

from yumekai_importer.storage.mangaupdates_cache import MangaUpdatesCache


API_URL = "https://api.mangaupdates.com/v1"
DAY = 86400
MAX_CANDIDATES = 3
SUPPORTED_TYPES = {"Manga", "Manhwa", "Manhua"}


@dataclass(frozen=True)
class MangaUpdatesResult:
    status: str
    work_type: str | None = None
    demographic: str | None = None
    series_id: int | None = None
    title: str = ""
    url: str = ""
    message: str = ""


class MangaUpdatesCancelled(Exception):
    pass


class MangaUpdatesError(ValueError):
    pass


def metadata_key(value):
    folded = unicodedata.normalize("NFKD", str(value or "")).casefold()
    folded = "".join(character for character in folded if not unicodedata.combining(character))
    return " ".join("".join(character if character.isalnum() else " " for character in folded).split())


def author_keys(value):
    # Ignore studio annotations, preserve the individual pen names, and allow surname-first order.
    value = re.sub(r"\([^)]*\)", " ", str(value or ""))
    keys = set()
    for name in re.split(r"\s*/\s*|\s*;\s*|\s+&\s+|\s+ y \s+", value, flags=re.I):
        words = metadata_key(name).split()
        if words and any(len(word) >= 2 for word in words) and (len(words) > 1 or len(words[0]) >= 3):
            keys.add(" ".join(sorted(words)))
    return keys


def is_comic_title(title):
    return not re.search(r"\b(?:novela|novel|artbook|databook|fanbook|guia|ilustraciones)\b|\barte de\b|\blibro de arte\b",
                         metadata_key(title))


def _safe_api_url(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname == "api.mangaupdates.com"
                and parts.port in (None, 443) and not parts.username and not parts.password)
    except ValueError:
        return False


def _safe_series_url(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname == "www.mangaupdates.com"
                and parts.port in (None, 443) and not parts.username and not parts.password
                and parts.path.startswith("/series/"))
    except (ValueError, TypeError):
        return False


class _ApiRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _safe_api_url(newurl):
            raise MangaUpdatesError("MangaUpdates ha redirigido fuera de su API HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _demographic(record):
    if record.get("type") != "Manga":
        return None
    genres = {metadata_key(item.get("genre")) for item in (record.get("genres") or []) if isinstance(item, dict)}
    # Yumekai also groups BL and Yuri here, with the same priority used in its catalogue.
    specific = set()
    if genres & {"yaoi", "shounen ai", "boys love"}:
        specific.add("Yaoi / BL")
    if genres & {"yuri", "shoujo ai", "girls love"}:
        specific.add("Yuri")
    if specific:
        return next(iter(specific)) if len(specific) == 1 else None
    aliases = {"shounen": "Shonen", "shonen": "Shonen", "shoujo": "Shōjo",
               "shojo": "Shōjo", "seinen": "Seinen", "josei": "Josei", "kodomo": "Kodomo"}
    found = {aliases[value] for value in genres if value in aliases}
    return next(iter(found)) if len(found) == 1 else None


def _matches(record, title, authors):
    titles = {metadata_key(record.get("title"))}
    titles.update(metadata_key(item.get("title")) for item in (record.get("associated") or []) if isinstance(item, dict))
    found_authors = set()
    for person in (record.get("authors") or []):
        if isinstance(person, dict):
            found_authors.update(author_keys(person.get("name")))
    return (record.get("type") in SUPPORTED_TYPES and metadata_key(title) in titles
            and bool(author_keys(authors) & found_authors))


class MangaUpdatesClient:
    def __init__(self, stop_requested=None, *, cache=None, refresh=False):
        self.stop = stop_requested if stop_requested is not None else Event()
        self.cache = cache if cache is not None else MangaUpdatesCache()
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.opener = build_opener(HTTPSHandler(context=context), _ApiRedirects())
        self._last_request = 0.0
        self._disabled = ""
        self._memo = {}
        self.refresh = refresh
        self._refreshed = set()

    def close(self):
        self.cache.flush()

    def _request(self, path, *, data=None):
        if self.stop.is_set():
            raise MangaUpdatesCancelled()
        url = API_URL + path
        if not _safe_api_url(url):
            raise MangaUpdatesError("Dirección de metadatos no reconocida.")
        delay = max(0.0, 1.0 - (time.monotonic() - self._last_request))
        if self.stop.wait(delay):
            raise MangaUpdatesCancelled()
        self._last_request = time.monotonic()
        request = Request(url, data=json.dumps(data).encode("utf-8") if data is not None else None,
                          headers={"User-Agent": "YumekaiImporter/1.0 (MangaUpdates metadata)",
                                   "Accept": "application/json", "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=15) as response:
                if not _safe_api_url(response.geturl()):
                    raise MangaUpdatesError("Respuesta fuera de la API de MangaUpdates.")
                payload = response.read(3_000_001)
            if len(payload) > 3_000_000:
                raise MangaUpdatesError("La respuesta de MangaUpdates es demasiado grande.")
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise MangaUpdatesError("MangaUpdates no ha devuelto datos reconocibles.")
        except HTTPError as error:
            raise MangaUpdatesError(f"MangaUpdates no disponible (HTTP {error.code}). Se conservan los datos de Norma.") from None
        except (URLError, OSError, TimeoutError, ValueError) as error:
            if isinstance(error, MangaUpdatesError):
                raise
            raise MangaUpdatesError("No se pudo consultar MangaUpdates. Se conservan los datos de Norma.") from None
        if self.stop.is_set():
            raise MangaUpdatesCancelled()
        return value

    def _record(self, identifier):
        key = f"series:{identifier}"
        value = None if self.refresh and key not in self._refreshed else self.cache.get(key, 7 * DAY)
        if not isinstance(value, dict):
            value = self._request(f"/series/{identifier}")
            if value.get("series_id") != identifier or not isinstance(value.get("title"), str):
                raise MangaUpdatesError("MangaUpdates ha devuelto una ficha de serie no reconocible.")
            self.cache.put(key, {field: value.get(field) for field in
                ("series_id", "title", "associated", "type", "genres", "authors", "url")})
            self._refreshed.add(key)
        if value.get("series_id") != identifier or not isinstance(value.get("title"), str):
            raise MangaUpdatesError("MangaUpdates ha devuelto una ficha de serie no reconocible.")
        return value

    def lookup(self, title, authors):
        if self.stop.is_set():
            raise MangaUpdatesCancelled()
        if not is_comic_title(title):
            return MangaUpdatesResult("unverified", message="MangaUpdates: novela o libro ilustrado; revisar el tipo de obra manualmente.")
        if not metadata_key(title) or not author_keys(authors):
            return MangaUpdatesResult("unverified", message="MangaUpdates: faltan colección o autoría para confirmar una coincidencia.")
        fingerprint = json.dumps([metadata_key(title), sorted(author_keys(authors))], ensure_ascii=False)
        key = "match:" + hashlib.sha256(fingerprint.encode()).hexdigest()
        if key in self._memo:
            return self._memo[key]
        cached = None if self.refresh else self.cache.get(key, 30 * DAY)
        if isinstance(cached, dict) and cached.get("status") == "matched" and cached.get("work_type") in SUPPORTED_TYPES:
            valid_demo = cached.get("demographic") in {None, "Shonen", "Shōjo", "Seinen", "Josei", "Kodomo", "Yaoi / BL", "Yuri"}
            if (_safe_series_url(cached.get("url")) and valid_demo
                    and (cached["work_type"] == "Manga" or cached.get("demographic") is None)):
                try:
                    result = MangaUpdatesResult(**cached)
                    self._memo[key] = result
                    return result
                except TypeError:
                    pass
        if self._disabled:
            return MangaUpdatesResult("error", message=self._disabled)
        try:
            search_key = "search:" + hashlib.sha256(metadata_key(title).encode()).hexdigest()
            search = None if self.refresh and search_key not in self._refreshed else self.cache.get(search_key, DAY)
            if not isinstance(search, dict):
                search = self._request("/series/search", data={"search": str(title).strip(), "perpage": 10})
                if not isinstance(search.get("results"), list):
                    raise MangaUpdatesError("MangaUpdates ha devuelto una búsqueda no reconocible.")
                # Keep only public identification metadata, without descriptions or images.
                search = {"results": [{"record": {field: entry["record"].get(field)
                    for field in ("series_id", "title", "type")}, "hit_title": entry.get("hit_title", "")}
                    for entry in search["results"] if isinstance(entry, dict) and isinstance(entry.get("record"), dict)]}
                self.cache.put(search_key, search)
                self._refreshed.add(search_key)
            if not isinstance(search.get("results"), list):
                raise MangaUpdatesError("MangaUpdates ha devuelto una búsqueda no reconocible.")
            entries = [entry for entry in search["results"] if isinstance(entry, dict)
                       and isinstance(entry.get("record"), dict) and entry["record"].get("type") in SUPPORTED_TYPES]
            query_key = metadata_key(title)
            def rank(entry):
                variants = (entry["record"].get("title", ""), entry.get("hit_title", ""))
                return max(SequenceMatcher(None, query_key, metadata_key(value)).ratio() for value in variants)
            entries.sort(key=rank, reverse=True)
            matches = []
            seen = set()
            candidates = []
            for entry in entries:
                identifier = entry["record"].get("series_id")
                if not isinstance(identifier, int) or identifier <= 0 or identifier in seen:
                    continue
                seen.add(identifier)
                candidates.append(entry)
            # Do not accept one of a truncated set of equally plausible exact-title hits.
            if any(rank(entry) == 1 for entry in candidates[MAX_CANDIDATES:]):
                result = MangaUpdatesResult("ambiguous", message="MangaUpdates: demasiadas obras comparten este título. Revisar manualmente.")
                self._memo[key] = result
                return result
            for entry in candidates[:MAX_CANDIDATES]:
                identifier = entry["record"]["series_id"]
                record = self._record(identifier)
                if _matches(record, title, authors) and _safe_series_url(record.get("url")):
                    matches.append(record)
            if len(matches) == 1:
                record = matches[0]
                result = MangaUpdatesResult("matched", record["type"], _demographic(record),
                    record["series_id"], record["title"], record["url"],
                    "MangaUpdates: colección/título alternativo y autoría coinciden. " + record["url"])
                self.cache.put(key, asdict(result))
            elif matches:
                names = "; ".join(record["title"] for record in matches[:3])
                result = MangaUpdatesResult("ambiguous", message=f"MangaUpdates: varias obras coinciden ({names}). Revisar manualmente.")
            else:
                result = MangaUpdatesResult("not_found", message="MangaUpdates: sin coincidencia confirmada de colección y autoría. Clasificación pendiente.")
            self._memo[key] = result
            return result
        except MangaUpdatesError as error:
            self._disabled = str(error)
            return MangaUpdatesResult("error", message=self._disabled)
