{#- Deterministic surrogate key: md5 over the given columns, NULL-safe.
    Local equivalent of dbt_utils.generate_surrogate_key, kept in-repo so the
    project has no package dependencies. -#}
{% macro surrogate_key(columns) -%}
    md5(
        {%- for column in columns %}
        coalesce(cast({{ column }} as varchar), '_null_')
        {%- if not loop.last %} || '|' || {% endif -%}
        {%- endfor %}
    )
{%- endmacro %}
