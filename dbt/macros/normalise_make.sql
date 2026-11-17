{#- Reduce a hand-typed make to a lookup key: upper case, without the
    country-of-manufacturer suffix some stations append, e.g.
    "Skoda (CZ)" -> "SKODA", "FORD (D)" -> "FORD". -#}
{% macro normalise_make(column) -%}
    trim(regexp_replace(upper({{ column }}), '\s*\([A-Z/ ]{1,3}\)\s*$', ''))
{%- endmacro %}
