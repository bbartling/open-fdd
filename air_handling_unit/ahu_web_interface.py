import inspect
import typing
from io import BytesIO

import pandas as pd
import streamlit as st

import faults
import reports

# streamlit run .\ahu_web_interface.py

st.title("G36 Fault Condition Analysis")
st.subheader("Select a rule to check and upload a CSV file to run the analysis")

fault_map = {x[0]: x[1] for x in inspect.getmembers(faults, inspect.isclass) if x[0].startswith("FaultCondition")}
report_map = {x[0]: x[1] for x in inspect.getmembers(reports, inspect.isclass)}

input_map = {
    float: st.number_input,
    int: st.number_input,
    str: st.text_input,
    bool: st.checkbox,
}

rule_to_check = st.selectbox("What rule would you like to check?", sorted(fault_map.keys()))
inputs = inspect.signature(fault_map[rule_to_check])
samples = st.file_uploader("Upload a CSV file", type="csv")

column_mappings = {}
parameters = {}
if samples is not None:
    dataframe = pd.read_csv(samples, index_col="Date", parse_dates=True).rolling("5T").mean()
    st.write(dataframe)
    for input in (input for input in inputs.parameters if input.endswith("_col")):
        column_mappings[input] = st.selectbox(
            f"Input for {rule_to_check} - {input}", [col for col in dataframe.columns]
        )
    for input, p in {
        input: p for input, p in inputs.parameters.items() if not input.endswith("_col")
    }.items():
        parameters[input] = input_map[p.annotation](
            f"Input for {rule_to_check} - {input}"
        )

    if st.button("Run Analysis"):
        res = fault_map[rule_to_check](**column_mappings, **parameters).apply(dataframe)
        st.write(res)
        st.download_button('Download Results', res.to_csv().encode('utf-8'), 'results.csv', 'text/csv')

    # Report Generation
    report_name = st.text_input("Report Name")
    report_def = report_map[f'{rule_to_check.replace("Condition", "Code")}Report']
    report_args = inspect.signature(report_def).parameters
    filtered_report_args = {key: value for key, value in report_args.items() if key not in dict(**column_mappings, **parameters)}
    for report_input in (report_input for report_input in filtered_report_args if report_input.endswith("_col")):
        column_mappings[report_input] = st.selectbox(
            f"Input for {rule_to_check} - {report_input}", [col for col in dataframe.columns]
        )
    for report_input, p in {
        report_input: p for report_input, p in filtered_report_args.items() if not report_input.endswith("_col")
    }.items():
        parameters[report_input] = input_map[p.annotation](
            f"Input for {rule_to_check} - {report_input}"
        )
    if st.button("Run Report"):
        filtered_fault_args = {key: value for key, value in dict(**column_mappings, **parameters).items() if key in inputs.parameters}
        res = fault_map[rule_to_check](**filtered_fault_args).apply(dataframe)
        filtered_report_args = {key: value for key, value in column_mappings.items() if key in report_args}
        report = report_def(**filtered_report_args).create_report(report_name, res)
        download_file = BytesIO()
        report.save(download_file)
        download_file.seek(0)
        st.write(
            st.download_button(
                "DownloadReport",
                download_file,
                f"{report_name}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        )
