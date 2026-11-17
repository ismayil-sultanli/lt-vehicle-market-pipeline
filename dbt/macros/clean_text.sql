{#- Normalise free text from the source: non-breaking spaces -> spaces,
    collapse repeated whitespace, trim. -#}
{% macro clean_text(column) -%}
    trim(regexp_replace(replace({{ column }}, chr(160), ' '), '\s+', ' ', 'g'))
{%- endmacro %}
