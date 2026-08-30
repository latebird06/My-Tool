#!/usr/bin/env python3
"""IP Purity core: exit reputation, leak hints, route quality and reachability.

Only Python's standard library is required.  Every probe returns a structured
result so the desktop UI can distinguish a failed request from a clean result.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
TIMEOUT = 12
APP_DIR = os.path.dirname(os.path.abspath(__file__))

FLAG_ORDER = [
    "Datacenter", "VPN", "Anonymizing VPN", "Public Proxy", "Web Proxy",
    "Tor Exit Node", "Residential Proxy", "Server", "Apple iCloud Private Relay",
    "AWS IP Address", "Google IP Address", "Search Engine Robot",
]
BLACKLIST_FIELDS = ["Firehol", "IP2ProxyLite", "IPsum", "Spamhaus", "X4Bnet Spambot"]
LABEL_ZH = {
    "VPN": "VPN", "Datacenter": "机房 IP", "Apple iCloud Private Relay": "iCloud 私密中继",
    "AWS IP Address": "AWS 机房", "Google IP Address": "Google 机房",
    "Anonymizing VPN": "匿名 VPN", "Tor Exit Node": "Tor 出口节点", "Server": "服务器",
    "Public Proxy": "公共代理", "Web Proxy": "网页代理", "Search Engine Robot": "搜索引擎机器人",
    "Residential Proxy": "住宅代理", "Firehol": "Firehol 黑名单",
    "IP2ProxyLite": "IP2Proxy 黑名单", "IPsum": "IPsum 黑名单",
    "Spamhaus": "Spamhaus 黑名单", "X4Bnet Spambot": "X4Bnet 黑名单",
}


def ok(data=None, *, latency_ms=None, status=None, note=None):
    return {"ok": True, "data": data, "error": None, "latency_ms": latency_ms,
            "status": status, "note": note}


def fail(kind, message, *, status=None, latency_ms=None):
    return {"ok": False, "data": None, "error": {"kind": kind, "message": message},
            "latency_ms": latency_ms, "status": status, "note": None}


def _http(url, *, headers=None, timeout=TIMEOUT, expect_json=False):
    request_headers = {"User-Agent": UA, "Accept": "application/json" if expect_json else "*/*"}
    request_headers.update(headers or {})
    req = urllib.request.Request(url, headers=request_headers, method="GET")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            elapsed = round((time.monotonic() - started) * 1000)
            if expect_json:
                try:
                    body = json.loads(body)
                except json.JSONDecodeError as exc:
                    return fail("format", f"返回内容不是有效 JSON：{exc}", status=response.status, latency_ms=elapsed)
            return ok(body, latency_ms=elapsed, status=response.status)
    except urllib.error.HTTPError as exc:
        elapsed = round((time.monotonic() - started) * 1000)
        detail = exc.read().decode("utf-8", "replace")[:240]
        kind = "rate_limit" if exc.code == 429 else "auth" if exc.code in (401, 403) else "http"
        return fail(kind, f"HTTP {exc.code}" + (f"：{detail}" if detail else ""), status=exc.code, latency_ms=elapsed)
    except urllib.error.URLError as exc:
        elapsed = round((time.monotonic() - started) * 1000)
        reason = str(exc.reason)
        kind = "timeout" if "timed out" in reason.lower() else "network"
        return fail(kind, reason, latency_ms=elapsed)
    except (TimeoutError, socket.timeout):
        return fail("timeout", f"超过 {timeout} 秒未响应", latency_ms=round((time.monotonic() - started) * 1000))
    except Exception as exc:
        return fail("exception", str(exc), latency_ms=round((time.monotonic() - started) * 1000))


def valid_ip(value):
    try:
        return str(ipaddress.ip_address(value.strip()))
    except (ValueError, AttributeError):
        return None


def get_keys():
    keys = {name: os.environ[name].strip() for name in ("IPQS_KEY", "ABUSEIPDB_KEY")
            if os.environ.get(name, "").strip()}
    path = os.path.join(APP_DIR, "config.json")
    try:
        with open(path, encoding="utf-8") as stream:
            stored = json.load(stream)
        for name in ("IPQS_KEY", "ABUSEIPDB_KEY"):
            if name not in keys and str(stored.get(name, "")).strip():
                keys[name] = str(stored[name]).strip()
    except (OSError, ValueError, TypeError):
        pass
    return keys


def _discover_family(family):
    endpoints = {
        4: ["https://api4.ipify.org", "https://ipv4.icanhazip.com", "https://ipinfo.io/ip"],
        6: ["https://api6.ipify.org", "https://ipv6.icanhazip.com"],
    }[family]
    errors = []
    for endpoint in endpoints:
        result = _http(endpoint, timeout=7)
        if result["ok"]:
            candidate = valid_ip(str(result["data"]).strip())
            if candidate and ipaddress.ip_address(candidate).version == family:
                result["data"] = {"ip": candidate, "source": endpoint}
                return result
            errors.append(f"{endpoint}: 地址格式不符")
        else:
            errors.append(f"{endpoint}: {result['error']['message']}")
    return fail("unavailable", "；".join(errors))


def discover_public_ips():
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        v4_future = pool.submit(_discover_family, 4)
        v6_future = pool.submit(_discover_family, 6)
        return {"ipv4": v4_future.result(), "ipv6": v6_future.result()}


def get_public_ip():
    """Compatibility wrapper used by older callers."""
    result = _discover_family(4)
    if result["ok"]:
        return result["data"]["ip"], result["data"]["source"]
    return None, None


def _normalize_ipinfo(data, source):
    if source == "ipwho.is":
        connection = data.get("connection") or {}
        return {
            "ip": data.get("ip"), "city": data.get("city"), "region": data.get("region"),
            "country": data.get("country_code"), "country_name": data.get("country"),
            "org": connection.get("org") or connection.get("isp"), "asn": connection.get("asn"),
            "source": source,
        }
    org = data.get("org") or ""
    asn = (re.search(r"AS\d+", org) or [None])[0]
    return {**data, "asn": asn, "source": source}


def get_ipinfo(target_ip):
    first = _http(f"https://ipinfo.io/{urllib.parse.quote(target_ip, safe=':')}/json", expect_json=True)
    if first["ok"] and isinstance(first["data"], dict) and not first["data"].get("bogon"):
        first["data"] = _normalize_ipinfo(first["data"], "IPinfo")
        return first
    fallback = _http(f"https://ipwho.is/{urllib.parse.quote(target_ip, safe=':')}", expect_json=True)
    if fallback["ok"] and isinstance(fallback["data"], dict) and fallback["data"].get("success", True):
        fallback["data"] = _normalize_ipinfo(fallback["data"], "ipwho.is")
        fallback["note"] = "IPinfo 未响应，已使用备用地理信息源"
        return fallback
    messages = []
    for name, result in (("IPinfo", first), ("备用源", fallback)):
        if not result["ok"]:
            messages.append(f"{name}: {result['error']['message']}")
    return fail("all_sources_failed", "；".join(messages) or "未获得有效地理信息")


def strip_tags(html):
    return re.sub(r"<[^>]+>", "", html).strip()


def parse_scamalytics(target_ip):
    result = _http("https://www.scamalytics.com/ip/" + urllib.parse.quote(target_ip, safe=":"))
    if not result["ok"]:
        return result
    html = result["data"]
    if len(html) < 1000:
        return fail("format", "页面内容过短，可能被限流或拦截", status=result["status"], latency_ms=result["latency_ms"])
    data = {"score": None, "connection": None, "flags": {}, "blacklist": {}}
    match = re.search(r"Fraud Score:\s*(\d+)", html)
    if match:
        data["score"] = int(match.group(1))
    match = re.search(r"<th>Connection type</th>\s*<td>(.*?)</td>", html, re.S)
    if match:
        data["connection"] = strip_tags(match.group(1))
    for match in re.finditer(r'<th>([^<]+)</th>\s*<td>\s*<div class="risk[^"]*">([^<]*)</div>', html):
        name, value = strip_tags(match.group(1)), strip_tags(match.group(2))
        bucket = data["blacklist"] if name in BLACKLIST_FIELDS else data["flags"]
        if name not in bucket or value == "Yes":
            bucket[name] = value
    if data["score"] is None and not data["flags"]:
        return fail("format", "页面结构已变化，未解析到信誉字段", status=result["status"], latency_ms=result["latency_ms"])
    result["data"] = data
    return result


def get_ipqs(target_ip, key):
    query = urllib.parse.urlencode({
        "ip": target_ip, "strictness": 0, "allow_public_access_points": "true",
        "lighter_penalties": "true",
    })
    result = _http("https://ipqualityscore.com/api/json/ip?" + query,
                   headers={"IPQS-KEY": key}, expect_json=True)
    if result["ok"] and isinstance(result["data"], dict) and result["data"].get("success") is False:
        return fail("api", str(result["data"].get("message") or "IPQS 查询失败"),
                    status=result["status"], latency_ms=result["latency_ms"])
    return result


def get_abuseipdb(target_ip, key):
    query = urllib.parse.urlencode({"ipAddress": target_ip, "maxAgeInDays": 90, "verbose": ""})
    result = _http("https://api.abuseipdb.com/api/v2/check?" + query,
                   headers={"Key": key, "Accept": "application/json"}, expect_json=True)
    if result["ok"] and isinstance(result["data"], dict) and result["data"].get("errors"):
        return fail("api", str(result["data"]["errors"]), status=result["status"], latency_ms=result["latency_ms"])
    if result["ok"]:
        result["data"] = (result["data"] or {}).get("data", result["data"])
    return result


def _run(command, timeout=12):
    started = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        elapsed = round((time.monotonic() - started) * 1000)
        if proc.returncode == 0:
            return ok(proc.stdout, latency_ms=elapsed, status=proc.returncode)
        failed = fail("command", (proc.stderr or proc.stdout or f"退出码 {proc.returncode}").strip(),
                      status=proc.returncode, latency_ms=elapsed)
        failed["output"] = proc.stdout
        return failed
    except FileNotFoundError:
        return fail("missing_tool", f"系统未安装 {command[0]}")
    except subprocess.TimeoutExpired:
        return fail("timeout", f"{command[0]} 执行超时")
    except Exception as exc:
        return fail("exception", str(exc))


def get_interface_exposure():
    result = _run(["ip", "-j", "address", "show"])
    if not result["ok"]:
        return result
    try:
        raw = json.loads(result["data"])
    except ValueError as exc:
        return fail("format", f"无法解析 ip 输出：{exc}")
    addresses = []
    for interface in raw:
        if interface.get("ifname") == "lo":
            continue
        for item in interface.get("addr_info", []):
            value = item.get("local")
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                continue
            if parsed.is_loopback or parsed.is_link_local:
                continue
            addresses.append({"interface": interface.get("ifname"), "ip": value,
                              "family": parsed.version, "public": parsed.is_global,
                              "scope": item.get("scope")})
    public = [item for item in addresses if item["public"]]
    return ok({"addresses": addresses, "public": public,
               "status": "warn" if public else "good",
               "summary": "发现本机网卡具有公网地址，浏览器或直连程序可能绕过代理" if public
                          else "未在本机网卡发现可直接暴露的公网地址"})


def get_dns_route(exit_country=None):
    result = _run(["resolvectl", "dns"])
    if not result["ok"]:
        return result
    found = []
    for line in result["data"].splitlines():
        for token in line.replace("[", " ").replace("]", " ").split():
            candidate = token.strip("#,:()%")
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if not address.is_unspecified:
                found.append(str(address))
    found = list(dict.fromkeys(found))
    public = [value for value in found if ipaddress.ip_address(value).is_global]
    local = [value for value in found if value not in public]
    locations = []
    for value in public[:3]:
        geo = get_ipinfo(value)
        if geo["ok"]:
            locations.append({"ip": value, "country": geo["data"].get("country"),
                              "org": geo["data"].get("org")})
    mismatches = [item for item in locations if exit_country and item.get("country")
                  and item["country"] != exit_country]
    status = "warn" if mismatches else "good" if found else "unknown"
    summary = ("DNS 解析器地区与出口地区不一致，存在 DNS 旁路可能" if mismatches else
               "系统 DNS 路由未发现明显地区错配" if found else "未解析到系统 DNS 服务器")
    return ok({"servers": found, "public": public, "local": local, "locations": locations,
               "mismatches": mismatches, "status": status, "summary": summary,
               "caveat": "这是系统 DNS 路由检查，不等同于浏览器网页的完整 DNS 泄漏测试"})


def get_network_quality():
    probes = []
    for host in ("1.1.1.1", "8.8.8.8"):
        result = _run(["ping", "-n", "-c", "4", "-W", "2", host], timeout=12)
        item = {"host": host, "ok": result["ok"], "loss": None, "avg_ms": None,
                "error": None if result["ok"] else result["error"]}
        text = result["data"] if result["ok"] else result.get("output", "")
        loss = re.search(r"([\d.]+)% packet loss", text)
        timing = re.search(r"=\s*[\d.]+/([\d.]+)/", text)
        if loss:
            item["loss"] = float(loss.group(1))
        if timing:
            item["avg_ms"] = float(timing.group(1))
        probes.append(item)
    valid = [item for item in probes if item["loss"] is not None]
    if not valid:
        return fail("unavailable", "两个系统路由探测点均未返回结果")
    average_loss = round(statistics.mean(item["loss"] for item in valid), 1)
    latencies = [item["avg_ms"] for item in valid if item["avg_ms"] is not None]
    average_ms = round(statistics.mean(latencies), 1) if latencies else None
    status = "bad" if average_loss >= 20 else "warn" if average_loss > 0 or (average_ms or 0) > 180 else "good"
    return ok({"probes": probes, "loss": average_loss, "latency_ms": average_ms, "status": status,
               "summary": f"平均延迟 {average_ms if average_ms is not None else '未知'} ms，丢包 {average_loss}%",
               "caveat": "使用系统默认路由的 ICMP 探测；浏览器代理路径可能不同"})


def get_platform_access():
    targets = [
        ("YouTube", "https://www.youtube.com/generate_204"),
        ("Netflix", "https://www.netflix.com/"),
        ("Disney+", "https://www.disneyplus.com/"),
    ]
    def probe(name, url):
        result = _http(url, timeout=10)
        return {"name": name, "reachable": result["ok"], "status": result.get("status"),
                "latency_ms": result.get("latency_ms"), "error": result.get("error")}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda item: probe(*item), targets))
    return ok({"services": rows, "reachable": sum(item["reachable"] for item in rows),
               "summary": f"{sum(item['reachable'] for item in rows)} / {len(rows)} 个站点可建立访问",
               "caveat": "仅验证网站连通与 HTTP 响应，不代表账号地区、片库或视频播放一定解锁"})


def _truthy(value):
    if isinstance(value, str):
        return value.lower() not in ("", "none", "false", "no", "low")
    return bool(value)


def build_assessment(results, leak_checks):
    components, notes = [], []
    scam = results.get("scamalytics") or {}
    if scam.get("ok"):
        data = scam["data"]
        if data.get("score") is not None:
            components.append({"source": "Scamalytics", "score": int(data["score"])})
        positive = [LABEL_ZH.get(k, k) for k, value in data.get("flags", {}).items() if value == "Yes"]
        blacklist = [LABEL_ZH.get(k, k) for k, value in data.get("blacklist", {}).items() if value == "Yes"]
        if positive:
            notes.append("信誉标记：" + "、".join(positive))
        if blacklist:
            components.append({"source": "公开黑名单", "score": 75})
            notes.append("黑名单命中：" + "、".join(blacklist))
    ipqs = results.get("ipqs") or {}
    if ipqs.get("ok"):
        data = ipqs["data"] or {}
        if data.get("fraud_score") is not None:
            components.append({"source": "IPQualityScore", "score": int(data["fraud_score"])})
        severe = [key for key in ("tor", "active_tor", "recent_abuse", "frequent_abuser", "bot_status") if _truthy(data.get(key))]
        if severe:
            components.append({"source": "IPQS 高风险信号", "score": 78})
            notes.append("IPQS 高风险信号：" + "、".join(severe))
        elif any(_truthy(data.get(key)) for key in ("proxy", "vpn", "active_vpn")):
            notes.append("IPQS 检测到代理或 VPN 特征")
    abuse = results.get("abuse") or {}
    if abuse.get("ok"):
        data = abuse["data"] or {}
        value = data.get("abuseConfidenceScore")
        if value is not None:
            components.append({"source": "AbuseIPDB", "score": int(value)})
        if data.get("totalReports"):
            notes.append(f"AbuseIPDB 近 90 天报告 {data['totalReports']} 次")
    reputation = max((item["score"] for item in components), default=0)
    leak_score, leak_notes = 0, []
    interfaces = leak_checks.get("interfaces") or {}
    dns = leak_checks.get("dns") or {}
    ipv6 = leak_checks.get("ipv6") or {}
    if interfaces.get("ok") and interfaces["data"].get("public"):
        leak_score = max(leak_score, 65)
        leak_notes.append("本机网卡存在公网地址")
    if dns.get("ok") and dns["data"].get("mismatches"):
        # Resolver geolocation is only a clue: anycast, encrypted DNS and VPN
        # fake-IP modes can legitimately place it in another country.
        leak_score = max(leak_score, 30)
        leak_notes.append("DNS 解析器与出口地区不一致（旁路线索，非确定泄漏）")
    if ipv6.get("status") == "warn":
        leak_score = max(leak_score, 70)
        leak_notes.append(ipv6.get("summary", "IPv6 出口不一致"))
    overall = max(reputation, leak_score)
    if overall <= 10:
        label, level = "低风险", "good"
    elif overall <= 35:
        label, level = "需要留意", "warn"
    elif overall <= 65:
        label, level = "较高风险", "warn"
    else:
        label, level = "高风险", "bad"
    return {"overall": overall, "reputation": reputation, "leak": leak_score,
            "label": label, "level": level, "components": components,
            "notes": notes + leak_notes, "method": "多源最高风险原则 v2",
            "coverage": len(components)}


def run_diagnostics(target_ip=None, progress=None):
    notify = progress or (lambda _message, _fraction: None)
    notify("正在识别 IPv4 与 IPv6 出口", 0.06)
    exits = discover_public_ips()
    target = valid_ip(target_ip) if target_ip else None
    if target_ip and not target:
        raise ValueError("IPv4 或 IPv6 地址格式不正确")
    if not target:
        preferred = exits["ipv4"] if exits["ipv4"]["ok"] else exits["ipv6"]
        if not preferred["ok"]:
            raise RuntimeError("无法识别公网出口 IP")
        target = preferred["data"]["ip"]
    notify("正在查询信誉、网络身份和滥用记录", 0.20)
    keys = get_keys()
    jobs = {
        "ipinfo": (get_ipinfo, (target,)),
        "scamalytics": (parse_scamalytics, (target,)),
        "interfaces": (get_interface_exposure, ()),
        "quality": (get_network_quality, ()),
        "platforms": (get_platform_access, ()),
    }
    if keys.get("IPQS_KEY"):
        jobs["ipqs"] = (get_ipqs, (target, keys["IPQS_KEY"]))
    if keys.get("ABUSEIPDB_KEY"):
        jobs["abuse"] = (get_abuseipdb, (target, keys["ABUSEIPDB_KEY"]))
    results = {"ipinfo": fail("not_run", "未执行"), "scamalytics": fail("not_run", "未执行"),
               "ipqs": fail("not_configured", "未配置 API Key"),
               "abuse": fail("not_configured", "未配置 API Key")}
    local = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(func, *args): name for name, (func, args) in jobs.items()}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                value = future.result()
            except Exception as exc:
                value = fail("exception", str(exc))
            if name in ("interfaces", "quality", "platforms"):
                local[name] = value
            else:
                results[name] = value
            done += 1
            notify(f"已完成 {done} / {len(jobs)} 个检测模块", 0.20 + 0.52 * done / len(jobs))
    geo = results["ipinfo"]["data"] if results["ipinfo"]["ok"] else {}
    notify("正在检查 DNS 与 IPv6 出口一致性", 0.78)
    v4_ip = exits["ipv4"]["data"]["ip"] if exits["ipv4"]["ok"] else None
    v6_ip = exits["ipv6"]["data"]["ip"] if exits["ipv6"]["ok"] else None
    # Only compare DNS country with the inspected address when that address is
    # the actual current exit.  A manually entered third-party IP is unrelated
    # to this machine's resolver route.
    dns = get_dns_route(geo.get("country") if target in (v4_ip, v6_ip) else None)
    ipv6 = {"status": "unknown", "summary": "当前网络未检测到可用 IPv6 出口", "v4": v4_ip, "v6": v6_ip}
    if v6_ip:
        v6_geo = get_ipinfo(v6_ip)
        v6_country = v6_geo["data"].get("country") if v6_geo["ok"] else None
        mismatch = bool(geo.get("country") and v6_country and geo.get("country") != v6_country)
        ipv6 = {"status": "warn" if mismatch else "good",
                "summary": "IPv4 与 IPv6 出口国家不一致，可能存在 IPv6 旁路" if mismatch else "已检测 IPv6，未发现明显出口地区错配",
                "v4": v4_ip, "v6": v6_ip, "v6_country": v6_country,
                "v6_org": v6_geo["data"].get("org") if v6_geo["ok"] else None}
    leaks = {"interfaces": local.get("interfaces", fail("not_run", "未执行")), "dns": dns, "ipv6": ipv6}
    assessment = build_assessment(results, leaks)
    notify("正在生成完整诊断报告", 0.96)
    return {"target_ip": target, "exits": exits, "sources": results, "leaks": leaks,
            "quality": local.get("quality", fail("not_run", "未执行")),
            "platforms": local.get("platforms", fail("not_run", "未执行")),
            "assessment": assessment,
            "configured": {"ipqs": bool(keys.get("IPQS_KEY")), "abuse": bool(keys.get("ABUSEIPDB_KEY"))},
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def main():
    target = next((arg for arg in sys.argv[1:] if not arg.startswith("--")), None)
    report = run_diagnostics(target, lambda msg, _fraction: print(msg + "...", file=sys.stderr))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
