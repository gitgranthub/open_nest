"""Websites: what Open Nest can read about a page, and the changes the recipes make.

A website is three plain files, and the starter already says where things belong:
colours are variables at the top of ``styles.css``, sections live in ``<main>``, the
navigation links to them by id, and the cards are a list. So the operations here find
those places -- with Python's own HTML parser and a strict reading of the stylesheet's
``:root`` blocks -- and put new pieces there, shaped by what the child asked for: a
section called "My favourite films" becomes a list, one called "How I made it" becomes
steps, one called "Contact me" says to ask a grown-up before putting an address online.

What this can never do is look at the page. Gary cannot see it either (the Website
prompt says so), so the checks are about the files -- every tag closed, every link
pointing somewhere real, nothing loaded from the internet -- and the reply always
ends by asking the child to press Preview Website and look.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from opennest.assets import manager as assets
from opennest.execution import web_preview
from opennest.fastpath import slots
from opennest.fastpath.classifier import OTHER, Option
from opennest.fastpath.kinds import (
    AlreadyDone,
    Change,
    Context,
    Facts,
    NeedsAnswer,
    NotApplicable,
    confident,
    game_things,
)

PAGE = "src/index.html"
STYLES = "src/styles.css"
SCRIPT = "src/script.js"

#: Tags whose opening and closing have to pair up for the page to be the page it looks
#: like in the file. Void tags (img, br, meta, link, input) have no closing tag.
_PAIRED = frozenset({
    "html", "head", "body", "header", "nav", "main", "section", "footer", "article",
    "aside", "div", "ul", "ol", "li", "p", "h1", "h2", "h3", "h4", "button", "a",
    "figure", "figcaption", "span", "strong", "em", "title", "script", "style", "code",
})


# ----------------------------------------------------------------------------- facts

class _Scan(HTMLParser):
    """Where each tag starts and ends, by line. Records; never judges."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.starts: list[tuple[str, dict, int]] = []
        self.ends: list[tuple[str, int]] = []
        self.stack: list[str] = []
        self.unbalanced: list[str] = []
        self.text: dict[str, str] = {}
        self._capture: str | None = None
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        self.starts.append((tag, attributes, self.getpos()[0] - 1))
        if tag in _PAIRED:
            self.stack.append(tag)
        if tag in ("h1", "title"):
            self._capture = tag
            self.text.setdefault(tag, "")
        if tag == "a" and attributes.get("href", "").startswith("#"):
            self.hrefs.append(attributes["href"][1:])

    def handle_endtag(self, tag):
        self.ends.append((tag, self.getpos()[0] - 1))
        if tag in _PAIRED:
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            elif tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.unbalanced.append(self.stack.pop())
                self.stack.pop()
            else:
                self.unbalanced.append(f"/{tag}")
        if tag == self._capture:
            self._capture = None

    def handle_data(self, data):
        if self._capture:
            self.text[self._capture] += data


def _scan(source: str) -> _Scan:
    scan = _Scan()
    scan.feed(source)
    scan.close()
    return scan


@dataclass(frozen=True)
class CssValue:
    name: str
    value: str
    line: int
    start: int
    end: int


_CSS_VAR = re.compile(r"^(\s*)(--[\w-]+)\s*:\s*([^;]+);")
_FONT_SIZE = re.compile(r"^(\s*)font-size\s*:\s*(\d+)px\s*;")


def _css_facts(source: str, values: dict) -> None:
    """Every ``--variable`` in a ``:root`` block, and the body's font size.

    Read line by line rather than parsed: the starter writes one declaration per line,
    and anything that does not look like that is simply not found -- which makes the
    operation step aside rather than edit something it half-understood.
    """
    variables: dict[str, list[CssValue]] = {}
    depth = 0
    block = None
    for number, line in enumerate(source.split("\n")):
        stripped = line.strip()
        if block is None and stripped.startswith(":root") and "{" in stripped:
            block, depth = "root", 0
        elif block is None and re.match(r"^body\s*\{", stripped):
            block, depth = "body", 0
        if block == "root":
            match = _CSS_VAR.match(line)
            if match:
                start = line.index(match.group(3))
                variables.setdefault(match.group(2), []).append(
                    CssValue(match.group(2), match.group(3).strip(), number, start,
                             start + len(match.group(3).rstrip())))
        if block == "body":
            match = _FONT_SIZE.match(line)
            if match:
                start = line.index(match.group(2))
                values["body_font"] = CssValue("font-size", match.group(2), number, start,
                                               start + len(match.group(2)))
        depth += line.count("{") - line.count("}")
        if block is not None and depth <= 0 and "}" in line:
            block = None
    values["css_vars"] = variables or None


def facts(project, attachments=()) -> Facts:
    values: dict = {"entry": PAGE}
    images = [a.path for a in assets.list_assets(project) if a.kind == "image"]
    attached = [a.path for a in attachments if getattr(a, "kind", "") == "image"]
    values["images"] = images or None
    values["attached_images"] = attached or None

    page = project.directory / PAGE
    styles = project.directory / STYLES
    script = project.directory / SCRIPT
    if styles.is_file():
        values["styles"] = styles.read_text(encoding="utf-8")
        _css_facts(values["styles"], values)
    if script.is_file():
        values["script"] = script.read_text(encoding="utf-8")
        values["script_ids"] = tuple(re.findall(r"getElementById\(\s*[\"']([\w-]+)[\"']\s*\)",
                                                values["script"]))
    if not page.is_file():
        return Facts(values)
    source = page.read_text(encoding="utf-8")
    values["page"] = source
    scan = _scan(source)
    lines = source.split("\n")
    values["ids"] = tuple(attrs["id"] for _, attrs, _ in scan.starts if attrs.get("id"))
    values["balanced"] = not scan.unbalanced and not scan.stack

    def only_end(tag: str) -> int | None:
        found = [line for name, line in scan.ends if name == tag]
        if len(found) == 1 and lines[found[0]].strip() == f"</{tag}>":
            return found[0]
        return None

    values["main_end"] = only_end("main")
    values["nav_end"] = only_end("nav")
    # The cards list: the <ul class="cards"> and its own closing tag.
    starts = [(line, attrs) for tag, attrs, line in scan.starts if tag == "ul"
              and "cards" in attrs.get("class", "").split()]
    if len(starts) == 1:
        opened = starts[0][0]
        closing = [line for name, line in scan.ends if name == "ul" and line > opened]
        if closing and lines[closing[0]].strip() == "</ul>":
            values["cards_end"] = closing[0]
            values["cards"] = sum(
                1 for tag, attrs, line in scan.starts
                if tag == "li" and "card" in attrs.get("class", "").split()
                and opened < line < closing[0]
            )
    sections = [line for name, line in scan.ends if name == "section"]
    if sections and lines[sections[0]].strip() == "</section>":
        values["first_section_end"] = sections[0]
    values["sections"] = sum(1 for tag, _, _ in scan.starts if tag == "section") or None

    for tag in ("h1", "title"):
        text = scan.text.get(tag, "").strip()
        if not text:
            continue
        matches = [n for n, line in enumerate(lines) if f"<{tag}" in line and text in line]
        if len(matches) == 1:
            line = lines[matches[0]]
            start = line.index(text, line.index(f"<{tag}"))
            values[tag] = (matches[0], start, start + len(text), text)
    return Facts(values)


def where(facts: Facts) -> str:
    """Where things are in this site, for Gary when he makes the change himself."""
    notes = ["WHERE THINGS ARE IN THIS SITE RIGHT NOW"]
    if facts.has("css_vars"):
        notes.append("- The colours are the variables in :root at the top of "
                     f"src/styles.css: {', '.join(facts.get('css_vars'))}. There is a second "
                     "set for dark mode just below it.")
    page = (facts.get("page") or "").split("\n")
    if facts.has("main_end"):
        notes.append(f"- New sections go inside <main>, before line "
                     f"{facts.get('main_end') + 1}: {page[facts.get('main_end')].strip()}")
    if facts.has("nav_end"):
        notes.append(f"- Navigation links go before line {facts.get('nav_end') + 1}, and each "
                     "href=\"#id\" must match a section's id.")
    if facts.has("cards_end"):
        notes.append(f"- The cards are the <li class=\"card\"> items; the list ends at line "
                     f"{facts.get('cards_end') + 1}.")
    if facts.has("script_ids"):
        notes.append(f"- script.js looks up these ids: {', '.join(facts.get('script_ids'))}. "
                     "Keep them in the page.")
    return "\n".join(notes) if len(notes) > 1 else ""


# ------------------------------------------------------------------------ editing

class _Lines:
    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self.inserts: dict[int, list[str]] = {}
        self.spans: list[tuple[int, int, int, str]] = []

    def before(self, index: int, block: list[str], indent: str = "") -> None:
        self.inserts.setdefault(index, []).extend(
            (indent + line) if line else "" for line in block)

    def replace(self, line: int, start: int, end: int, text: str) -> None:
        self.spans.append((line, start, end, text))

    def text(self) -> str:
        lines = list(self.lines)
        for line, start, end, text in sorted(self.spans, reverse=True):
            lines[line] = lines[line][:start] + text + lines[line][end:]
        for index in sorted(self.inserts, reverse=True):
            lines[index:index] = self.inserts[index]
        return "\n".join(lines)


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _require(facts: Facts, *names: str) -> None:
    missing = facts.missing(names)
    if missing:
        raise NotApplicable(f"the site does not have: {', '.join(missing)}")


def _slug(text: str, taken: tuple[str, ...]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    slug, number = base, 2
    while slug in taken:
        slug, number = f"{base}-{number}", number + 1
    return slug


def _luminance(hex_value: str) -> float | None:
    match = re.fullmatch(r"#([0-9a-fA-F]{6})", hex_value.strip())
    if not match:
        return None
    channels = [int(match.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float | None:
    """WCAG contrast ratio between two hex colours, or None if either is not hex."""
    la, lb = _luminance(a), _luminance(b)
    if la is None or lb is None:
        return None
    high, low = max(la, lb), min(la, lb)
    return (high + 0.05) / (low + 0.05)


#: The parts of the site a colour change can mean, and the variable each one is.
_COLOUR_PARTS = {
    "--accent": ("the accent", "the accent colour: links, buttons, highlights and the "
                               "navigation"),
    "--bg": ("the background", "the background of the whole page"),
    "--ink": ("the writing", "the colour of the writing"),
    "--card": ("the cards", "the background of the cards or boxes"),
}


#: Words that name one part of the site outright. Checked before any model question.
_PART_WORDS = (
    ("--card", r"\b(cards?|boxes|box)\b"),
    ("--ink", r"\b(writing|words|text|letters|font colou?r)\b"),
    ("--accent", r"\b(accent|buttons?|links?|menu|nav|highlights?)\b"),
    ("--bg", r"\b(back\s*g?round|page colou?r|whole page)\b"),
)


def set_colour(ctx: Context) -> Change:
    """Change one colour variable -- in light and dark mode both, so the child sees it
    whichever way their Mac is set -- and warn if the writing becomes hard to read."""
    _require(ctx.facts, "css_vars")
    variables = ctx.facts.get("css_vars")
    # The child's own word for the part decides it before any question is asked.
    # Measured in SPIKES.md section 25: asked "which part should change colour?" for
    # "make the background dark blue", the model answered "the cards" with 0.99 of its
    # weight, and the cards went dark blue.
    named = [name for name, pattern in _PART_WORDS if re.search(pattern, ctx.request, re.I)]
    part = named[0] if len(named) == 1 and named[0] in variables else None
    if part is None:
        if ctx.choose is None:
            raise NotApplicable("no model to ask which colour")
        parts = [Option(name, description)
                 for name, (_, description) in _COLOUR_PARTS.items() if name in variables]
        parts.append(Option(OTHER, "several colours at once, or none of these"))
        part = confident(ctx.choose("Which part of the site should change colour?", parts))
    if part is None or part == OTHER:
        raise NotApplicable("not sure which colour to change")
    named = game_things.colour_in(ctx.request)
    if named is None:
        options = [Option(name, name) for name in slots.PALETTE]
        options.append(Option(OTHER, "a colour not in this list, or no colour named"))
        answer = confident(ctx.choose("Which colour do they want?", options))
        if answer is None or answer == OTHER:
            raise NotApplicable("not sure which colour")
        named = (answer, slots.PALETTE[answer])
    colour_name, rgb = named
    value = slots.hex_of(rgb)
    edit = _Lines(ctx.facts.get("styles"))
    old = variables[part][0].value
    for css in variables[part]:
        edit.replace(css.line, css.start, css.end, value)
    styles = edit.text()

    note = ""
    after = {}
    _css_facts(styles, after)
    for block in range(len(after["css_vars"].get("--bg", []))):
        try:
            bg = after["css_vars"]["--bg"][block].value
            ink = after["css_vars"]["--ink"][block].value
        except (KeyError, IndexError):
            continue
        ratio = contrast(bg, ink)
        if ratio is not None and ratio < 4.5:
            note = ("The writing may be hard to read on it now -- ask me to change the "
                    "writing colour too.")
    return Change(
        files={STYLES: styles},
        values={"part": _COLOUR_PARTS[part][0], "colour": colour_name, "hex": value,
                "var": part, "old": old, "note": note,
                "changes": "change" if part == "--card" else "changes"},
        expect={"css_var": part, "value": value},
    )


def set_heading(ctx: Context) -> Change:
    """Change the big headline, and the tab's title with it when they matched."""
    _require(ctx.facts, "h1")
    words = slots.words_in(ctx.request) or slots.title_in(ctx.request)
    if not words:
        raise NotApplicable("the message does not say what the headline should say")
    line, start, end, old = ctx.facts.get("h1")
    edit = _Lines(ctx.facts.get("page"))
    edit.replace(line, start, end, html.escape(words, quote=False))
    title = ctx.facts.get("title")
    tab = ""
    if title is not None and title[3] == old:
        edit.replace(title[0], title[1], title[2], html.escape(words, quote=False))
        tab = " The browser tab says the same."
    return Change(files={PAGE: edit.text()},
                  values={"words": words, "old": old, "tab": tab},
                  expect={"present": [html.escape(words, quote=False)]})


#: The words a child most often wants changed, other than the headline: the line under
#: it, the footer, and the button. Each is found by the child's own name for it -- never
#: by a question -- and by exactly one element in the page that holds only words.
_TEXT_PARTS = (
    ("tagline", "the line under the headline",
     r"\b(tag\s*line|subtitle|sub-title|slogan|motto|"
     r"under the (title|heading|headline|big title|name))\b"),
    ("footer", "the footer", r"\b(footer|bottom of the page|at the (very )?bottom)\b"),
    ("button", "the button", r"\bbutton\b"),
)
_WORDS_ONLY = r"([^<>]*)"


def _text_place(page: str, part: str) -> tuple[int, int, int, str] | None:
    """(line, start, end, words) of the one element that holds that part's words."""
    lines = page.split("\n")
    if part == "tagline":
        pattern = re.compile(rf'<p class="tagline">{_WORDS_ONLY}</p>')
        candidates = range(len(lines))
    elif part == "button":
        if page.count("<button") != 1:
            return None
        pattern = re.compile(rf"<button\b[^>]*>{_WORDS_ONLY}</button>")
        candidates = range(len(lines))
    else:
        opened = [n for n, line in enumerate(lines) if "<footer" in line]
        closed = [n for n, line in enumerate(lines) if "</footer>" in line]
        if len(opened) != 1 or len(closed) != 1:
            return None
        pattern = re.compile(rf"<p\b[^>]*>{_WORDS_ONLY}</p>")
        candidates = range(opened[0], closed[0] + 1)
    found = [(n, match) for n in candidates for match in [pattern.search(lines[n])] if match]
    if len(found) != 1:
        return None
    number, match = found[0]
    return number, match.start(1), match.end(1), match.group(1)


def set_text(ctx: Context) -> Change:
    """Change the words of the tagline, the footer or the button to what the child wrote.

    Measured need: three of the first label set's requests ("make the tagline say i like
    cats and minecraft", "change the button to say Surprise me!", "change the footer to
    made by jayden 2026") were recognised with certainty and then handed to Gary,
    because this recipe only guided. Anything other than those three parts, or words
    that are not spelled out, still is.
    """
    _require(ctx.facts, "page")
    named = [(part, spoken) for part, spoken, pattern in _TEXT_PARTS
             if re.search(pattern, ctx.request, re.IGNORECASE)]
    if len(named) != 1:
        raise NotApplicable("the message does not name one of the tagline, the footer or "
                            "the button")
    part, spoken = named[0]
    words = slots.words_in(ctx.request)
    if not words:
        raise NotApplicable("the message does not say what the words should be")
    page = ctx.facts.get("page")
    place = _text_place(page, part)
    if place is None:
        raise NotApplicable(f"{spoken} is not one plain piece of words in the page")
    line, start, end, old = place
    written = html.escape(words, quote=False)
    # "Made with Open Nest" asked of a footer that says "Made with Open Nest." is the
    # same words: changing only the full stop is not what anyone meant.
    if html.unescape(old).strip().rstrip(".!?") == words.strip().rstrip(".!?"):
        raise AlreadyDone(f"{spoken[0].upper()}{spoken[1:]} already says "
                          f"\u201c{words}\u201d.")
    edit = _Lines(page)
    edit.replace(line, start, end, written)
    return Change(files={PAGE: edit.text()},
                  values={"part": spoken, "words": words, "old": html.unescape(old).strip()},
                  expect={"present": [written]})


_SECTION_TITLE = (
    re.compile(r"\b(?:section|part|bit|area|page)\s+(?:about|called|named|for|on|with)\s+"
               r"(?:the\s+)?(.+?)\s*[.!?]?\s*$", re.IGNORECASE),
    re.compile(r"\badd\s+(?:a|an|another|some)\s+(.+?)\s+(?:section|part)\b", re.IGNORECASE),
)

#: What a section's title suggests it should hold. Checked in order; the first wins.
_SECTION_KINDS = (
    ("contact", r"\b(contact|reach|email|phone|address)\b"),
    ("steps", r"\b(how i|how to|steps|timeline|history|story of|instructions|recipe)\b"),
    ("list", r"\b(favou?rite|top|things i|likes?|hobbies|facts|reasons|ideas|list|"
             r"collection|games|books|films|movies|songs|animals|foods?|friends|pets?)\b"),
)

_PARAGRAPHS = (
    "Write about {topic} here. A few sentences is plenty to start.",
    "This is where {topic} goes. Say it the way you would tell a friend.",
    "Start writing about {topic} here -- you can change every word of this.",
)


def _title_from(request: str) -> str | None:
    for pattern in _SECTION_TITLE:
        match = pattern.search(request.strip())
        if match:
            found = match.group(1).strip().strip("\"'“”")
            found = re.sub(r"^(?:a|an|the)\s+", "", found, flags=re.IGNORECASE)
            if 0 < len(found) <= 50:
                return found[0].upper() + found[1:]
    quoted = slots.title_in(request)
    return quoted[0].upper() + quoted[1:] if quoted else None


def _section_body(title: str, rng) -> tuple[str, list[str]]:
    topic = title.lower() if not title.isupper() else title
    lowered = title.lower()
    kind = next((name for name, pattern in _SECTION_KINDS if re.search(pattern, lowered)),
                "text")
    if kind == "list":
        return kind, ["<ul>", "  <li>Write the first one here.</li>",
                      "  <li>And the next one.</li>", "  <li>One more.</li>", "</ul>"]
    if kind == "steps":
        return kind, ["<ol>", "  <li>What happened first.</li>", "  <li>Then this.</li>",
                      "  <li>And how it ended.</li>", "</ol>"]
    if kind == "contact":
        return kind, ["<p>",
                      "  Write how people can reach you here. Ask a grown-up before you put",
                      "  an email address, a phone number or where you live on a website.",
                      "</p>"]
    return kind, [f"<p>{html.escape(rng.choice(_PARAGRAPHS).format(topic=topic))}</p>"]


def add_section(ctx: Context) -> Change:
    """A new section inside <main>, shaped by its title, and a link to it in the nav."""
    _require(ctx.facts, "main_end", "nav_end")
    title = _title_from(ctx.request)
    if not title:
        raise NotApplicable("the message does not say what the section is called")
    page = ctx.facts.get("page")
    lines = page.split("\n")
    slug = _slug(title, ctx.facts.get("ids") or ())
    rng = game_things.variety(ctx.project, "section", slug)
    kind, body = _section_body(title, rng)
    main_line = ctx.facts.get("main_end")
    inside = _indent(lines[main_line]) + "  "
    edit = _Lines(page)
    escaped = html.escape(title, quote=False)
    edit.before(main_line, ["", f'<section id="{slug}">', f"  <h2>{escaped}</h2>"]
                + [f"  {line}" for line in body] + ["</section>"], inside)
    nav_line = ctx.facts.get("nav_end")
    edit.before(nav_line, [f'<a href="#{slug}">{escaped}</a>'],
                _indent(lines[nav_line]) + "  ")
    what = {"list": "a list to fill in", "steps": "numbered steps to fill in",
            "contact": "a note about keeping personal details safe",
            "text": "a paragraph to write in"}[kind]
    return Change(files={PAGE: edit.text()},
                  values={"title": title, "id": slug, "what": what},
                  expect={"present": [f'id="{slug}"', f'href="#{slug}"']})


_CARD_TITLE = re.compile(r"\bcards?\s+(?:about|called|named|for|with|that says)\s+(.+?)\s*"
                         r"[.!?]?\s*$", re.IGNORECASE)
_CARD_TEXT = ("Change this to something of yours.", "Say a little about it here.",
              "A sentence or two about this one.", "Write what makes this one good.")


def add_card(ctx: Context) -> Change:
    """Another card in the list of cards, in the same shape as the ones already there."""
    _require(ctx.facts, "cards_end")
    page = ctx.facts.get("page")
    lines = page.split("\n")
    match = _CARD_TITLE.search(ctx.request.strip())
    titles = []
    if match:
        found = match.group(1).strip().strip("\"'“”")
        titles = [part.strip() for part in re.split(r",|\band\b", found) if part.strip()]
    count = len(titles) or slots.count_in(ctx.request) or 1
    count = min(count, 8)
    number = ctx.facts.get("cards", 0)
    rng = game_things.variety(ctx.project, "card", number)
    close = ctx.facts.get("cards_end")
    item = _indent(lines[close]) + "  "
    block = []
    made = []
    for index in range(count):
        title = titles[index] if index < len(titles) else f"Card {number + index + 1}"
        title = title[0].upper() + title[1:]
        made.append(title)
        block += ['<li class="card">', f"  <h3>{html.escape(title, quote=False)}</h3>",
                  f"  <p>{rng.choice(_CARD_TEXT)}</p>", "</li>"]
    edit = _Lines(page)
    edit.before(close, block, item)
    quoted = [f'"{title}"' for title in made]
    names = quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + f" and {quoted[-1]}"
    return Change(files={PAGE: edit.text()},
                  values={"cards": names, "count": str(count),
                          "plural": "" if count == 1 else "s"},
                  expect={"present": [html.escape(t, quote=False) for t in made]})


_PICTURE_OF = re.compile(r"\b(?:picture|photo|image|drawing|pic)\s+of\s+(.+?)\s*[.!?]?\s*$",
                         re.IGNORECASE)


def add_image(ctx: Context) -> Change:
    """Put the child's picture on the page. Its description comes from the child alone."""
    _require(ctx.facts, "first_section_end")
    choices = ctx.facts.get("attached_images") or ctx.facts.get("images") or []
    if not choices:
        raise NeedsAnswer("there is no picture in the project yet")
    if len(choices) > 1:
        raise NeedsAnswer("there is more than one picture, and it does not say which")
    picture = choices[0]
    match = _PICTURE_OF.search(ctx.request.strip())
    # Nobody has seen the picture. The child's own words may describe it; nothing else
    # may -- not the file name, and not a guess (WORKORDER_01 section 13).
    alt = match.group(1).strip() if match else ""
    page = ctx.facts.get("page")
    lines = page.split("\n")
    close = ctx.facts.get("first_section_end")
    edit = _Lines(page)
    shown = alt or "Say what this picture shows"
    edit.before(close, [f'<img src="../{picture}" alt="{html.escape(shown)}">'],
                _indent(lines[close]) + "  ")
    ask = ("" if alt else "I haven't seen the picture, so tell me what it shows and I'll "
                          "add that as its description for people who can't see it.")
    return Change(files={PAGE: edit.text()},
                  values={"picture": picture, "ask": ask},
                  expect={"present": [f"../{picture}"], "picture": picture})


def change_font_size(ctx: Context) -> Change:
    """Make the writing bigger or smaller: the body's font size, which everything uses."""
    _require(ctx.facts, "body_font")
    font = ctx.facts.get("body_font")
    old = int(font.value)
    amount = slots.explicit_amount(ctx.request)
    if amount is not None and amount.value is not None:
        new = int(amount.value)
    else:
        if ctx.choose is None:
            raise NotApplicable("no model to ask which way")
        answer = confident(ctx.choose("Should the writing get bigger or smaller?", [
            Option("up", "bigger"), Option("down", "smaller"),
            Option(OTHER, "neither, or something else"),
        ]))
        if answer not in ("up", "down"):
            raise NotApplicable("not sure which way")
        new = round(old * (1.25 if answer == "up" else 0.85))
    new = max(11, min(40, new))
    if new == old:
        raise NotApplicable("the size would not change")
    edit = _Lines(ctx.facts.get("styles"))
    edit.replace(font.line, font.start, font.end, str(new))
    return Change(files={STYLES: edit.text()},
                  values={"old": str(old), "new": str(new),
                          "direction": "bigger" if new > old else "smaller"},
                  expect={"font_size": str(new)})


#: What a new button can do. Each is a complete, small interaction.
_BUTTON_KINDS = {
    "count": "count how many times it is pressed",
    "message": "show a message or some words when it is pressed",
    "colour": "change the colours of the page when it is pressed",
}
_MESSAGES = ("Hello! Thanks for pressing.", "You found the button.", "Nice one.",
             "Surprise!", "Press it again, I dare you.")


def add_button(ctx: Context) -> Change:
    """A button that does one complete thing, with its code in script.js."""
    _require(ctx.facts, "first_section_end")
    if ctx.facts.get("script") is None:
        raise NotApplicable("the site has no script.js")
    if ctx.choose is None:
        raise NotApplicable("no model to ask what the button does")
    options = [Option(name, text) for name, text in _BUTTON_KINDS.items()]
    options.append(Option(OTHER, "something else"))
    kind = confident(ctx.choose("What should the new button do?", options))
    if kind is None or kind == OTHER:
        raise NotApplicable("not sure what the button should do")
    taken = ctx.facts.get("ids") or ()
    rng = game_things.variety(ctx.project, "button", kind, len(taken))
    button_id = _slug(f"{kind}-button", taken)
    output_id = _slug(f"{kind}-output", taken + (button_id,))
    label = slots.title_in(ctx.request) or {
        "count": "Press me", "message": "Say something", "colour": "New colours"}[kind]
    said = slots.words_in(ctx.request) if kind == "message" else None
    message = said or rng.choice(_MESSAGES)
    page = ctx.facts.get("page")
    lines = page.split("\n")
    close = ctx.facts.get("first_section_end")
    edit = _Lines(page)
    markup = [f'<button id="{button_id}" type="button">{html.escape(label)}</button>']
    if kind in ("count", "message"):
        markup.append(f'<p id="{output_id}" aria-live="polite"></p>')
    edit.before(close, markup, _indent(lines[close]) + "  ")

    variable = re.sub(r"-(\w)", lambda m: m.group(1).upper(), button_id)
    if kind == "count":
        script = [
            "", f"// Counts presses of the {label!r} button.",
            f'const {variable} = document.getElementById("{button_id}");',
            f"let {variable}Presses = 0;",
            f'{variable}.addEventListener("click", () => {{',
            f"  {variable}Presses = {variable}Presses + 1;",
            f'  document.getElementById("{output_id}").textContent =',
            f'    "Pressed " + {variable}Presses + ({variable}Presses === 1 ? " time" : " times");',
            "});",
        ]
        what = "counts how many times it is pressed and shows the number under it"
    elif kind == "message":
        script = [
            "", f"// Shows a message when the {label!r} button is pressed.",
            f'const {variable} = document.getElementById("{button_id}");',
            f'{variable}.addEventListener("click", () => {{',
            f'  document.getElementById("{output_id}").textContent = {json.dumps(message)};',
            "});",
        ]
        what = f"shows “{message}” under it when pressed"
    else:
        # Soft tints of the shared palette -- each colour mixed 80% of the way to white --
        # so the writing stays readable on every one of them.
        tints = [slots.hex_of(tuple(round(c + (255 - c) * 0.8) for c in slots.PALETTE[name]))
                 for name in ("orange", "green", "blue", "pink", "yellow", "purple")]
        backgrounds = rng.sample(tints, 4)
        script = [
            "", f"// Gives the page new colours each time the {label!r} button is pressed.",
            f'const {variable} = document.getElementById("{button_id}");',
            f"const {variable}Colours = {json.dumps(backgrounds)};",
            f"let {variable}Next = 0;",
            f'{variable}.addEventListener("click", () => {{',
            f"  const pick = {variable}Colours[{variable}Next % {variable}Colours.length];",
            f"  {variable}Next = {variable}Next + 1;",
            '  document.documentElement.style.setProperty("--bg", pick);',
            "});",
        ]
        what = "changes the page's background colour each time it is pressed"
    scripts = ctx.facts.get("script").rstrip("\n") + "\n" + "\n".join(script) + "\n"
    return Change(files={PAGE: edit.text(), SCRIPT: scripts},
                  values={"label": label, "what": what},
                  expect={"present": [f'id="{button_id}"']})


OPS = {
    "set_colour": set_colour,
    "set_heading": set_heading,
    "set_text": set_text,
    "add_section": add_section,
    "add_card": add_card,
    "add_image": add_image,
    "change_font_size": change_font_size,
    "add_button": add_button,
}


# ------------------------------------------------------------------------ checks

def _check_balanced(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    if ctx.facts_after.get("balanced"):
        return Check("html_balanced", PASS)
    return Check("html_balanced", FAIL, "a tag in index.html is not closed")


def _check_offline(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    remote = web_preview.remote_references(ctx.project)
    if not remote:
        return Check("offline", PASS)
    return Check("offline", FAIL, f"asks the internet for {remote[0].url}")


def _check_links(ctx):
    """Every nav link points at an id, and every id the script looks up exists."""
    from opennest.fastpath.verifier import FAIL, PASS, Check

    page = ctx.facts_after.get("page") or ""
    ids = set(ctx.facts_after.get("ids") or ())
    wanted = set(_scan(page).hrefs) | set(ctx.facts_after.get("script_ids") or ())
    missing = sorted(wanted - ids)
    if missing:
        return Check("links_resolve", FAIL, f"nothing has the id {missing[0]!r}")
    return Check("links_resolve", PASS)


def _check_css(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    name, value = ctx.expect.get("css_var"), ctx.expect.get("value")
    found = [v.value for v in (ctx.facts_after.get("css_vars") or {}).get(name, [])]
    if found and all(v == value for v in found):
        return Check("css_value_set", PASS, f"{name}: {value}")
    return Check("css_value_set", FAIL, f"{name} is {found}")


def _check_present(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    page = ctx.facts_after.get("page") or ""
    missing = [text for text in ctx.expect.get("present", []) if text not in page]
    if missing:
        return Check("added_present", FAIL, f"not in the page: {missing[0]!r}")
    return Check("added_present", PASS)


def _check_picture(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    picture = ctx.expect.get("picture")
    if picture and (ctx.project.directory / picture).is_file():
        return Check("picture_exists", PASS, picture)
    return Check("picture_exists", FAIL, f"{picture} is not in the project")


def _check_font(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    font = ctx.facts_after.get("body_font")
    if font is not None and font.value == ctx.expect.get("font_size"):
        return Check("font_size_set", PASS, f"{font.value}px")
    return Check("font_size_set", FAIL, "the body font size is not what was asked")


CHECKS = {
    "html_balanced": _check_balanced,
    "offline": _check_offline,
    "links_resolve": _check_links,
    "css_value_set": _check_css,
    "added_present": _check_present,
    "picture_exists": _check_picture,
    "font_size_set": _check_font,
}


#: How a change Gary makes here is checked, for his context (router._context).
CHECKED = ("Open Nest checks the files afterwards: every tag closed, every link pointing "
           "somewhere real, nothing loaded from the internet. Nobody can see the page but "
           "the child.")


def verifiable(project) -> bool:
    """Every website check reads the files, so any project with the files can run them."""
    return True


def confirmation(verification, project=None) -> str:
    """What was checked -- the files -- and the one thing only the child can check."""
    from opennest.fastpath.verifier import PASS

    checked = []
    if verification.status_of("html_balanced") == PASS:
        checked.append("every tag is closed")
    if verification.status_of("links_resolve") == PASS:
        checked.append("every link goes somewhere real")
    if verification.status_of("offline") == PASS:
        checked.append("nothing loads from the internet")
    profile = getattr(project, "profile", None)
    if profile is None or profile.previews:
        look = "I can't see the page myself, so press Preview Website and have a look."
    else:
        # A Blank project has no preview button, and saying "press Preview Website"
        # there would send the child looking for one.
        look = "I can't see the page myself, and this project has no preview to open."
    if not checked:
        return look
    listed = checked[0] if len(checked) == 1 else ", ".join(checked[:-1]) + \
        f" and {checked[-1]}"
    return f"I checked the files: {listed}. {look}"


def brief(facts: Facts) -> str:
    """What the classifier is told about the site, from the facts alone."""
    if not facts.has("page"):
        return ""
    parts = []
    headline = facts.get("h1")
    if headline:
        parts.append(f'The page has a big headline "{headline[3]}"')
    else:
        parts.append("The page has")
    extras = ["a menu"] if facts.has("nav_end") else []
    if facts.has("sections"):
        extras.append(f"{facts.get('sections')} sections")
    if facts.has("cards"):
        extras.append(f"a list of {facts.get('cards')} cards")
    if "<button" in (facts.get("page") or ""):
        extras.append("a button")
    listed = extras[0] if len(extras) == 1 else ", ".join(extras[:-1]) + f" and {extras[-1]}"
    return f"{parts[0]}{', ' if headline else ' '}{listed}."
