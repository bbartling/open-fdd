"""Open-FDD reporting package.

This package initializer must stay lightweight and pandas-free.

Import concrete report helpers directly, for example:

    from open_fdd.reports.rcx_placeholders import chart_placeholder_spec
    from open_fdd.reports.rcx_docx import build_rcx_docx

Legacy pandas-era reporting modules should not be imported here because that
breaks Arrow-native installs that intentionally do not install pandas.
"""

__all__: list[str] = []
