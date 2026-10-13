"""Python stand-ins for dbt macros that sqlfluff's Jinja templater can't render as text.

`config(**iceberg_table_config(...))` unpacks a dict, which a Jinja macro can't return.
"""


def iceberg_table_config(partition_by=()):
    return {}
