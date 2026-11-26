"""Regression tests for the docs prose counter (scripts/check_pages.py::prose_words) and the Markdown escaping of
generated rule text (scripts/nf/docs_units.py), issue #1769."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


check_pages = _load("check_pages", ROOT / "scripts" / "check_pages.py")
sys.path.insert(0, str(ROOT / "scripts" / "nf"))
docs_units = _load("docs_units", ROOT / "scripts" / "nf" / "docs_units.py")
words = check_pages.prose_words


def test_inequalities_are_prose():
    # the #1769 reproduction: the old "<[^>]+>" strip returned 2
    assert words("alpha < 1.7 degC. important words here > omega") == 6
    assert words("SAT <= SP AND fan >= 0.9") == 4
    assert words("a<b and c>d") == 2   # "<b and c>" is a real tag to Markdown too: that is why generated text escapes it
    assert words("OAT < 12.8 °C, damper > 42 %") == 3   # OAT C damper


def test_one_equation_cannot_hide_the_next_rule():
    page = (
        "### FC1\n\nDSP <DSPSP minus margin.\n\n**Parity** match\n\n"
        "### FC2\n\nMAT above envelope > limit.\n\nSecond rule words.\n"
    )
    # FC DSP DSPSP minus margin Parity match FC MAT above envelope limit Second rule words
    assert words(page) == 15
    assert words(page) == words(page.replace("<", " ").replace(">", " "))


def test_tag_like_text_cannot_swallow_the_next_line():
    # "<tag" then a newline: the next line's words stay prose (review on #1792)
    assert words("alpha <tag\nwords here > omega") == 5   # alpha tag words here omega
    assert words("alpha <tag\n\twords here > omega") == 5
    assert words("a <b c=\"d\">x</b> y") == 3          # a one-line real tag is still stripped: a x y


def test_real_tags_and_comments_are_not_prose():
    assert words('<a id="fc1"></a>Duct static') == 2
    assert words("one<br/>two <span class=\"x\">three</span>") == 3
    assert words("before <!-- a generated note\nacross lines --> after") == 2
    assert words("see <https://example.org/page> now") == 2


def test_entities_are_not_words():
    assert words("DSP &lt; SP and 1 h &plusmn; 0.5 &#8805; x") == 5  # DSP SP and h x


def test_fenced_and_inline_code():
    assert words("text\n\n```python\nimport pandas as pd\nprint(x)\n```\n\nmore") == 2
    assert words("text\n~~~\ncode here\n~~~\nmore") == 2
    assert words("call `run_rule(df)` then `x < y` done") == 3


def test_unbalanced_backtick_or_bracket_stays_on_its_line():
    assert words("a stray ` backtick\nnext line words `x`") == 6   # a stray backtick next line words
    assert words("a [broken link\nnext line](target) words") == 7   # not a link: the target is counted, nothing is hidden


def test_links_count_text_not_target():
    assert words("[SQL entry](sql-cookbook.html#fc1) and ![chart](img/a.png)") == 4
    assert words("[`fc1`](https://github.com/x/y#L9) only") == 1


def test_tables_and_liquid_are_excluded():
    assert words("| Rule | Why |\n|---|---|\n| FC1 | words here |\nafter") == 1
    assert words("{% include x.html %}\nafter") == 1


def test_multiline_prose():
    assert words("first line\nsecond line\n\nthird paragraph") == 6


def test_md_text_escapes_angles_and_pipes_outside_code():
    assert docs_units.md_text("DSP < SP AND fan > 0.9") == "DSP &lt; SP AND fan &gt; 0.9"
    assert docs_units.md_text("|SAT - SP| > 2.8") == "\\|SAT - SP\\| &gt; 2.8"
    assert docs_units.md_text("keep `a < b | c` code") == "keep `a < b | c` code"
    assert docs_units.md_text("odd ` tick < x") == "odd ` tick &lt; x"
    assert docs_units.cell("a < b | c") == "a &lt; b \\| c"


def test_generated_rule_text_has_no_raw_angle_brackets():
    """Outside code, tags and comments, the generated rule pages carry no literal < or > that could render as HTML."""
    import re

    for name in ("sql-cookbook.md", "pandas-cookbook.md", "parity.md", "index.md"):
        body = (ROOT / "docs" / "rules" / name).read_text(encoding="utf-8")
        body = re.sub(r"```.*?```", " ", body, flags=re.S)
        body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
        body = re.sub(r"`[^`\n]*`", " ", body)
        body = re.sub(r'<a id="[^"]*"></a>', " ", body)
        body = "\n".join(ln for ln in body.splitlines() if not ln.startswith(">"))
        assert "<" not in body and ">" not in body.replace("->", ""), name
