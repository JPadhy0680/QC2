import os
import io
import json
import tempfile
from datetime import datetime
import streamlit as st

# Local imports
from quality_reviewer import run_qc

st.set_page_config(page_title="Quality Reviewer (Source vs XML)", layout="wide")
st.title("Quality Reviewer (Source vs Processed XML)")
st.caption("Upload a source document and a processed XML, provide a config, and generate a QC report.")

# Sidebar
with st.sidebar:
    st.header("Settings")
    report_format = st.selectbox("Report format", ["all", "xlsx", "csv", "json"], index=0)
    gen_html = st.checkbox("Generate HTML summary", value=True)
    outdir_name = st.text_input("Output folder name", value=f"qc_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

col1, col2, col3 = st.columns(3)

with col1:
    source_file = st.file_uploader("Source Document (PDF/DOCX/TXT/CSV/XLSX/XLS)", type=["pdf","docx","txt","csv","xlsx","xls"], accept_multiple_files=False)
with col2:
    xml_file = st.file_uploader("Processed XML", type=["xml"], accept_multiple_files=False)
with col3:
    config_file = st.file_uploader("Config (JSON)", type=["json"], accept_multiple_files=False)

run_btn = st.button("Run Quality Check", use_container_width=True)

placeholder = st.empty()

if run_btn:
    if not source_file or not xml_file or not config_file:
        st.error("Please upload Source, XML, and Config files.")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save uploads to disk
            src_path = os.path.join(tmpdir, source_file.name)
            with open(src_path, 'wb') as f:
                f.write(source_file.read())

            xml_path = os.path.join(tmpdir, xml_file.name)
            with open(xml_path, 'wb') as f:
                f.write(xml_file.read())

            cfg_path = os.path.join(tmpdir, config_file.name)
            with open(cfg_path, 'wb') as f:
                f.write(config_file.read())

            outdir = os.path.join(tmpdir, outdir_name)

            with st.spinner('Running QC...'):
                try:
                    paths = run_qc(src_path, xml_path, cfg_path, outdir, report_format, gen_html)
                except Exception as e:
                    st.exception(e)
                    st.stop()

            st.success("QC complete. Download your outputs below.")

            # Show download buttons
            for key, p in paths.items():
                label = f"Download {key.upper()} report"
                with open(p, 'rb') as fh:
                    st.download_button(label=label, data=fh.read(), file_name=os.path.basename(p), mime="text/csv" if p.endswith('.csv') else ("application/json" if p.endswith('.json') else ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if p.endswith('.xlsx') else "text/html")))

            # If CSV/JSON available, show preview
            import pandas as pd
            if 'csv' in paths and paths['csv'].endswith('.csv'):
                try:
                    df = pd.read_csv(paths['csv'])
                    st.subheader("QC Report Preview")
                    st.dataframe(df, use_container_width=True)
                except Exception:
                    pass
            elif 'json' in paths and paths['json'].endswith('.json'):
                try:
                    df = pd.read_json(paths['json'])
                    st.subheader("QC Report Preview")
                    st.dataframe(df, use_container_width=True)
                except Exception:
                    pass
