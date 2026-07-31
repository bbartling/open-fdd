# Streamlit → React component mapping

Use this while building the parity inventory. Match behavior and visible output
first; the React implementation is guidance, not a mandatory library choice.

| Streamlit pattern | React implementation | State/API notes |
|---|---|---|
| `st.sidebar` | Fixed or sticky `<aside>` | Preserve width, scroll, and order |
| `st.tabs` | Tablist + tab buttons + panels | Decide whether inactive panels unmount |
| Multipage navigation | Router or controlled shell | Preserve shareable URLs when present |
| `st.columns` | CSS grid or flex | Measure ratios and gaps |
| `st.container` / `st.empty` | Section/component slot | Preserve conditional layout shifts |
| `st.expander` | `<details>` or disclosure | Persist open state only when reference does |
| `st.form` | Controlled form + submit boundary | Do not calculate before submit |
| `st.selectbox` | Styled select or combobox | Match default, options, and clearability |
| `st.multiselect` | Accessible multi-combobox | Match chip order and filtering |
| `st.slider` | Range + value output | Match min/max/step/format/update timing |
| `st.number_input` | Numeric input | Enforce bounds client and server side |
| `st.checkbox` / toggle | Checkbox or switch | Match label target and default |
| `st.radio` | Radio group/segmented control | Preserve orientation |
| `st.button` | `<button>` | Match primary, disabled, and loading states |
| `st.file_uploader` | File input/drop zone | Validate type/size server side |
| `st.download_button` | Blob link or API download | Match name, MIME type, and content |
| `st.metric` | Metric card | Match delta direction/color/format |
| `st.dataframe` | Table or data grid | Match headers, row height, scroll, format |
| `st.table` | Semantic table | Avoid grid features absent from reference |
| `st.plotly_chart` | Plotly React/equivalent | Reuse data and trace config |
| `st.altair_chart` | Vega/Vega-Lite React | Preserve scales, tooltips, selections |
| `st.line_chart` / `bar_chart` | Chart library or SVG | Make generated defaults explicit |
| `st.progress` | Progress component | Match label and percentage placement |
| `st.spinner` / status | Loading/status component | Model async API state |
| `st.toast` | Toast region | Match icon, duration, position, stacking |
| `st.info/warning/error/success` | Alert component | Preserve text and semantic tone |
| `st.markdown` | Markup or safe renderer | Never inject unsanitized user HTML |
| `st.components` | Dedicated React component | Document event/message contract |
| `st.session_state` | Local/context/URL/server state | Classify every key |
| `st.cache_data` | API/query cache | Preserve freshness and invalidation |
| `st.cache_resource` | Server lifecycle | Do not recreate expensive clients/request |
| Callback + rerun | Event + state/query update | Reproduce outcome, not full rerun |

## State classification

1. Ephemeral UI state → local React state.
2. Cross-panel state → lifted state or context.
3. Shareable filters → URL parameters.
4. Server-derived result → query/cache state.
5. Durable project state → FastAPI persistence.
6. Security-sensitive state → server session or validated token.

## Chart parity

- Use identical raw data and rounding policy.
- Match domains, ticks, grid, and zero baseline.
- Match trace order, stroke, markers, fill, and colors.
- Match legend orientation and placement.
- Match internal margins and container height.
- Match hover values and annotations.
- Disable affordances absent from the reference.
