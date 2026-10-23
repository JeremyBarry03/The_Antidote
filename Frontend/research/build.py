"""Generate the static project overview and PDF from the standalone LaTeX source.

Requires Pandoc and pdfLaTeX on PATH; generated compiler files stay in artifacts.
"""

from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
BUILD = HERE.parents[1] / "Data_Science/artifacts/research_paper"


def main() -> None:
    for command in ("pandoc", "pdflatex"):
        if not shutil.which(command):
            raise SystemExit(f"Install {command} and make it available on PATH before rebuilding the overview.")
    html = subprocess.check_output([
        "pandoc", str(HERE / "paper.tex"), "--from=latex", "--to=html5", "--standalone",
        "--math-method=mathml", "--toc", "--toc-depth=2", "--shift-heading-level-by=1", "--section-divs", "--wrap=none",
        f"--template={HERE / 'template.html'}",
    ], text=True)
    html = re.sub(r'(<table\b[^>]*?)\sstyle="[^"]*"', r"\1", html)
    html = re.sub(r'(<math display="block".*?</math>)',
                  r'<span class="math display" tabindex="0" role="region" '
                  r'aria-label="Equation; scroll horizontally if needed">\1</span>', html, flags=re.S)
    html = re.sub(r"(<table\b[^>]*>)", '<div class="table-scroll" tabindex="0" role="region" '
                  'aria-label="Scrollable data table">\\1', html)
    html = html.replace("</table>", "</table></div>")
    BUILD.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        result = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                                 f"-output-directory={BUILD}", str(HERE / "paper.tex")],
                                cwd=HERE, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stdout[-6000:])
    (HERE / "index.html").write_text(html)
    shutil.copy2(BUILD / "paper.pdf", HERE / "paper.pdf")
    print("Built research/index.html and research/paper.pdf from paper.tex.")


if __name__ == "__main__":
    main()
