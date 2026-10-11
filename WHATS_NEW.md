# What's new: a Research report -- 8 x 10 pages, a PDF, and charts in the house style

*2026-10-11, branch `phase-13-live-preview`. The numbers are in SPIKES.md §34.*

## In one sentence

A Research project now makes a report -- its question, the charts the analysis draws, what
the child found and where the data came from, on 8 x 10 inch pages -- which the child sees
in the Workbench with **Show the report** and saves anywhere on the Mac with **Export
PDF…**, and the charts in it finally draw in Open Nest's own colours.

## What changed

- **The report** (`opennest/export/report.py`). Title, date and a small amber bar on page
  1; the title along the top of the pages after; "Page 2 of 4" at the foot. The paper is the
  charts' own warm colour. A chart is never cut in two or made bigger than it was drawn: it
  fits the page's width, one taller than a page gets a page of its own, and a second chart
  shrinks a little to share a page rather than leave a gap (five charts: 4 pages, not 7).
  Text never leaves one line alone at the top or foot of a page. Only the child's own words
  go in: the starter's instructions and its `<!-- -->` notes are left out, and the
  Workbench says which files were.
- **Always the charts the code draws now.** Making the report runs the analysis first
  (half a second), so a chart left over from an older version can never get in. A failed
  analysis makes no report, and says so.
- **The preview is the PDF.** The Workbench shows the PDF's own pages, from the same bytes
  Export PDF saves. What the child sees is what they save.
- **Export PDF…** opens the Mac's save window (Documents first, "Weather Study report.pdf").
  Open Nest writes that one file and nothing else. It checks the file is really there
  before saying "Saved “Weather Study report.pdf” in Documents. 4 pages." It refuses its own
  folders, folders it cannot write to, and anything key-shaped in the text. **No parent PIN**:
  saving your own work should not need one (PLAN.md D14). Gary cannot export: it is a
  button, not a tool.
- **Gary changes the report** through `src/report.toml`, a file in the project like
  `matplotlibrc`: the title, your name, the sizes, the order of the parts, which charts.
  "Make the title of my report bigger" or "put the charts first" is one line. Asked how to
  save or print the report, he now names the real buttons; before, he told the child to add
  `savefig(format='pdf')` or a `print()` line.
- **The chart style really applies** (the pass before this one, checked and finished here).
  The house `matplotlibrc` was never being read, so every chart drew in stock matplotlib.
  Open Nest now points matplotlib at it. Colours Gary names that the child did not ask for
  are taken out. The starter converts dates. Fixed in this pass: a colour hidden inside
  another word ("hund**red**", "bo**red**") no longer counted as asked for, and the
  starter's `matplotlibrc` no longer tells Gary the wrong reason it works.

## Then the owner's own report: "a dashboard report", and Gary built none

On Gary Smart, a new Research project with the weather CSV: "Make a weather report
dashboard report with a few modern visualizations of the data analyzed." Gary only wrote
three made-up chart names into report.toml, said "the analysis will draw them", and Show
the report had nothing to show. Reproduced: 0 of 3 such messages. Now **3 of 3 on both
Gary Smart and Gary Fast** -- three new charts each, run, and in the report. What was
wrong, all Open Nest's (SPIKES.md §34G):

- A report that needs charts made is the **analysis's** work, not the layout's: Gary is
  told the report shows every chart the analysis draws, and **where in the analysis to add
  them** -- Gary Smart had been aiming his edits at a "# Add your analysis here." line that
  does not exist, ten times a turn.
- The starter now **imports seaborn**, which the research prompt says is there.
- **A Research turn now runs the analysis after it changes it**, as a game is tested: a
  failure goes back to Gary to fix, and if he cannot, the child is told it failed -- never
  "the chart now shows ...".
- A `report.toml` naming charts nobody drew is **refused** when Gary writes it; one
  already like that gets every chart that was drawn, said in one sentence.
- **Charts one after another share a page at one size**: Gary Smart's big charts had taken
  a page each, half of it empty -- 4 pages became 3.

Your weather3 project still has the made-up names in its report.toml; it now makes a report
anyway (with the one chart it has). Send the message again and Gary builds the charts.

## What we measured

Gary Fast, one turn per message on the weather project, before and after this pass's Gary
changes:

| | before | after |
|---|---:|---:|
| changes to the report (7) | 5 | **7** |
| chart requests (fair 3) | 1 | 3 |
| "how do I save/print my report?" (2) | 0 | 2 |

Report changes took about 11 s each (20-55 s before). The research prompt edit from the
pass before (colours, figure sizes, dates) had never been measured; it cost nothing here.

Gary Smart: 6 of 7 report changes before, 7 of 7 after; both export questions after, none
before. A message about a chart *in* the report ("the rain chart in my report should be
called ...") still goes to the analysis, as it always did: measured on Gary Fast, with the
report note it went into the report's own title instead and Gary said the chart was
renamed, so the note now stays off messages about a chart itself.

Found, and fixed: Gary Smart's dashboard used matplotlib's `tab:blue`, `tab:green`,
`tab:red`, which the colour guard did not know; and a Research turn could change the
analysis, not run it, and say the chart changed (fixed in the owner's-report section
above).

## Not done yet

- **Try it by hand**: the real macOS save window (asking before it replaces a file, adding
  `.pdf`), printing an exported PDF, and the pages on a Retina screen. The tests replace
  the save window.
- A new Research project's very first Run Analysis takes about 6 seconds while matplotlib
  builds that project's font cache; after that, half a second. Older than this pass, and
  noticed, not changed.
- Some chart edits still miss (the edit tool's exact text): asked to rename the rain chart,
  both models said they could not, truthfully.
- An emoji in the findings cannot be printed; it is left out, and said.
- No 8 GB Mac has been measured.
