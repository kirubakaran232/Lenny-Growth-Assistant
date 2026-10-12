"""Untrusted-content handling. Layers: (1) allow-list sanitiser (nh3), (2) CSS URL stripping,
(3) CSP meta inside the document, (4) <iframe sandbox=""> in the UI (no scripts, no same-origin)."""
import html
import re

import markdown as md
import nh3

_MD_TAGS = {"p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em", "b", "i",
            "code", "pre", "blockquote", "table", "thead", "tbody", "tr", "th", "td", "a", "sup", "sub", "del"}
_HTML_TAGS = _MD_TAGS | {"div", "span", "section", "article", "header", "footer", "main", "nav", "aside",
                         "figure", "figcaption", "dl", "dt", "dd", "small", "mark", "style", "button", "label",
                         "details", "summary", "abbr", "cite", "q", "kbd", "time"}
_ATTRS = {"*": {"class", "id", "style", "title", "role", "aria-label", "aria-hidden", "lang"},
          "a": {"href"}, "th": {"colspan", "rowspan"}, "td": {"colspan", "rowspan"}}
_SCHEMES = {"http", "https", "mailto"}

SANDBOX_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; "
               "script-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'")

_CSS_URL = re.compile(r"url\s*\([^)]*\)", re.I)
_CSS_IMPORT = re.compile(r"@import[^;{]*;?", re.I)
_CSS_EXPR = re.compile(r"expression\s*\([^)]*\)|javascript\s*:|behavior\s*:", re.I)
_CITE = re.compile(r"\[S(\d{1,2})\]")


def _scrub_css(css: str) -> str:
    return _CSS_EXPR.sub("", _CSS_IMPORT.sub("", _CSS_URL.sub("none", css)))


def sanitize_html_fragment(raw: str) -> str:
    cleaned = nh3.clean(raw, tags=_HTML_TAGS, clean_content_tags=set(), attributes=_ATTRS,
                        url_schemes=_SCHEMES, link_rel="noopener noreferrer nofollow", strip_comments=True)
    # defence in depth: remove any remaining CSS fetch vectors in <style> blocks and style="" attributes
    cleaned = re.sub(r"(<style[^>]*>)(.*?)(</style>)",
                     lambda m: m.group(1) + _scrub_css(html.unescape(m.group(2))).replace("<", "") + m.group(3),
                     cleaned, flags=re.S | re.I)
    cleaned = re.sub(r'(style=")([^"]*)(")', lambda m: m.group(1) + _scrub_css(html.unescape(m.group(2))).replace('"', "") + m.group(3), cleaned, flags=re.I)
    return cleaned


def render_markdown(text: str, link_citations: bool = False) -> str:
    raw = md.markdown(text, extensions=["extra", "sane_lists"])
    safe = nh3.clean(raw, tags=_MD_TAGS, attributes={"a": {"href"}, "th": {"colspan"}, "td": {"colspan"}},
                     url_schemes=_SCHEMES, link_rel="noopener noreferrer nofollow")
    if link_citations:  # digits only, inserted after sanitising, so cannot carry markup
        safe = _CITE.sub(lambda m: f'<a class="cite" href="#src-{m.group(1)}" data-n="{m.group(1)}">[{m.group(1)}]</a>', safe)
    return safe


_BASE_CSS = ("body{font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:24px;"
             "color:#1b1b1f;background:#fff}h1,h2,h3{line-height:1.25}table{border-collapse:collapse}"
             "td,th{border:1px solid #d0d0d8;padding:6px 10px}pre{background:#f3f3f6;padding:12px;overflow:auto}"
             "code{background:#f3f3f6;padding:0 4px;border-radius:3px}blockquote{border-left:4px solid #d0d0d8;"
             "margin:0;padding-left:16px;color:#555}")


def build_sandbox_document(artifact_type: str, content: str) -> str:
    """Full HTML document string for <iframe sandbox="" srcdoc=...>. Never contains script."""
    if artifact_type == "markdown":
        body, base = render_markdown(content), _BASE_CSS
    else:
        body, base = sanitize_html_fragment(content), ""  # HTML artifacts bring their own styling
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta http-equiv="Content-Security-Policy" content="{SANDBOX_CSP}">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<style>{base}</style></head><body>{body}</body></html>")
