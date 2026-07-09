use std::path::Path;

use anyhow::Result;
use walkdir::WalkDir;

pub fn write_inventory(app_root: &Path, out: &Path) -> Result<()> {
    let backend = app_root.join("backend");
    let mut lines = vec![
        "# Python inventory (CLI-generated)".into(),
        String::new(),
        "| File | pandas refs | FDD keywords |".into(),
        "| --- | ---: | --- |".into(),
    ];

    for entry in WalkDir::new(&backend)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().is_some_and(|x| x == "py"))
    {
        let path = entry.path();
        let text = std::fs::read_to_string(path).unwrap_or_default();
        let pandas_refs = text.matches("pd.").count() + text.matches("pandas").count();
        let keywords = if text.contains("confirm_fault") || text.contains("fault_hours") {
            "fault/rollup"
        } else if text.contains("CookbookRule") {
            "cookbook rule"
        } else if text.contains("compute_") {
            "analytics compute"
        } else {
            "glue/other"
        };
        let rel = path.strip_prefix(app_root).unwrap_or(path);
        lines.push(format!(
            "| `{}` | {} | {} |",
            rel.display(),
            pandas_refs,
            keywords
        ));
    }

    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(out, lines.join("\n"))?;
    Ok(())
}
