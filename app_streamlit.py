# app_streamlit.py
import os
import io
import json
import tempfile
from datetime import datetime
import pathlib
import importlib.util
import sys
import streamlit as st
from typing import List

# ---------------------------------------------------------------------
# Robust loader for run_qc():
#   1) QUALITY_REVIEWER_PATH env (full path to quality_reviewer.py)
#   2) Same folder as this file
#   3) Recursively walk up parents and check direct children for quality_reviewer.py
#   4) Try common subfolders under repo root: src/, app/, qc/, qc2/, tools/
#   5) Fallback: normal "from quality_reviewer import run_qc"
# Also exposes a small debug panel to show what paths were tested.
# ---------------------------------------------------------------------
_DEBUG_SEARCH_PATHS: List[str] = []
_DEBUG_LOAD_ERROR: str = ""

def _try_load_from_file(py_path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("quality_reviewer", str(py_path))
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return getattr(mod, "run_qc", None)

def _add(p: pathlib.Path):
    _DEBUG_SEARCH_PATHS.append(str(p))

def _load_run_qc():
    global _DEBUG_LOAD_ERROR

    this = pathlib.Path(__file__).resolve()
    tried = []

    # 1) Env var
    env_path = os.environ.get("QUALITY_REVIEWER_PATH", "").strip()
    if env_path:
        p = pathlib.Path(env_path).expanduser().resolve()
        _add(p)
        if p.exists() and p.is_file():
            r = _try_load_from_file(p)
            if r:
                return r
            tried.append(f"Env path exists but run_qc not found: {p}")

    # 2) Same folder
    candidate = this.with_name("quality_reviewer.py")
    _add(candidate)
    if candidate.exists():
        r = _try_load_from_file(candidate)
        if r:
            return r
        tried.append(f"Same folder file exists but run_qc missing: {candidate}")

    # 3) Recursively walk up parents (up to 5 levels) and check direct child "quality_reviewer.py"
    cur = this.parent
    for _ in range(5):
        cand = (cur / "quality_reviewer.py").resolve()
        _add(cand)
        if cand.exists():
            r = _try_load_from_file(cand)
            if r:
                return r
            tried.append(f"Found {cand} but run_qc missing")
        cur = cur.parent

    # 4) Common subfolders under repo root (guess: topmost git-like root)
    #    We assume repo root is within a few parent levels.
    roots = [this.parent, this.parent.parent, this.parent.parent.parent]
    common_dirs = ("src", "app", "qc", "qc2", "tools", "code")
    for root in roots:
        for d in common_dirs:
            cand = (root / d / "quality_reviewer.py").resolve()
            _add(cand)
            if cand.exists():
                r = _try_load_from_file(cand)
                if r:
                    return r
                tried.append(f"Found {cand} but run_qc missing")

    # 5) Fallback to normal import (package installed / PYTHONPATH)
    try:
        from quality_reviewer import run_qc as _run_qc  # type: ignore
        return _run_qc
    except Exception as e:
        _DEBUG_LOAD_ERROR = f"Fallback import failed: {e!r}"
        raise ModuleNotFoundError(
            "Unable to import run_qc.\n"
            "Tried:\n - QUALITY_REVIEWER_PATH env\n - Same folder\n - Parents\n - Common subfolders\n - Package import\n"
            "Fix by placing quality_reviewer.py in the same folder as this app or set QUALITY_REVIEWER_PATH "
            "to the absolute path of quality_reviewer.py."
        ) from e

run_qc = _load_run_qc()

# ---------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------
st.set_page_config(page_title="Quality Reviewer (Source vs XML)", layout="wide")
st.title("Quality Reviewer (Source vs Processed XML)")
st.caption("Upload a source document and a processed XML, provide a config, and generate a QC report.")

# Sidebar controls
with st.sidebar:
    st.header("Settings")
    report_format = st.selectbox("Report format", ["all", "xlsx", "csv", "json"], index=0)
    gen_html = st.checkbox("Generate HTML summary", value=True)
    outdir_name = st.text_input(
        "Output folder name",
        value=f"qc_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

# Debug expander to help diagnose paths on Streamlit Cloud
with st.expander("Debug: loader paths and environment", expanded=False):
    st.markdown("**Searched paths for `quality_reviewer.py` (in order):**")
    st.code("\n".join(_DEBUG_SEARCH_PATHS) or "(no paths)", language="bash")
    if _DEBUG_LOAD_ERROR:
        st.error(_DEBUG_LOAD_ERROR)
    st.write({
        "WORKING_DIR": os.getcwd(),
        "FILE_DIR": str(pathlib.Path(__file__).resolve().parent),
        "QUALITY_REVIEWER_PATH (env)": os.environ.get("QUALITY_REVIEWER_PATH")
    })

col1, col2, col3 = st.columns(3)

with col1:
    source_file = st.file_uploader(
        "Source Document (PDF/DOCX/TXT/CSV/XLSX/XLS)",
        type=["pdf", "docx", "txt", "csv", "xlsx", "xls"],
        accept_multiple_files=False
    )

with col2:
    xml_file = st.file_uploader(
        "Processed XML",
        type=["xml"],
        accept_multiple_files=False
    )

with col3:
    config_file = st.file_uploader(
        "Config (JSON)",
        type=["json"],
        accept_multiple_files=False
    )

run_btn = st.button("Run Quality Check", use_container_width=True)

def _infer_mime(path: str) -> str:
    p = path.lower()
    if p.endswith(".csv"):
        return "text/csv"
    if p.endswith(".json"):
        return "application/json"
    if p.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if p.endswith(".html"):
        return "text/html"
    return "application/octet-stream"

def _preview_config(cfg_bytes: bytes):
    try:
        txt = cfg_bytes.decode("utf-8", errors="ignore")
        obj = json.loads(txt)
        st.markdown("**Config (JSON) preview:**")
        pretty = json.dumps(obj, indent=2)
        st.code(pretty[:2000] + ("..." if len(pretty) > 2000 else ""), language="json")
    except Exception:
        pass

if run_btn:
    if not source_file or not xml_file or not config_file:
        st.error("Please upload Source, XML, and Config files.")
        st.stop()

    with st.expander("Uploaded files"):
        st.write({
            "source": source_file.name if source_file else None,
            "xml": xml_file.name if xml_file else None,
            "config": config_file.name if config_file else None
        })
        _preview_config(config_file.getvalue())

    with tempfile.TemporaryDirectory() as tmpdir:
        # Save uploads to disk
        src_path = os.path.join(tmpdir, source_file.name)
        with open(src_path, "wb") as f:
            f.write(source_file.read())
        xml_path = os.path.join(tmpdir, xml_file.name)
        with open(xml_path, "wb") as f:
            f.write(xml_file.read())
        cfg_path = os.path.join(tmpdir, config_file.name)
        with open(cfg_path, "wb") as f:
            f.write(config_file.read())

        outdir = os.path.join(tmpdir, outdir_name)

        with st.spinner("Running QC..."):
            try:
                paths = run_qc(src_path, xml_path, cfg_path, outdir, report_format, gen_html)
            except Exception as e:
                st.error("QC failed. See details below:")
                st.exception(e)
                st.stop()

        st.success("QC complete. Download your outputs below.")

        # Download buttons
        if not paths:
            st.warning("No outputs were generated. Please check your config/inputs.")
        else:
            for key, p in paths.items():
                label = f"Download {key.upper()} report"
                with open(p, "rb") as fh:
                    st.download_button(
                        label=label,
                        data=fh.read(),
                        file_name=os.path.basename(p),
                        mime=_infer_mime(p),
                        use_container_width=True
                    )

        # Preview
        import pandas as pd
        if "csv" in paths and paths["csv"].endswith(".csv"):
            try:
                df = pd.read_csv(paths["csv"])
                st.subheader("QC Report Preview")
                st.dataframe(df, use_container_width=True)
            except Exception:
                pass
        elif "json" in paths and paths["json"].endswith(".json"):
            try:
                df = pd.read_json(paths["json"])
                st.subheader("QC Report Preview")
                st.dataframe(df, use_container_width=True)
            except Exception:
                pass

st.caption(
    "If you still see a ModuleNotFoundError, either place `quality_reviewer.py` in the same folder as this app, "
    "or set env var QUALITY_REVIEWER_PATH to its absolute path."
)
