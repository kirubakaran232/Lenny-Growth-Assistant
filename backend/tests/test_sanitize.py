from app.sanitize import build_sandbox_document, render_markdown, sanitize_html_fragment

EVIL = ('<h1 onclick="x()">Hi</h1><script>alert(1)</script><img src=x onerror=alert(1)>'
        '<a href="javascript:alert(1)">bad</a><a href="https://ok.example">ok</a>'
        '<iframe src="https://evil.example"></iframe><form action="https://evil.example"><input></form>'
        '<style>@import url(https://evil.example/x.css);body{background:url(https://evil.example/p.png);color:red}</style>'
        '<div style="background:url(http://evil.example/a);color:blue">x</div><svg onload=alert(1)></svg>')


def test_html_fragment_blocks_active_content():
    out = sanitize_html_fragment(EVIL)
    low = out.lower()
    for bad in ("<script", "onclick", "onerror", "javascript:", "<iframe", "<form", "<input", "<img", "onload", "@import", "evil.example"):
        assert bad not in low, bad
    assert "color:red" in out and "color:blue" in out  # styling survives
    assert 'href="https://ok.example"' in out and "noopener" in out


def test_sandbox_document_has_csp_and_no_script():
    doc = build_sandbox_document("html", EVIL)
    assert "Content-Security-Policy" in doc and "default-src 'none'" in doc and "script-src 'none'" in doc
    assert "<script" not in doc.lower()


def test_markdown_raw_html_is_sanitised_and_citations_linked():
    out = render_markdown("**hi** <script>alert(1)</script> <img src=x onerror=1> [S2]", link_citations=True)
    assert "<script" not in out and "onerror" not in out and "<strong>hi</strong>" in out
    assert 'href="#src-2"' in out


def test_markdown_artifact_document():
    doc = build_sandbox_document("markdown", "# T\n\n- a\n- b\n\n<script>x</script>")
    assert "<h1>T</h1>" in doc and "<li>a</li>" in doc and "<script" not in doc.lower()
