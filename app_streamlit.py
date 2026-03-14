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

# ---------------------------------------------------------------------
# Robust loader: finds run_qc() whether quality_reviewer.py is
#   - in the SAME folder as this file,
#   - in the PARENT folder, or
#   - installed/importable as a package.
# ---------------------------------------------------------------------
def _load_run_qc():
    this = pathlib.Path(__file__).resolve()

    # 1) Try same folder
    candidate = this.with_name("quality_reviewer.py")
    if candidate.exists():
        spec = importlib.util.spec_from_file_location("quality_reviewer", str(candidate))
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        if hasattr(mod, "run_qc"):
            return mod.run_qc

    # 2) Try one level up (e.g., repo_root/quality_reviewer.py and repo_root/qc2/app_streamlit.py)
    candidate = (this.parent.parent / "quality_reviewer.py").resolve()
    if candidate.exists():
        spec = importlib.util.spec_from_file_location("quality_reviewer", str(candidate))
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        if hasattr(mod, "run_qc"):
            return mod.run_qc

    # 3) Fall back to normal import (if installed or on PYTHONPATH)
    try:
        from quality_reviewer import run_qc as _run_qc  # type: ignore
        return _run_qc
    except Exception as e:
        raise ModuleNotFoundError(
            "Unable to import run_qc. Ensure quality_reviewer.py is in the same "
            "folder or parent folder, or install the package."
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

# Optional helper: show a preview of the uploaded config (first 2000 chars)
def _preview_config(cfg_bytes: bytes):
    try:
        txt = cfg_bytes.decode("utf-8", errors="ignore")
        # Basic validation that it's JSON (and pretty print a short snippet)
        obj = json.loads(txt)
        st.markdown("**Config (JSON) preview:**")
        st.code(json.dumps(obj, indent=2)[:2000] + ("..." if len(json.dumps(obj, indent=2)) > 2000 else ""), language="json")
    except Exception:
        pass

if run_btn:
    if not source_file or not xml_file or not config_file:
        st.error("Please upload Source, XML, and Config files.")
        st.stop()

    # Basic visibility for what was uploaded
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
                # Show the full exception to help fix bad regex/XPath or missing deps
                st.error("QC failed. See details below:")
                st.exception(e)
                st.stop()

        st.success("QC complete. Download your outputs below.")

        # Download buttons for each generated artifact
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

        # Preview (CSV preferred; otherwise JSON)
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

# Helpful footnote
st.caption(
    "Tip: If you see `ModuleNotFoundError: quality_reviewer`, put `app_streamlit.py` and `quality_reviewer.py` in the same folder, "
    "or keep `quality_reviewer.py` in the parent folder. This app already tries both, and then a normal package import."
)
