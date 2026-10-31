"""翻译引擎：多个免密钥在线接口，按配置顺序自动降级。

provider:
  bing       cn.bing.com 网页翻译（提取 IG/token 后调 ttranslatev3；国内可用）
  mymemory   MyMemory 免费接口（单次 450 字符以内，作兜底）
  google     Google 翻译 gtx 接口（需能访问 Google）

统一对外：Translator.translate(text) -> (译文, 引擎显示名)
失败会按 providers 顺序换下一个引擎；全部失败抛 TranslationError。
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

BING_HOST = "https://cn.bing.com"
BING_PAGE = f"{BING_HOST}/translator"
BING_API = f"{BING_HOST}/ttranslatev3"
BING_IID = "translator.5023.1"

GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"

GOOGLE_LANG = {"zh-CN": "zh-CN", "zh-TW": "zh-TW", "en": "en"}


class TranslationError(Exception):
    def __init__(self, provider: str, message: str):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    max_chunk: int


PROVIDERS: dict[str, ProviderSpec] = {
    "bing": ProviderSpec("bing", "必应翻译", 1800),
    "mymemory": ProviderSpec("mymemory", "MyMemory", 450),
    "google": ProviderSpec("google", "Google 翻译", 1800),
}


# ---------------------------------------------------------------- HTTP
def _http_get(url: str, timeout: float, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={**BASE_HEADERS, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------- 分段
_SENT_SPLIT = re.compile(r"(?<=[.!?;:])\s+")
_PARA_SPLIT = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARA_SPLIT.split(text) if p.strip()]


def chunk_paragraph(paragraph: str, limit: int) -> list[str]:
    """把一段文字按句子切成不超过 limit 的块；超长句硬切。"""
    if len(paragraph) <= limit:
        return [paragraph]
    chunks: list[str] = []
    buf = ""
    for sentence in _SENT_SPLIT.split(paragraph):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(sentence), limit):
                chunks.append(sentence[i : i + limit])
        elif not buf:
            buf = sentence
        elif len(buf) + 1 + len(sentence) <= limit:
            buf = f"{buf} {sentence}"
        else:
            chunks.append(buf)
            buf = sentence
    if buf:
        chunks.append(buf)
    return chunks or [paragraph[:limit]]


# ---------------------------------------------------------------- 必应
class _Bing:
    """cn.bing.com 网页翻译。

    流程：GET /translator 拿 IG 与 params_AbusePreventionHelper（key, token），
    再 POST /ttranslatev3 翻译。token 会过期，失败时自动重新抓取一次。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._opener: urllib.request.OpenerDirector | None = None
        self._ig: str | None = None
        self._key: str | None = None
        self._token: str | None = None
        self._fetched_at = 0.0

    # ------------------------------------------------------------ 会话/token
    def _session(self) -> urllib.request.OpenerDirector:
        if self._opener is None:
            jar = http.cookiejar.CookieJar()
            self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        return self._opener

    def _refresh_tokens(self, timeout: float) -> None:
        opener = self._session()
        req = urllib.request.Request(
            BING_PAGE,
            headers={**BASE_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        )
        html = opener.open(req, timeout=timeout).read().decode("utf-8", "replace")
        ig = re.search(r'IG:"([^"]+)"', html)
        helper = re.search(r'params_AbusePreventionHelper\s*=\s*\[(\d+),\s*"([^"]+)"', html)
        if not ig or not helper:
            raise TranslationError("bing", f"页面解析失败（长度 {len(html)}）")
        self._ig = ig.group(1)
        self._key = helper.group(1)
        self._token = helper.group(2)
        self._fetched_at = time.time()

    def _ensure_tokens(self, timeout: float) -> None:
        if self._ig and time.time() - self._fetched_at < 540:
            return
        self._refresh_tokens(timeout)

    # ------------------------------------------------------------ 翻译
    def translate(self, chunk: str, src: str, dst: str, timeout: float) -> str:
        with self._lock:
            try:
                self._ensure_tokens(timeout)
                return self._post(chunk, src, dst, timeout)
            except TranslationError:
                # token 过期/被拒：重抓一次
                self._refresh_tokens(timeout)
                return self._post(chunk, src, dst, timeout)

    def _post(self, chunk: str, src: str, dst: str, timeout: float) -> str:
        params = {"isVertical": "1", "IG": self._ig, "IID": BING_IID}
        url = f"{BING_API}?{urllib.parse.urlencode(params)}"
        body = urllib.parse.urlencode({
            "fromLang": "auto-detect" if src in ("auto", "", None) else src,
            "to": "zh-Hans" if dst == "zh-CN" else dst,
            "text": chunk,
            "token": self._token,
            "key": self._key,
        }).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                **BASE_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": BING_PAGE,
                "Origin": BING_HOST,
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            },
            method="POST",
        )
        with self._session().open(req, timeout=timeout) as resp:
            raw = resp.read()
        if not raw:
            raise TranslationError("bing", "响应为空")
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise TranslationError("bing", f"响应不是 JSON: {raw[:80]!r}") from exc
        if isinstance(data, dict):
            raise TranslationError("bing", str(data.get("statusCode") or data)[:160])
        if not isinstance(data, list) or not data:
            raise TranslationError("bing", "响应结构异常")
        try:
            return "".join(item["translations"][0]["text"] for item in data)
        except (KeyError, IndexError, TypeError) as exc:
            raise TranslationError("bing", f"响应解析失败: {exc}") from exc


# ---------------------------------------------------------------- Google
class _Google:
    def translate(self, chunk: str, src: str, dst: str, timeout: float) -> str:
        params = {
            "client": "gtx",
            "sl": "auto" if src in ("auto", "", None) else src,
            "tl": GOOGLE_LANG.get(dst, "zh-CN"),
            "dt": "t",
            "q": chunk,
        }
        url = f"{GOOGLE_URL}?{urllib.parse.urlencode(params)}"
        data = json.loads(_http_get(url, timeout).decode("utf-8"))
        if not isinstance(data, list) or not data or not isinstance(data[0], list):
            raise TranslationError("google", "响应结构异常")
        parts = []
        for seg in data[0]:
            if isinstance(seg, list) and seg and isinstance(seg[0], str):
                parts.append(seg[0])
        if not parts:
            raise TranslationError("google", "响应中没有译文")
        return "".join(parts)


# ---------------------------------------------------------------- MyMemory
class _MyMemory:
    def translate(self, chunk: str, src: str, dst: str, timeout: float) -> str:
        source = "en" if src in ("auto", "", None) else src
        params = {"q": chunk, "langpair": f"{source}|{GOOGLE_LANG.get(dst, 'zh-CN')}"}
        url = f"{MYMEMORY_URL}?{urllib.parse.urlencode(params)}"
        data = json.loads(_http_get(url, timeout).decode("utf-8"))
        status = data.get("responseStatus")
        if status != 200:
            raise TranslationError("mymemory", str(data.get("responseDetails") or status))
        text = (data.get("responseData") or {}).get("translatedText") or ""
        if not text or text.isupper():
            raise TranslationError("mymemory", "响应中没有有效译文")
        return text


# ---------------------------------------------------------------- 门面
class Translator:
    def __init__(self, cfg):
        self.cfg = cfg
        self._engines = {"bing": _Bing(), "google": _Google(), "mymemory": _MyMemory()}
        self._cache: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._cache_max = int(cfg.get("cache_size", 200))

    # ------------------------------------------------------------ 缓存
    def _cache_key(self, text: str) -> str:
        raw = f"{self.cfg.get('source_lang')}|{self.cfg.get('target_lang')}|{text}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> tuple[str, str] | None:
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
            return hit

    def _cache_put(self, key: str, value: tuple[str, str]) -> None:
        with self._cache_lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)

    # ------------------------------------------------------------ 对外
    def provider_order(self) -> list[str]:
        configured = self.cfg.get("providers") or ["bing"]
        order = [name for name in configured if name in PROVIDERS]
        return order or ["bing"]

    def translate(self, text: str, progress=None) -> tuple[str, str]:
        key = self._cache_key(text)
        cached = self._cache_get(key)
        if cached:
            return cached

        timeout = float(self.cfg.get("request_timeout_s", 9))
        source = self.cfg.get("source_lang", "auto")
        target = self.cfg.get("target_lang", "zh-CN")
        errors: list[str] = []
        for name in self.provider_order():
            spec = PROVIDERS[name]
            try:
                result = self._translate_with(name, spec, text, source, target, timeout, progress)
                if not result.strip():
                    raise TranslationError(name, "译文为空")
                self._cache_put(key, (result, spec.label))
                return result, spec.label
            except Exception as exc:  # 换下一个引擎
                errors.append(str(exc))
                log.warning("引擎 %s 失败: %s", name, exc)
        raise TranslationError("all", "所有引擎都不可用：" + " | ".join(errors))

    def _translate_with(self, name, spec, text, source, target, timeout, progress) -> str:
        paragraphs = split_paragraphs(text) or [text]
        chunks_per_para = [chunk_paragraph(p, spec.max_chunk) for p in paragraphs]
        total = sum(len(chunks) for chunks in chunks_per_para)
        done = 0
        translated_paragraphs: list[str] = []
        for chunks in chunks_per_para:
            pieces = []
            for chunk in chunks:
                pieces.append(self._call(name, chunk, source, target, timeout))
                done += 1
                if progress:
                    try:
                        progress(done, total)
                    except Exception:
                        pass
            translated_paragraphs.append("".join(pieces))
        return "\n\n".join(translated_paragraphs)

    def _call(self, name: str, chunk: str, source: str, target: str, timeout: float) -> str:
        engine = self._engines[name]
        last: Exception | None = None
        for attempt in range(2):
            try:
                return engine.translate(chunk, source, target, timeout)
            except urllib.error.HTTPError as exc:
                last = TranslationError(name, f"HTTP {exc.code}")
                if exc.code in (400, 401, 403, 429):  # 重试无意义/被限流
                    break
            except urllib.error.URLError as exc:
                last = TranslationError(name, f"网络错误 {exc.reason}")
            except TranslationError as exc:
                last = exc
            except Exception as exc:  # noqa: BLE001 - 统一转为引擎错误
                last = TranslationError(name, f"{type(exc).__name__}: {exc}")
            if attempt == 0:
                time.sleep(0.4)
        raise last or TranslationError(name, "未知错误")

    # ------------------------------------------------------------ 诊断
    def test(self, sample: str = "The quick brown fox jumps over the lazy dog.") -> list[dict]:
        """逐个引擎试译，供「测试翻译引擎」使用。"""
        timeout = float(self.cfg.get("request_timeout_s", 9))
        results = []
        for name in self.provider_order():
            spec = PROVIDERS[name]
            started = time.monotonic()
            try:
                text = self._engines[name].translate(
                    sample, "en", self.cfg.get("target_lang", "zh-CN"), timeout
                )
                results.append({
                    "provider": name,
                    "label": spec.label,
                    "ok": True,
                    "detail": text.strip()[:120],
                    "ms": int((time.monotonic() - started) * 1000),
                })
            except Exception as exc:
                results.append({
                    "provider": name,
                    "label": spec.label,
                    "ok": False,
                    "detail": str(exc)[:200],
                    "ms": int((time.monotonic() - started) * 1000),
                })
        return results
