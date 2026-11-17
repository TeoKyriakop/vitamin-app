"""Builds the static site published on GitHub Pages: app/ with index.html wrapped
into a full, installable document. Run: python -m vitapp.site [out_dir]"""
import os, shutil, sys
from pathlib import Path
from . import store

SKELETON_HEAD = ('<!doctype html><html lang="el"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                 '<meta name="theme-color" content="#12332B"><link rel="manifest" href="manifest.webmanifest">'
                 '<link rel="icon" href="icon.svg"><link rel="apple-touch-icon" href="icon.svg">'
                 '<meta name="apple-mobile-web-app-capable" content="yes">{extra}'
                 '<style>:root{{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}'
                 'body{{margin:0}}img{{max-width:100%}}[hidden]{{display:none!important}}</style></head><body>')


def wrap(body: bytes, repo: str = "") -> bytes:
    extra = f'<meta name="vc-repo" content="{repo}">' if repo else ""
    return SKELETON_HEAD.format(extra=extra).encode() + body + b"</body></html>"


def build_site(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(store.APP, out)
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    (out / "index.html").write_bytes(wrap((store.APP / "index.html").read_bytes(), repo))
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print("site:", build_site(sys.argv[1] if len(sys.argv) > 1 else store.ROOT.parent / "site"))
