#!/usr/bin/env python3
"""IP Purity GTK desktop application."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
import check_ip_purity as core  # noqa: E402

import gi  # noqa: E402
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID = "local.ipcheck.purity"
APP_NAME = "IP Purity"
ICON_PATH = APP_DIR / "assets" / "ip-purity.svg"
CONFIG_PATH = APP_DIR / "config.json"

CSS = b"""
@define-color ink #20252f;
@define-color muted #7d8694;
@define-color paper #fffdfa;
@define-color line #e9e5dd;
@define-color orange #ff8c42;
@define-color orange_soft #fff4eb;
@define-color green #369567;
@define-color green_soft #edf8f1;
@define-color amber #c98b22;
@define-color amber_soft #fff8e7;
@define-color red #df5b5b;
@define-color red_soft #fff0f0;
window, .app-root { background: @paper; color: @ink; }
headerbar { background: #f7f6f4; border-bottom: 1px solid @line; box-shadow: none; }
headerbar .title { color: @ink; font-weight: 700; }
.page { background: @paper; padding: 28px 40px 42px; }
.brand-row { margin-bottom: 20px; }
.brand-mark { min-width: 46px; min-height: 46px; border-radius: 15px; background: @orange; color: white; font-size: 16px; font-weight: 900; }
.brand-title { color: @ink; font-size: 22px; font-weight: 800; }
.muted { color: @muted; }
.micro { color: @muted; font-size: 11px; }
.eyebrow { color: @orange; font-size: 11px; font-weight: 800; letter-spacing: 1px; }
.hero-title { color: @ink; font-size: 32px; font-weight: 800; }
.hero-copy { color: @muted; font-size: 13px; }
.card { background: white; border: 1px solid @line; border-radius: 17px; padding: 18px; }
.section-wrap { margin-bottom: 14px; }
.soft-card { background: #faf8f4; border-radius: 13px; padding: 13px; }
.input-card { background: @orange_soft; border: 1px solid @orange; border-radius: 17px; padding: 17px; margin-top: 18px; margin-bottom: 18px; }
.ip-entry { background: white; color: @ink; border: 1px solid #ded8cf; border-radius: 11px; padding: 10px 12px; font-size: 14px; }
.primary-button { background: @orange; color: white; border: 0; border-radius: 11px; padding: 10px 17px; font-weight: 800; box-shadow: none; }
.primary-button:hover { background: #f47f35; }
.secondary-button { background: white; color: @ink; border: 1px solid @line; border-radius: 11px; padding: 9px 14px; font-weight: 700; box-shadow: none; }
.quiet-button { background: transparent; color: @muted; border: 0; box-shadow: none; }
.status-strip { background: #faf8f4; border-radius: 13px; padding: 12px 15px; margin-bottom: 18px; }
.status-dot { min-width: 9px; min-height: 9px; border-radius: 99px; background: @green; }
.section-title { color: @ink; font-size: 18px; font-weight: 800; }
.section-copy { color: @muted; font-size: 12px; }
.result-hero { background: white; border: 1px solid @line; border-radius: 20px; padding: 21px; margin-bottom: 14px; }
.score-box { min-width: 135px; border-radius: 16px; padding: 15px; }
.score-number { font-size: 39px; font-weight: 900; }
.score-caption { font-size: 11px; font-weight: 700; }
.risk-good { background: @green_soft; color: @green; }
.risk-warn { background: @amber_soft; color: @amber; }
.risk-bad { background: @red_soft; color: @red; }
.verdict { color: @ink; font-size: 24px; font-weight: 900; }
.ip-value { color: @ink; font-size: 16px; font-weight: 800; }
.metric-grid { margin-bottom: 14px; }
.metric-card { background: white; border: 1px solid @line; border-radius: 14px; padding: 14px; }
.metric-label { color: @muted; font-size: 10px; font-weight: 800; letter-spacing: .6px; }
.metric-value { color: @ink; font-size: 14px; font-weight: 700; }
.detail-row { border-bottom: 1px solid @line; padding: 10px 0; }
.detail-name { color: @ink; font-weight: 700; }
.chip { border-radius: 99px; padding: 5px 10px; font-size: 11px; font-weight: 700; }
.chip-good { background: @green_soft; color: @green; }
.chip-warn { background: @amber_soft; color: @amber; }
.chip-bad { background: @red_soft; color: @red; }
.chip-neutral { background: #f2efe9; color: @muted; }
.notice { background: @orange_soft; border-radius: 13px; padding: 14px; color: #9a592b; }
.error-card { background: @red_soft; color: @red; border: 1px solid alpha(@red, .35); border-radius: 15px; padding: 17px; }
.loading-title { color: @ink; font-size: 18px; font-weight: 800; }
.progressbar trough { min-height: 7px; border-radius: 99px; background: #eeeae2; border: 0; }
.progressbar progress { min-height: 7px; border-radius: 99px; background: @orange; border: 0; }
.dialog-page { background: @paper; padding: 20px; }
.dialog-title { color: @ink; font-size: 21px; font-weight: 800; }
.field-label { color: @ink; font-weight: 700; }
.config-entry { background: white; color: @ink; border: 1px solid #ded8cf; border-radius: 10px; padding: 9px; }
"""


def add_class(widget, *names):
    for name in names:
        widget.get_style_context().add_class(name)
    return widget


def label(text="", *classes, xalign=0, selectable=False):
    item = Gtk.Label(label=str(text), xalign=xalign)
    item.set_line_wrap(True)
    item.set_selectable(selectable)
    add_class(item, *classes)
    return item


def clear_box(box):
    for child in box.get_children():
        box.remove(child)


def error_text(result):
    error = (result or {}).get("error") or {}
    kinds = {"timeout": "请求超时", "rate_limit": "额度或频率受限", "auth": "密钥无效或无权限",
             "network": "网络连接失败", "format": "返回格式已变化", "not_configured": "未配置",
             "missing_tool": "缺少系统工具", "api": "服务返回错误"}
    return f"{kinds.get(error.get('kind'), '检测失败')}：{error.get('message', '未知原因')}"


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(title="数据源设置", transient_for=parent, modal=True)
        self.set_default_size(600, 440)
        self.add_button("取消", Gtk.ResponseType.CANCEL)
        add_class(self.add_button("保存设置", Gtk.ResponseType.OK), "primary-button")
        content = self.get_content_area()
        add_class(content, "dialog-page")
        content.set_spacing(16)
        content.pack_start(label("数据源设置", "dialog-title"), False, False, 0)
        content.pack_start(label("基础诊断无需密钥。可选数据源只在检测时使用，密钥保存在本机且不会写入报告。", "muted"), False, False, 0)
        keys = core.get_keys()
        self.ipqs_entry = self._field(content, "IPQualityScore API Key", "补充欺诈分、代理、VPN、Tor 与近期滥用信号。", keys.get("IPQS_KEY", ""))
        self.abuse_entry = self._field(content, "AbuseIPDB API Key", "补充近 90 天滥用置信度、报告数量和网络用途。", keys.get("ABUSEIPDB_KEY", ""))
        content.pack_start(label("留空并保存即可删除对应密钥。", "micro"), False, False, 0)
        self.show_all()

    def _field(self, parent, title, help_text, value):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        add_class(card, "card")
        card.pack_start(label(title, "field-label"), False, False, 0)
        card.pack_start(label(help_text, "micro"), False, False, 0)
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_text(value)
        entry.set_placeholder_text("未配置")
        entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
        entry.connect("icon-press", lambda field, _pos, _event: field.set_visibility(not field.get_visibility()))
        add_class(entry, "config-entry")
        card.pack_start(entry, False, False, 0)
        parent.pack_start(card, False, False, 0)
        return entry

    def save(self):
        values = {"IPQS_KEY": self.ipqs_entry.get_text().strip(), "ABUSEIPDB_KEY": self.abuse_entry.get_text().strip()}
        values = {key: value for key, value in values.items() if value}
        if values:
            CONFIG_PATH.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
            os.chmod(CONFIG_PATH, 0o600)
        elif CONFIG_PATH.exists():
            CONFIG_PATH.unlink()


class PurityWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title=APP_NAME)
        if ICON_PATH.is_file():
            self.set_icon_from_file(str(ICON_PATH))
        self.set_default_size(1000, 820)
        self.set_size_request(780, 640)
        self._run_id = 0
        self._last_target = None
        self._busy = False
        header = Gtk.HeaderBar(title=APP_NAME)
        header.set_show_close_button(True)
        self.set_titlebar(header)
        settings = Gtk.Button(label="设置")
        add_class(settings, "quiet-button")
        settings.connect("clicked", self._open_settings)
        header.pack_start(settings)
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text("重新执行上一次检测")
        refresh.connect("clicked", lambda _button: self.start_check(self._last_target))
        header.pack_end(refresh)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.add(scrolled)
        self.page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        add_class(self.page, "page")
        self.page.set_size_request(730, -1)
        viewport = Gtk.Viewport()
        viewport.add(self.page)
        scrolled.add(viewport)
        self._build_header()
        self._build_input()
        self._build_status()
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.page.pack_start(self.content, True, True, 0)
        GLib.idle_add(self.start_check, None)

    def _build_header(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=13)
        add_class(row, "brand-row")
        mark = label("IP", "brand-mark", xalign=0.5)
        mark.set_yalign(0.5)
        row.pack_start(mark, False, False, 0)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        copy.pack_start(label(APP_NAME, "brand-title"), False, False, 0)
        copy.pack_start(label("出口信誉与本地网络诊断", "muted"), False, False, 0)
        row.pack_start(copy, False, False, 0)
        row.pack_end(label("隐私优先 · 本地运行", "eyebrow", xalign=1), False, False, 0)
        self.page.pack_start(row, False, False, 0)
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hero.pack_start(label("完整网络体检", "eyebrow"), False, False, 0)
        hero.pack_start(label("出口是否可靠，一次看清。", "hero-title"), False, False, 0)
        hero.pack_start(label("同时检查 IP 信誉、IPv6/DNS/本机旁路、延迟丢包和常用平台访问。", "hero-copy"), False, False, 0)
        self.page.pack_start(hero, False, False, 0)

    def _build_input(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        add_class(card, "input-card")
        card.pack_start(label("检测 IPv4 或 IPv6 地址", "section-title"), False, False, 0)
        card.pack_start(label("留空检测当前出口；指定地址时仍会检查本机 DNS、IPv6 与网络质量。", "section-copy"), False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        self.ip_entry = Gtk.Entry()
        self.ip_entry.set_hexpand(True)
        self.ip_entry.set_placeholder_text("当前连接，或输入 8.8.8.8 / 2001:4860:4860::8888")
        self.ip_entry.connect("activate", self._submit)
        add_class(self.ip_entry, "ip-entry")
        row.pack_start(self.ip_entry, True, True, 0)
        self.current_button = Gtk.Button(label="检测当前出口")
        add_class(self.current_button, "secondary-button")
        self.current_button.connect("clicked", lambda _button: self._use_current())
        row.pack_start(self.current_button, False, False, 0)
        self.check_button = Gtk.Button(label="开始完整检测  →")
        add_class(self.check_button, "primary-button")
        self.check_button.connect("clicked", self._submit)
        row.pack_start(self.check_button, False, False, 0)
        card.pack_start(row, False, False, 0)
        self.page.pack_start(card, False, False, 0)

    def _build_status(self):
        strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        add_class(strip, "status-strip")
        dot = Gtk.Box()
        add_class(dot, "status-dot")
        strip.pack_start(dot, False, False, 0)
        self.status_label = label("准备就绪", "muted")
        strip.pack_start(self.status_label, False, False, 0)
        self.source_summary = label("9 类诊断模块", "micro", xalign=1)
        strip.pack_end(self.source_summary, False, False, 0)
        self.page.pack_start(strip, False, False, 0)

    def _submit(self, _widget):
        value = self.ip_entry.get_text().strip()
        if value and not core.valid_ip(value):
            self._show_error("IP 地址格式不正确", "请输入有效 IPv4 或 IPv6 地址，或留空检测当前出口。")
            return
        self.start_check(value or None)

    def _use_current(self):
        self.ip_entry.set_text("")
        self.start_check(None)

    def _set_busy(self, busy):
        self._busy = busy
        for widget in (self.ip_entry, self.check_button, self.current_button):
            widget.set_sensitive(not busy)

    def start_check(self, target):
        if self._busy:
            return False
        self._run_id += 1
        run_id = self._run_id
        self._last_target = target
        self._set_busy(True)
        self.status_label.set_text("正在执行完整诊断…")
        self.source_summary.set_text("模块并行运行中")
        self._show_loading("正在准备网络检测", 0.03)
        threading.Thread(target=self._work, args=(run_id, target), daemon=True).start()
        return False

    def _show_loading(self, message, fraction):
        clear_box(self.content)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        add_class(card, "card")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        spinner = Gtk.Spinner()
        spinner.start()
        row.pack_start(spinner, False, False, 0)
        self.loading_title = label(message, "loading-title")
        row.pack_start(self.loading_title, False, False, 0)
        card.pack_start(row, False, False, 0)
        self.progress = Gtk.ProgressBar()
        add_class(self.progress, "progressbar")
        self.progress.set_fraction(fraction)
        card.pack_start(self.progress, False, False, 0)
        self.loading_detail = label("检测在后台并行运行，通常需要 10–30 秒。", "micro")
        card.pack_start(self.loading_detail, False, False, 0)
        self.content.pack_start(card, False, False, 0)
        self.content.show_all()

    def _queue_progress(self, run_id, message, fraction):
        def update():
            if run_id == self._run_id and self._busy:
                self.loading_title.set_text(message)
                self.progress.set_fraction(fraction)
            return False
        GLib.idle_add(update)

    def _work(self, run_id, target):
        try:
            report = core.run_diagnostics(target, lambda text, value: self._queue_progress(run_id, text, value))
            GLib.idle_add(self._finish_success, run_id, report)
        except Exception as exc:
            GLib.idle_add(self._finish_error, run_id, "检测意外中断", str(exc))

    def _finish_success(self, run_id, report):
        if run_id != self._run_id:
            return False
        self._set_busy(False)
        self.status_label.set_text("完整诊断已完成")
        sources = report["sources"]
        count = sum(1 for item in sources.values() if item.get("ok"))
        self.source_summary.set_text(f"{count} 个信誉源 + 5 个本地模块")
        self._render_result(report)
        return False

    def _finish_error(self, run_id, title, detail):
        if run_id != self._run_id:
            return False
        self._set_busy(False)
        self._show_error(title, detail)
        return False

    def _show_error(self, title, detail):
        self.status_label.set_text("检测失败")
        self.source_summary.set_text("可重新尝试")
        clear_box(self.content)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        add_class(card, "error-card")
        card.pack_start(label(title, "section-title"), False, False, 0)
        card.pack_start(label(detail), False, False, 0)
        retry = Gtk.Button(label="重新检测")
        add_class(retry, "secondary-button")
        retry.connect("clicked", lambda _button: self.start_check(self._last_target))
        card.pack_start(retry, False, False, 8)
        self.content.pack_start(card, False, False, 0)
        self.content.show_all()

    def _section(self, title, copy=None):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        add_class(outer, "section-wrap")
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        add_class(card, "card")
        card.pack_start(label(title, "section-title"), False, False, 0)
        if copy:
            card.pack_start(label(copy, "section-copy"), False, False, 8)
        outer.pack_start(card, False, False, 0)
        return outer, card

    def _detail_row(self, name, description, value, state="neutral"):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        add_class(row, "detail-row")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.pack_start(label(name, "detail-name"), False, False, 0)
        if description:
            text.pack_start(label(description, "micro"), False, False, 0)
        row.pack_start(text, True, True, 0)
        row.pack_end(label(value, "chip", f"chip-{state}", xalign=1), False, False, 0)
        return row

    def _render_result(self, report):
        clear_box(self.content)
        assessment = report["assessment"]
        risk = int(assessment["overall"])
        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=21)
        add_class(hero, "result-hero")
        score = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        add_class(score, "score-box", f"risk-{assessment['level']}")
        score.pack_start(label(risk, "score-number", xalign=0.5), False, False, 0)
        score.pack_start(label("综合风险 / 100", "score-caption", xalign=0.5), False, False, 0)
        hero.pack_start(score, False, False, 0)
        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        summary.set_valign(Gtk.Align.CENTER)
        summary.pack_start(label(assessment["method"], "eyebrow"), False, False, 0)
        summary.pack_start(label(assessment["label"], "verdict"), False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        row.pack_start(label(report["target_ip"], "ip-value", selectable=True), False, False, 0)
        copy = Gtk.Button.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON)
        add_class(copy, "quiet-button")
        copy.connect("clicked", lambda _button: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(report["target_ip"], -1))
        row.pack_start(copy, False, False, 0)
        summary.pack_start(row, False, False, 2)
        summary.pack_start(label(f"信誉风险 {assessment['reputation']} · 泄漏风险 {assessment['leak']} · {report['generated_at']}", "micro"), False, False, 0)
        hero.pack_start(summary, True, True, 0)
        self.content.pack_start(hero, False, False, 0)
        self.content.pack_start(self._metrics(report), False, False, 0)
        self.content.pack_start(self._reputation(report), False, False, 0)
        self.content.pack_start(self._leaks(report), False, False, 0)
        self.content.pack_start(self._quality(report), False, False, 0)
        self.content.pack_start(self._platforms(report), False, False, 0)
        self.content.pack_start(self._sources(report), False, False, 0)
        notice = label("结果说明：信誉分采用多源最高风险原则，避免平均值掩盖单一高危记录。DNS 与本机地址检查是旁路线索；浏览器 WebRTC 需要在实际浏览器中做 ICE 测试。平台模块只验证访问响应，不保证片库或播放权限。", "notice")
        self.content.pack_start(notice, False, False, 0)
        self.content.show_all()

    def _metrics(self, report):
        info_result = report["sources"]["ipinfo"]
        info = info_result["data"] if info_result["ok"] else {}
        scam_result = report["sources"]["scamalytics"]
        scam = scam_result["data"] if scam_result["ok"] else {}
        exits = report["exits"]
        v4 = exits["ipv4"]["data"]["ip"] if exits["ipv4"]["ok"] else "未检测到"
        v6 = exits["ipv6"]["data"]["ip"] if exits["ipv6"]["ok"] else "未检测到"
        location = " · ".join(x for x in (info.get("country"), info.get("region"), info.get("city")) if x) or "未获取"
        values = [("位置", location), ("网络 / ASN", info.get("org") or info.get("asn") or "未获取"),
                  ("IPv4 出口", v4), ("IPv6 出口", v6),
                  ("连接类型", scam.get("connection") or "未获取"), ("目标地址版本", "IPv6" if ":" in report["target_ip"] else "IPv4")]
        grid = Gtk.Grid(column_spacing=11, row_spacing=11)
        add_class(grid, "metric-grid")
        for index, (title, value) in enumerate(values):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            add_class(card, "metric-card")
            card.set_hexpand(True)
            card.pack_start(label(title, "metric-label"), False, False, 0)
            card.pack_start(label(value, "metric-value", selectable=True), False, False, 0)
            grid.attach(card, index % 2, index // 2, 1, 1)
        return grid

    def _reputation(self, report):
        outer, card = self._section("信誉与滥用记录", "每个已返回数据源都会参与综合风险，不再只看单一分数。")
        sources = report["sources"]
        scam = sources["scamalytics"]
        if scam["ok"]:
            data = scam["data"]
            card.pack_start(self._detail_row("Scamalytics", data.get("connection") or "代理特征与公开黑名单", f"{data.get('score', '未知')} 分", "bad" if (data.get("score") or 0) > 60 else "warn" if (data.get("score") or 0) > 10 else "good"), False, False, 0)
            positives = [core.LABEL_ZH.get(k, k) for k, v in data.get("flags", {}).items() if v == "Yes"]
            blocks = [core.LABEL_ZH.get(k, k) for k, v in data.get("blacklist", {}).items() if v == "Yes"]
            card.pack_start(self._detail_row("代理标记", "、".join(positives) if positives else "未发现明确代理高危标记", "有命中" if positives else "未命中", "warn" if positives else "good"), False, False, 0)
            card.pack_start(self._detail_row("公开黑名单", "、".join(blocks) if blocks else "未发现明确命中", "有命中" if blocks else "未命中", "bad" if blocks else "good"), False, False, 0)
        else:
            card.pack_start(self._detail_row("Scamalytics", error_text(scam), "失败", "bad"), False, False, 0)
        ipqs = sources["ipqs"]
        if ipqs["ok"]:
            data = ipqs["data"] or {}
            flags = [name for name in ("proxy", "vpn", "tor", "recent_abuse", "bot_status") if core._truthy(data.get(name))]
            card.pack_start(self._detail_row("IPQualityScore", "信号：" + ("、".join(flags) if flags else "未见高危标记"), f"{data.get('fraud_score', '未知')} 分", "bad" if (data.get("fraud_score") or 0) >= 75 else "good"), False, False, 0)
        else:
            card.pack_start(self._detail_row("IPQualityScore", error_text(ipqs), "可选" if not report["configured"]["ipqs"] else "失败", "neutral" if not report["configured"]["ipqs"] else "bad"), False, False, 0)
        abuse = sources["abuse"]
        if abuse["ok"]:
            data = abuse["data"] or {}
            detail = f"近 90 天报告 {data.get('totalReports', 0)} 次 · {data.get('usageType') or '用途未知'}"
            value = int(data.get("abuseConfidenceScore") or 0)
            card.pack_start(self._detail_row("AbuseIPDB", detail, f"{value}%", "bad" if value >= 50 else "warn" if value else "good"), False, False, 0)
        else:
            card.pack_start(self._detail_row("AbuseIPDB", error_text(abuse), "可选" if not report["configured"]["abuse"] else "失败", "neutral" if not report["configured"]["abuse"] else "bad"), False, False, 0)
        for note in report["assessment"].get("notes", []):
            card.pack_start(label("• " + note, "micro"), False, False, 2)
        return outer

    def _leaks(self, report):
        outer, card = self._section("泄漏与旁路检查", "检查 IPv6、系统 DNS 和本机网卡地址；结果按证据强弱展示。")
        leaks = report["leaks"]
        ipv6 = leaks["ipv6"]
        ipv6_state = ipv6["status"] if ipv6["status"] in ("good", "warn", "bad") else "neutral"
        card.pack_start(self._detail_row("IPv6 出口一致性", ipv6["summary"], ipv6["status"] == "good" and "正常" or ipv6["status"] == "warn" and "警告" or "未知", ipv6_state), False, False, 0)
        dns = leaks["dns"]
        if dns["ok"]:
            data = dns["data"]
            server_text = "、".join(data["servers"]) or "未解析到服务器"
            dns_state = data["status"] if data["status"] in ("good", "warn", "bad") else "neutral"
            card.pack_start(self._detail_row("系统 DNS 路由", f"{data['summary']} · {server_text}", "警告" if data["status"] == "warn" else "已检查", dns_state), False, False, 0)
        else:
            card.pack_start(self._detail_row("系统 DNS 路由", error_text(dns), "失败", "bad"), False, False, 0)
        interfaces = leaks["interfaces"]
        if interfaces["ok"]:
            data = interfaces["data"]
            exposed = "、".join(f"{item['interface']} {item['ip']}" for item in data["public"])
            detail = data["summary"] + (" · " + exposed if exposed else "")
            card.pack_start(self._detail_row("本机旁路 / WebRTC 线索", detail, "需留意" if data["public"] else "未发现", "warn" if data["public"] else "good"), False, False, 0)
        else:
            card.pack_start(self._detail_row("本机旁路 / WebRTC 线索", error_text(interfaces), "失败", "bad"), False, False, 0)
        card.pack_start(label("浏览器 WebRTC 可能通过 ICE/STUN 暴露更多地址，本机应用无法代替浏览器内的实际测试。", "micro"), False, False, 7)
        return outer

    def _quality(self, report):
        outer, card = self._section("网络质量", "通过系统默认路由测量，不把速度体验和 IP 信誉混为一谈。")
        result = report["quality"]
        if result["ok"]:
            data = result["data"]
            state = "bad" if data["status"] == "bad" else "warn" if data["status"] == "warn" else "good"
            card.pack_start(self._detail_row("延迟与丢包", data["caveat"], data["summary"], state), False, False, 0)
            for probe in data["probes"]:
                value = f"{probe['avg_ms'] if probe['avg_ms'] is not None else '—'} ms / {probe['loss'] if probe['loss'] is not None else '—'}%"
                card.pack_start(self._detail_row(probe["host"], "平均延迟 / 丢包率", value, "good" if probe["ok"] and (probe["loss"] or 0) == 0 else "warn"), False, False, 0)
        else:
            card.pack_start(self._detail_row("系统路由探测", error_text(result), "失败", "bad"), False, False, 0)
        return outer

    def _platforms(self, report):
        outer, card = self._section("平台访问（实验性）", "只验证站点连通和响应，不宣称视频、地区片库或账号权限已经解锁。")
        result = report["platforms"]
        if result["ok"]:
            for item in result["data"]["services"]:
                detail = f"HTTP {item['status']} · {item['latency_ms']} ms" if item["reachable"] else error_text({"error": item["error"]})
                card.pack_start(self._detail_row(item["name"], detail, "可访问" if item["reachable"] else "不可访问", "good" if item["reachable"] else "bad"), False, False, 0)
        else:
            card.pack_start(self._detail_row("平台访问", error_text(result), "失败", "bad"), False, False, 0)
        return outer

    def _sources(self, report):
        outer, card = self._section("数据源状态", "失败原因会明确区分超时、限流、密钥、网络和网页结构变化。")
        descriptions = {"ipinfo": "位置、ISP 与 ASN", "scamalytics": "欺诈分、代理和黑名单",
                        "ipqs": "欺诈与匿名网络信号", "abuse": "近期滥用记录"}
        names = {"ipinfo": "IPinfo / 备用源", "scamalytics": "Scamalytics", "ipqs": "IPQualityScore", "abuse": "AbuseIPDB"}
        for key in ("ipinfo", "scamalytics", "ipqs", "abuse"):
            result = report["sources"][key]
            if result["ok"]:
                value = f"正常 · {result.get('latency_ms') or '—'} ms"
                detail = descriptions[key] + (f" · {result['note']}" if result.get("note") else "")
                state = "good"
            else:
                value = "未配置" if (result.get("error") or {}).get("kind") == "not_configured" else "失败"
                detail = error_text(result)
                state = "neutral" if value == "未配置" else "bad"
            card.pack_start(self._detail_row(names[key], detail, value, state), False, False, 0)
        return outer

    def _open_settings(self, _button):
        dialog = SettingsDialog(self)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                dialog.save()
                self.source_summary.set_text("设置已保存在本机")
            except OSError as exc:
                self._show_error("设置保存失败", str(exc))
        dialog.destroy()


class PurityApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        window = self.get_active_window()
        if window is None:
            window = PurityWindow(self)
            window.show_all()
        window.present()


def main():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    GLib.set_prgname(APP_ID)
    GLib.set_application_name(APP_NAME)
    Gdk.set_program_class("IPPurity")
    if ICON_PATH.is_file():
        Gtk.Window.set_default_icon_from_file(str(ICON_PATH))
    return PurityApplication().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
