"""CLIタブのMarkdown描画（app/static/markdown_view.js）のテスト

Node.jsでrenderMarkdownを実行し、生成したHTML文字列を確認する。
Node.jsが無い環境ではスキップする。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "app" / "static" / "markdown_view.js"
NODE = shutil.which("node")

RUNNER = """
const fs = require("fs");
const vm = require("vm");
const context = {};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8") + ";this.renderMarkdown = renderMarkdown;", context);
const input = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(context.renderMarkdown(input)));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.jsが無い")


def render(text: str) -> str:
    result = subprocess.run(
        [NODE, "-e", RUNNER, str(SCRIPT_PATH)],
        input=json.dumps(text),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def test_heading_and_paragraph_keep_line_breaks():
    html = render("# 見出し\n本文1行目。\n本文2行目。\\\n3行目")
    assert html == "<h1>見出し</h1><p>本文1行目。<br>本文2行目。<br>3行目</p>"


def test_nested_list_and_ordered_list():
    html = render("- a\n- b\n  - nested\n- c\n\n1. one\n2. two")
    assert html == (
        "<ul><li>a</li><li>b<ul><li>nested</li></ul></li><li>c</li></ul>"
        "<ol><li>one</li><li>two</li></ol>"
    )


def test_ordered_list_keeps_start_number():
    assert render("3. three") == '<ol start="3"><li>three</li></ol>'


def test_code_block_is_escaped_and_not_formatted():
    html = render("```js\nconst a = '<b>**x**</b>';\n  indent\n```")
    assert html == "<pre><code>const a = &#39;&lt;b&gt;**x**&lt;/b&gt;&#39;;\n  indent</code></pre>"


def test_unclosed_code_block_runs_to_end():
    assert render("```\nunclosed\n# not heading") == "<pre><code>unclosed\n# not heading</code></pre>"


def test_table_with_alignment_and_escaped_pipe():
    html = render("| No. | ファイル | 変更 |\n|:---|:---:|---:|\n| 1 | `a\\|b` | x |\n| 2 |")
    assert html == (
        '<div class="md-table-wrap"><table><thead><tr>'
        '<th class="md-align-left">No.</th><th class="md-align-center">ファイル</th>'
        '<th class="md-align-right">変更</th></tr></thead><tbody>'
        '<tr><td class="md-align-left">1</td><td class="md-align-center"><code>a|b</code></td>'
        '<td class="md-align-right">x</td></tr>'
        '<tr><td class="md-align-left">2</td><td class="md-align-center"></td>'
        '<td class="md-align-right"></td></tr>'
        "</tbody></table></div>"
    )


def test_table_right_after_paragraph():
    html = render("結果は以下。\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert html.startswith("<p>結果は以下。</p><div class=\"md-table-wrap\">")


def test_inline_formatting():
    html = render("**太字** *斜体* ~~消~~ `x<y>` snake_case_name a*b")
    assert html == (
        "<p><strong>太字</strong> <em>斜体</em> <del>消</del> <code>x&lt;y&gt;</code> snake_case_name a*b</p>"
    )


def test_quote_and_horizontal_rule():
    assert render("> 引用\n> **b**\n\n---") == "<blockquote><p>引用<br><strong>b</strong></p></blockquote><hr>"


def test_only_http_links_become_anchor():
    html = render("[ok](https://example.com/?a=1&b=2) [bad](javascript:alert(1))")
    assert html == '<p><a href="https://example.com/?a=1&amp;b=2">ok</a> [bad](javascript:alert(1))</p>'


def test_raw_html_is_escaped():
    html = render('<img src=x onerror="alert(1)"><script>alert(1)</script>')
    assert "<img" not in html and "<script" not in html
    assert html.startswith("<p>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")
